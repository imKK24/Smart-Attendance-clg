"""Attendance records (PostgreSQL) with a CSV copy per day, plus their API."""
import csv
import io
from datetime import date

from flask import Blueprint, Response, request
from sqlalchemy import String

import config
from common import fail, ok, parse_day, safe_cell
from models import AttendanceRecord, Holiday, LeaveRequest, Student, db, in_units
from orgs import COLLEGE, current_org, uses_courses

bp = Blueprint("attendance", __name__, url_prefix="/api")
CSV_HEADER = ["Name", "Registration No", "Date", "Time", "Status"]


def today():
    return date.today()


def row_dict(r, roll=""):
    return {"Name": r.student_name, "RollNo": roll, "Date": r.day.isoformat(), "Time": r.time or "-", "Status": r.status,
            "Source": r.source or "camera", "Course": r.course or ""}


# ---- organisation / course helpers ----
def course_of(course):
    """College rows have course ""; IT Hub rows always name their course."""
    return (course or "") if uses_courses() else ""


def rec_query(s, course=None):
    """Attendance rows of this organisation (and of one course, for the IT Hub)."""
    q = s.query(AttendanceRecord).filter(AttendanceRecord.org == current_org())
    if uses_courses() and course is not None:
        q = q.filter(AttendanceRecord.course == course)
    return q


def enrolled(q, course):
    """Limit a Student query to one IT Hub class: a whole course ("Python") or
    one batch of it ("Python · 4–6 PM")."""
    return q.filter(in_units([course])) if uses_courses() and course else q


def org_students(s, course=None):
    q = s.query(Student).filter(Student.org == current_org())
    return enrolled(q, course)


def course_param():
    return course_of(request.args.get("course", ""))


def leave_days(start=None, end=None):
    """{student_id: set of dates} covered by APPROVED leave."""
    out = {}
    with db() as s:
        q = (s.query(LeaveRequest).join(Student, Student.id == LeaveRequest.student_id)
             .filter(LeaveRequest.status == "approved", Student.org == current_org()))
        if start:
            q = q.filter(LeaveRequest.end_date >= start)
        if end:
            q = q.filter(LeaveRequest.start_date <= end)
        for lv in q:
            d = lv.start_date
            while d <= lv.end_date:
                out.setdefault(lv.student_id, set()).add(d)
                d = date.fromordinal(d.toordinal() + 1)
    return out


def records_for(day, course=""):
    """Records for a day (IT Hub: of one course). For today, students who are
    not marked yet are shown as Absent so the numbers are live."""
    from auth import scope, scope_query
    course = course_of(course)
    if uses_courses() and not course:
        return []
    with db() as s:
        students = {st.name: st for st in enrolled(scope_query(s.query(Student)), course).all()}
        rows = rec_query(s, course).filter(AttendanceRecord.day == day).all()
        if scope() is not None:   # teachers: only their branches
            rows = [r for r in rows if r.student_name in students]
        out = [row_dict(r, (students.get(r.student_name).roll_no or "") if students.get(r.student_name) else "")
               for r in rows]
    if day == today():
        have = {r["Name"] for r in out}
        on_leave = leave_days(day, day)
        out += [{"Name": n, "RollNo": st.roll_no or "", "Date": day.isoformat(), "Time": "-",
                 "Status": "Leave" if day in on_leave.get(st.id, ()) else "Absent"}
                for n, st in students.items() if n not in have]
    return sorted(out, key=lambda r: r["Name"].lower())


def summary(day, records):
    present = sum(1 for r in records if r["Status"] == "Present")
    leave = sum(1 for r in records if r["Status"] == "Leave")
    total = len(records)
    return {"date": day.isoformat(), "records": records, "present_count": present,
            "absent_count": total - present - leave, "leave_count": leave, "total": total,
            "percentage": round(present / total * 100) if total else 0}


def present_names(day, course=""):
    course = course_of(course)
    with db() as s:
        return {r.student_name for r in rec_query(s, course).filter(
            AttendanceRecord.day == day, AttendanceRecord.status == "Present")}


def mark_present(day, name, time_str, source="camera", write=True, course=""):
    """Insert or upgrade a student's row to Present (IT Hub: for one course)."""
    course = course_of(course)
    with db() as s:
        st = org_students(s).filter(Student.name == name).first()
        row = rec_query(s, course).filter(AttendanceRecord.day == day, AttendanceRecord.student_name == name).first()
        if row:
            row.status, row.time, row.source = "Present", time_str, source
        else:
            s.add(AttendanceRecord(org=current_org(), course=course, day=day, student_name=name,
                                   student_id=st.id if st else None, time=time_str, status="Present", source=source))
    if write:
        write_csv(day, course)


def finalize_students(day, student_ids, source="photo", course=""):
    """Like finalize_day, but only for these students (one branch's class photo
    must not mark other branches absent)."""
    course = course_of(course)
    on_leave = leave_days(day, day)
    with db() as s:
        have = {r.student_name for r in rec_query(s, course).filter(AttendanceRecord.day == day)}
        for st in org_students(s).filter(Student.id.in_(list(student_ids) or [-1])):
            if st.name not in have:
                status = "Leave" if day in on_leave.get(st.id, ()) else "Absent"
                s.add(AttendanceRecord(org=current_org(), course=course, day=day, student_name=st.name,
                                       student_id=st.id, time="-", status=status, source=source))
    write_csv(day, course)


def finalize_day(day):
    """Everyone registered who isn't Present gets one row: Leave if on approved
    leave, otherwise Absent. Safe to run many times.
    IT Hub: only courses that had a class that day (someone was marked), and
    only students of that course."""
    if uses_courses():
        with db() as s:
            held = [c for (c,) in rec_query(s).filter(AttendanceRecord.day == day)
                    .with_entities(AttendanceRecord.course).distinct() if c]
        for course in held:
            with db() as s:
                ids = [i for (i,) in org_students(s, course).with_entities(Student.id)]
            finalize_students(day, ids, source="camera", course=course)
        return
    on_leave = leave_days(day, day)
    with db() as s:
        have = {r.student_name for r in rec_query(s).filter(AttendanceRecord.day == day)}
        for st in org_students(s).all():
            if st.name not in have:
                status = "Leave" if day in on_leave.get(st.id, ()) else "Absent"
                s.add(AttendanceRecord(org=COLLEGE, day=day, student_name=st.name, student_id=st.id,
                                       time="-", status=status))
    write_csv(day)


def csv_bytes(day, course=""):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADER + (["Course"] if uses_courses() else []))
    for r in sorted(records_for(day, course), key=lambda r: (r["Status"] != "Present", r["Name"].lower())):
        cells = [r["Name"], r["RollNo"], r["Date"], r["Time"], r["Status"]] + ([course] if uses_courses() else [])
        w.writerow([safe_cell(x) for x in cells])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel shows names correctly


def write_csv(day, course=""):
    """Keep attendance_records/YYYY-MM-DD.csv in step with the database
    (IT Hub: attendance_records/ithub/<course>/YYYY-MM-DD.csv)."""
    course = course_of(course)
    folder = config.ATTENDANCE_DIR
    if uses_courses():
        if not course:
            return
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in course).strip() or "course"
        folder = folder / current_org() / safe
        folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day.isoformat()}.csv"
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(csv_bytes(day, course))
    tmp.replace(path)


def saved_days(limit=None, course=None):
    """Days with a register (IT Hub: with a class of that course; course=None = any course)."""
    with db() as s:
        q = rec_query(s, course_of(course) if course is not None else None)
        q = q.with_entities(AttendanceRecord.day).distinct().order_by(AttendanceRecord.day.desc())
        if limit:
            q = q.limit(limit)
        return [d for (d,) in q]


def holiday_dates(start=None):
    out = set()
    with db() as s:
        q = s.query(Holiday).filter(Holiday.org == current_org())
        if start:
            q = q.filter(Holiday.end_date >= start)
        for h in q:
            d = h.start_date
            while d <= h.end_date:
                out.add(d)
                d = date.fromordinal(d.toordinal() + 1)
    return out


def holiday_on(day):
    with db() as s:
        h = s.query(Holiday).filter(Holiday.org == current_org(), Holiday.start_date <= day,
                                    Holiday.end_date >= day).first()
        return h.title if h else None


def absence_streaks():
    """{student_id: [absent dates, oldest first]} counting back from the most
    recent saved day. Days with no register (weekends), holidays and approved
    leave are skipped, and a day where the student has no row yet doesn't count.
    IT Hub: counted per course (classes of that course); the longest streak wins."""
    if uses_courses():
        best = {}
        for course in _held_courses():
            for sid, dates in _streaks(course).items():
                if len(dates) > len(best.get(sid, [])):
                    best[sid] = dates
        return best
    return _streaks(None)


def _held_courses():
    with db() as s:
        return [c for (c,) in rec_query(s).with_entities(AttendanceRecord.course).distinct() if c]


def _streaks(course):
    days = saved_days(60, course)
    if not days:
        return {}
    skip = holiday_dates(days[-1])
    days = [d for d in days if d not in skip]
    with db() as s:
        rows = rec_query(s, course).filter(AttendanceRecord.day.in_(days)).all()
        students = org_students(s, course).all()
    status = {(r.day, r.student_name): r.status for r in rows}
    on_leave = leave_days(days[-1], days[0])
    streaks = {}
    for st in students:
        dates = []
        for d in days:
            v = status.get((d, st.name))
            if v == "Leave" or d in on_leave.get(st.id, ()):
                continue
            if v == "Present":
                break
            if v == "Absent":
                dates.append(d)
        if dates:
            streaks[st.id] = sorted(dates)
    return streaks


# ---------------- API ----------------
# IT Hub: every endpoint below takes ?course=<course name>.
@bp.get("/attendance/today")
def get_today():
    d, c = today(), course_param()
    return ok(**summary(d, records_for(d, c)), holiday=holiday_on(d), course=c)


@bp.get("/attendance/<day_str>")
def get_day(day_str):
    d, c = parse_day(day_str), course_param()
    if not d:
        return fail("Invalid date.")
    if d != today() and d not in saved_days(course=c):
        return fail(f"No record for {day_str}.", 404)
    return ok(**summary(d, records_for(d, c)), holiday=holiday_on(d), course=c)


@bp.get("/attendance/<day_str>/export")
def export_day(day_str):
    d, c = parse_day(day_str), course_param()
    if not d:
        return fail("Invalid date.")
    tag = "".join(ch if ch.isalnum() else "-" for ch in c).strip("-")
    name = f"attendance-{tag + '-' if tag else ''}{d}.csv"
    return Response(csv_bytes(d, c), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.get("/attendance-dates")
def get_dates():
    return ok(dates=[d.isoformat() for d in saved_days(course=course_param())])


@bp.get("/history")
def get_history():
    c = course_param()
    days = list(reversed(saved_days(7, c)))
    if not days:
        return ok(history=[])
    out = []
    for d in days:   # records_for() already limits teachers to their branches
        sm = summary(d, records_for(d, c))
        p = sm["present_count"]
        t = p + sm["absent_count"]           # approved leave isn't counted
        out.append({"date": d.isoformat(), "present": p, "total": t, "percentage": round(p / t * 100) if t else 0})
    return ok(history=out)

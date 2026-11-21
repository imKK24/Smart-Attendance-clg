"""Charts data (trend, weekday, branch, month) and the 'students at risk' list."""
from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, request

import attendance
import reports
from auth import scope_query
from common import fmt_day, get_settings, ok, parse_day
from models import AttendanceRecord, Exam, ExamResult, Student, db
from orgs import current_org, uses_courses

bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def pct(p, t):
    return round(p / t * 100, 1) if t else None


def scoped_students(branch=""):
    with db() as s:
        q = scope_query(s.query(Student))
        if uses_courses():
            q = attendance.enrolled(q, branch)   # IT Hub: `branch` is a course
        elif branch:
            q = q.filter(Student.branch == branch)
        return q.all()


def counted_rows(start, end, names, course=None, with_course=False):
    """Present/Absent rows in the period for these students. Holidays and leave are left out.
    IT Hub: one course, or every course (course=None)."""
    holidays = attendance.holiday_dates(start)
    with db() as s:
        rows = (attendance.rec_query(s, course or None)
                .with_entities(AttendanceRecord.day, AttendanceRecord.student_name, AttendanceRecord.status,
                               AttendanceRecord.course)
                .filter(AttendanceRecord.day >= start, AttendanceRecord.day <= end,
                        AttendanceRecord.status.in_(("Present", "Absent"))).all())
    if with_course:
        return [(d, n, st, c) for d, n, st, c in rows if n in names and d not in holidays]
    return [(d, n, st) for d, n, st, _ in rows if n in names and d not in holidays]


@bp.get("")
def charts():
    days_back = max(7, min(int(request.args.get("days") or 60), 400))
    branch = request.args.get("branch") or ""
    end = date.today()
    start = end - timedelta(days=days_back)
    students = scoped_students(branch)
    names = {st.name for st in students}
    branch_of = {st.name: st.branch or "No branch" for st in students}
    hub = uses_courses()
    rows = counted_rows(start, end, names, branch or None, with_course=True)

    by_day = defaultdict(lambda: [0, 0])
    by_week = defaultdict(lambda: [0, 0])
    by_branch = defaultdict(lambda: [0, 0])
    for d, n, st, course in rows:
        hit = 1 if st == "Present" else 0
        group = (course or "No course") if hub else branch_of[n]   # IT Hub: compare courses
        for bucket, key in ((by_day, d), (by_week, d.weekday()), (by_branch, group)):
            bucket[key][0] += hit
            bucket[key][1] += 1

    # last 6 calendar months (separate query so the chart is always 6 months long)
    m_start = (end.replace(day=1) - timedelta(days=150)).replace(day=1)
    by_month = defaultdict(lambda: [0, 0])
    for d, n, st in counted_rows(m_start, end, names, branch or None):
        by_month[d.strftime("%Y-%m")][0] += st == "Present"
        by_month[d.strftime("%Y-%m")][1] += 1
    months, cur = [], m_start
    while cur <= end:
        k = cur.strftime("%Y-%m")
        months.append({"month": k, "label": cur.strftime("%b"), "percentage": pct(*by_month[k]) if k in by_month else None})
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)

    trend = [{"date": d.isoformat(), "percentage": pct(p, t), "present": p, "total": t}
             for d, (p, t) in sorted(by_day.items())]
    weekday = [{"day": WEEKDAYS[w], "percentage": pct(*by_week[w])} for w in range(6) if w in by_week]
    def members(b):
        if hub:
            return sum(1 for x in students if b in (x.units or x.courses or []))
        return sum(1 for x in students if (x.branch or "No branch") == b)
    branches = sorted(({"branch": b, "percentage": pct(p, t), "students": members(b)}
                       for b, (p, t) in by_branch.items()), key=lambda r: r["percentage"] or 0)
    total_p = sum(p for p, _ in by_day.values())
    total_t = sum(t for _, t in by_day.values())
    notes = []
    if len(weekday) > 1:
        lo = min(weekday, key=lambda r: r["percentage"])
        hi = max(weekday, key=lambda r: r["percentage"])
        if hi["percentage"] - lo["percentage"] >= 5:
            notes.append(f"{lo['day']} attendance is {round(hi['percentage'] - lo['percentage'])} points lower than {hi['day']}.")
    if len(branches) > 1 and branches[-1]["percentage"] - branches[0]["percentage"] >= 5:
        notes.append(f"{branches[0]['branch']} has the lowest attendance ({branches[0]['percentage']}%).")
    if len(trend) >= 10:
        a = pct(sum(r["present"] for r in trend[-5:]), sum(r["total"] for r in trend[-5:]))
        b = pct(sum(r["present"] for r in trend[-10:-5]), sum(r["total"] for r in trend[-10:-5]))
        if a is not None and b is not None and abs(a - b) >= 5:
            notes.append(f"The last 5 class days were {'up' if a > b else 'down'} {abs(round(a - b))} points on the 5 before.")
    return ok(trend=trend, weekday=weekday, branches=branches, months=months, average=pct(total_p, total_t),
              days=len(trend), start=start.isoformat(), notes=notes)


# ============================================================
#  STUDENTS AT RISK
# ============================================================
RECENT = 10   # class days in the "recent" window


def at_risk_rows(branch=""):
    settings = get_settings()
    minimum = float(settings.get("eligibility_min") or 75)
    students = scoped_students(branch)
    names = {st.name for st in students}
    days = sorted({d for d in attendance.saved_days(120)} - attendance.holiday_dates(date.today() - timedelta(days=200)))
    status = defaultdict(dict)
    if days:
        for d, n, st in counted_rows(days[0], days[-1], names, branch or None):
            status[n][d] = st
    streaks = attendance.absence_streaks()
    term_start = parse_day(settings.get("term_start")) or (days[0] if days else date.today())
    elig = ({} if uses_courses() and not branch   # IT Hub: eligibility is per course
            else {r["id"]: r for r in reports.eligibility(term_start, date.today(), branch, minimum)[0]})

    with db() as s:
        exams = (s.query(Exam).filter(Exam.org == current_org())
                 .order_by(Exam.exam_date.is_(None), Exam.exam_date, Exam.created_at).all())
        order = {e.id: i for i, e in enumerate(exams)}
        names_by_exam = {e.id: e.name for e in exams}
        results = defaultdict(list)
        for r in s.query(ExamResult).filter(ExamResult.student_id.in_([st.id for st in students] or [-1])):
            if r.max_total:
                results[r.student_id].append((order.get(r.exam_id, 0), names_by_exam.get(r.exam_id, "exam"),
                                              round(r.total / r.max_total * 100, 1)))

    out = []
    for st in students:
        reasons, score = [], 0
        mine = [status[st.name][d] for d in days if d in status[st.name]]
        recent, earlier = mine[-RECENT:], mine[-2 * RECENT:-RECENT]
        e = elig.get(st.id)
        if e and e["percentage"] is not None:
            if not e["eligible"]:
                reasons.append(f"Below the {minimum:g}% minimum ({e['percentage']}%)")
                score += 3
            elif e["percentage"] < minimum + 5:
                reasons.append(f"Close to the minimum ({e['percentage']}%)")
                score += 1
        streak = len(streaks.get(st.id, []))
        if streak >= 2:
            reasons.append(f"Absent {streak} class days in a row")
            score += 3 if streak >= 3 else 2
        if len(recent) >= 5 and len(earlier) >= 5:
            r_pct = pct(recent.count("Present"), len(recent))
            e_pct = pct(earlier.count("Present"), len(earlier))
            if e_pct - r_pct >= 20:
                reasons.append(f"Attendance fell from {e_pct:g}% to {r_pct:g}% (last {len(recent)} days)")
                score += 2
        marks = sorted(results.get(st.id, []))
        if marks:
            _, last_name, last_pct = marks[-1]
            if last_pct < 40:
                reasons.append(f"Scored {last_pct:g}% in {last_name}")
                score += 2
            if len(marks) >= 2 and marks[-2][2] - last_pct >= 15:
                reasons.append(f"Marks fell from {marks[-2][2]:g}% to {last_pct:g}% ({last_name})")
                score += 1
        if score >= 2:
            out.append({"id": st.id, "name": st.name, "roll_no": st.roll_no or "", "branch": st.branch,
                        "level": "high" if score >= 4 else "medium", "score": score, "reasons": reasons,
                        "attendance": e["percentage"] if e else None,
                        "parent_name": st.parent_name, "parent_phone": st.parent_phone, "parent_email": st.parent_email})
    out.sort(key=lambda r: (-r["score"], r["name"].lower()))
    return out


@bp.get("/at-risk")
def at_risk():
    rows = at_risk_rows(request.args.get("branch") or "")
    return ok(students=rows, high=sum(1 for r in rows if r["level"] == "high"), as_of=fmt_day(date.today()))

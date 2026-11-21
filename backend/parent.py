"""Parent portal (college) and student portal (Aakansha IT Hub): a read-only
view of ONE student, plus applying for leave.

Login needs all three to match what was saved at registration:
  college:  registration number + student's name + the parent's mobile number
  IT Hub:   registration number + student's name + the student's own mobile number
(Registration numbers and names are often public, so the phone number is the
part only the family / student knows.) The token it gives only opens /api/parent/*,
in that organisation's database.
"""
import re
from datetime import date, datetime, timedelta, timezone

import jwt
from flask import Blueprint, g, request

import attendance
import config
import reports
from common import Throttle, clean_text, fail, fmt_day, get_settings, iso, ok, parse_day, stamp, visitor_keys
from models import AttendanceRecord, Exam, ExamResult, FeeDue, LeaveRequest, Student, db
from orgs import COLLEGE, ITHUB, clean_org, uses_courses

bp = Blueprint("parent", __name__, url_prefix="/api/parent")
# Counted per computer AND per registration number (see common.Throttle).
_failures = Throttle(tries=5, first_lock=120)
MAX_LEAVE_DAYS = 30


def _norm(text):
    return " ".join(str(text or "").lower().split())


def _digits(text):
    return re.sub(r"\D", "", str(text or ""))[-10:]       # last 10 digits: +91 or not doesn't matter


def student():
    with db() as s:
        return s.get(Student, g.parent_sid)


@bp.post("/login")
def login():
    d = request.get_json(silent=True) or {}
    reg, name, phone = _norm(d.get("reg_no")), _norm(d.get("name")), _digits(d.get("phone"))
    org = clean_org(d.get("org"))
    g.org = org                          # look only in that organisation's database
    keys = visitor_keys(f"reg:{org}:{reg}")
    wait = _failures.wait(*keys)
    if wait:
        return fail(f"Too many wrong tries. Wait {wait} seconds.", 429)
    if not reg or not name or len(phone) < 10:
        return fail("Enter the registration number, the student's full name and your 10-digit mobile number.")
    with db() as s:
        st = next((x for x in s.query(Student).filter(Student.org == org, Student.roll_no.isnot(None))
                   if _norm(x.roll_no) == reg and _norm(x.name) == name), None)
        # college: a parent's number; IT Hub: the student's own number
        phones = ({st.student_phone} if org == ITHUB else {st.parent_phone, st.alt_phone}) if st else set()
        good = st and phone in {_digits(p) for p in phones} - {""}
    if not good:   # one message for every mismatch: don't reveal which part was wrong
        _failures.failed(*keys)
        where = "Aakansha IT Hub" if org == ITHUB else "the college"
        return fail(f"These details don't match our records. Use the mobile number you gave {where}.", 401)
    _failures.passed(*keys)
    exp = datetime.now(timezone.utc) + timedelta(hours=config.PARENT_TOKEN_HOURS)
    role = "student" if org == ITHUB else "parent"
    token = jwt.encode({"sub": f"{role}:{st.id}", "kind": "parent", "org": org, "sid": st.id, "exp": exp},
                       config.SECRET_KEY, algorithm="HS256")
    return ok(token=token, user={"role": role, "org": org, "student": st.name,
                                 "username": st.name if org == ITHUB else (st.parent_name or "Parent")})


@bp.get("/me")
def me():
    st = student()
    sc = get_settings()
    return ok(student={"name": st.name, "reg_no": st.roll_no or "", "branch": st.branch, "class_name": st.class_name,
                       "parent_name": st.parent_name, "school": sc.get("school_name") or "",
                       "courses": st.courses or [], "batches": st.batches or {}, "org": g.org})


@bp.get("/attendance")
def my_attendance():
    """Semester %, eligibility, this month's register and the last 30 class days.
    IT Hub: the same numbers for each course the student joined."""
    st = student()
    sc = get_settings()
    minimum = float(sc.get("eligibility_min") or 75)
    start = parse_day(sc.get("term_start"))
    if not start:
        days = attendance.saved_days()
        start = days[-1] if days else date.today()
    if uses_courses():
        from courses import unit_key   # each course in the student's own batch
        return ok(minimum=minimum, start=iso(start), courses=[
            _course_attendance(st, unit_key(c, (st.batches or {}).get(c, "")), start, minimum) for c in (st.courses or [])])
    row = next((r for r in reports.eligibility(start, date.today(), "", minimum)[0] if r["id"] == st.id), None)
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    if not reports.month_range(month)[0]:
        month = date.today().strftime("%Y-%m")
    m = reports.monthly(month, "")
    mrow = next((r for r in m["rows"] if r["id"] == st.id), {"marks": [], "present": 0, "absent": 0, "leave": 0, "percentage": None})
    with db() as s:
        recent = (s.query(AttendanceRecord).filter(AttendanceRecord.org == COLLEGE,
                                                   AttendanceRecord.student_name == st.name)
                  .order_by(AttendanceRecord.day.desc()).limit(30).all())
    return ok(minimum=minimum, start=iso(start),
              summary={k: row[k] for k in ("present", "absent", "leave", "percentage", "eligible", "need", "can_miss")} if row else None,
              month=month, days=m["columns"], holidays=m["holidays"], marks=mrow["marks"],
              month_totals={k: mrow[k] for k in ("present", "absent", "leave", "percentage")},
              recent=[{"date": iso(r.day), "status": r.status, "time": r.time} for r in recent])


def _course_attendance(st, course, start, minimum):
    """One IT Hub course: % since the start date, eligibility, and the last 15 classes."""
    row = next((r for r in reports.eligibility(start, date.today(), course, minimum)[0] if r["id"] == st.id), None)
    with db() as s:
        recent = (attendance.rec_query(s, course).filter(AttendanceRecord.student_name == st.name)
                  .order_by(AttendanceRecord.day.desc()).limit(15).all())
    keys = ("present", "absent", "leave", "percentage", "eligible", "need", "can_miss")
    return {"course": course, "summary": {k: row[k] for k in keys} if row else None,
            "recent": [{"date": iso(r.day), "status": r.status, "time": r.time} for r in recent]}


@bp.get("/results")
def my_results():
    st = student()
    with db() as s:
        rows = (s.query(ExamResult, Exam).join(Exam, Exam.id == ExamResult.exam_id)
                .filter(ExamResult.student_id == st.id).order_by(Exam.exam_date.is_(None), Exam.exam_date.desc(), Exam.id.desc()).all())
        out = [{"exam": e.name, "course": e.course or "", "date": iso(e.exam_date), "subjects": e.subjects,
                "marks": r.marks, "total": r.total,
                "max_total": r.max_total, "percentage": round(r.total / r.max_total * 100, 1) if r.max_total else None}
               for r, e in rows]
    return ok(results=out)


def leave_json(lv):
    return {"id": lv.id, "start_date": iso(lv.start_date), "end_date": iso(lv.end_date),
            "days": (lv.end_date - lv.start_date).days + 1, "reason": lv.reason, "status": lv.status,
            "note": lv.note, "created_at": stamp(lv.created_at), "decided_at": stamp(lv.decided_at), "source": lv.source}


@bp.get("/leaves")
def my_leaves():
    with db() as s:
        rows = (s.query(LeaveRequest).filter(LeaveRequest.student_id == g.parent_sid)
                .order_by(LeaveRequest.start_date.desc()).limit(100).all())
        return ok(leaves=[leave_json(lv) for lv in rows])


@bp.post("/leaves")
def apply_leave():
    d = request.get_json(silent=True) or {}
    start = parse_day(d.get("start_date"))
    end = parse_day(d.get("end_date") or d.get("start_date"))
    reason = str(d.get("reason") or "").strip()[:500]
    if not start or not end:
        return fail("Pick the leave dates.")
    if end < start:
        return fail("The last day can't be before the first day.")
    if (end - start).days + 1 > MAX_LEAVE_DAYS:
        return fail(f"Apply for at most {MAX_LEAVE_DAYS} days at a time.")
    if start < date.today() - timedelta(days=15):
        return fail("Leave can be applied for up to 15 days back.")
    if len(reason) < 5:
        return fail("Write the reason for the leave.")
    with db() as s:
        clash = s.query(LeaveRequest).filter(
            LeaveRequest.student_id == g.parent_sid, LeaveRequest.status != "rejected",
            LeaveRequest.start_date <= end, LeaveRequest.end_date >= start).first()
        if clash:
            return fail(f"There is already a leave for {fmt_day(clash.start_date)} to {fmt_day(clash.end_date)}.", 409)
        hub = g.org == ITHUB
        lv = LeaveRequest(student_id=g.parent_sid, start_date=start, end_date=end,
                          reason=clean_text(reason, 500), source="student" if hub else "parent", status="pending")
        s.add(lv)
        s.flush()
        who = "Your teacher or the IT Hub admin" if hub else "The class teacher"
        return ok(f"Leave application sent. {who} will approve or reject it.", leave=leave_json(lv))


@bp.get("/fees")
def my_fees():
    import fees
    with db() as s:
        rows = s.query(FeeDue).filter(FeeDue.student_id == g.parent_sid).order_by(FeeDue.due_date).all()
        return ok(fees=[{"title": f.title, "course": f.course or "", "amount": f.amount, "paid_amount": f.paid_amount,
                         "balance": max(0, f.amount - f.paid_amount), "due_date": iso(f.due_date),
                         "paid_on": iso(f.paid_on), "status": fees.status_of(f)} for f in rows])


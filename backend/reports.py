"""Attendance reports: eligibility % for exams and the month-wise register."""
import calendar
import io
import math
import re
from datetime import date

from flask import Blueprint, Response, request

import attendance
from common import fail, get_settings, ok, parse_day, safe_cell, update_settings
from models import AttendanceRecord, Student, db
from orgs import uses_courses

bp = Blueprint("reports", __name__, url_prefix="/api/reports")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def students_in(branch):
    """Students of a branch (college) or of a course (IT Hub: `branch` holds the course)."""
    from auth import scope_query
    with db() as s:
        q = scope_query(s.query(Student))
        if uses_courses():
            q = attendance.enrolled(q, branch)
        elif branch:
            q = q.filter(Student.branch == branch)
        return q.order_by(Student.roll_no, Student.name).all()


def statuses(start, end, branch=""):
    """{(day, name): status} and the register days in [start, end], holidays removed.
    IT Hub: only the classes of one course."""
    with db() as s:
        rows = attendance.rec_query(s, attendance.course_of(branch)).filter(
            AttendanceRecord.day >= start, AttendanceRecord.day <= end).all()
    holidays = attendance.holiday_dates(start)
    days = sorted({r.day for r in rows} - holidays)
    return {(r.day, r.student_name): r.status for r in rows}, days, holidays


# ============================================================
#  ELIGIBILITY
# ============================================================
def eligibility(start, end, branch, minimum):
    status, days, _ = statuses(start, end, branch)
    on_leave = attendance.leave_days(start, end)
    th = minimum / 100
    out = []
    for st in students_in(branch):
        present = absent = leave = 0
        for d in days:
            v = status.get((d, st.name))
            if v == "Leave" or (v != "Present" and d in on_leave.get(st.id, ())):
                leave += 1
            elif v == "Present":
                present += 1
            elif v == "Absent":
                absent += 1
        counted = present + absent                 # approved leave isn't held against the student
        pct = round(present / counted * 100, 1) if counted else None
        eligible = pct is None or pct >= minimum
        # classes in a row needed to get back to the minimum / classes that can still be missed
        need = 0 if eligible else math.ceil((th * counted - present) / (1 - th)) if th < 1 else None
        can_miss = max(0, math.floor(present / th - counted)) if eligible and th > 0 else 0
        out.append({"id": st.id, "name": st.name, "roll_no": st.roll_no or "", "branch": st.branch,
                    "present": present, "absent": absent, "leave": leave, "counted": counted,
                    "percentage": pct, "eligible": eligible, "need": need, "can_miss": can_miss,
                    "parent_phone": st.parent_phone})
    out.sort(key=lambda r: (r["percentage"] if r["percentage"] is not None else 101, r["name"].lower()))
    return out, days


def period_from_args():
    st = get_settings()
    end = parse_day(request.args.get("to")) or date.today()
    start = parse_day(request.args.get("from")) or parse_day(st.get("term_start"))
    if not start:
        days = attendance.saved_days()
        start = days[-1] if days else end
    try:
        minimum = float(request.args.get("min") or st.get("eligibility_min") or 75)
    except ValueError:
        minimum = 75.0
    return start, end, request.args.get("branch") or "", max(1.0, min(minimum, 100.0))


@bp.get("/eligibility")
def get_eligibility():
    start, end, branch, minimum = period_from_args()
    if uses_courses() and not branch:
        return fail("Choose a course.")
    if end < start:
        return fail("The end date is before the start date.")
    rows, days = eligibility(start, end, branch, minimum)
    return ok(rows=rows, start=start.isoformat(), end=end.isoformat(), minimum=minimum, days=len(days),
              below=sum(1 for r in rows if not r["eligible"]))


@bp.get("/settings")
def get_report_settings():
    st = get_settings()
    return ok(term_start=st.get("term_start") or "", eligibility_min=st.get("eligibility_min") or 75)


@bp.post("/settings")
def set_report_settings():
    d = request.get_json(silent=True) or {}
    term = str(d.get("term_start") or "").strip()
    if term and not parse_day(term):
        return fail("Pick a valid semester start date.")
    try:
        minimum = float(d.get("eligibility_min") or 75)
    except (TypeError, ValueError):
        return fail("Minimum % must be a number.")
    if not 1 <= minimum <= 100:
        return fail("Minimum % must be between 1 and 100.")
    update_settings(term_start=term, eligibility_min=int(minimum) if minimum.is_integer() else minimum)
    return ok("Report settings saved")


# ============================================================
#  MONTHLY REGISTER
# ============================================================
MARK = {"Present": "P", "Absent": "A", "Leave": "L"}


def month_range(text):
    if not MONTH_RE.match(text or ""):
        return None, None
    y, m = map(int, text.split("-"))
    if not 1 <= m <= 12:
        return None, None
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def monthly(month, branch):
    start, end = month_range(month)
    status, days, holidays = statuses(start, end, branch)
    hol_days = sorted(d for d in holidays if start <= d <= end and d.weekday() < 6)
    columns = sorted(set(days) | set(hol_days))
    rows = []
    for st in students_in(branch):
        marks, p, a, lv = [], 0, 0, 0
        for d in columns:
            if d in holidays:
                marks.append("H")
                continue
            m = MARK.get(status.get((d, st.name)), "")
            marks.append(m)
            p, a, lv = p + (m == "P"), a + (m == "A"), lv + (m == "L")
        counted = p + a
        rows.append({"id": st.id, "name": st.name, "roll_no": st.roll_no or "", "marks": marks,
                     "present": p, "absent": a, "leave": lv,
                     "percentage": round(p / counted * 100, 1) if counted else None})
    return {"month": month, "columns": [d.isoformat() for d in columns],
            "holidays": [d.isoformat() for d in hol_days], "rows": rows, "register_days": len(days)}


@bp.get("/monthly")
def get_monthly():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    if not month_range(month)[0]:
        return fail("Use a month like 2026-11.")
    return ok(**monthly(month, request.args.get("branch") or ""))


def _xlsx(build):
    from openpyxl import Workbook
    wb = Workbook()
    build(wb.active)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _download(data, name):
    return Response(data, headers={"Content-Disposition": f"attachment; filename={name}"},
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.get("/monthly/export")
def export_monthly():
    from openpyxl.styles import Alignment, Font, PatternFill
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    if not month_range(month)[0]:
        return fail("Use a month like 2026-11.")
    branch = request.args.get("branch") or ""
    data = monthly(month, branch)
    school = get_settings().get("school_name") or ""
    fills = {"P": "DDF4E9", "A": "FCE4E7", "L": "FFF1CF", "H": "E6EAF5"}

    def build(ws):
        ws.title = month
        title = f"Attendance register: {date.fromisoformat(month + '-01').strftime('%B %Y')}"
        ws.append([" · ".join(x for x in (school, title, branch) if x)])
        ws["A1"].font = Font(bold=True, size=13)
        days = [date.fromisoformat(d) for d in data["columns"]]
        ws.append(["Registration No", "Name"] + [d.day for d in days] + ["Present", "Absent", "Leave", "%"])
        ws.append(["", ""] + [d.strftime("%a") for d in days] + ["", "", "", ""])
        for c in list(ws[2]) + list(ws[3]):
            c.font, c.alignment = Font(bold=True), Alignment(horizontal="center")
        for r in data["rows"]:
            ws.append([safe_cell(r["roll_no"]), safe_cell(r["name"])] + r["marks"] + [r["present"], r["absent"], r["leave"],
                                                               r["percentage"] if r["percentage"] is not None else "-"])
            for c in ws[ws.max_row][2:2 + len(days)]:
                c.alignment = Alignment(horizontal="center")
                if c.value in fills:
                    c.fill = PatternFill("solid", fgColor=fills[c.value])
        ws.append([])
        ws.append(["P = present, A = absent, L = approved leave, H = holiday. % = present / (present + absent)."])
        ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 14, 26
        from openpyxl.utils import get_column_letter
        for i in range(3, 3 + len(days)):
            ws.column_dimensions[get_column_letter(i)].width = 5
        ws.freeze_panes = "C4"

    return _download(_xlsx(build), f"register-{month}{'-' + branch if branch else ''}.xlsx")


@bp.get("/eligibility/export")
def export_eligibility():
    from openpyxl.styles import Font, PatternFill
    start, end, branch, minimum = period_from_args()
    rows, days = eligibility(start, end, branch, minimum)

    def build(ws):
        ws.title = "Eligibility"
        ws.append([f"Attendance eligibility {start:%d %b %Y} to {end:%d %b %Y} (minimum {minimum:g}%)"
                   + (f" · {branch}" if branch else "")])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append(["Registration No", "Name", "Branch", "Present", "Absent", "Leave", "Attendance %", "Eligible",
                   "Classes needed to reach minimum"])
        for c in ws[2]:
            c.font = Font(bold=True)
        for r in sorted(rows, key=lambda r: (r["roll_no"], r["name"])):
            ws.append([safe_cell(r["roll_no"]), safe_cell(r["name"]), safe_cell(r["branch"]), r["present"], r["absent"], r["leave"],
                       r["percentage"] if r["percentage"] is not None else "-",
                       "Yes" if r["eligible"] else "No", r["need"] or ""])
            if not r["eligible"]:
                for c in ws[ws.max_row]:
                    c.fill = PatternFill("solid", fgColor="FCE4E7")
        for col, w in zip("ABCDEFGHI", (14, 26, 10, 9, 9, 8, 14, 9, 30)):
            ws.column_dimensions[col].width = w

    return _download(_xlsx(build), f"eligibility-{start}-to-{end}.xlsx")

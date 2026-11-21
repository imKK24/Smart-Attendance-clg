"""Events, holidays and exam results, and sending them to parents/students."""
import csv
import io
import re

from flask import Blueprint, Response, request
from sqlalchemy import func

from auth import scope_query
from common import (TIME_RE, safe_cell, channels_from, clean_text, email_ready, fail, fmt_day, get_settings, iso, ok,
                    parse_day, plural, stamp)
from models import Event, Exam, ExamResult, Holiday, Student, db, now
from orgs import current_org, uses_courses


def own(s, model, oid):
    """Holiday / event / exam by id, only if it belongs to this organisation."""
    obj = s.get(model, oid)
    return obj if obj is not None and (obj.org or "college") == current_org() else None


def exam_students(q, exam):
    """IT Hub tests are for one course: only its students."""
    import attendance
    return attendance.enrolled(q, exam.course) if uses_courses() and exam.course else q
from notify import enqueue, html_wrap, parent_targets, sign

bp = Blueprint("content", __name__, url_prefix="/api")
MAX_UPLOAD = 2 * 1024 * 1024


def usable_channels(raw, st):
    channels = channels_from(raw)
    if "email" in channels and not email_ready(st):
        channels.remove("email")
    return channels


def message_items(kind, st_settings, channels, title, lines, students=None, to_parents=True, to_students=False,
                  extra=None):
    """Build one WhatsApp text + one email per recipient, without duplicates."""
    items, seen = [], set()
    with db() as s:
        students = students if students is not None else (
            s.query(Student).filter(Student.org == current_org()).order_by(Student.name).all())
    footer = sign(st_settings)
    for st in students:
        targets = []
        if to_parents:
            greet = f"Dear {st.parent_name or 'Parent or Guardian'}"
            targets += [(c, a, greet) for c, a in parent_targets(st, channels)]
        if to_students:
            greet = f"Hi {st.name}"
            if "whatsapp" in channels and st.student_phone:
                targets.append(("whatsapp", st.student_phone, greet))
            if "email" in channels and st.student_email:
                targets.append(("email", st.student_email, greet))
        for channel, to, greet in targets:
            key = (channel, to.lower())
            if key in seen:
                continue
            seen.add(key)
            body_lines = lines(st) if callable(lines) else lines
            item = {"channel": channel, "kind": kind, "to": to, "who": st.name, "student_id": st.id,
                    "meta": (extra(st) if callable(extra) else {})}
            if channel == "whatsapp":
                item["body"] = f"*{title}*\n\n{greet},\n" + "\n".join(body_lines) + f"\n\n- {footer}"
            else:
                item.update(subject=title, body=f"{greet},\n\n" + "\n".join(body_lines) + f"\n\nRegards,\n{footer}",
                            html=html_wrap(title, [greet + ","] + list(body_lines), f"Regards, {footer}"))
            items.append(item)
    return items


# ============================================================
#  EVENTS
# ============================================================
def event_json(e):
    return {"id": e.id, "title": e.title, "date": iso(e.date), "time": e.time, "venue": e.venue,
            "description": e.description, "last_notified_at": stamp(e.last_notified_at),
            "last_recipients": e.last_recipients}


@bp.get("/events")
def list_events():
    with db() as s:
        return ok(events=[event_json(e) for e in s.query(Event).filter(Event.org == current_org()).order_by(Event.date, Event.time)])


@bp.post("/events")
def create_event():
    d = request.get_json(silent=True) or {}
    title, day, when = clean_text(d.get("title"), 80), parse_day(d.get("date")), str(d.get("time") or "").strip()
    if not title:
        return fail("Give the event a title.")
    if not day:
        return fail("Pick a valid date.")
    if when and not TIME_RE.match(when):
        return fail("Enter the time like 14:30.")
    with db() as s:
        e = Event(org=current_org(), title=title, date=day, time=when, venue=clean_text(d.get("venue"), 80),
                  description=str(d.get("description") or "").strip()[:1000])
        s.add(e)
        s.flush()
        return ok("Event saved", event=event_json(e))


@bp.delete("/events/<int:eid>")
def delete_event(eid):
    with db() as s:
        e = own(s, Event, eid)
        if not e:
            return fail("Event not found.", 404)
        s.delete(e)
    return ok("Event deleted")


@bp.post("/events/<int:eid>/notify")
def notify_event(eid):
    d = request.get_json(silent=True) or {}
    st = get_settings()
    channels = usable_channels(d.get("channels"), st)
    to_students, to_parents = bool(d.get("to_students", True)), bool(d.get("to_parents"))
    with db() as s:
        e = own(s, Event, eid)
        if not e:
            return fail("Event not found.", 404)
        ev = event_json(e)
    when = fmt_day(ev["date"]) + (f" at {ev['time']}" if ev["time"] else "")
    lines = [f"Event: {ev['title']}", f"When: {when}"]
    if ev["venue"]:
        lines.append(f"Where: {ev['venue']}")
    if ev["description"]:
        lines += ["", ev["description"]]
    items = message_items("event", st, channels, f"Event: {ev['title']} on {fmt_day(ev['date'])}", lines,
                          to_parents=to_parents, to_students=to_students)
    if not items:
        return fail("Nobody to send to. Check the channels and that students have phone numbers or emails saved.")
    _, n = enqueue(items)
    with db() as s:
        e = own(s, Event, eid)
        e.last_notified_at, e.last_recipients = now(), n
    return ok(f"Sending {plural(n, 'message')}", queued=n)


# ============================================================
#  HOLIDAYS (also skipped when counting absence streaks)
# ============================================================
def holiday_json(h):
    return {"id": h.id, "title": h.title, "start_date": iso(h.start_date), "end_date": iso(h.end_date),
            "note": h.note, "last_notified_at": stamp(h.last_notified_at), "last_recipients": h.last_recipients}


def holiday_when(h):
    if h["start_date"] == h["end_date"]:
        return f"on {fmt_day(h['start_date'])}"
    return f"from {fmt_day(h['start_date'])} to {fmt_day(h['end_date'])}"


@bp.get("/holidays")
def list_holidays():
    with db() as s:
        return ok(holidays=[holiday_json(h) for h in s.query(Holiday).filter(Holiday.org == current_org()).order_by(Holiday.start_date)])


@bp.post("/holidays")
def create_holiday():
    d = request.get_json(silent=True) or {}
    title = clean_text(d.get("title"), 80)
    start, end = parse_day(d.get("start_date")), parse_day(d.get("end_date") or d.get("start_date"))
    if not title:
        return fail("Give the holiday a name, e.g. Diwali.")
    if not start or not end:
        return fail("Pick the holiday dates.")
    if end < start:
        return fail("The last day can't be before the first day.")
    if (end - start).days > 120:
        return fail("A holiday can be at most 120 days long.")
    with db() as s:
        h = Holiday(org=current_org(), title=title, start_date=start, end_date=end, note=str(d.get("note") or "").strip()[:600])
        s.add(h)
        s.flush()
        return ok("Holiday saved", holiday=holiday_json(h))


@bp.delete("/holidays/<int:hid>")
def delete_holiday(hid):
    with db() as s:
        h = own(s, Holiday, hid)
        if not h:
            return fail("Holiday not found.", 404)
        s.delete(h)
    return ok("Holiday deleted")


@bp.post("/holidays/<int:hid>/notify")
def notify_holiday(hid):
    d = request.get_json(silent=True) or {}
    st = get_settings()
    channels = usable_channels(d.get("channels"), st)
    with db() as s:
        h = own(s, Holiday, hid)
        if not h:
            return fail("Holiday not found.", 404)
        hj = holiday_json(h)
    lines = [f"The college will be closed for {hj['title']} {holiday_when(hj)}."]
    if hj["note"]:
        lines += ["", hj["note"]]
    items = message_items("holiday", st, channels, f"Holiday notice: {hj['title']}", lines,
                          to_parents=True, to_students=bool(d.get("to_students")))
    if not items:
        return fail("No parent phone numbers or emails are saved for the chosen channels.")
    _, n = enqueue(items)
    with db() as s:
        h = own(s, Holiday, hid)
        h.last_notified_at, h.last_recipients = now(), n
    return ok(f"Sending {plural(n, 'message')}", queued=n)


# ============================================================
#  EXAMS: create, upload marks (CSV / Excel), send results
# ============================================================
ABSENT_WORDS = {"ab", "a", "abs", "absent"}


def exam_json(e, count=None):
    return {"id": e.id, "name": e.name, "exam_date": iso(e.exam_date), "subjects": e.subjects or [],
            "max_total": sum(x["max"] for x in e.subjects or []), "published_at": stamp(e.published_at),
            "last_recipients": e.last_recipients, "results_count": count, "course": e.course or ""}


def result_json(r, st):
    pct = round(r.total / r.max_total * 100, 1) if r.max_total else 0
    return {"id": r.id, "student_id": st.id, "name": st.name, "roll_no": st.roll_no or "", "marks": r.marks,
            "total": r.total, "max_total": r.max_total, "percentage": pct, "notified_at": stamp(r.notified_at),
            "has_contact": bool(st.parent_phone or st.parent_email)}


def clean_subjects(raw):
    out, names = [], set()
    for item in (raw if isinstance(raw, list) else [])[:15]:
        name = clean_text((item or {}).get("name"), 40)
        if not name:
            continue
        if name.lower() in names:
            return None, f"Subject '{name}' is listed twice."
        try:
            mx = float((item or {}).get("max") or 0)
        except (TypeError, ValueError):
            mx = 0
        if not 0 < mx <= 1000:
            return None, f"Give '{name}' a maximum mark between 1 and 1000."
        names.add(name.lower())
        out.append({"name": name, "max": int(mx) if mx.is_integer() else mx})
    if not out:
        return None, "Add at least one subject."
    return out, None


@bp.get("/exams")
def list_exams():
    with db() as s:
        exams = s.query(Exam).filter(Exam.org == current_org()).order_by(Exam.created_at.desc()).all()
        counts = {eid: n for eid, n in s.query(ExamResult.exam_id, func.count())
                  .group_by(ExamResult.exam_id)}
        return ok(exams=[exam_json(e, counts.get(e.id, 0)) for e in exams])


@bp.post("/exams")
def create_exam():
    d = request.get_json(silent=True) or {}
    name = clean_text(d.get("name"), 80)
    if not name:
        return fail("Give the exam a name, e.g. Mid-term 1.")
    subjects, error = clean_subjects(d.get("subjects"))
    if error:
        return fail(error)
    day = parse_day(d.get("exam_date")) if d.get("exam_date") else None
    with db() as s:
        course = str(d.get("course") or "").strip() if uses_courses() else ""
        from courses import all_course_names
        if uses_courses() and course not in all_course_names():
            return fail("Choose the course this test is for.")
        from auth import scope
        if uses_courses() and scope() is not None and not any(
                u == course or u.startswith(course + " · ") for u in scope()):
            return fail("You can only create tests for your own courses.", 403)
        e = Exam(org=current_org(), course=course, name=name, exam_date=day, subjects=subjects)
        s.add(e)
        s.flush()
        return ok("Exam created. Now upload the marks.", exam=exam_json(e, 0))


@bp.get("/exams/<int:eid>")
def get_exam(eid):
    with db() as s:
        e = own(s, Exam, eid)
        if not e:
            return fail("Exam not found.", 404)
        rows = scope_query(s.query(ExamResult, Student).join(Student, Student.id == ExamResult.student_id)
                           .filter(ExamResult.exam_id == eid)).order_by(Student.name).all()
        have = {st.id for _, st in rows}
        missing = [{"id": st.id, "name": st.name, "roll_no": st.roll_no or ""}
                   for st in exam_students(scope_query(s.query(Student)), e).order_by(Student.name)
                   if st.id not in have]
        return ok(exam=exam_json(e, len(rows)), results=[result_json(r, st) for r, st in rows], missing=missing)


@bp.delete("/exams/<int:eid>")
def delete_exam(eid):
    with db() as s:
        e = own(s, Exam, eid)
        if not e:
            return fail("Exam not found.", 404)
        s.delete(e)
    return ok("Exam deleted")


@bp.get("/exams/<int:eid>/template")
def exam_template(eid):
    """An Excel sheet with every student listed, ready for marks."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    with db() as s:
        e = own(s, Exam, eid)
        if not e:
            return fail("Exam not found.", 404)
        students = exam_students(scope_query(s.query(Student)), e).order_by(Student.roll_no, Student.name).all()
        existing = {r.student_id: r.marks for r in s.query(ExamResult).filter(ExamResult.exam_id == eid)}
        subjects = e.subjects
        title = e.name
    wb = Workbook()
    ws = wb.active
    ws.title = "Marks"
    ws.append(["Registration No", "Name"] + [f"{x['name']} (/{x['max']})" for x in subjects])
    for c in ws[1]:
        c.font = Font(bold=True)
    for st in students:
        marks = existing.get(st.id, {})
        ws.append([safe_cell(st.roll_no or ""), safe_cell(st.name)] + [marks.get(x["name"], "") for x in subjects])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 14, 28
    ws.freeze_panes = "C2"
    buf = io.BytesIO()
    wb.save(buf)
    safe = re.sub(r"[^\w\-]+", "-", title).strip("-") or "exam"
    return Response(buf.getvalue(), headers={"Content-Disposition": f"attachment; filename=marks-{safe}.xlsx"},
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def read_table(filename, raw):
    """Rows (lists of strings) from a .csv or .xlsx upload."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [["" if v is None else str(v).strip() for v in row] for row in ws.iter_rows(values_only=True)]
    if filename.lower().endswith(".csv"):
        text = raw.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [[c.strip() for c in row] for row in csv.reader(io.StringIO(text), dialect)]
    raise ValueError("Upload a .xlsx (Excel) or .csv file.")


def _norm(text):
    return re.sub(r"\(.*?\)", "", str(text)).strip().lower()


@bp.post("/exams/<int:eid>/upload")
def upload_marks(eid):
    f = request.files.get("file")
    if not f or not f.filename:
        return fail("Choose a file to upload.")
    raw = f.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        return fail("The file is bigger than 2 MB.")
    try:
        rows = [r for r in read_table(f.filename, raw) if any(c for c in r)]
    except ValueError as e:
        return fail(str(e))
    except Exception:
        return fail("That file couldn't be read. Save it as .xlsx or .csv and try again.")
    if len(rows) < 2:
        return fail("The file has no student rows.")

    with db() as s:
        e = own(s, Exam, eid)
        if not e:
            return fail("Exam not found.", 404)
        subjects = e.subjects
        header = [_norm(h) for h in rows[0]]
        roll_col = next((i for i, h in enumerate(header) if h in ("registration no", "registration number", "reg no", "reg. no", "regd no", "regd. no",
                                                                     "roll no", "roll", "roll number", "rollno", "roll no.")), None)
        name_col = next((i for i, h in enumerate(header) if h in ("name", "student name", "student")), None)
        if roll_col is None and name_col is None:
            return fail("The first row needs a 'Registration No' or 'Name' column. Download the template to see the layout.")
        subj_cols = {x["name"]: header.index(x["name"].lower()) for x in subjects if x["name"].lower() in header}
        if not subj_cols:
            return fail("No subject columns found. The column names must match: "
                        + ", ".join(x["name"] for x in subjects))
        by_roll = {(st.roll_no or "").strip().lower(): st for st in exam_students(scope_query(s.query(Student)), e)
                   if st.roll_no}
        by_name = {st.name.lower(): st for st in exam_students(scope_query(s.query(Student)), e)}
        maxes = {x["name"]: float(x["max"]) for x in subjects}

        saved, unmatched, problems = 0, [], []
        for n, row in enumerate(rows[1:], start=2):
            cell = lambda i: row[i] if i is not None and i < len(row) else ""  # noqa: E731
            st = by_roll.get(cell(roll_col).lower()) if cell(roll_col) else None
            st = st or by_name.get(" ".join(cell(name_col).split()).lower())
            if not st:
                unmatched.append(f"Row {n}: {cell(roll_col) or cell(name_col) or '(blank)'}")
                continue
            marks, bad = {}, False
            for subj, col in subj_cols.items():
                v = cell(col)
                if v == "":
                    continue
                if v.lower() in ABSENT_WORDS:
                    marks[subj] = "AB"
                    continue
                try:
                    num = float(v)
                except ValueError:
                    problems.append(f"Row {n} ({st.name}): '{v}' in {subj} isn't a number")
                    bad = True
                    continue
                if not 0 <= num <= maxes[subj]:
                    problems.append(f"Row {n} ({st.name}): {subj} is {v}, more than the max {maxes[subj]:g}")
                    bad = True
                    continue
                marks[subj] = int(num) if num.is_integer() else num
            if bad or not marks:
                continue
            total = sum(v for v in marks.values() if v != "AB")
            r = s.query(ExamResult).filter_by(exam_id=eid, student_id=st.id).first()
            if not r:
                r = ExamResult(exam_id=eid, student_id=st.id)
                s.add(r)
            r.marks, r.total, r.max_total = marks, total, sum(maxes.values())
            r.notified_at = None   # changed marks should be sent again
            saved += 1
    msg = f"Saved marks for {plural(saved, 'student')}."
    if unmatched:
        msg += f" {len(unmatched)} row(s) didn't match a registered student."
    if problems:
        msg += f" {len(problems)} row(s) were skipped because of errors."
    return ok(msg, saved=saved, unmatched=unmatched[:50], problems=problems[:50])


@bp.post("/exams/<int:eid>/publish")
def publish_exam(eid):
    d = request.get_json(silent=True) or {}
    st = get_settings()
    channels = usable_channels(d.get("channels"), st)
    only_new = bool(d.get("only_new", True))
    with db() as s:
        e = own(s, Exam, eid)
        if not e:
            return fail("Exam not found.", 404)
        exam = exam_json(e)
        q = scope_query(s.query(ExamResult, Student).join(Student, Student.id == ExamResult.student_id)
                        .filter(ExamResult.exam_id == eid))
        if only_new:
            q = q.filter(ExamResult.notified_at.is_(None))
        pairs = q.all()
    if not pairs:
        return fail("No results to send. Upload marks first." if not only_new else "Every result has already been sent.")
    results = {st.id: r for r, st in pairs}
    when = f" ({fmt_day(exam['exam_date'])})" if exam["exam_date"] else ""

    def lines(student):
        r = results[student.id]
        out = [f"Results of {exam['name']}{when} for {student.name}"
               + (f" (Reg. No {student.roll_no})" if student.roll_no else "") + ":", ""]
        for x in exam["subjects"]:
            v = r.marks.get(x["name"])
            if v is not None:
                out.append(f"{x['name']}: {'Absent' if v == 'AB' else f'{v:g}' if isinstance(v, float) else v}/{x['max']}")
        pct = round(r.total / r.max_total * 100, 1) if r.max_total else 0
        out += ["", f"Total: {r.total:g}/{r.max_total:g} ({pct}%)"]
        return out

    items = message_items("result", st, channels, f"Exam results: {exam['name']}", lines,
                          students=[stu for _, stu in pairs], extra=lambda stu: {"hook": "result", "result_id": results[stu.id].id})
    if not items:
        return fail("None of these students have a parent phone or email saved for the chosen channels.")
    _, n = enqueue(items)
    with db() as s:
        e = own(s, Exam, eid)
        e.published_at, e.last_recipients = now(), n
    return ok(f"Sending {plural(n, 'result message')}", queued=n)

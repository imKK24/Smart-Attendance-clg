"""Leave applications. Approved leave turns 'Absent' into 'Leave' for those days,
doesn't count toward absence alerts and isn't held against eligibility %."""
from datetime import date

from flask import Blueprint, request

import attendance
from auth import scope_query, visible
from common import channels_from, email_ready, fail, fmt_day, get_settings, iso, ok, parse_day, plural, stamp
from models import AttendanceRecord, InboxMail, LeaveRequest, Student, db, now
from notify import enqueue, html_wrap, parent_targets, sign

bp = Blueprint("leaves", __name__, url_prefix="/api/leaves")
MAX_DAYS = 60


def leave_json(lv, st):
    return {"id": lv.id, "student_id": st.id, "name": st.name, "roll_no": st.roll_no or "", "branch": st.branch,
            "start_date": iso(lv.start_date), "end_date": iso(lv.end_date),
            "days": (lv.end_date - lv.start_date).days + 1, "reason": lv.reason, "source": lv.source,
            "inbox_id": lv.inbox_id, "status": lv.status, "note": lv.note,
            "created_at": stamp(lv.created_at), "decided_at": stamp(lv.decided_at),
            "has_contact": bool(st.parent_phone or st.parent_email)}


def apply_to_register(student_id, start, end, approved):
    """Switch saved Absent <-> Leave rows in the range, and refresh the CSV copies."""
    touched = set()
    with db() as s:
        rows = s.query(AttendanceRecord).filter(AttendanceRecord.student_id == student_id,
                                                AttendanceRecord.day >= start, AttendanceRecord.day <= end).all()
        for r in rows:   # IT Hub: every course's row that day
            if approved and r.status == "Absent":
                r.status = "Leave"
                touched.add((r.day, r.course or ""))
            elif not approved and r.status == "Leave":
                r.status = "Absent"
                touched.add((r.day, r.course or ""))
    for d, course in touched:
        attendance.write_csv(d, course)
    return len({d for d, _ in touched})


def tell_parent(lv, st, channels):
    settings = get_settings()
    if not email_ready(settings):
        channels = [c for c in channels if c != "email"]
    when = fmt_day(lv["start_date"]) if lv["days"] == 1 else f"{fmt_day(lv['start_date'])} to {fmt_day(lv['end_date'])}"
    approved = lv["status"] == "approved"
    title = f"Leave {'approved' if approved else 'not approved'}: {st.name}"
    lines = [f"The leave for {st.name} on {when} has been {'approved' if approved else 'not approved'}."]
    if lv["note"]:
        lines.append(f"Note: {lv['note']}")
    items = []
    for channel, to in parent_targets(st, channels):
        greet = f"Dear {st.parent_name or 'Parent or Guardian'}"
        if channel == "whatsapp":
            body = f"*{title}*\n\n{greet},\n" + "\n".join(lines) + f"\n\n- {sign(settings)}"
            items.append({"channel": channel, "kind": "leave", "to": to, "who": st.name, "student_id": st.id, "body": body})
        else:
            items.append({"channel": channel, "kind": "leave", "to": to, "who": st.name, "student_id": st.id,
                          "subject": title, "body": f"{greet},\n\n" + "\n".join(lines) + f"\n\nRegards,\n{sign(settings)}",
                          "html": html_wrap(title, [greet + ","] + lines, f"Regards, {sign(settings)}")})
    if items:
        enqueue(items)
    return len(items)


@bp.get("")
def list_leaves():
    status = request.args.get("status")
    with db() as s:
        q = scope_query(s.query(LeaveRequest, Student).join(Student, Student.id == LeaveRequest.student_id))
        if status in ("pending", "approved", "rejected"):
            q = q.filter(LeaveRequest.status == status)
        rows = q.order_by(LeaveRequest.start_date.desc(), LeaveRequest.id.desc()).limit(300).all()
        pending = scope_query(s.query(LeaveRequest).join(Student, Student.id == LeaveRequest.student_id)
                              .filter(LeaveRequest.status == "pending")).count()
        return ok(leaves=[leave_json(lv, st) for lv, st in rows], pending=pending)


@bp.post("")
def create_leave():
    d = request.get_json(silent=True) or {}
    start = parse_day(d.get("start_date"))
    end = parse_day(d.get("end_date") or d.get("start_date"))
    if not start or not end:
        return fail("Pick the leave dates.")
    if end < start:
        return fail("The last day can't be before the first day.")
    if (end - start).days + 1 > MAX_DAYS:
        return fail(f"A leave can be at most {MAX_DAYS} days.")
    reason = str(d.get("reason") or "").strip()[:500]
    if not reason:
        return fail("Write the reason for the leave.")
    with db() as s:
        st = s.get(Student, int(d.get("student_id") or 0))
        if not visible(st):
            return fail("Choose a student.")
        overlap = s.query(LeaveRequest).filter(
            LeaveRequest.student_id == st.id, LeaveRequest.status != "rejected",
            LeaveRequest.start_date <= end, LeaveRequest.end_date >= start).first()
        if overlap:
            return fail(f"{st.name} already has a leave from {fmt_day(overlap.start_date)} to {fmt_day(overlap.end_date)}.", 409)
        inbox_id = d.get("inbox_id")
        if inbox_id and not s.get(InboxMail, int(inbox_id)):
            inbox_id = None
        approve = bool(d.get("approve"))
        lv = LeaveRequest(student_id=st.id, start_date=start, end_date=end, reason=reason,
                          source="email" if inbox_id else "admin", inbox_id=inbox_id,
                          status="approved" if approve else "pending", decided_at=now() if approve else None)
        s.add(lv)
        s.flush()
        out = leave_json(lv, st)
        sid = st.id
    if approve:
        apply_to_register(sid, start, end, True)
    return ok("Leave approved" if approve else "Leave saved. Approve it when you're ready.", leave=out)


@bp.post("/<int:lid>/decide")
def decide(lid):
    d = request.get_json(silent=True) or {}
    status = d.get("status")
    if status not in ("approved", "rejected"):
        return fail("Choose approve or reject.")
    with db() as s:
        lv = s.get(LeaveRequest, lid)
        if not lv or not visible(s.get(Student, lv.student_id)):
            return fail("Leave not found.", 404)
        was = lv.status
        lv.status, lv.note, lv.decided_at = status, str(d.get("note") or "").strip()[:300], now()
        st = s.get(Student, lv.student_id)
        out = leave_json(lv, st)
    if status != was:
        apply_to_register(out["student_id"], date.fromisoformat(out["start_date"]),
                          date.fromisoformat(out["end_date"]), status == "approved")
    sent = tell_parent(out, st, channels_from(d.get("notify"), [])) if d.get("notify") else 0
    msg = f"Leave {status}" + (f". Telling the parent ({plural(sent, 'message')})." if sent else ".")
    return ok(msg, leave=out, queued=sent)


@bp.delete("/<int:lid>")
def delete_leave(lid):
    with db() as s:
        lv = s.get(LeaveRequest, lid)
        if not lv or not visible(s.get(Student, lv.student_id)):
            return fail("Leave not found.", 404)
        args = (lv.student_id, lv.start_date, lv.end_date)
        was_approved = lv.status == "approved"
        s.delete(lv)
    if was_approved:
        apply_to_register(*args, False)
    return ok("Leave deleted")


@bp.get("/today")
def on_leave_today():
    """Students on approved leave today (shown on the Live camera page)."""
    t = date.today()
    ids = {sid for sid, days in attendance.leave_days(t, t).items() if t in days}
    with db() as s:
        names = [st.name for st in s.query(Student).filter(Student.id.in_(ids or [-1])).order_by(Student.name)]
    return ok(names=names)


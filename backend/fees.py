"""Fees: dues per student, payments, and WhatsApp / email reminders to parents.
Admin only. Reminders can also go out by themselves once a day (off by default)."""
import threading
import time
from datetime import date, timedelta

from flask import Blueprint, request

from common import channels_from, clean_text, email_ready, fail, fmt_day, get_settings, iso, ok, parse_day, plural, stamp, update_settings
from models import FeeDue, Student, db
from orgs import current_org, uses_courses


def own_fee(s, fid):
    """A fee by id, only if its student belongs to this organisation."""
    f = s.get(FeeDue, fid)
    st = s.get(Student, f.student_id) if f else None
    return f if st is not None and st.org == current_org() else None


def org_fees(s):
    """FeeDue rows of this organisation's students (as a FeeDue query)."""
    return s.query(FeeDue).filter(FeeDue.student_id.in_(
        s.query(Student.id).filter(Student.org == current_org()).scalar_subquery()))
from notify import enqueue, html_wrap, parent_targets, sign

bp = Blueprint("fees", __name__, url_prefix="/api/fees")
SOON_DAYS = 7


def inr(x):
    """45000 -> '₹45,000', 120000 -> '₹1,20,000' (Indian grouping)."""
    neg, x = x < 0, abs(x)
    whole, paise = divmod(round(x * 100), 100)
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + parts) + "," + tail
    return ("-" if neg else "") + "₹" + s + (f".{paise:02d}" if paise else "")


def status_of(f, today=None):
    today = today or date.today()
    if f.paid_amount >= f.amount:
        return "paid"
    if f.due_date < today:
        return "overdue"
    if (f.due_date - today).days <= SOON_DAYS:
        return "due_soon"
    return "partial" if f.paid_amount > 0 else "unpaid"


def fee_json(f, st):
    return {"id": f.id, "student_id": st.id, "name": st.name, "roll_no": st.roll_no or "", "branch": st.branch,
            "course": f.course or "", "title": f.title, "amount": f.amount, "paid_amount": f.paid_amount, "balance": max(0, f.amount - f.paid_amount),
            "due_date": iso(f.due_date), "paid_on": iso(f.paid_on), "note": f.note, "status": status_of(f),
            "reminders_sent": f.reminders_sent, "last_reminded_at": stamp(f.last_reminded_at),
            "has_contact": bool(st.parent_phone or st.parent_email)}


@bp.get("")
def list_fees():
    title = request.args.get("title") or ""
    with db() as s:
        rows = (s.query(FeeDue, Student).join(Student, Student.id == FeeDue.student_id)
                .filter(Student.org == current_org()).order_by(FeeDue.due_date, Student.name).all())
    items = [fee_json(f, st) for f, st in rows]
    groups = {}
    for it in items:
        g = groups.setdefault(it["title"], {"title": it["title"], "due_date": it["due_date"], "total": 0, "collected": 0,
                                            "students": 0, "paid": 0, "overdue": 0})
        g["due_date"] = min(g["due_date"], it["due_date"])
        g["total"] += it["amount"]
        g["collected"] += min(it["paid_amount"], it["amount"])
        g["students"] += 1
        g["paid"] += it["status"] == "paid"
        g["overdue"] += it["status"] == "overdue"
    return ok(fees=[i for i in items if not title or i["title"] == title],
              groups=sorted(groups.values(), key=lambda g: g["due_date"]))


@bp.post("")
def create_fee():
    """Add one fee for many students at once (all, one branch, one semester, or chosen ids)."""
    d = request.get_json(silent=True) or {}
    title = clean_text(d.get("title"), 80)
    due = parse_day(d.get("due_date"))
    try:
        amount = round(float(d.get("amount") or 0), 2)
    except (TypeError, ValueError):
        amount = 0
    if not title:
        return fail("Give the fee a name, e.g. Semester 6 tuition.")
    if not 0 < amount <= 10_000_000:
        return fail("Enter the amount in rupees.")
    if not due:
        return fail("Pick the due date.")
    with db() as s:
        q = s.query(Student).filter(Student.org == current_org())
        course = ""
        if uses_courses() and d.get("course"):   # IT Hub: a fee for one course's students
            import attendance
            course = clean_text(d.get("course"), 60)
            q = attendance.enrolled(q, course)
        if d.get("branch"):
            q = q.filter(Student.branch == d["branch"])
        if d.get("class_name"):
            q = q.filter(Student.class_name == d["class_name"])
        if d.get("student_ids"):
            q = q.filter(Student.id.in_([int(x) for x in d["student_ids"]]))
        students = q.all()
        have = {f.student_id for f in org_fees(s).filter(FeeDue.title == title)}
        added = 0
        for st in students:
            if st.id not in have:
                s.add(FeeDue(student_id=st.id, title=title, amount=amount, due_date=due, course=course))
                added += 1
    if not students:
        return fail("No students match. Check the branch and semester.")
    skipped = len(students) - added
    return ok(f"Added '{title}' for {plural(added, 'student')}" + (f" ({skipped} already had it)" if skipped else ""), added=added)


@bp.post("/<int:fid>/pay")
def pay(fid):
    """Record a payment. {full: true} = paid in full; otherwise {amount} is added."""
    d = request.get_json(silent=True) or {}
    with db() as s:
        f = own_fee(s, fid)
        if not f:
            return fail("Fee not found.", 404)
        if d.get("full"):
            add = f.amount - f.paid_amount
        else:
            try:
                add = round(float(d.get("amount") or 0), 2)
            except (TypeError, ValueError):
                add = 0
            if add <= 0:
                return fail("Enter the amount paid.")
        f.paid_amount = round(min(f.amount, f.paid_amount + add), 2)
        f.paid_on = parse_day(d.get("paid_on")) or date.today()
        if "note" in d:
            f.note = clean_text(d.get("note"), 200)
        st = s.get(Student, f.student_id)
        out = fee_json(f, st)
    msg = f"{st.name}: paid in full" if out["status"] == "paid" else f"{st.name}: {inr(out['balance'])} still due"
    return ok(msg, fee=out)


@bp.post("/<int:fid>/undo")
def undo_payment(fid):
    with db() as s:
        f = own_fee(s, fid)
        if not f:
            return fail("Fee not found.", 404)
        f.paid_amount, f.paid_on = 0, None
    return ok("Payment removed")


@bp.put("/<int:fid>")
def edit_fee(fid):
    d = request.get_json(silent=True) or {}
    with db() as s:
        f = own_fee(s, fid)
        if not f:
            return fail("Fee not found.", 404)
        if "amount" in d:
            try:
                f.amount = round(float(d["amount"]), 2)
            except (TypeError, ValueError):
                return fail("Enter the amount in rupees.")
        if d.get("due_date"):
            f.due_date = parse_day(d["due_date"]) or f.due_date
        if "note" in d:
            f.note = clean_text(d.get("note"), 200)
    return ok("Fee updated")


@bp.delete("/<int:fid>")
def delete_fee(fid):
    with db() as s:
        f = own_fee(s, fid)
        if not f:
            return fail("Fee not found.", 404)
        s.delete(f)
    return ok("Fee removed for this student")


@bp.post("/delete-title")
def delete_title():
    title = clean_text((request.get_json(silent=True) or {}).get("title"), 80)
    with db() as s:
        n = org_fees(s).filter(FeeDue.title == title).delete(synchronize_session=False)
    return ok(f"Removed '{title}' for {plural(n, 'student')}")


# ---------------- reminders ----------------
def reminder_items(pairs, channels):
    st_settings = get_settings()
    if not email_ready(st_settings):
        channels = [c for c in channels if c != "email"]
    today = date.today()
    items = []
    for f, st in pairs:
        bal = f.amount - f.paid_amount
        if bal <= 0:
            continue
        late = (today - f.due_date).days
        when = (f"was due on {fmt_day(f.due_date)} and is {plural(late, 'day')} overdue" if late > 0
                else "is due today" if late == 0 else f"is due on {fmt_day(f.due_date)}")
        lines = [f"This is a reminder that {f.title} for {st.name}" + (f" (Reg. No {st.roll_no})" if st.roll_no else "") + f" {when}.",
                 f"Amount due: {inr(bal)}" + (f" (paid so far: {inr(f.paid_amount)})" if f.paid_amount else ""),
                 "Please ignore this message if you have already paid."]
        title = "Fee overdue" if late > 0 else "Fee reminder"
        greet = f"Dear {st.parent_name or 'Parent or Guardian'}"
        meta = {"hook": "fee", "fee_id": f.id}
        for channel, to in parent_targets(st, channels):
            if channel == "whatsapp":
                body = f"*{title}*\n\n{greet},\n" + "\n".join(lines) + f"\n\n- {sign(st_settings)}"
                items.append({"channel": channel, "kind": "fee", "to": to, "who": st.name, "student_id": st.id, "body": body, "meta": meta})
            else:
                items.append({"channel": channel, "kind": "fee", "to": to, "who": st.name, "student_id": st.id, "meta": meta,
                              "subject": f"{title}: {f.title} for {st.name}",
                              "body": f"{greet},\n\n" + "\n".join(lines) + f"\n\nRegards,\n{sign(st_settings)}",
                              "html": html_wrap(title, [greet + ","] + lines, f"Regards, {sign(st_settings)}")})
    return items


@bp.post("/remind")
def remind():
    """{ids: [..]} or {title, which: 'overdue' | 'unpaid'}; channels optional."""
    d = request.get_json(silent=True) or {}
    channels = channels_from(d.get("channels"), get_settings()["fee_channels"])
    with db() as s:
        q = (s.query(FeeDue, Student).join(Student, Student.id == FeeDue.student_id)
             .filter(Student.org == current_org(), FeeDue.paid_amount < FeeDue.amount))
        if d.get("ids"):
            q = q.filter(FeeDue.id.in_([int(x) for x in d["ids"]]))
        if d.get("title"):
            q = q.filter(FeeDue.title == d["title"])
        if d.get("which") == "overdue":
            q = q.filter(FeeDue.due_date < date.today())
        pairs = q.all()
    if not pairs:
        return fail("Nobody to remind: everyone in this list has paid.")
    items = reminder_items(pairs, channels)
    if not items:
        return fail("None of these parents has a phone or email saved for the chosen channels.")
    _, n = enqueue(items)
    return ok(f"Sending {plural(n, 'reminder')}", queued=n)


def due_for_auto(today=None):
    """Unpaid fees that need a reminder today under the automatic rules."""
    st = get_settings()
    today = today or date.today()
    before, repeat = int(st.get("fee_days_before") or 3), max(1, int(st.get("fee_repeat_days") or 7))
    with db() as s:
        rows = (s.query(FeeDue, Student).join(Student, Student.id == FeeDue.student_id)
                .filter(Student.org == current_org(), FeeDue.paid_amount < FeeDue.amount,
                        FeeDue.due_date <= today + timedelta(days=before)).all())
    return [(f, stu) for f, stu in rows
            if not f.last_reminded_at or (today - f.last_reminded_at.date()).days >= repeat]


def run_auto_reminders(today=None):
    st = get_settings()
    if not st.get("fee_auto"):
        return 0
    items = reminder_items(due_for_auto(today), channels_from(st["fee_channels"]))
    if items:
        enqueue(items)
    return len(items)


def _loop():
    """Check once a day (after 9 AM) while the server is running."""
    last = None
    time.sleep(30)
    while True:
        try:
            t = date.today()
            if last != t and time.localtime().tm_hour >= 9:
                last = t
                from orgs import ORGS, as_org
                for org in ORGS:   # each organisation's own reminder settings
                    with as_org(org):
                        n = run_auto_reminders()
                    if n:
                        print(f"Fee reminders queued ({org}): {n}")
        except Exception as exc:
            print("Fee reminder error:", exc)
        time.sleep(600)


def start_auto_reminders():
    threading.Thread(target=_loop, daemon=True, name="fee-reminders").start()


@bp.get("/settings")
def get_fee_settings():
    st = get_settings()
    return ok(fee_auto=bool(st["fee_auto"]), fee_days_before=st["fee_days_before"], fee_repeat_days=st["fee_repeat_days"],
              fee_channels=channels_from(st["fee_channels"]), due_today=len(due_for_auto()))


@bp.post("/settings")
def set_fee_settings():
    d = request.get_json(silent=True) or {}
    try:
        before, repeat = int(d.get("fee_days_before", 3)), int(d.get("fee_repeat_days", 7))
    except (TypeError, ValueError):
        return fail("Use whole numbers of days.")
    if not 0 <= before <= 30 or not 1 <= repeat <= 30:
        return fail("Days before: 0 to 30. Repeat every: 1 to 30 days.")
    update_settings(fee_auto=bool(d.get("fee_auto")), fee_days_before=before, fee_repeat_days=repeat,
                    fee_channels=channels_from(d.get("fee_channels")))
    return ok("Fee reminder settings saved")


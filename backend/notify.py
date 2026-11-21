"""Outgoing messages (Gmail + WhatsApp), absence alerts, settings."""
import contextlib
import random
import smtplib
import ssl
import threading
import time
import uuid
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape

import requests
from flask import Blueprint, request
from sqlalchemy import func

import attendance
import config
from common import (CHANNELS, EMAIL_RE, channels_from, email_ready, fail, fmt_day, get_settings,
                    normalize_phone, ok, plural, stamp, update_settings)
from models import AbsenceAlert, ExamResult, InboxMail, Message, Student, db, now
from orgs import COLLEGE, current_org

bp = Blueprint("notify", __name__, url_prefix="/api")


# ============================================================
#  WhatsApp bridge client
# ============================================================
def _bridge(method, path, payload=None, timeout=20):
    try:
        r = requests.request(method, config.WA_BRIDGE_URL + path, json=payload, timeout=timeout,
                             headers={"X-Bridge-Token": config.WA_BRIDGE_TOKEN})
        data = r.json() if r.content else {}
        return r.status_code, data
    except requests.RequestException:
        return 0, {"error": "The WhatsApp bridge isn't running. Open a terminal in whatsapp-bridge and run: npm start"}
    except ValueError:
        return 500, {"error": "The WhatsApp bridge sent a bad reply."}


def wa_status():
    code, data = _bridge("GET", "/status", timeout=4)
    if code != 200:
        return {"state": "offline", "qr": None, "me": None, "error": data.get("error", "Bridge offline.")}
    return {k: data.get(k) for k in ("state", "qr", "me", "error")}


def wa_send(to, text):
    code, data = _bridge("POST", "/send", {"to": to, "text": text}, timeout=40)
    if code != 200 or not data.get("ok"):
        raise RuntimeError(data.get("error") or f"WhatsApp bridge error ({code}).")


# ============================================================
#  Gmail
# ============================================================
def friendly_mail_error(exc):
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "Gmail rejected the login. Use a 16-character App Password and turn on 2-Step Verification."
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "Gmail refused the recipient address."
    if isinstance(exc, smtplib.SMTPException):
        return str(exc) or exc.__class__.__name__
    if isinstance(exc, OSError):
        return "Could not reach Gmail. Check the internet connection."
    return str(exc) or exc.__class__.__name__


@contextlib.contextmanager
def open_smtp(st):
    smtp = smtplib.SMTP("smtp.gmail.com", 587, timeout=25)
    try:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(st["gmail"], st["app_password"])
        yield smtp
    finally:
        with contextlib.suppress(Exception):
            smtp.quit()


def build_email(st, to, subject, text, html=None, meta=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((st["sender_name"], st["gmail"]))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=st["gmail"].split("@")[-1] or None)
    meta = meta or {}
    if meta.get("in_reply_to"):
        msg["In-Reply-To"] = meta["in_reply_to"]
        msg["References"] = (meta.get("references", "") + " " + meta["in_reply_to"]).strip()
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def html_wrap(title, paragraphs, footer):
    body = "".join(f"<p style='margin:0 0 12px'>{escape(p)}</p>" for p in paragraphs if p)
    return ("<div style=\"font-family:'Segoe UI',Arial,sans-serif;font-size:15px;color:#14172B;"
            "max-width:540px;line-height:1.5\">"
            f"<h2 style='margin:0 0 16px'>{escape(title)}</h2>{body}"
            f"<p style='color:#6F748C;margin-top:24px'>{escape(footer)}</p></div>")


# ============================================================
#  Queue: every message is a row; one worker sends them in order
# ============================================================
_wake = threading.Event()
_worker = None


def enqueue(items):
    """items: dicts with channel, kind, to, body (+ who, subject, html, student_id, meta).
    Returns (batch id, count)."""
    batch = uuid.uuid4().hex[:12]
    with db() as s:
        for it in items:
            s.add(Message(org=current_org(), batch=batch, channel=it["channel"], kind=it["kind"], to=it["to"], body=it["body"],
                          who=it.get("who", ""), subject=it.get("subject", ""), html=it.get("html"),
                          student_id=it.get("student_id"), meta=it.get("meta") or {}))
    _wake.set()
    return batch, len(items)


def _after_sent(s, m):
    hook = (m.meta or {}).get("hook")
    if hook == "absence":
        from datetime import date
        start = date.fromisoformat(m.meta["streak_start"])
        row = s.query(AbsenceAlert).filter_by(student_id=m.meta["student_id"], streak_start=start).first()
        if not row:
            row = AbsenceAlert(student_id=m.meta["student_id"], streak_start=start, days=m.meta["days"], channels=[])
            s.add(row)
        row.days, row.sent_at = m.meta["days"], now()
        row.channels = sorted(set((row.channels or []) + [m.channel]))
    elif hook == "result":
        r = s.get(ExamResult, m.meta["result_id"])
        if r:
            r.notified_at = now()
    elif hook == "fee":
        from models import FeeDue
        f = s.get(FeeDue, m.meta["fee_id"])
        if f and (not f.last_reminded_at or (now() - f.last_reminded_at).total_seconds() > 600):
            f.reminders_sent += 1          # WhatsApp + email to one parent count as one reminder
        if f:
            f.last_reminded_at = now()
    elif hook == "reply":
        mail = s.get(InboxMail, m.meta["inbox_id"])
        if mail:
            mail.replied_at, mail.is_read = now(), True


def _work():
    while True:
        _wake.wait(15)
        _wake.clear()
        try:
            process_queue()
        except Exception as exc:  # database down etc.: try again on the next wake-up
            print("Message worker error:", exc)
            time.sleep(5)


def process_queue():
    """Send every queued message of both organisations (each database has its own queue)."""
    from orgs import ORGS, as_org
    for org in ORGS:
        with as_org(org):
            _process_queue()


def _process_queue():
    """Send every queued message, oldest first."""
    smtp_cm = smtp = None
    last_wa = 0.0
    try:
        while True:
            with db() as s:
                m = s.query(Message).filter(Message.status == "queued").order_by(Message.id).first()
                if not m:
                    break
                mid, channel = m.id, m.channel
                payload = (m.to, m.subject, m.body, m.html, dict(m.meta or {}))
            st = get_settings()
            error = ""
            try:
                to, subject, body, html, meta = payload
                if channel == "email":
                    if not email_ready(st):
                        raise RuntimeError("Gmail isn't set up. Add it under Notify > Settings.")
                    if smtp is None:
                        smtp_cm = open_smtp(st)
                        smtp = smtp_cm.__enter__()
                    smtp.send_message(build_email(st, to, subject, body, html, meta))
                    time.sleep(0.4)
                else:
                    delay = max(2, int(st.get("wa_delay") or 6))
                    wait = last_wa + random.uniform(delay, delay * 1.6) - time.time()
                    if last_wa and wait > 0:
                        time.sleep(wait)   # spaced out so WhatsApp doesn't flag the number
                    wa_send(to, body)
                    last_wa = time.time()
            except Exception as exc:
                error = friendly_mail_error(exc) if channel == "email" else str(exc)
                if channel == "email" and smtp is not None:
                    with contextlib.suppress(Exception):
                        smtp_cm.__exit__(None, None, None)
                    smtp_cm = smtp = None
            with db() as s:
                m = s.get(Message, mid)
                if error:
                    m.status, m.error = "failed", error[:500]
                else:
                    m.status, m.sent_at, m.error = "sent", now(), ""
                    _after_sent(s, m)
    finally:
        if smtp_cm is not None:
            with contextlib.suppress(Exception):
                smtp_cm.__exit__(None, None, None)


def start_worker():
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_work, daemon=True, name="message-worker")
        _worker.start()
        _wake.set()


def message_json(m):
    return {"id": m.id, "batch": m.batch, "channel": m.channel, "kind": m.kind, "who": m.who, "to": m.to,
            "subject": m.subject, "body": m.body, "status": m.status, "error": m.error,
            "created_at": stamp(m.created_at), "sent_at": stamp(m.sent_at)}


# ============================================================
#  Contacts for a student, per channel
# ============================================================
def parent_targets(st, channels):
    """[(channel, address)] for the student's parent."""
    out = []
    if "whatsapp" in channels and st.parent_phone:
        out.append(("whatsapp", st.parent_phone))
    if "email" in channels and st.parent_email:
        out.append(("email", st.parent_email))
    return out


def sign(st_settings):
    name = st_settings["sender_name"]
    school = st_settings.get("school_name")
    return f"{name}, {school}" if school else name


# ============================================================
#  Absence alerts (N school days absent in a row)
# ============================================================
def alert_rows():
    st_settings = get_settings()
    channels = channels_from(st_settings["alert_channels"])
    streaks = attendance.absence_streaks()
    from auth import visible_ids
    allowed = visible_ids()
    if allowed is not None:
        streaks = {k: v for k, v in streaks.items() if k in allowed}
    with db() as s:
        students = {x.id: x for x in s.query(Student).filter(Student.id.in_(list(streaks) or [-1]))}
        sent = {(a.student_id, a.streak_start): a for a in s.query(AbsenceAlert)}
    rows = []
    for sid, dates in streaks.items():
        st = students.get(sid)
        if not st:
            continue
        a = sent.get((sid, dates[0]))
        reached = len(dates) >= st_settings["threshold"]
        targets = parent_targets(st, channels)
        rows.append({
            "id": sid, "name": st.name, "roll_no": st.roll_no or "", "days": len(dates),
            "dates": [d.isoformat() for d in dates], "reached": reached, "alerted": bool(a),
            "sent_at": stamp(a.sent_at) if a else "", "sent_channels": a.channels if a else [],
            "due": reached and not a and bool(targets),
            "parent_name": st.parent_name, "parent_phone": st.parent_phone, "parent_email": st.parent_email,
        })
    rows.sort(key=lambda r: (-r["days"], r["name"].lower()))
    return rows


def absence_items(row, st_settings, channels):
    with db() as s:
        st = s.get(Student, row["id"])
    greet = st.parent_name or "Parent or Guardian"
    dates_txt = ", ".join(fmt_day(d) for d in row["dates"])
    meta = {"hook": "absence", "student_id": st.id, "streak_start": row["dates"][0], "days": row["days"]}
    items = []
    for channel, to in parent_targets(st, channels):
        if channel == "whatsapp":
            body = (f"*Attendance alert*\n\nDear {greet},\n{st.name}"
                    + (f" (Reg. No {st.roll_no})" if st.roll_no else "")
                    + f" has been absent for *{row['days']} days in a row*: {dates_txt}.\n\n"
                      "Please contact the class teacher to share the reason.\n\n"
                      f"- {sign(st_settings)}")
            items.append({"channel": "whatsapp", "kind": "absence", "to": to, "who": st.name,
                          "student_id": st.id, "body": body, "meta": meta})
        else:
            lines = [f"{st.name} has not attended class for {row['days']} days in a row ({dates_txt}).",
                     "Please contact the class teacher to share the reason, or tell us if there is anything we can help with."]
            items.append({"channel": "email", "kind": "absence", "to": to, "who": st.name, "student_id": st.id,
                          "subject": f"Attendance alert: {st.name} absent {row['days']} days in a row",
                          "body": f"Dear {greet},\n\n" + "\n\n".join(lines) + f"\n\nRegards,\n{sign(st_settings)}",
                          "html": html_wrap("Attendance alert", [f"Dear {greet},"] + lines, f"Regards, {sign(st_settings)}"),
                          "meta": meta})
    return items


def run_auto_alerts():
    """Called after the camera is stopped and the day is saved."""
    st = get_settings()
    if not st["auto_send"]:
        return
    channels = channels_from(st["alert_channels"])
    if not email_ready(st):
        channels = [c for c in channels if c != "email"]
    items = [it for r in alert_rows() if r["due"] for it in absence_items(r, st, channels)]
    if items:
        enqueue(items)


# ============================================================
#  API
# ============================================================
@bp.get("/settings")
def read_settings():
    st = get_settings()
    return ok(gmail=st["gmail"], password_set=bool(st["app_password"]), sender_name=st["sender_name"],
              school_name=st["school_name"], threshold=st["threshold"], auto_send=bool(st["auto_send"]),
              alert_channels=channels_from(st["alert_channels"]), country_code=st["country_code"],
              wa_delay=st["wa_delay"], configured=email_ready(st), camera=st["camera"],
              shared_here=current_org() == COLLEGE)   # Gmail / WhatsApp: set by the college admin


@bp.post("/settings")
def write_settings():
    d = request.get_json(silent=True) or {}
    gmail = str(d.get("gmail") or "").strip()
    if gmail and not EMAIL_RE.match(gmail):
        return fail("Enter a valid Gmail address.")
    try:
        threshold = int(d.get("threshold", 3))
        wa_delay = int(d.get("wa_delay", 6))
    except (TypeError, ValueError):
        return fail("Use whole numbers for days and seconds.")
    if not 1 <= threshold <= 14:
        return fail("Alert days must be between 1 and 14.")
    if not 3 <= wa_delay <= 60:
        return fail("The WhatsApp gap must be between 3 and 60 seconds.")
    cc = "".join(ch for ch in str(d.get("country_code") or "91") if ch.isdigit())
    if not 1 <= len(cc) <= 3:
        return fail("Country code is 1 to 3 digits, e.g. 91 for India.")
    changes = {
        "gmail": gmail, "threshold": threshold, "wa_delay": wa_delay, "country_code": cc,
        "sender_name": str(d.get("sender_name") or "Class Teacher").strip()[:60],
        "school_name": str(d.get("school_name") or "").strip()[:80],
        "auto_send": bool(d.get("auto_send", True)),
        "alert_channels": channels_from(d.get("alert_channels"), CHANNELS),
    }
    password = str(d.get("app_password") or "").replace(" ", "")
    if password:
        changes["app_password"] = password
    update_settings(**changes)
    return ok("Settings saved")


@bp.post("/settings/test-email")
def test_email():
    st = get_settings()
    if not email_ready(st):
        return fail("Enter your Gmail address and App Password first.")
    try:
        with open_smtp(st) as smtp:
            smtp.send_message(build_email(st, st["gmail"], "AttendAI test email",
                                          "Your email setup works. Parents will receive messages from this address."))
    except Exception as exc:
        return fail(friendly_mail_error(exc))
    return ok(f"Test email sent to {st['gmail']}")


@bp.get("/whatsapp/status")
def whatsapp_status():
    from auth import is_admin
    st = wa_status()
    if not is_admin() or current_org() != COLLEGE:
        st["qr"] = None    # scanning it would link someone's own phone as the school's WhatsApp
    st["managed_here"] = current_org() == COLLEGE     # the IT Hub uses the college's WhatsApp
    return ok(**st)


def scope_messages(q):
    """Only this organisation's messages; teachers only those about their own students."""
    from auth import visible_ids
    q = q.filter(Message.org == current_org())
    allowed = visible_ids()
    return q if allowed is None else q.filter(Message.student_id.in_(list(allowed) or [-1]))


@bp.post("/whatsapp/logout")
def whatsapp_logout():
    if current_org() != COLLEGE:
        return fail("The WhatsApp number is managed by the college admin.", 403)
    code, data = _bridge("POST", "/logout")
    if code != 200:
        return fail(data.get("error", "Couldn't reach the WhatsApp bridge."), 502)
    return ok("WhatsApp unlinked. Scan the new QR code to link again.")


@bp.post("/whatsapp/test")
def whatsapp_test():
    d = request.get_json(silent=True) or {}
    try:
        to = normalize_phone(d.get("phone"), get_settings()["country_code"])
    except ValueError as e:
        return fail(str(e))
    if not to:
        return fail("Enter a phone number.")
    enqueue([{"channel": "whatsapp", "kind": "test", "to": to, "who": "Test",
              "body": "AttendAI test message. WhatsApp alerts are working."}])
    return ok(f"Test message queued for {to}")


@bp.get("/messages")
def list_messages():
    limit = min(int(request.args.get("limit", 60)), 300)
    kind = request.args.get("kind")
    with db() as s:
        q = scope_messages(s.query(Message))
        if kind:
            q = q.filter(Message.kind == kind)
        rows = q.order_by(Message.id.desc()).limit(limit).all()
        return ok(messages=[message_json(m) for m in rows])


@bp.get("/messages/status")
def messages_status():
    with db() as s:
        active = [b for (b,) in scope_messages(s.query(Message)).filter(Message.status == "queued")
                  .with_entities(Message.batch).distinct()]
        counts = {"queued": 0, "sent": 0, "failed": 0}
        if active:
            for st_, n in (s.query(Message.status, func.count()).filter(Message.batch.in_(active))
                           .group_by(Message.status)):
                counts[st_] = n
        last = scope_messages(s.query(Message)).filter(Message.status != "queued").order_by(Message.id.desc()).first()
        failed_total = scope_messages(s.query(Message)).filter(Message.status == "failed").count()
    total = sum(counts.values())
    return ok(running=bool(active), total=total, sent=counts["sent"], failed=counts["failed"],
              queued=counts["queued"], failed_total=failed_total,
              last=message_json(last) if last else None)


@bp.post("/messages/retry")
def retry_failed():
    with db() as s:
        rows = scope_messages(s.query(Message)).filter(Message.status == "failed").all()
        for m in rows:
            m.status, m.error = "queued", ""
        n = len(rows)
    if n:
        _wake.set()
    return ok(f"Retrying {plural(n, 'message')}" if n else "Nothing to retry.", queued=n)


@bp.get("/alerts")
def get_alerts():
    st = get_settings()
    rows = alert_rows()
    return ok(threshold=st["threshold"], configured=email_ready(st), auto_send=bool(st["auto_send"]),
              channels=channels_from(st["alert_channels"]), students=rows,
              due_count=sum(1 for r in rows if r["due"]))


@bp.post("/alerts/send")
def send_alerts():
    """No id: every due alert. With an id: send (or resend) for that student."""
    d = request.get_json(silent=True) or {}
    st = get_settings()
    channels = channels_from(d.get("channels"), st["alert_channels"])
    if "email" in channels and not email_ready(st):
        channels.remove("email")
    if not channels:
        return fail("Choose WhatsApp or set up Gmail first.")
    rows = alert_rows()
    sid = d.get("id")
    chosen = [r for r in rows if r["id"] == sid] if sid else [r for r in rows if r["due"]]
    items = [it for r in chosen for it in absence_items(r, st, channels)]
    if not items:
        return fail("No parent contact saved for this student.") if sid else ok("No alerts are due right now.", queued=0)
    _, n = enqueue(items)
    return ok(f"Sending {plural(n, 'message')}", queued=n)

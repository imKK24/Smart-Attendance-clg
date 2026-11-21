"""Parent emails: read from Gmail (IMAP, read-only) and reply from the app."""
import email
import imaplib
import re
import ssl
import threading
import time
from datetime import date, timedelta
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape

from flask import Blueprint, request

from auth import scope, scope_query
from common import email_ready, fail, get_settings, ok, stamp
from orgs import COLLEGE, ITHUB, current_org
from models import InboxMail, Message, Student, db, now
from notify import enqueue

bp = Blueprint("inbox", __name__, url_prefix="/api/inbox")

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
SYNC_EVERY = 300          # seconds between automatic checks
MAX_NEW_PER_SYNC = 100
_sync_lock = threading.Lock()
sync_state = {"running": False, "last_sync": None, "error": "", "new": 0}


def imap_date(d):
    return f"{d.day:02d}-{MONTHS[d.month - 1]}-{d.year}"  # IMAP needs English month names


def html_to_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", "", html))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def body_text(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        content = part.get_content()
    except Exception:
        content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    return (html_to_text(content) if part.get_content_type() == "text/html" else content).strip()[:20000]


def parent_map():
    """{parent email (lower): [(student id, org)]}. IT Hub students' own emails count too
    (they are usually adults who write themselves)."""
    out = {}
    for org in (COLLEGE, ITHUB):        # both databases; the college wins a shared address
        with db(org) as s:
            for st in s.query(Student):
                mails = [st.parent_email] + ([st.student_email] if org == ITHUB else [])
                for m in mails:
                    if m:
                        out.setdefault(m.lower(), []).append((st.id, org))
    return out


def _uid_of(head):
    m = re.search(rb"UID (\d+)", head)
    return m.group(1).decode() if m else None


def sync():
    """Copy new parent emails from Gmail. Returns how many were added."""
    st = get_settings()
    if not email_ready(st):
        raise RuntimeError("Set up Gmail first (Notify > Settings).")
    parents = parent_map()
    if not parents:
        return 0
    known = set()
    for org in (COLLEGE, ITHUB):
        with db(org) as s:
            known |= {m for (m,) in s.query(InboxMail.msg_id)}
    since = date.today() - timedelta(days=int(st.get("inbox_days") or 30))
    added = 0
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=30)
    try:
        try:
            imap.login(st["gmail"], st["app_password"])
        except imaplib.IMAP4.error:
            raise RuntimeError("Gmail rejected the login. Check the App Password, and that IMAP is on in Gmail settings.")
        imap.select("INBOX", readonly=True)    # read-only: we never change or delete Gmail mail
        typ, data = imap.uid("search", None, "SINCE", imap_date(since))
        uids = data[0].split() if typ == "OK" and data and data[0] else []
        wanted = []
        for i in range(0, len(uids), 200):
            chunk = b",".join(uids[i:i + 200]).decode()
            typ, resp = imap.uid("fetch", chunk, "(BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)])")
            for item in resp or []:
                if not isinstance(item, tuple):
                    continue
                uid = _uid_of(item[0])
                head = email.message_from_bytes(item[1], policy=policy.default)
                addr = parseaddr(str(head.get("From", "")))[1].lower()
                mid = str(head.get("Message-ID", "")).strip() or f"<uid-{uid}@gmail>"
                if uid and addr in parents and mid not in known:
                    wanted.append(uid)
        for uid in wanted[-MAX_NEW_PER_SYNC:]:
            typ, resp = imap.uid("fetch", uid, "(BODY.PEEK[])")
            raw = next((x[1] for x in resp or [] if isinstance(x, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=policy.default)
            name, addr = parseaddr(str(msg.get("From", "")))
            addr = addr.lower()
            mid = str(msg.get("Message-ID", "")).strip() or f"<uid-{uid}@gmail>"
            if mid in known:
                continue
            try:
                received = parsedate_to_datetime(str(msg.get("Date"))).astimezone().replace(tzinfo=None, microsecond=0)
            except (TypeError, ValueError):
                received = now()
            owner = (parents.get(addr) or [(None, COLLEGE)])[0][1]
            with db(owner) as s:   # the email is stored in the database of the student it's about
                s.add(InboxMail(msg_id=mid[:300], from_email=addr, from_name=name[:160],
                                subject=str(msg.get("Subject", "") or "(no subject)")[:300],
                                body=body_text(msg), references=str(msg.get("References", "") or "")[:2000],
                                received_at=received, student_id=(parents.get(addr) or [(None, COLLEGE)])[0][0],
                                org=(parents.get(addr) or [(None, COLLEGE)])[0][1]))
            known.add(mid)
            added += 1
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return added


def run_sync():
    if not _sync_lock.acquire(blocking=False):
        return None
    sync_state.update(running=True, error="")
    try:
        n = sync()
        sync_state.update(new=n, last_sync=stamp(now()))
        return n
    except Exception as exc:
        sync_state["error"] = str(exc) if isinstance(exc, RuntimeError) else f"Couldn't check Gmail: {exc}"
        return None
    finally:
        sync_state["running"] = False
        _sync_lock.release()


def _auto_loop():
    time.sleep(20)
    while True:
        try:
            if email_ready():
                run_sync()
        except Exception as exc:
            print("Inbox sync error:", exc)
        time.sleep(SYNC_EVERY)


def start_auto_sync():
    threading.Thread(target=_auto_loop, daemon=True, name="inbox-sync").start()


def mail_json(m, children, full=False):
    out = {"id": m.id, "from_email": m.from_email, "from_name": m.from_name, "subject": m.subject,
           "received_at": stamp(m.received_at), "is_read": m.is_read, "replied_at": stamp(m.replied_at),
           "children": children, "preview": " ".join(m.body.split())[:160]}
    if full:
        out["body"] = m.body
    return out


def children_of(s):
    out = {}
    for st in scope_query(s.query(Student)):
        mails = [st.parent_email] + ([st.student_email] if st.org == ITHUB else [])
        for m in mails:
            if m:
                out.setdefault(m.lower(), []).append({"id": st.id, "name": st.name, "roll_no": st.roll_no or ""})
    return out


# ---------------- API ----------------
@bp.get("")
def list_mail():
    show = request.args.get("show", "all")
    limit = min(int(request.args.get("limit", 100)), 300)
    q = str(request.args.get("q") or "").strip().lower()
    with db() as s:
        kids = children_of(s)
        query = s.query(InboxMail).filter(InboxMail.org == current_org())
        if show == "unread":
            query = query.filter(InboxMail.is_read.is_(False))
        rows = query.order_by(InboxMail.received_at.desc()).limit(500 if q else limit).all()
        unread = s.query(InboxMail).filter(InboxMail.org == current_org(), InboxMail.is_read.is_(False)).count()
        out = []
        if scope() is not None:   # teachers: only parents of their students
            rows = [m for m in rows if m.from_email in kids]
            unread = sum(1 for m in rows if not m.is_read)
        for m in rows:
            ch = kids.get(m.from_email, [])
            hay = " ".join([m.from_name, m.from_email, m.subject, m.body] + [c["name"] for c in ch]).lower()
            if q and q not in hay:
                continue
            out.append(mail_json(m, ch))
    return ok(mails=out[:limit], unread=unread, sync=sync_state, configured=email_ready())


@bp.get("/<int:mid>")
def get_mail(mid):
    with db() as s:
        m = s.get(InboxMail, mid)
        m = m if m is not None and m.org == current_org() else None
        if not m or (scope() is not None and m.from_email not in children_of(s)):
            return fail("Email not found.", 404)
        m.is_read = True
        replies = [{"body": r.body, "status": r.status, "error": r.error, "created_at": stamp(r.created_at),
                    "sent_at": stamp(r.sent_at)}
                   for r in s.query(Message).filter(Message.kind == "reply", Message.to == m.from_email)
                   .order_by(Message.id) if (r.meta or {}).get("inbox_id") == mid]
        return ok(mail=mail_json(m, children_of(s).get(m.from_email, []), full=True), replies=replies)


@bp.post("/<int:mid>/read")
def set_read(mid):
    read = bool((request.get_json(silent=True) or {}).get("read", True))
    with db() as s:
        m = s.get(InboxMail, mid)
        m = m if m is not None and m.org == current_org() else None
        if not m:
            return fail("Email not found.", 404)
        m.is_read = read
    return ok()


@bp.post("/<int:mid>/reply")
def reply(mid):
    text = str((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return fail("Write a reply first.")
    if len(text) > 10000:
        return fail("The reply is too long.")
    if not email_ready():
        return fail("Set up Gmail first (Notify > Settings).")
    with db() as s:
        m = s.get(InboxMail, mid)
        m = m if m is not None and m.org == current_org() else None
        if not m or (scope() is not None and m.from_email not in children_of(s)):
            return fail("Email not found.", 404)
        subject = m.subject if m.subject.lower().startswith("re:") else f"Re: {m.subject}"
        item = {"channel": "email", "kind": "reply", "to": m.from_email, "who": m.from_name or m.from_email,
                "student_id": m.student_id, "subject": subject, "body": text,
                "meta": {"hook": "reply", "inbox_id": m.id, "in_reply_to": m.msg_id, "references": m.references}}
    enqueue([item])
    return ok("Reply is being sent")


@bp.post("/sync")
def sync_now():
    if not email_ready():
        return fail("Set up Gmail first (Notify > Settings).")
    n = run_sync()
    if n is None:
        if sync_state["error"]:
            return fail(sync_state["error"], 502)
        return ok("Already checking Gmail.", new=0)
    return ok("No new parent emails." if n == 0 else f"{n} new parent email(s).", new=n)

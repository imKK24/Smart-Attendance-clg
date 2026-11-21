"""Two-way WhatsApp: parents' replies come in through the bridge and show as chats.
Only messages from phone numbers saved on a student are kept; others are ignored."""
import hmac
import re
from datetime import datetime

from flask import Blueprint, request

import config
from auth import scope_query
from common import fail, ok, stamp
from models import Message, Student, WaIncoming, db, now
from notify import enqueue

bp = Blueprint("wa_chats", __name__, url_prefix="/api/whatsapp")
KINDS = {"text", "photo", "video", "voice", "document", "sticker", "location", "other"}


def digits(phone):
    return re.sub(r"\D", "", str(phone or ""))


def phone_book(scoped=True):
    """{digits: [students]} for every saved parent / student number.
    scoped=False: both organisations' databases (to file an incoming message)."""
    book = {}
    for org in ([None] if scoped else ["college", "ithub"]):
        with db(org) as s:
            q = scope_query(s.query(Student)) if scoped else s.query(Student)
            for st in q:
                for ph in (st.parent_phone, st.alt_phone, st.student_phone):
                    if digits(ph):
                        book.setdefault(digits(ph), []).append(st)
    return book


def who(sts, ph):
    """Describe the contact: 'Ravi Kumar, parent of Dhanish Kumar'."""
    parents = [st for st in sts if digits(st.parent_phone) == ph or digits(st.alt_phone) == ph]
    if parents:
        st = parents[0]
        return st.parent_name or "Parent", "parent of " + ", ".join(x.name for x in parents)
    return sts[0].name, "student"


@bp.post("/incoming")
def incoming():
    """Called by the WhatsApp bridge for each message a contact sends to the school number."""
    if not hmac.compare_digest(request.headers.get("X-Bridge-Token", ""), config.WA_BRIDGE_TOKEN):
        return fail("Bad bridge token.", 401)
    d = request.get_json(silent=True) or {}
    ph = digits(d.get("phone"))
    wa_id = str(d.get("id") or "")[:120]
    if not ph or not wa_id:
        return fail("Missing phone or id.")
    book = phone_book(scoped=False)
    if ph not in book:
        return ok(stored=False, reason="unknown number")      # privacy: strangers aren't stored
    try:
        when = datetime.fromtimestamp(int(d.get("ts"))) if d.get("ts") else now()
    except (TypeError, ValueError, OSError):
        when = now()
    orgs_ = {st.org or "college" for st in book.get(ph, [])}
    owner = "ithub" if orgs_ == {"ithub"} else "college"   # a number known to both: the college
    with db(owner) as s:
        if s.query(WaIncoming).filter(WaIncoming.wa_id == wa_id).first():
            return ok(stored=False, reason="duplicate")
        s.add(WaIncoming(org=owner, wa_id=wa_id, phone="+" + ph, name=str(d.get("name") or "")[:120],
                         text=str(d.get("text") or "")[:4000], kind=d.get("kind") if d.get("kind") in KINDS else "other",
                         received_at=when.replace(microsecond=0)))
    return ok(stored=True)


def chat_items(ph, s):
    """Incoming + outgoing messages for one number, oldest first."""
    out = [{"dir": "in", "text": m.text, "kind": m.kind, "at": stamp(m.received_at), "_t": m.received_at}
           for m in s.query(WaIncoming).filter(WaIncoming.phone == "+" + ph)]
    for m in s.query(Message).filter(Message.channel == "whatsapp", Message.to == "+" + ph):
        t = m.sent_at or m.created_at
        out.append({"dir": "out", "text": m.body, "kind": m.kind, "status": m.status, "error": m.error,
                    "at": stamp(t), "_t": t})
    out.sort(key=lambda x: x["_t"])
    for x in out:
        x.pop("_t")
    return out


@bp.get("/chats")
def chats():
    book = phone_book()
    with db() as s:
        rows = s.query(WaIncoming).order_by(WaIncoming.received_at).all()
        by_phone = {}
        for m in rows:
            ph = digits(m.phone)
            if ph not in book:            # teachers: only their students' parents
                continue
            c = by_phone.setdefault(ph, {"phone": m.phone, "unread": 0, "wa_name": m.name})
            c["unread"] += 0 if m.is_read else 1
            c["last_text"], c["last_at"], c["last_dir"] = (m.text or f"[{m.kind}]"), stamp(m.received_at), "in"
            c["wa_name"] = m.name or c["wa_name"]
        for ph, c in by_phone.items():   # was our message newer than their last one?
            last_out = (s.query(Message).filter(Message.channel == "whatsapp", Message.to == "+" + ph)
                        .order_by(Message.id.desc()).first())
            if last_out and stamp(last_out.sent_at or last_out.created_at) > c["last_at"]:
                c["last_text"], c["last_at"], c["last_dir"] = last_out.body, stamp(last_out.sent_at or last_out.created_at), "out"
            name, role = who(book[ph], ph)
            c.update(name=name, role=role, students=[{"id": st.id, "name": st.name, "roll_no": st.roll_no or ""} for st in book[ph]])
    items = sorted(by_phone.values(), key=lambda c: c["last_at"], reverse=True)
    return ok(chats=items, unread=sum(c["unread"] for c in items))


@bp.get("/chats/<ph>")
def chat(ph):
    ph = digits(ph)
    book = phone_book()
    if ph not in book:
        return fail("Chat not found.", 404)
    with db() as s:
        for m in s.query(WaIncoming).filter(WaIncoming.phone == "+" + ph, WaIncoming.is_read.is_(False)):
            m.is_read = True
        items = chat_items(ph, s)
    name, role = who(book[ph], ph)
    return ok(phone="+" + ph, name=name, role=role, messages=items,
              students=[{"id": st.id, "name": st.name, "roll_no": st.roll_no or ""} for st in book[ph]])


@bp.post("/chats/<ph>/reply")
def reply(ph):
    ph = digits(ph)
    book = phone_book()
    if ph not in book:
        return fail("Chat not found.", 404)
    text = str((request.get_json(silent=True) or {}).get("text") or "").strip()
    if not text:
        return fail("Write a message first.")
    if len(text) > 3000:
        return fail("The message is too long.")
    st = book[ph][0]
    enqueue([{"channel": "whatsapp", "kind": "chat", "to": "+" + ph, "who": who(book[ph], ph)[0],
              "student_id": st.id, "body": text}])
    return ok("Sending")

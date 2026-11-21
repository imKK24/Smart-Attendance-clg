"""Shared helpers: settings store, validation, date and text formatting."""
import base64
import hashlib
import re
import time
import threading
from datetime import date, datetime

from cryptography.fernet import Fernet, InvalidToken
from flask import jsonify

import config
from models import Setting, db

NAME_RE = re.compile(r"^\w[\w .'\-]{0,59}$", re.UNICODE)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

DEFAULT_SETTINGS = {
    "school_name": "",
    "gmail": "",
    "app_password": "",          # stored encrypted
    "sender_name": "Class Teacher",
    "threshold": 3,              # absent days in a row before parents are told
    "auto_send": True,           # check for absence alerts whenever the camera is stopped
    "alert_channels": ["whatsapp", "email"],
    "country_code": "91",        # added to 10-digit phone numbers
    "camera": "default",         # "default" = laptop camera first, or a camera number
    "wa_delay": 6,               # seconds between WhatsApp messages (protects the number)
    "inbox_days": 30,            # how far back to look for parent emails
    "term_start": "",            # first day of the semester (YYYY-MM-DD) for eligibility
    "eligibility_min": 75,       # minimum attendance % to sit exams
    "fee_auto": False,           # send fee reminders by themselves once a day
    "fee_days_before": 3,        # first reminder this many days before the due date
    "fee_repeat_days": 7,        # then again every N days while unpaid / overdue
    "fee_channels": ["whatsapp", "email"],
    "attendance_methods": ["camera", "photo"],   # which ways of taking attendance are switched on
    "ip_cameras": [],            # [{id, name, kind: wired|wifi, url (encrypted)}]
    "liveness_mode": "quick",    # quick = blink twice; secure = 2 random actions (blink, turn, open mouth)
    "courses": [],               # Aakansha IT Hub: the courses students can join (old; now the Course table)
    "batches": ["4–6 PM", "6–8 PM"],   # Aakansha IT Hub: batch timings the admin offers
    "attendance_guard": {},             # proxy protection rules (guard.py)
}
# Shared by both organisations (one Gmail, one WhatsApp, one phone format).
# Only the college admin changes these; everything else is kept per organisation.
SHARED_SETTINGS = {"gmail", "app_password", "country_code", "wa_delay", "inbox_days"}


def _setting_db(key, org):
    """Each organisation keeps its settings in its own database; the shared ones
    (Gmail, WhatsApp, phone format) live in the college database."""
    from orgs import COLLEGE
    return COLLEGE if key in SHARED_SETTINGS else org
CHANNELS = ("whatsapp", "email")
_lock = threading.RLock()
_fernet = Fernet(base64.urlsafe_b64encode(hashlib.sha256(config.SECRET_KEY.encode()).digest()))


def fail(message, code=400, **extra):
    return jsonify(success=False, message=message, **extra), code


def ok(message=None, **extra):
    if message:
        extra["message"] = message
    return jsonify(success=True, **extra)


# ---------- settings ----------
def get_settings(org=None):
    """Settings of this request's organisation (shared ones are the same for both)."""
    from orgs import current_org
    org = org or current_org()
    from orgs import COLLEGE
    stored = {}
    for where in {COLLEGE, org}:
        with db(where) as s:
            stored[where] = {row.key: row.value.get("v") for row in s.query(Setting).all()}
    out = dict(DEFAULT_SETTINGS)
    for k in DEFAULT_SETTINGS:
        home = stored[_setting_db(k, org)]
        if k in home:
            out[k] = home[k]
    if out["app_password"]:
        try:
            out["app_password"] = _fernet.decrypt(out["app_password"].encode()).decode()
        except (InvalidToken, ValueError):
            out["app_password"] = ""
    import os
    out["gmail"] = os.environ.get("GMAIL_ADDRESS", out["gmail"]).strip()
    out["app_password"] = os.environ.get("GMAIL_APP_PASSWORD", out["app_password"]).replace(" ", "")
    return out


def update_settings(org=None, **changes):
    from orgs import COLLEGE, current_org
    org = org or current_org()
    with _lock, db(org) as s:
        for key, value in changes.items():
            if key not in DEFAULT_SETTINGS:
                continue
            if key in SHARED_SETTINGS and org != COLLEGE:
                continue              # Gmail / WhatsApp belong to the college admin
            if key == "app_password" and value:
                value = _fernet.encrypt(value.encode()).decode()
            row = s.get(Setting, key)
            if row:
                row.value = {"v": value}
            else:
                s.add(Setting(key=key, value={"v": value}))


def encrypt_text(text):
    return _fernet.encrypt(str(text).encode()).decode()


def decrypt_text(token):
    try:
        return _fernet.decrypt(str(token).encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def email_ready(st=None):
    st = st or get_settings()
    return bool(st["gmail"] and st["app_password"])


# ---------- validation ----------
def clean_name(raw):
    """A safe student name or None. Blocks path tricks like ../"""
    name = " ".join(str(raw or "").split())
    if not NAME_RE.match(name) or ".." in name:
        return None
    return name


REG_NO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/.\- ]{0,29}$")


def safe_cell(value):
    """Stop Excel from running text as a formula (=, +, -, @ at the start)."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def clean_text(raw, limit):
    return " ".join(str(raw or "").split())[:limit]


def normalize_phone(raw, country_code="91"):
    """Return '+<country><number>' or '' when empty. Raises ValueError if invalid.
    10-digit numbers get the default country code (India: 91)."""
    raw = str(raw or "").strip()
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00"):
        digits = digits[2:]
    elif not raw.startswith("+"):
        digits = digits.lstrip("0") if len(digits) == 11 and digits.startswith("0") else digits
        if len(digits) == 10:
            digits = str(country_code) + digits
    if not 10 <= len(digits) <= 15:
        raise ValueError("Phone numbers need 10 digits, or + and the country code.")
    return "+" + digits


def parse_day(text):
    if not DATE_RE.match(str(text or "")):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def iso(d):
    return d.isoformat() if d else None


def stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def fmt_day(d):
    if isinstance(d, str):
        d = parse_day(d) or d
    return d.strftime("%a %d %b %Y") if isinstance(d, date) else str(d)


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def channels_from(raw, fallback=CHANNELS):
    chosen = [c for c in (raw if isinstance(raw, list) else fallback) if c in CHANNELS]
    return list(dict.fromkeys(chosen))


# ── Login throttle ────────────────────────────────────────────────────
class Throttle(dict):
    """Counts wrong logins per key (an IP address, an account). After `tries`
    wrong ones the key is locked; each new lock lasts twice as long as the last
    one (1 min, 2, 4 ... up to 15 min), so guessing doesn't get faster by waiting."""

    def __init__(self, tries=5, first_lock=60, max_lock=900):
        super().__init__()
        self.tries, self.first_lock, self.max_lock = tries, first_lock, max_lock

    def wait(self, *keys):
        """Seconds still locked for any of these keys (0 = free)."""
        now = time.time()
        return max([int(self[k][1] - now) + 1 for k in keys if k in self and self[k][1] > now] or [0])

    def failed(self, *keys):
        for k in keys:
            count, until, locks = self.get(k, (0, 0, 0))
            count += 1
            if count >= self.tries:
                lock = min(self.first_lock * 2 ** locks, self.max_lock)
                self[k] = (0, time.time() + lock, locks + 1)
            else:
                self[k] = (count, until, locks)

    def passed(self, *keys):
        for k in keys:
            self.pop(k, None)


# ── Password rule ─────────────────────────────────────────────────────
COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890", "qwerty123",
    "qwertyuiop", "iloveyou", "admin123", "admin@123", "welcome1", "welcome123", "abc12345",
    "11111111", "00000000", "attendai", "attendai1", "attendai123", "teacher123", "college123",
    "india123", "letmein1", "changeme", "passw0rd", "p@ssw0rd", "admin@2026", "teacher@2026",
}


def password_problem(password, username=""):
    """Return why a password is too weak, or None if it's fine."""
    pw = str(password or "")
    if len(pw) < 8:
        return "The password must be at least 8 characters."
    if len(pw) > 128:
        return "The password is too long (max 128 characters)."
    low = pw.lower()
    name = str(username or "").lower().split("@")[0]
    if low in COMMON_PASSWORDS or len(set(low)) <= 2:
        return "That password is too easy to guess. Use a longer mix of words and numbers."
    if name and len(name) >= 3 and name in low:
        return "Don't use your login name inside the password."
    return None


# ── Picture size check ────────────────────────────────────────────────
MAX_PIXELS = 40_000_000


def too_many_pixels(raw):
    """Read only the picture's header and say if it's bigger than 40 megapixels.
    Stops 'picture bombs': a small file that unpacks into gigabytes of memory."""
    import io
    from PIL import Image
    try:
        with Image.open(io.BytesIO(bytes(raw))) as im:
            w, h = im.size
    except Image.DecompressionBombError:
        return True           # Pillow already knows it's far too big
    except Exception:
        return False          # not a picture Pillow knows; OpenCV decides
    return w * h > MAX_PIXELS


def visitor_keys(*others):
    """Throttle keys for this request: the visitor's IP plus the given ones.
    Behind a tunnel, a visitor that still shows as 127.0.0.1 has an unknown IP;
    counting them all as one would let one person lock everybody out, so then
    only the account / registration-number key is used."""
    from flask import request
    ip = request.remote_addr or "?"
    if config.BEHIND_TUNNEL and ip in ("127.0.0.1", "::1"):
        return tuple(others)
    return ("ip:" + ip,) + tuple(others)

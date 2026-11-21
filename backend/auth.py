"""Admin login. Every /api route needs a JWT except the few listed in PUBLIC."""
import re
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import String, false, func
from flask import Blueprint, g, has_request_context, request
from werkzeug.security import check_password_hash, generate_password_hash

import config
from common import Throttle, fail, ok, password_problem, visitor_keys
from models import Admin, Student, db, in_units
from orgs import COLLEGE, ITHUB, ORGS, clean_org, current_org, uses_courses

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# /api/whatsapp/incoming is called by the WhatsApp bridge, which proves itself
# with the shared bridge token instead of a login (checked in wa_chats.py).
PUBLIC = {"/api/health", "/api/auth/status", "/api/auth/setup", "/api/auth/login", "/api/whatsapp/incoming",
          "/api/parent/login"}
# <img> and <a download> can't send headers, so these GET routes also accept ?token=
QUERY_TOKEN_OK = ("/api/video-feed", "/api/camera-frame", "/api/students/", "/api/attendance/", "/api/exams/", "/api/reports/",
                  "/api/photo-attendance/", "/api/courses/")

# Wrong logins are counted per computer AND per account, so trying many
# passwords from many computers against one account gets locked too.
_failures = Throttle(tries=5, first_lock=60)


MEDIA_MINUTES = 30
# Passwords that were once published with the project (manage.py create-accounts,
# guides, chat). Accounts still using one must set a new password at next login.
RETIRED_PASSWORDS = {"admin@attendai.local": "Admin@2026", "teacher@attendai.local": "Teacher@2026"}
ALWAYS_ALLOWED = {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}


def make_token(admin):
    """The login token. Sent only in the Authorization header."""
    exp = datetime.now(timezone.utc) + timedelta(hours=config.TOKEN_HOURS)
    return jwt.encode({"sub": str(admin.id), "name": admin.username, "kind": "staff", "org": clean_org(admin.org),
                       "v": admin.token_version or 0, "exp": exp}, config.SECRET_KEY, algorithm="HS256")


def make_media_token(admin):
    """Short, view-only token for <img src> and download links (they can't send headers).
    It only opens the photo / video / download routes, and only for 30 minutes."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=MEDIA_MINUTES)
    return jwt.encode({"sub": str(admin.id), "kind": "media", "org": clean_org(admin.org),
                       "v": admin.token_version or 0, "exp": exp}, config.SECRET_KEY, algorithm="HS256")


def retire_known_passwords():
    """Called on start: force a new password on accounts still using a published one."""
    with db() as s:
        for name, pw in RETIRED_PASSWORDS.items():
            a = s.query(Admin).filter(Admin.username == name).first()
            if a and not a.must_change and check_password_hash(a.password_hash, pw):
                a.must_change = True


# Only role 'admin' may call these (method, path pattern). Teachers get 403.
ADMIN_ONLY = [
    ("POST", r"/api/settings(/.*)?"),
    ("GET", r"/api/courses"),                     # the IT Hub course catalogue is for admins only
    ("PUT", r"/api/courses/batches"),
    ("*", r"/api/attendance-guard"), ("*", r"/api/devices/\d+(/approve)?"),   # proxy protection
    ("POST", r"/api/courses"), ("PUT", r"/api/courses/\d+"), ("DELETE", r"/api/courses/\d+"),
    ("*", r"/api/whatsapp/(logout|test)"),
    ("*", r"/api/users(/.*)?"),
    ("POST", r"/api/holidays(/.*)?"), ("DELETE", r"/api/holidays/.*"),
    ("POST", r"/api/events(/.*)?"), ("DELETE", r"/api/events/.*"),
    ("DELETE", r"/api/students/\d+"),
    ("DELETE", r"/api/exams/\d+"),
    ("POST", r"/api/reports/settings"),
    ("*", r"/api/fees(/.*)?"),
    ("*", r"/api/ip-cameras(/.*)?"),
    ("POST", r"/api/attendance-methods"),
    ("POST", r"/api/liveness-mode"),
    ("DELETE", r"/api/photo-attendance/\d+"),
]
ADMIN_ONLY = [(m, re.compile(p + "$")) for m, p in ADMIN_ONLY]


def check_request():
    """Flask before_request hook: valid token, active user, role allowed."""
    path = request.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in PUBLIC:
        return None
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else ""
    from_url = False
    if not token and request.method == "GET" and path.startswith(QUERY_TOKEN_OK):
        token, from_url = request.args.get("token", ""), True
    if not token:
        return fail("Please log in.", 401, auth=True)
    try:
        data = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        if from_url:
            return fail("This link has expired. Reload the page.", 401)
        return fail("Your session expired. Please log in again.", 401, auth=True)
    except jwt.InvalidTokenError:
        return fail("Please log in.", 401, auth=True)
    # A token in a web address must be a short view-only media token, and a
    # media token is never accepted anywhere else.
    if from_url != (data.get("kind") == "media"):
        return fail("Please log in.", 401, auth=not from_url)
    # Which database this login belongs to: account ids only mean something inside it.
    g.org = clean_org(data.get("org"))
    if data.get("kind") == "parent":   # parent (college) or student (IT Hub) portal: one student, /api/parent/* only
        if not path.startswith("/api/parent/"):
            return fail("This login only opens the student's own page.", 403)
        with db() as s:                  # the college or IT Hub database, from the token
            if not s.get(Student, int(data["sid"])):
                return fail("This student is no longer registered.", 401, auth=True)
        who = "student" if g.org == ITHUB else "parent"
        g.role, g.scope, g.parent_sid, g.admin_name = who, None, int(data["sid"]), who
        return None
    if path.startswith("/api/parent/"):
        return fail("Log in as a parent or student to open this page.", 403)
    with db() as s:   # read the user every time, so role changes apply at once
        user = s.get(Admin, int(data["sub"]))
        if not user or not user.active or clean_org(user.org) != g.org:
            return fail("This account was removed or switched off.", 401, auth=True)
        if data.get("v", 0) != (user.token_version or 0):
            return fail("You were logged out (password changed or logged out). Please log in again.", 401, auth=True)
        if user.must_change and path not in ALWAYS_ALLOWED:
            return fail("Set a new password first.", 403, must_change=True)
        g.admin_id, g.admin_name, g.role = user.id, user.username, user.role or "admin"
        g.org = clean_org(user.org)
        # branches (college) or courses (IT Hub) this teacher may see; None = all of their organisation.
        # IT Hub teachers see only the courses an admin assigned them (none assigned = nothing).
        if g.role == "admin":
            g.scope = None
        elif g.org == ITHUB:
            g.scope = list(user.branches or [])
        else:
            g.scope = list(user.branches) if user.branches else None
    if g.role != "admin" and any(m in ("*", request.method) and rx.match(path) for m, rx in ADMIN_ONLY):
        return fail("Only an admin can do this.", 403)
    return None


# ---------- scope: own organisation, and teachers only their branches / courses ----------
def scope():
    """None = every branch (course), otherwise the list this user may see."""
    return g.get("scope") if has_request_context() else None


def scope_query(q):
    """Limit a Student query to this organisation and, for teachers, their branches or courses."""
    org = current_org()
    q = q.filter(Student.org == org)
    sc = scope()
    if sc is None:
        return q
    if uses_courses(org):
        if not sc:                       # an IT Hub teacher with no course assigned sees nobody
            return q.filter(false())
        # a teacher's scope holds whole courses and/or "Course · Batch" classes
        return q.filter(in_units(sc))
    return q.filter(Student.branch.in_(sc))


def visible(student):
    if student is None or (student.org or COLLEGE) != current_org():
        return False
    sc = scope()
    if sc is None:
        return True
    if uses_courses(student.org):
        return bool(set(student.units or student.courses or []) & set(sc))
    return student.branch in sc


def visible_ids():
    """Set of student ids this user may see, or None for all."""
    if scope() is None:
        return None
    with db() as s:
        return {i for (i,) in scope_query(s.query(Student.id))}


def is_admin():
    return not has_request_context() or g.get("role", "admin") == "admin"


def user_json(a):
    org = clean_org(a.org)
    return {"id": a.id, "username": a.username, "full_name": a.full_name, "role": a.role or "admin",
            "branches": a.branches or [], "active": a.active, "must_change": bool(a.must_change),
            "org": org, "org_name": ORGS[org]["name"], "unit": ORGS[org]["unit"]}


def _valid_pair(username, password):
    if not 3 <= len(username) <= 60:
        return "Username must be 3 to 60 characters."
    return password_problem(password, username)


@bp.get("/status")
def status():
    with db() as s:
        return ok(setup_needed=s.query(Admin).count() == 0)


@bp.post("/setup")
def setup():
    """Creates the first admin. Only works while there is no admin yet, and only
    from the PC itself, so nobody on the internet can grab a new install first."""
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return fail("Create the first admin on the AttendAI computer itself (http://localhost:5000).", 403)
    d = request.get_json(silent=True) or {}
    username, password = str(d.get("username") or "").strip(), str(d.get("password") or "")
    with db() as s:
        if s.query(Admin).count():
            return fail("An admin account already exists. Log in instead.", 409)
        error = _valid_pair(username, password)
        if error:
            return fail(error)
        admin = Admin(username=username, password_hash=generate_password_hash(password))
        s.add(admin)
        s.flush()
        admin.role = "admin"
        s.flush()
        return ok("Admin account created", token=make_token(admin), username=admin.username, user=user_json(admin))


@bp.post("/login")
def login():
    d = request.get_json(silent=True) or {}
    username, password = str(d.get("username") or "").strip(), str(d.get("password") or "")[:200]
    keys = visitor_keys("user:" + username.lower())
    wait = _failures.wait(*keys)
    if wait:
        return fail(f"Too many wrong tries. Wait {wait} seconds.", 429)
    wanted = d.get("role")   # "admin" or "teacher", from the switch on the login page
    page_org = clean_org(d.get("org"))   # which login page: college (/) or IT Hub (/it-hub)
    g.org = page_org                     # look only in that organisation's database
    with db() as s:
        admin = s.query(Admin).filter(func.lower(Admin.username) == username.lower()).first()
        if not admin:   # an account of the other organisation, on the wrong login page?
            other = ITHUB if page_org == COLLEGE else COLLEGE
            with db(other) as s2:
                elsewhere = s2.query(Admin).filter(func.lower(Admin.username) == username.lower()).first()
                if elsewhere and elsewhere.active and check_password_hash(elsewhere.password_hash, password):
                    _failures.passed(*keys)
                    where = "the IT Hub login page (/it-hub)" if other == ITHUB else "the college login page"
                    return fail(f"This account belongs to {ORGS[other]['name']}. Log in on {where}.", 403)
        if not admin or not check_password_hash(admin.password_hash, password):
            _failures.failed(*keys)
            return fail("Wrong username or password.", 401)
        if not admin.active:   # only said after the right password, so it can't be used to find accounts
            return fail("This account is switched off. Ask the admin.", 403)
        _failures.passed(*keys)
        if clean_org(admin.org) != page_org:   # each organisation logs in on its own page
            other = ORGS[clean_org(admin.org)]["name"]
            where = "the IT Hub login page (/it-hub)" if clean_org(admin.org) == ITHUB else "the college login page"
            return fail(f"This account belongs to {other}. Log in on {where}.", 403)
        role = admin.role or "admin"
        if wanted in ("admin", "teacher") and wanted != role:
            return fail(f"This is a{'n Admin' if role == 'admin' else ' Teacher'} account. "
                        f"Choose \"{role.title()}\" at the top and log in again.", 403)
        return ok(token=make_token(admin), username=admin.username, user=user_json(admin))


@bp.get("/me")
def me():
    with db() as s:
        return ok(username=g.admin_name, user=user_json(s.get(Admin, g.admin_id)))


@bp.post("/password")
def change_password():
    d = request.get_json(silent=True) or {}
    current, new = str(d.get("current") or ""), str(d.get("new") or "")
    problem = password_problem(new, g.admin_name)
    if problem:
        return fail(problem)
    if new == current:
        return fail("Choose a password different from the current one.")
    if new in RETIRED_PASSWORDS.values():
        return fail("That password was published with the project. Choose another one.")
    with db() as s:
        admin = s.get(Admin, g.admin_id)
        if not admin or not check_password_hash(admin.password_hash, current):
            return fail("Your current password is wrong.", 400)
        admin.password_hash = generate_password_hash(new)
        admin.must_change = False
        admin.token_version = (admin.token_version or 0) + 1   # logs out every other device
        return ok("Password changed. Other devices were logged out.", token=make_token(admin), user=user_json(admin))


@bp.post("/logout")
def logout():
    """Ends this login everywhere: every token of this user stops working."""
    with db() as s:
        admin = s.get(Admin, g.admin_id)
        admin.token_version = (admin.token_version or 0) + 1
    return ok("Logged out")


@bp.post("/media-token")
def media_token():
    with db() as s:
        return ok(token=make_media_token(s.get(Admin, g.admin_id)), minutes=MEDIA_MINUTES)

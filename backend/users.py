"""Team accounts (admin only): add teachers, choose their branches, switch them off."""
from flask import Blueprint, g, request
from werkzeug.security import generate_password_hash

from auth import user_json
from common import clean_text, fail, ok, password_problem
from models import Admin, db
from orgs import current_org

bp = Blueprint("users", __name__, url_prefix="/api/users")
ROLES = ("admin", "teacher")


def _branches(raw):
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    return sorted({clean_text(b, 60) for b in items if clean_text(b, 60)})


def _active_admins(s, excluding=None):
    q = s.query(Admin).filter(Admin.org == current_org(), Admin.role == "admin", Admin.active.is_(True))
    if excluding:
        q = q.filter(Admin.id != excluding)
    return q.count()


@bp.get("")
def list_users():
    with db() as s:
        rows = s.query(Admin).filter(Admin.org == current_org()).order_by(Admin.role, Admin.username)
        return ok(users=[user_json(a) for a in rows], me=g.admin_id)


@bp.post("")
def create_user():
    d = request.get_json(silent=True) or {}
    username = str(d.get("username") or "").strip()
    password = str(d.get("password") or "")
    role = d.get("role") if d.get("role") in ROLES else "teacher"
    if not 3 <= len(username) <= 60 or " " in username:
        return fail("Username: 3 to 60 characters, no spaces.")
    problem = password_problem(password, username)
    if problem:
        return fail(problem)
    with db() as s:
        if s.query(Admin).filter(Admin.username == username).first():
            return fail("That username is taken.", 409)
        a = Admin(org=current_org(), username=username, password_hash=generate_password_hash(password), role=role,
                  must_change=True,
                  full_name=clean_text(d.get("full_name"), 80), branches=_branches(d.get("branches")) if role == "teacher" else [])
        s.add(a)
        s.flush()
        return ok(f"{username} can now log in", user=user_json(a))


@bp.put("/<int:uid>")
def update_user(uid):
    d = request.get_json(silent=True) or {}
    with db() as s:
        a = s.get(Admin, uid)
        a = a if a and a.org == current_org() else None
        if not a:
            return fail("User not found.", 404)
        role = d.get("role", a.role)
        active = bool(d.get("active", a.active))
        if role not in ROLES:
            return fail("Role must be admin or teacher.")
        losing_admin = a.role == "admin" and a.active and (role != "admin" or not active)
        if losing_admin and _active_admins(s, excluding=a.id) == 0:
            return fail("There must always be at least one active admin.")
        if uid == g.admin_id and (role != "admin" or not active):
            return fail("You can't remove your own admin access. Ask another admin.")
        a.role, a.active = role, active
        if "full_name" in d:
            a.full_name = clean_text(d.get("full_name"), 80)
        if "branches" in d or role == "admin":
            a.branches = _branches(d.get("branches")) if role == "teacher" else []
        if d.get("password"):
            problem = password_problem(d["password"], a.username)
            if problem:
                return fail(problem)
            a.password_hash = generate_password_hash(str(d["password"]))
            a.must_change = True                               # the admin knows it, so they set their own
            a.token_version = (a.token_version or 0) + 1       # and old logins stop working
        return ok(f"{a.username} updated", user=user_json(a))


@bp.delete("/<int:uid>")
def delete_user(uid):
    with db() as s:
        a = s.get(Admin, uid)
        a = a if a and a.org == current_org() else None
        if not a:
            return fail("User not found.", 404)
        if uid == g.admin_id:
            return fail("You can't delete your own account.")
        if a.role == "admin" and a.active and _active_admins(s, excluding=a.id) == 0:
            return fail("There must always be at least one active admin.")
        name = a.username
        s.delete(a)
    return ok(f"{name} removed")

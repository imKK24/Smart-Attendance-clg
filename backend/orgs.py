"""Two organisations in one AttendAI: the college and Aakansha IT Hub.

Every account, student, attendance row, holiday, exam, message and class photo
belongs to one organisation. A request works only inside its user's
organisation (g.org, set at login check). Background jobs (night finalize,
message worker, fee reminders) run once per organisation with `as_org(...)`.

College students have one *branch*. IT Hub students have several *courses*,
and IT Hub attendance is kept per course.
"""
from contextlib import contextmanager
from contextvars import ContextVar

COLLEGE, ITHUB = "college", "ithub"
ORGS = {
    COLLEGE: {"name": "College", "unit": "branch", "parents": True},
    ITHUB: {"name": "Aakansha IT Hub", "unit": "course", "parents": False},
}
_bg_org = ContextVar("attendai_org", default=None)


def clean_org(value):
    return value if value in ORGS else COLLEGE


def current_org():
    """The organisation of this request (or of the background job). An explicit
    `with as_org(...)` always wins, so code can briefly work on the other database."""
    forced = _bg_org.get()
    if forced:
        return forced
    from flask import g, has_request_context
    if has_request_context() and g.get("org"):
        return g.org
    return COLLEGE


def uses_courses(org=None):
    return (org or current_org()) == ITHUB


@contextmanager
def as_org(org):
    """with as_org("ithub"): ...  run background work for one organisation."""
    token = _bg_org.set(clean_org(org))
    try:
        yield
    finally:
        _bg_org.reset(token)


def org_name(org=None):
    return ORGS[org or current_org()]["name"]

"""Aakansha IT Hub course catalogue: name, picture, price, duration, description.

Admins add and edit courses; everyone at the IT Hub sees them. The course
names are what students join, what attendance is kept by, and what tests
and fees are for. Courses live only in the IT Hub database.
"""
import uuid

import cv2
import numpy as np
from flask import Blueprint, request, send_file

import config
from common import clean_text, fail, get_settings, ok, stamp, too_many_pixels
from models import (AttendanceRecord, Admin, ClassPhoto, Course, Exam, FeeDue, Student, db)
from orgs import ITHUB, uses_courses

bp = Blueprint("courses", __name__, url_prefix="/api/courses")
MAX_IMAGE_BYTES = 6 * 1024 * 1024
IMAGE_WIDTH = 1200
NAME_CHARS = set(" .+#&/-()")


def _seed_from_old_list():
    """The first version kept only names in Settings: turn them into courses once."""
    with db() as s:
        if s.query(Course).count():
            return
        for name in get_settings().get("courses") or []:
            if name and not s.query(Course).filter(Course.name == name).first():
                s.add(Course(org=ITHUB, name=name))


def course_names(active_only=True):
    """Names of the IT Hub's courses (the ones open for new students by default)."""
    if not uses_courses():
        return []
    _seed_from_old_list()
    with db() as s:
        q = s.query(Course.name)
        if active_only:
            q = q.filter(Course.active.is_(True))
        return [n for (n,) in q.order_by(Course.name)]


def all_course_names():
    return course_names(active_only=False)


# ---------------- batches: "Course · Batch" classes ----------------
SEP = " · "


def unit_key(course, batch=""):
    return f"{course}{SEP}{batch}" if batch else course


def unit_course(unit):
    return str(unit or "").split(SEP, 1)[0]


def units_for(courses, batches):
    """A student's classes: each course (for 'whole course' access) and its Course · Batch."""
    out = []
    for c in courses or []:
        out.append(c)
        b = (batches or {}).get(c)
        if b:
            out.append(unit_key(c, b))
    return out


def batch_list():
    return [b for b in (get_settings().get("batches") or []) if b]


def picker_units(courses=None):
    """The classes to pick from when taking attendance: Course · Batch for every batch
    (just the course while no batches are set up)."""
    bs = batch_list()
    out = []
    for c in (courses if courses is not None else all_course_names()):
        out += [unit_key(c, b) for b in bs] if bs else [c]
    return out


def team_units():
    """What an admin can give a teacher: a whole course, or one batch of it."""
    bs = batch_list()
    out = []
    for c in all_course_names():
        out.append(c)
        out += [unit_key(c, b) for b in bs]
    return out


def valid_unit(unit):
    course, _, batch = str(unit or "").partition(SEP)
    return course in all_course_names() and (not batch or batch in batch_list())


def unit_allowed(unit, sc):
    """May a teacher with scope sc work with this class? (None = everything)"""
    return sc is None or unit in sc or unit_course(unit) in sc


def course_json(c, students=None):
    return {"id": c.id, "name": c.name, "description": c.description, "price": c.price, "duration": c.duration,
            "active": c.active, "has_image": bool(c.image_file), "image_v": stamp(c.updated_at),
            "students": students, "created_at": stamp(c.created_at)}


def _hub_only():
    if not uses_courses():
        return fail("Courses are only used by Aakansha IT Hub.", 400)
    return None


def _clean_fields(d, partial=False):
    """(fields, error) from a form or JSON body."""
    out = {}
    if not partial or "name" in d:
        name = clean_text(d.get("name"), 60)
        if not name:
            return None, "Give the course a name, e.g. Python programming."
        if not all(ch.isalnum() or ch in NAME_CHARS for ch in name):
            return None, "Course names can use letters, numbers, spaces and . + # & / - ( )"
        out["name"] = name
    if not partial or "description" in d:
        out["description"] = str(d.get("description") or "").strip()[:2000]
    if not partial or "duration" in d:
        out["duration"] = clean_text(d.get("duration"), 40)
    if not partial or "price" in d:
        raw = str(d.get("price") if d.get("price") is not None else "0").replace(",", "").strip() or "0"
        try:
            price = round(float(raw), 2)
        except ValueError:
            return None, "Enter the price in rupees, e.g. 6000."
        if not 0 <= price <= 10_000_000:
            return None, "Enter the price in rupees, e.g. 6000."
        out["price"] = price
    if "active" in d:
        out["active"] = str(d.get("active")).lower() in ("1", "true", "yes", "on")
    return out, None


def _save_image(file, course_id):
    """Store an uploaded picture as a resized JPEG. Returns (file name, error)."""
    raw = file.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        return None, "The picture is too big (max 6 MB)."
    data = np.frombuffer(raw, np.uint8)
    if too_many_pixels(data):
        return None, "The picture is too big."
    try:
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except cv2.error:
        img = None
    if img is None:
        return None, "That file isn't a picture that can be read. Use JPG or PNG."
    h, w = img.shape[:2]
    if w > IMAGE_WIDTH:
        img = cv2.resize(img, (IMAGE_WIDTH, round(h * IMAGE_WIDTH / w)), interpolation=cv2.INTER_AREA)
    name = f"course_{course_id}_{uuid.uuid4().hex[:8]}.jpg"
    cv2.imwrite(str(config.COURSE_IMAGES_DIR / name), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return name, None


def _body():
    return request.form if request.files or request.form else (request.get_json(silent=True) or {})


def _rename_everywhere(s, old, new):
    """A renamed course keeps its students, registers, tests and fees."""
    for st in s.query(Student).all():
        if old in (st.courses or []):
            st.courses = [new if c == old else c for c in st.courses]
    for a in s.query(Admin).all():
        if old in (a.branches or []):
            a.branches = [new if c == old else c for c in a.branches]
    for st in s.query(Student).all():
        if old in (st.batches or {}):
            st.batches = {(new if k == old else k): v for k, v in st.batches.items()}
        st.units = units_for(st.courses, st.batches)
    for a in s.query(Admin).all():   # whole-course and per-batch assignments
        if any(unit_course(u) == old for u in (a.branches or [])):
            a.branches = [unit_key(new, u.partition(SEP)[2]) if unit_course(u) == old else u for u in a.branches]
    for rec in s.query(AttendanceRecord).filter(
            (AttendanceRecord.course == old) | AttendanceRecord.course.like(old + SEP + "%")):
        rec.course = new + rec.course[len(old):]
    for cp in s.query(ClassPhoto).filter(
            (ClassPhoto.branch == old) | ClassPhoto.branch.like(old + SEP + "%")):
        cp.branch = new + cp.branch[len(old):]
    s.query(Exam).filter(Exam.course == old).update({"course": new})
    s.query(FeeDue).filter(FeeDue.course == old).update({"course": new})



# ---------------- API ----------------
@bp.get("")
def list_courses():
    err = _hub_only()
    if err:
        return err
    _seed_from_old_list()
    with db() as s:
        counts = {}
        for st in s.query(Student.courses):
            for c in st[0] or []:
                counts[c] = counts.get(c, 0) + 1
        rows = s.query(Course).order_by(Course.active.desc(), Course.name).all()
        return ok(courses=[course_json(c, counts.get(c.name, 0)) for c in rows], batches=batch_list())


@bp.put("/batches")
def set_batches():
    """IT Hub admin: the batch timings students can be put in (e.g. 4–6 PM, 6–8 PM)."""
    err = _hub_only()
    if err:
        return err
    raw = (request.get_json(silent=True) or {}).get("batches")
    out = []
    for b in (raw if isinstance(raw, list) else []):
        b = clean_text(b, 30)
        if b and b not in out:
            if SEP.strip() in b:
                return fail("A batch name can't contain '·'.")
            out.append(b)
    if len(out) > 20:
        return fail("At most 20 batches.")
    from common import update_settings
    update_settings(batches=out)
    return ok("Batch timings saved. Students already in a removed batch keep it until you edit them.", batches=out)


@bp.post("")
def create_course():
    err = _hub_only()
    if err:
        return err
    fields, error = _clean_fields(_body())
    if error:
        return fail(error)
    with db() as s:
        if s.query(Course).filter(Course.name == fields["name"]).first():
            return fail(f"There is already a course called {fields['name']}.", 409)
        if s.query(Course).count() >= 100:
            return fail("At most 100 courses.")
        c = Course(org=ITHUB, **fields)
        s.add(c)
        s.flush()
        if "image" in request.files and request.files["image"].filename:
            name, error = _save_image(request.files["image"], c.id)
            if error:
                s.rollback()
                return fail(error)
            c.image_file = name
        s.flush()
        return ok(f"{c.name} added", course=course_json(c, 0))


@bp.put("/<int:cid>")
def update_course(cid):
    err = _hub_only()
    if err:
        return err
    fields, error = _clean_fields(_body(), partial=True)
    if error:
        return fail(error)
    old_file = None
    with db() as s:
        c = s.get(Course, cid)
        if not c:
            return fail("Course not found.", 404)
        if "name" in fields and fields["name"] != c.name:
            if s.query(Course).filter(Course.name == fields["name"], Course.id != cid).first():
                return fail(f"There is already a course called {fields['name']}.", 409)
            _rename_everywhere(s, c.name, fields["name"])
        for k, v in fields.items():
            setattr(c, k, v)
        if "image" in request.files and request.files["image"].filename:
            name, error = _save_image(request.files["image"], c.id)
            if error:
                return fail(error)
            old_file, c.image_file = c.image_file, name
        elif str(_body().get("remove_image") or "").lower() in ("1", "true"):
            old_file, c.image_file = c.image_file, ""
        s.flush()
        out = course_json(c)
    if old_file:
        (config.COURSE_IMAGES_DIR / old_file).unlink(missing_ok=True)
    return ok(f"{out['name']} saved", course=out)


@bp.delete("/<int:cid>")
def delete_course(cid):
    err = _hub_only()
    if err:
        return err
    with db() as s:
        c = s.get(Course, cid)
        if not c:
            return fail("Course not found.", 404)
        joined = sum(1 for (cs,) in s.query(Student.courses) if c.name in (cs or []))
        if joined:
            return fail(f"{joined} student(s) are in {c.name}. Switch the course off instead: "
                        "it then can't be picked for new students, and old records stay.", 409)
        name, image = c.name, c.image_file
        s.delete(c)
    if image:
        (config.COURSE_IMAGES_DIR / image).unlink(missing_ok=True)
    return ok(f"{name} removed")


@bp.get("/<int:cid>/image")
def course_image(cid):
    err = _hub_only()
    if err:
        return err
    with db() as s:
        c = s.get(Course, cid)
    path = config.COURSE_IMAGES_DIR / c.image_file if c and c.image_file else None
    if not path or not path.is_file():
        return fail("No picture.", 404)
    resp = send_file(path, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp

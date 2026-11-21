"""Student registration and profiles."""
import base64

import cv2
import numpy as np
from flask import Blueprint, request, send_file
from sqlalchemy.exc import IntegrityError

import config
from auth import scope, scope_query, visible
from common import EMAIL_RE, REG_NO_RE, clean_name, clean_text, fail, get_settings, normalize_phone, ok, stamp, too_many_pixels
from models import AbsenceAlert, Student, db
from orgs import COLLEGE, current_org, uses_courses

bp = Blueprint("students", __name__, url_prefix="/api")

TEXT_FIELDS = {  # field: max length
    "roll_no": 30, "branch": 60, "class_name": 30, "parent_name": 80, "parent_relation": 20,
    "student_email": 120, "parent_email": 120,
}
PHONE_FIELDS = ("parent_phone", "alt_phone", "student_phone")
LABELS = {"student_email": "Student email", "parent_email": "Parent email", "parent_phone": "Parent WhatsApp number",
          "alt_phone": "Other phone", "student_phone": "Student phone"}
MAX_ITEMS = 15


def encoding_of(img_bgr):
    import face_recognition
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    faces = face_recognition.face_locations(rgb)
    if not faces:
        return None, "No face found. Face the camera in good light and try again."
    if len(faces) > 1:
        return None, "More than one face found. Only the student should be in the photo."
    enc = face_recognition.face_encodings(rgb, faces)
    if not enc:
        return None, "The face isn't clear enough. Try another photo."
    return enc[0], None


def _items(raw, keys):
    """Clean a list of qualification / achievement rows; drop empty ones."""
    out = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        row = {k: clean_text(item.get(k), lim) for k, lim in keys.items()}
        if any(row.values()):
            out.append(row)
    return out


def clean_details(raw, partial=False):
    """Validate the details form. Returns (dict, error)."""
    raw = raw if isinstance(raw, dict) else {}
    cc = get_settings()["country_code"]
    out = {}
    for k, lim in TEXT_FIELDS.items():
        if partial and k not in raw:
            continue
        out[k] = clean_text(raw.get(k), lim)
    for key in ("student_email", "parent_email"):
        if out.get(key) and not EMAIL_RE.match(out[key]):
            return None, f"{LABELS[key]} is not a valid email address."
    for key in PHONE_FIELDS:
        if partial and key not in raw:
            continue
        try:
            out[key] = normalize_phone(raw.get(key), cc)
        except ValueError as e:
            return None, f"{LABELS[key]}: {e}"
    if not partial or "address" in raw:
        out["address"] = str(raw.get("address") or "").strip()[:400]
    if not partial or "qualifications" in raw:
        out["qualifications"] = _items(raw.get("qualifications"),
                                       {"course": 80, "board": 80, "year": 10, "score": 20})
    if not partial or "achievements" in raw:
        out["achievements"] = _items(raw.get("achievements"), {"title": 120, "year": 10, "details": 300})
    if "roll_no" in out:
        out["roll_no"] = out["roll_no"] or None
        if out["roll_no"] and not REG_NO_RE.match(out["roll_no"]):
            return None, "Registration number: use only letters, numbers, / - and . (max 30)."
    if uses_courses():                 # IT Hub: courses (each with a batch) instead of a branch
        out.pop("branch", None)
        if not partial or "courses" in raw:
            courses, error = clean_courses(raw.get("courses"))
            if error:
                return None, error
            batches, error = clean_batches(raw.get("batches"), courses)
            if error:
                return None, error
            from courses import units_for
            out.update(courses=courses, batches=batches, units=units_for(courses, batches))
    return out, None


def clean_batches(raw, courses):
    """IT Hub: {course: batch} for the student's courses, each from the admin's batch list."""
    from courses import SEP, batch_list
    offered = batch_list()
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for c in courses:
        b = clean_text(raw.get(c), 30)
        if not offered:
            continue                      # no batches set up: courses only
        if not b:
            return None, f"Choose the batch timing for {c}."
        if b not in offered or SEP.strip() in b:
            return None, f"{b} isn't one of the batch timings. Pick one from the list."
        out[c] = b
    return out, None


def clean_courses(raw):
    """IT Hub: the student's courses, each one from the course list in Settings."""
    from courses import course_names
    offered = course_names()          # only courses open for new students
    picked = []
    for c in (raw if isinstance(raw, list) else [raw] if raw else []):
        c = clean_text(c, 60)
        if c and c not in picked:
            picked.append(c)
    if not picked:
        return None, "Choose at least one course."
    unknown = [c for c in picked if c not in offered]
    if unknown:
        return None, f"Not in the course list: {', '.join(unknown)}. An admin can add courses on the Students page."
    return picked, None


def check_scope(details):
    """Teachers can only put students in their own branches (college) or courses (IT Hub)."""
    sc = scope()
    if sc is None:
        return None
    if uses_courses():
        from courses import unit_allowed, unit_key
        if "courses" in details:
            for c in details["courses"]:
                unit = unit_key(c, (details.get("batches") or {}).get(c, ""))
                if not unit_allowed(unit, sc):
                    return (f"You can only add students to your own classes: {', '.join(sc)}." if sc
                            else "No course has been assigned to you yet. Ask the IT Hub admin.")
        return None
    if "branch" in details and details["branch"] not in sc:
        return f"Choose one of your branches: {', '.join(sc)}."
    return None


def to_json(st):
    return {
        "id": st.id, "name": st.name, "roll_no": st.roll_no or "", "branch": st.branch, "class_name": st.class_name,
        "courses": st.courses or [], "batches": st.batches or {}, "units": st.units or [],
        "student_email": st.student_email, "student_phone": st.student_phone,
        "parent_name": st.parent_name, "parent_relation": st.parent_relation,
        "parent_phone": st.parent_phone, "parent_email": st.parent_email, "alt_phone": st.alt_phone,
        "address": st.address, "qualifications": st.qualifications or [], "achievements": st.achievements or [],
        "consent": st.consent, "registered_at": stamp(st.registered_at), "updated_at": stamp(st.updated_at),
        "has_face": st.face_encoding is not None,
    }


def decode_image(data_url):
    data = str(data_url or "")
    if "," in data:
        data = data.split(",", 1)[1]
    if len(data) > 16 * 1024 * 1024:     # ~12 MB photo; webcam shots are far smaller
        return None
    try:
        raw = base64.b64decode(data)
        if too_many_pixels(raw):
            return None
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None
    if frame is None:
        return None
    h, w = frame.shape[:2]
    scale = 960 / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    return frame


def _dup_message(exc):
    text = str(getattr(exc, "orig", exc)).lower()
    if "roll_no" in text or "org_roll" in text:     # PostgreSQL names the column, MySQL the index
        return "Another student already has this registration number."
    return "A student with this name already exists."


# ---------------- API ----------------
@bp.get("/students")
def list_students():
    with db() as s:
        rows = scope_query(s.query(Student)).order_by(Student.name).all()
        return ok(students=[to_json(r) for r in rows], total=len(rows))


@bp.get("/students/<int:sid>/photo")
def photo(sid):
    with db() as s:
        st = s.get(Student, sid)
    path = config.KNOWN_FACES_DIR / st.photo_file if visible(st) and st.photo_file else None
    if not path or not path.is_file():
        return fail("Photo not found.", 404)
    resp = send_file(path)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@bp.post("/register")
def register():
    """Photo (base64) + details. The photo must contain exactly one face."""
    data = request.get_json(silent=True) or {}
    name = clean_name(data.get("name"))
    if not name:
        return fail("Use a name with letters, numbers, spaces, . ' or - (max 60).")
    details, error = clean_details(data.get("details"))
    if error:
        return fail(error)
    sc = scope()
    if sc is not None and not uses_courses():   # teachers register students into their own branches
        if not details.get("branch") and len(sc) == 1:
            details["branch"] = sc[0]
        if details.get("branch") not in sc:
            return fail(f"Choose one of your branches: {', '.join(sc)}.", 403)
    error = check_scope(details)
    if error:
        return fail(error, 403)
    if not data.get("consent"):
        return fail("Tick the consent box. A signed consent form is needed before saving a face (report section 3.6.3).")

    frame = decode_image(data.get("image"))
    if frame is None:
        return fail("The photo could not be read. Try another one.")
    enc, error = encoding_of(frame)
    if error:
        return fail(error, 422)

    org = current_org()
    with db() as s:
        existing = s.query(Student).filter(Student.org == org, Student.name == name).first()
        if existing and not visible(existing):
            return fail("A student with this name is registered in another branch / course.", 409)
        if existing and not data.get("overwrite"):
            return fail(f"{name} is already registered.", 409, exists=True)

    # IT Hub photos get a prefix: the same name can exist in both organisations.
    filename = f"{name}.jpg" if org == COLLEGE else f"{org}__{name}.jpg"
    cv2.imwrite(str(config.KNOWN_FACES_DIR / filename), frame)
    try:
        with db() as s:
            st = (s.query(Student).filter(Student.org == org, Student.name == name).first()
                  or Student(name=name, org=org))
            for k, v in details.items():
                if v or not st.id:  # replacing a photo keeps old details unless new ones were typed
                    setattr(st, k, v)
            st.photo_file, st.face_encoding, st.consent = filename, enc.astype(np.float64).tobytes(), True
            if st.id:
                from models import now
                st.registered_at = now()
            s.add(st)
            s.flush()
            sid = st.id
    except IntegrityError as e:
        return fail(_dup_message(e), 409)
    return ok(f"{name} registered", id=sid)


@bp.put("/students/<int:sid>")
def update(sid):
    details, error = clean_details(request.get_json(silent=True) or {}, partial=True)
    if error:
        return fail(error)
    try:
        with db() as s:
            st = s.get(Student, sid)
            if not visible(st):
                return fail("Student not found.", 404)
            error = check_scope(details)
            if error:
                return fail(error, 403)
            for k, v in details.items():
                setattr(st, k, v)
            s.flush()
            name = st.name
    except IntegrityError as e:
        return fail(_dup_message(e), 409)
    return ok(f"{name} updated")


@bp.delete("/students/<int:sid>")
def delete(sid):
    """Erase a student completely (e.g. after they leave): profile, every photo, attendance
    history and its CSV copies, fees, leave, results, messages and replies. Nothing remains."""
    from models import (AttendanceRecord, ClassPhoto, ExamResult, FeeDue, InboxMail, LeaveRequest,
                        Message, StudentFace, StudentUnit, WaIncoming)
    from faces import extra_rel
    org = current_org()
    with db() as s:
        st = s.get(Student, sid)
        if not visible(st):
            return fail("Student not found.", 404)
        name, photo_file = st.name, st.photo_file
        extra_files = [f.photo_file for f in s.query(StudentFace).filter(StudentFace.student_id == sid) if f.photo_file]
        # attendance: rows linked to the profile, and rows of the same name left unlinked by an older delete
        att = s.query(AttendanceRecord).filter(AttendanceRecord.org == org).filter(
            (AttendanceRecord.student_id == sid) |
            ((AttendanceRecord.student_id.is_(None)) & (AttendanceRecord.student_name == name)))
        registers = {(r.day, r.course or "") for r in att}       # CSV copies to rewrite
        att.delete(synchronize_session=False)
        # WhatsApp replies from the family's numbers, unless another student shares that number
        phones = {p for p in (st.parent_phone, st.alt_phone, st.student_phone) if p}
        shared = set()
        if phones:
            for o in s.query(Student).filter(Student.id != sid):
                shared |= {o.parent_phone, o.alt_phone, o.student_phone} & phones
            gone = phones - shared
            if gone:
                s.query(WaIncoming).filter(WaIncoming.org == org, WaIncoming.phone.in_(gone)).delete(synchronize_session=False)
        for model in (Message, InboxMail, FeeDue, LeaveRequest, ExamResult, StudentFace, AbsenceAlert, StudentUnit):
            s.query(model).filter(model.student_id == sid).delete(synchronize_session=False)
        # class photos stay (they show other students too), but no longer name this one
        for cp in s.query(ClassPhoto).filter(ClassPhoto.org == org):
            if sid in (cp.present_ids or []) or any(f.get("student_id") == sid for f in cp.faces or []):
                cp.present_ids = [i for i in (cp.present_ids or []) if i != sid]
                cp.faces = [{**f, "student_id": None, "name": "", "confidence": 0} if f.get("student_id") == sid else f
                            for f in cp.faces or []]
        s.delete(st)
    # files: registration photo, extra photos, and the daily CSV registers rewritten without the student
    for rel in [photo_file, *extra_files]:
        if rel:
            (config.KNOWN_FACES_DIR / rel).unlink(missing_ok=True)
    import shutil
    shutil.rmtree(config.KNOWN_FACES_DIR / extra_rel(sid, org), ignore_errors=True)
    from attendance import write_csv
    for day, course in registers:
        try:
            write_csv(day, course)
        except OSError:
            pass                      # a CSV open in Excel: it is rewritten with the next save
    return ok(f"{name} and all their records were removed")


@bp.get("/students/branches")
def branches():
    if uses_courses():   # IT Hub: the course list (teachers: their own courses)
        sc = scope()
        # branches = the classes this user can pick (Course · Batch); courses = course names
        # they can register students into; team = what an admin can assign to a teacher.
        from courses import all_course_names, batch_list, picker_units, team_units, unit_allowed
        offered = all_course_names()
        units = [u for u in picker_units(offered) if unit_allowed(u, sc)]
        mine = [c for c in offered if sc is None or c in sc or any(u.startswith(c + " · ") for u in sc)]
        return ok(branches=units, courses=offered, my_courses=mine, batches=batch_list(),
                  team=team_units() if sc is None else [], classes=[])
    with db() as s:
        rows = scope_query(s.query(Student.branch, Student.class_name)).distinct().all()
    return ok(branches=sorted({b for b, _ in rows if b}), classes=sorted({c for _, c in rows if c}))

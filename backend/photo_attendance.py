"""Attendance from class photos taken on the teacher's phone.

1. analyze: up to 5 photos -> find every face -> match against the class's students
2. the teacher reviews (fix a wrong name, tick someone who was missed)
3. save: Present / Absent rows are written and the photos are kept as evidence
There is no liveness check here: the teacher taking the photo is the witness.
"""
import shutil
import threading
from datetime import date, datetime, timedelta

import cv2
import numpy as np
from flask import Blueprint, g, request, send_file

import attendance
import config
from auth import scope, scope_query
from common import fail, iso, ok, parse_day, plural, stamp, too_many_pixels
from models import ClassPhoto, Student, StudentFace, db, now
from orgs import as_org, current_org, uses_courses

bp = Blueprint("photo_attendance", __name__, url_prefix="/api/photo-attendance")
PHOTO_DIR = config.BASE_DIR / "class_photos"


def photo_rel(cp_id, org=None):
    """class_photos/<id> (college) or class_photos/ithub/<id>: ids repeat between the two databases."""
    org = org or current_org()
    return str(cp_id) if org == "college" else f"{org}/{cp_id}"
MAX_PHOTOS = 5
MAX_SIDE = 2000          # phone photos are shrunk to this; big enough for back rows, still quick
MATCH = 0.55             # a little looser than the live camera: group photos are softer
SMALL_FACE = 45          # px; smaller faces are flagged as "too small to be sure"


def class_students(branch):
    """The class: students of one branch (college) or one course (IT Hub; `branch` holds the course)."""
    with db() as s:
        q = scope_query(s.query(Student))
        if uses_courses():
            q = attendance.enrolled(q, branch)
        elif branch:
            q = q.filter(Student.branch == branch)
        return q.order_by(Student.roll_no, Student.name).all()


def encodings_for(students):
    """(matrix of encodings, list of student ids) - main photo plus extra angles."""
    ids = {st.id for st in students}
    encs, owners = [], []
    for st in students:
        if st.face_encoding:
            encs.append(np.frombuffer(st.face_encoding, dtype=np.float64))
            owners.append(st.id)
    with db() as s:
        for f in s.query(StudentFace).filter(StudentFace.student_id.in_(list(ids) or [-1])):
            encs.append(np.frombuffer(f.encoding, dtype=np.float64))
            owners.append(f.student_id)
    return (np.array(encs) if encs else np.zeros((0, 128))), owners


def read_photo(file):
    raw = np.frombuffer(file.read(), np.uint8)
    if too_many_pixels(raw):
        return None
    try:   # pictures over 40 megapixels are refused by OpenCV (see config.py)
        img = cv2.imdecode(raw, cv2.IMREAD_COLOR)      # also applies the phone's EXIF rotation
    except cv2.error:
        return None
    if img is None:
        return None
    h, w = img.shape[:2]
    scale = MAX_SIDE / max(h, w)
    return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img


def match_faces(photos, students):
    """Find faces in every photo and give each the closest student (one face per
    student per photo). Returns the face list for the review screen."""
    import face_recognition
    known, owners = encodings_for(students)
    names = {st.id: st.name for st in students}
    faces = []
    for p, img in enumerate(photos):
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        locs = face_recognition.face_locations(rgb, number_of_times_to_upsample=1, model="hog")
        encs = face_recognition.face_encodings(rgb, locs)
        h, w = img.shape[:2]
        found = []
        for (top, right, bottom, left), enc in zip(locs, encs):
            best = {}
            if len(known):
                dists = face_recognition.face_distance(known, enc)
                for d, sid in zip(dists, owners):
                    best[sid] = min(best.get(sid, 9), float(d))
            found.append({"photo": p, "box": [round(top / h, 4), round(right / w, 4), round(bottom / h, 4), round(left / w, 4)],
                          "size": right - left, "best": sorted(best.items(), key=lambda kv: kv[1])})
        # closest pairs first, so two faces never get the same student in one photo
        pairs = sorted(((d, i, sid) for i, f in enumerate(found) for sid, d in f["best"] if d < MATCH))
        taken_faces, taken_students = set(), set()
        for d, i, sid in pairs:
            if i in taken_faces or sid in taken_students:
                continue
            taken_faces.add(i)
            taken_students.add(sid)
            found[i].update(student_id=sid, name=names[sid], confidence=round((1 - d) * 100))
        for f in found:
            f.setdefault("student_id", None)
            f.setdefault("name", "")
            f.setdefault("confidence", 0)
            f["small"] = f.pop("size") < SMALL_FACE
            f.pop("best")
            faces.append(f)
    return faces


def session_json(cp, students=None):
    out = {"id": cp.id, "day": iso(cp.day), "branch": cp.branch, "photos": len(cp.files), "faces": cp.faces,
           "status": cp.status, "present_ids": cp.present_ids, "taken_by": cp.taken_by,
           "created_at": stamp(cp.created_at), "saved_at": stamp(cp.saved_at)}
    if students is not None:
        matched = {f["student_id"] for f in cp.faces if f.get("student_id")}
        with db() as s:
            from models import AttendanceRecord
            rows = {r.student_name: r.status for r in attendance.rec_query(s, attendance.course_of(cp.branch))
                    .filter(AttendanceRecord.day == cp.day)}
        on_leave = attendance.leave_days(cp.day, cp.day)
        out["students"] = [{"id": st.id, "name": st.name, "roll_no": st.roll_no or "", "branch": st.branch,
                            "found": st.id in matched, "already": rows.get(st.name),
                            "on_leave": cp.day in on_leave.get(st.id, ()), "has_face": st.face_encoding is not None}
                           for st in students]
    return out


def _session(sid):
    """The session if this user may see it (teachers: their branches only)."""
    with db() as s:
        cp = s.get(ClassPhoto, sid)
    if not cp or (cp.org or "college") != current_org():
        return None
    sc = scope()
    if uses_courses():
        from courses import unit_allowed
        return cp if unit_allowed(cp.branch, sc) else None
    if sc is not None and cp.branch not in sc:
        return None
    return cp


def _cleanup_drafts():
    """Unsaved photos are deleted after a day (they show the whole class)."""
    cutoff = now() - timedelta(days=1)
    with db() as s:
        for cp in s.query(ClassPhoto).filter(ClassPhoto.status == "draft", ClassPhoto.created_at < cutoff):
            shutil.rmtree(PHOTO_DIR / photo_rel(cp.id), ignore_errors=True)
            s.delete(cp)


# ---------------- API ----------------
@bp.post("/analyze")
def analyze():
    import guard
    blocked = guard.check()        # proxy protection: approved device / college network / location
    if blocked:
        return blocked
    files = [f for f in request.files.getlist("photos") if f and f.filename]
    day = parse_day(request.form.get("day")) or date.today()
    branch = (request.form.get("branch") or request.form.get("course") or "").strip()
    sc = scope()
    if uses_courses():   # IT Hub: one course per class photo
        from courses import unit_allowed, valid_unit
        if not valid_unit(branch):
            return fail("Choose the course and batch this class photo is for.")
        if not unit_allowed(branch, sc):
            return fail("No course has been assigned to you yet. Ask the IT Hub admin." if not sc
                        else f"Choose one of your classes: {', '.join(sc)}.", 403)
    elif sc is not None:
        if not branch and len(sc) == 1:
            branch = sc[0]
        if branch not in sc:
            return fail(f"Choose one of your branches: {', '.join(sc)}.", 403)
    if not files:
        return fail("Add at least one class photo.")
    if len(files) > MAX_PHOTOS:
        return fail(f"At most {MAX_PHOTOS} photos at a time. Split big classes by rows.")
    if day > date.today():
        return fail("The date can't be in the future.")
    students = class_students(branch)
    if not students:
        return fail("No students are registered in this " + ("course." if uses_courses() else "branch."))
    photos = []
    for f in files:
        img = read_photo(f)
        if img is None:
            return fail(f"{f.filename} isn't a photo that can be read. Use JPG or PNG.")
        photos.append(img)
    _cleanup_drafts()
    faces = match_faces(photos, students)
    with db() as s:
        cp = ClassPhoto(org=current_org(), day=day, branch=branch, faces=faces, taken_by=g.get("admin_name", ""))
        s.add(cp)
        s.flush()
        folder = PHOTO_DIR / photo_rel(cp.id)
        folder.mkdir(parents=True, exist_ok=True)
        cp.files = []
        for i, img in enumerate(photos, start=1):
            cv2.imwrite(str(folder / f"{i}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
            cp.files = cp.files + [f"{photo_rel(cp.id)}/{i}.jpg"]
        out = session_json(cp, students)
    found = sum(1 for x in out["students"] if x["found"])
    unknown = sum(1 for f in faces if not f["student_id"])
    msg = f"Found {plural(len(faces), 'face')}: {found} of {len(students)} students recognised"
    msg += f", {unknown} not recognised." if unknown else "."
    return ok(msg, session=out)


@bp.get("/<int:sid>")
def get_session(sid):
    cp = _session(sid)
    if not cp:
        return fail("Not found.", 404)
    return ok(session=session_json(cp, class_students(cp.branch)))


@bp.get("/<int:sid>/photo/<int:n>")
def photo(sid, n):
    cp = _session(sid)
    if not cp or not 1 <= n <= len(cp.files):
        return fail("Photo not found.", 404)
    path = PHOTO_DIR / cp.files[n - 1]
    if not path.is_file():
        return fail("Photo not found.", 404)
    resp = send_file(path)
    resp.headers["Cache-Control"] = "private, max-age=3600"
    return resp


@bp.post("/<int:sid>/save")
def save(sid):
    import guard
    blocked = guard.check()
    if blocked:
        return blocked
    cp = _session(sid)
    if not cp:
        return fail("Not found.", 404)
    students = class_students(cp.branch)
    allowed = {st.id: st for st in students}
    ids = [int(x) for x in (request.get_json(silent=True) or {}).get("present_ids") or [] if int(x) in allowed]
    stamp_ = f"{datetime.now().strftime('%I:%M %p')} (photo)"
    from models import AttendanceRecord
    course = attendance.course_of(cp.branch)
    with db() as s:   # already marked present (e.g. by the live camera): keep that time
        done = {r.student_name for r in attendance.rec_query(s, course).filter(
            AttendanceRecord.day == cp.day, AttendanceRecord.status == "Present")}
    for i in ids:
        if allowed[i].name not in done:
            attendance.mark_present(cp.day, allowed[i].name, stamp_, source="photo", write=False, course=course)
    attendance.finalize_students(cp.day, allowed.keys(), source="photo", course=course)   # the rest: Absent / Leave
    with db() as s:
        row = s.get(ClassPhoto, sid)
        row.status, row.present_ids, row.saved_at = "saved", ids, now()
    import notify
    org = current_org()

    def alerts():
        with as_org(org):
            notify.run_auto_alerts()
    threading.Thread(target=alerts, daemon=True).start()
    absent = len(students) - len(ids)
    return ok(f"Saved: {len(ids)} present, {absent} not present. The photos are kept as evidence.")


@bp.get("")
def list_sessions():
    """Saved class photos for a day (evidence shown on the Attendance page)."""
    day = parse_day(request.args.get("day"))
    with db() as s:
        q = s.query(ClassPhoto).filter(ClassPhoto.status == "saved", ClassPhoto.org == current_org())
        if uses_courses() and request.args.get("course"):
            q = q.filter(ClassPhoto.branch == request.args.get("course"))
        if day:
            q = q.filter(ClassPhoto.day == day)
        sc = scope()
        if sc is not None:
            q = q.filter(ClassPhoto.branch.in_(sc))
        return ok(sessions=[session_json(cp) for cp in q.order_by(ClassPhoto.saved_at.desc()).limit(50)])


@bp.delete("/<int:sid>")
def delete_session(sid):
    with db() as s:
        cp = s.get(ClassPhoto, sid)
        if not cp or (cp.org or "college") != current_org():
            return fail("Not found.", 404)
        s.delete(cp)
    shutil.rmtree(PHOTO_DIR / photo_rel(sid), ignore_errors=True)
    return ok("Photos deleted. The attendance that was saved stays.")


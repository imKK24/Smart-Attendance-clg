"""Several photos per student. Each extra photo (turned a little, with glasses,
in other light) adds one face encoding, so recognition works in more conditions."""
import shutil
import uuid

import cv2
import numpy as np
from flask import Blueprint, request, send_file
from sqlalchemy import event

import config
from auth import visible
from common import clean_text, fail, ok, stamp
from models import Student, StudentFace, db
from students import decode_image, encoding_of

bp = Blueprint("faces", __name__, url_prefix="/api/students")

MAX_EXTRA = 6
SAME_PERSON = 0.6   # an extra photo must be at least this close to the student's main photo


def extra_rel(sid, org=None):
    """extra/<id> (college) or extra/ithub/<id>: ids repeat between the two databases."""
    from orgs import COLLEGE, current_org
    org = org or current_org()
    return f"extra/{sid}" if org == COLLEGE else f"extra/{org}/{sid}"


def extra_dir(sid):
    path = config.KNOWN_FACES_DIR / extra_rel(sid)
    path.mkdir(parents=True, exist_ok=True)
    return path


def face_json(f):
    return {"id": f.id, "label": f.label, "created_at": stamp(f.created_at)}


@event.listens_for(Student, "after_delete")
def _remove_photos(_mapper, _conn, target):
    """Deleting a student also deletes their extra photos (biometric data)."""
    shutil.rmtree(config.KNOWN_FACES_DIR / extra_rel(target.id, target.org or "college"), ignore_errors=True)


@bp.get("/<int:sid>/faces")
def list_faces(sid):
    with db() as s:
        if not visible(s.get(Student, sid)):
            return fail("Student not found.", 404)
        rows = s.query(StudentFace).filter(StudentFace.student_id == sid).order_by(StudentFace.id).all()
        return ok(faces=[face_json(f) for f in rows], max=MAX_EXTRA)


@bp.post("/<int:sid>/faces")
def add_face(sid):
    d = request.get_json(silent=True) or {}
    frame = decode_image(d.get("image"))
    if frame is None:
        return fail("The photo could not be read. Try another one.")
    enc, error = encoding_of(frame)
    if error:
        return fail(error, 422)
    with db() as s:
        st = s.get(Student, sid)
        if not visible(st):
            return fail("Student not found.", 404)
        if s.query(StudentFace).filter(StudentFace.student_id == sid).count() >= MAX_EXTRA:
            return fail(f"A student can have at most {MAX_EXTRA} extra photos. Remove one first.")
        if st.face_encoding:
            main = np.frombuffer(st.face_encoding, dtype=np.float64)
            if float(np.linalg.norm(main - enc)) > SAME_PERSON:
                return fail(f"This doesn't look like {st.name}. Check that the right student is in the photo.", 422)
        filename = f"{uuid.uuid4().hex[:12]}.jpg"
        cv2.imwrite(str(extra_dir(sid) / filename), frame)
        f = StudentFace(student_id=sid, encoding=enc.astype(np.float64).tobytes(),
                        photo_file=f"{extra_rel(sid)}/{filename}", label=clean_text(d.get("label"), 30))
        s.add(f)
        s.flush()
        return ok("Photo added", face=face_json(f))


@bp.get("/<int:sid>/faces/<int:fid>/photo")
def face_photo(sid, fid):
    with db() as s:
        f = s.get(StudentFace, fid)
        allowed = f is not None and f.student_id == sid and visible(s.get(Student, sid))
    path = config.KNOWN_FACES_DIR / f.photo_file if allowed else None
    if not path or not path.is_file():
        return fail("Photo not found.", 404)
    resp = send_file(path)
    resp.headers["Cache-Control"] = "private, no-cache"
    return resp


@bp.delete("/<int:sid>/faces/<int:fid>")
def delete_face(sid, fid):
    with db() as s:
        f = s.get(StudentFace, fid)
        if not f or f.student_id != sid or not visible(s.get(Student, sid)):
            return fail("Photo not found.", 404)
        (config.KNOWN_FACES_DIR / f.photo_file).unlink(missing_ok=True)
        s.delete(f)
    return ok("Photo removed")

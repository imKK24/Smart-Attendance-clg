"""Deleting a student who has left erases everything about them, and nothing about anyone else."""
from datetime import date, datetime

import config
from conftest import image
from test_api import DETAILS, register
from test_batch1 import mirrored_photo


def _seed(client, sid, name, phone):
    """Attendance on two days, fee, leave, a message and a WhatsApp reply for one student."""
    from attendance import write_csv
    from models import (AttendanceRecord, FeeDue, LeaveRequest, Message, WaIncoming, db)
    with client.application.app_context():
        with db() as s:
            for d in (date(2026, 11, 2), date(2026, 11, 3)):
                s.add(AttendanceRecord(org="college", course="", day=d, student_name=name, student_id=sid,
                                       time=datetime(2026, 11, 2, 9, 5).time(), status="Present", source="camera"))
            s.add(FeeDue(student_id=sid, title="Semester fee", amount=1000, due_date=date(2026, 12, 1), paid_amount=0, course=""))
            s.add(LeaveRequest(student_id=sid, start_date=date(2026, 11, 25), end_date=date(2026, 11, 26),
                               reason="Family function", source="parent", status="pending"))
            s.add(Message(org="college", batch="b1", channel="whatsapp", kind="absence", student_id=sid,
                          to=phone, body=f"{name} was absent", status="sent"))
            s.add(WaIncoming(org="college", wa_id=f"wa-{sid}", phone=phone, name="Parent", text="Ok, noted"))
        for d in (date(2026, 11, 2), date(2026, 11, 3)):
            write_csv(d)


def test_delete_erases_everything(client, auth):
    r = register(client, auth)
    assert r.status_code == 200, r.json
    sid = r.json["id"]
    other = register(client, auth, name="Ananya Pradhan",
                     details={**DETAILS, "roll_no": "2301201099", "parent_phone": "91234 56789"})
    oid = other.json["id"]
    assert client.post(f"/api/students/{sid}/faces", json={"image": mirrored_photo(), "label": "Left"}, headers=auth).status_code == 200

    from models import (AttendanceRecord, FeeDue, LeaveRequest, Message, Student, StudentFace, WaIncoming, db)
    with client.application.app_context():
        with db() as s:
            st = s.get(Student, sid)
            phone, photo = st.parent_phone, st.photo_file
            extra = [f.photo_file for f in s.query(StudentFace).filter_by(student_id=sid)]
    _seed(client, sid, "Dhanish Kumar", phone)
    _seed(client, oid, "Ananya Pradhan", "+919123456789")
    assert (config.KNOWN_FACES_DIR / photo).exists() and all((config.KNOWN_FACES_DIR / e).exists() for e in extra)
    csv = config.ATTENDANCE_DIR / "2026-11-02.csv"
    assert "Dhanish Kumar" in csv.read_text(encoding="utf-8-sig")

    r = client.delete(f"/api/students/{sid}", headers=auth)
    assert r.status_code == 200 and "all their records" in r.json["message"]

    with client.application.app_context():
        with db() as s:
            assert s.get(Student, sid) is None
            for model in (FeeDue, LeaveRequest, Message, StudentFace):
                assert s.query(model).filter_by(student_id=sid).count() == 0, model.__name__
            assert s.query(AttendanceRecord).filter(AttendanceRecord.student_name == "Dhanish Kumar").count() == 0
            assert s.query(WaIncoming).filter_by(phone=phone).count() == 0
            # the other student is untouched
            assert s.query(AttendanceRecord).filter_by(student_id=oid).count() == 2
            assert s.query(FeeDue).filter_by(student_id=oid).count() == 1
            assert s.query(WaIncoming).filter_by(phone="+919123456789").count() == 1
    # files: photo and extra photos gone; CSV registers rewritten without the student
    assert not (config.KNOWN_FACES_DIR / photo).exists()
    assert not any((config.KNOWN_FACES_DIR / e).exists() for e in extra)
    text = csv.read_text(encoding="utf-8-sig")
    assert "Dhanish Kumar" not in text and "Ananya Pradhan" in text
    # and the dashboard / attendance list no longer show the name
    assert "Dhanish Kumar" not in str(client.get("/api/attendance/2026-11-02", headers=auth).json)


def test_shared_family_number_keeps_the_siblings_replies(client, auth):
    a = register(client, auth).json["id"]
    b = register(client, auth, name="Riya Kumar", details={**DETAILS, "roll_no": "2301201098"}).json["id"]
    from models import Student, WaIncoming, db
    with client.application.app_context():
        with db() as s:
            phone = s.get(Student, a).parent_phone
            s.add(WaIncoming(org="college", wa_id="wa-shared", phone=phone, name="Parent", text="Both will come"))
    client.delete(f"/api/students/{a}", headers=auth)
    with client.application.app_context():
        with db() as s:
            assert s.query(WaIncoming).filter_by(phone=phone).count() == 1    # still the sibling's parent
            assert s.get(Student, b) is not None


def test_clean_up_after_older_deletes(client, auth):
    """Students deleted before the full erase left unlinked attendance and photos: the cleanup command removes them."""
    import shutil
    from attendance import write_csv
    from models import AttendanceRecord, db
    keep = register(client, auth).json["id"]
    with client.application.app_context():
        with db() as s:
            for n, sid in (("Old Student", None), ("Dhanish Kumar", keep)):
                s.add(AttendanceRecord(org="college", course="", day=date(2026, 10, 5), student_name=n, student_id=sid,
                                       time=None, status="Absent", source="auto"))
        write_csv(date(2026, 10, 5))
    old_photo = config.KNOWN_FACES_DIR / "Old_Student.jpg"
    old_photo.write_bytes(b"jpg")
    old_extra = config.KNOWN_FACES_DIR / "extra" / "999"
    old_extra.mkdir(parents=True, exist_ok=True)
    (old_extra / "1.jpg").write_bytes(b"jpg")

    import manage
    with client.application.app_context():
        manage.clean_deleted_students()
        with db() as s:
            names = {r.student_name for r in s.query(AttendanceRecord).filter_by(day=date(2026, 10, 5))}
    assert names == {"Dhanish Kumar"}
    assert "Old Student" not in (config.ATTENDANCE_DIR / "2026-10-05.csv").read_text(encoding="utf-8-sig")
    moved = config.KNOWN_FACES_DIR / "_removed" / "college"
    assert not old_photo.exists() and (moved / "Old_Student.jpg").exists()
    assert not old_extra.exists() and (moved / "extra-999" / "1.jpg").exists()
    shutil.rmtree(config.KNOWN_FACES_DIR / "_removed", ignore_errors=True)

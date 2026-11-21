"""Aakansha IT Hub course catalogue, and the two separate databases."""
import io

import cv2
import numpy as np

from conftest import media
from test_api import DETAILS, register
from test_ithub import HUB_DETAILS, hub_login


def picture(w=1600, h=900):
    img = np.full((h, w, 3), (40, 120, 200), np.uint8)
    cv2.putText(img, "Python", (100, 400), cv2.FONT_HERSHEY_SIMPLEX, 8, (255, 255, 255), 12)
    return io.BytesIO(cv2.imencode(".png", img)[1].tobytes())


def test_admin_adds_course_with_picture_price_and_description(client, auth, app):
    import config
    h = hub_login(client)
    r = client.post("/api/courses", headers=h, content_type="multipart/form-data", data={
        "name": "Python programming", "price": "6,500", "duration": "3 months",
        "description": "Basics to projects: variables, loops, files, a small web app.",
        "image": (picture(), "python.png")})
    assert r.status_code == 200, r.json
    c = r.json["course"]
    assert (c["price"], c["duration"], c["has_image"]) == (6500, "3 months", True)
    assert c["description"].startswith("Basics")
    stored = list(config.COURSE_IMAGES_DIR.iterdir())
    assert len(stored) == 1 and cv2.imread(str(stored[0])).shape[1] == 1200          # resized
    img = client.get(f"/api/courses/{c['id']}/image?token={media(client, h)}")
    assert img.status_code == 200 and img.mimetype == "image/jpeg"
    listed = client.get("/api/courses", headers=h).json["courses"]
    assert [x["name"] for x in listed] == ["Python programming"] and listed[0]["students"] == 0
    # bad input
    assert client.post("/api/courses", json={"name": "Python programming"}, headers=h).status_code == 409
    assert client.post("/api/courses", json={"name": "X", "price": "lots"}, headers=h).status_code == 400
    bad = client.post("/api/courses", headers=h, content_type="multipart/form-data",
                      data={"name": "Tally", "image": (io.BytesIO(b"not a picture"), "t.png")})
    assert bad.status_code == 400 and client.get("/api/courses", headers=h).json["courses"][-1]["name"] != "Tally"


def test_only_admins_change_courses_and_college_has_none(client, auth):
    h = hub_login(client)
    cid = client.post("/api/courses", json={"name": "Python", "price": 6000}, headers=h).json["course"]["id"]
    t = hub_login(client, "trainer@aakansha.in", "train-pass-55", role="teacher", courses=["Python"])
    assert client.get("/api/courses", headers=t).status_code == 403                     # catalogue: admins only
    assert client.post("/api/courses", json={"name": "Hacking"}, headers=t).status_code == 403
    assert client.put(f"/api/courses/{cid}", json={"price": 1}, headers=t).status_code == 403
    assert client.delete(f"/api/courses/{cid}", headers=t).status_code == 403
    assert client.get("/api/courses", headers=auth).status_code == 400                  # college: branches


def test_rename_keeps_students_and_records_and_switch_off(client, auth):
    import attendance
    from datetime import date
    from orgs import as_org
    h = hub_login(client)
    cid = client.post("/api/courses", json={"name": "Python", "price": 6000}, headers=h).json["course"]["id"]
    client.post("/api/courses", json={"name": "Tally", "price": 4500}, headers=h)
    sid = register(client, h, details={**HUB_DETAILS, "courses": ["Python"]}).json["id"]
    with as_org("ithub"):
        attendance.mark_present(date.today(), "Dhanish Kumar", "10:00 AM", course="Python")
    r = client.put(f"/api/courses/{cid}", json={"name": "Python programming", "price": 7000}, headers=h)
    assert r.status_code == 200 and r.json["course"]["price"] == 7000
    st = next(x for x in client.get("/api/students", headers=h).json["students"] if x["id"] == sid)
    assert st["courses"] == ["Python programming"]
    rows = client.get("/api/attendance/today?course=Python%20programming", headers=h).json["records"]
    assert [(x["Name"], x["Status"]) for x in rows] == [("Dhanish Kumar", "Present")]
    # can't delete a course with students; switch it off instead
    assert client.delete(f"/api/courses/{cid}", headers=h).status_code == 409
    assert client.put(f"/api/courses/{cid}", json={"active": False}, headers=h).status_code == 200
    r = register(client, h, name="Riya Sahu", details={**HUB_DETAILS, "roll_no": "AIH-9", "courses": ["Python programming"]})
    assert r.status_code == 400                                                         # closed for new students
    assert "Python programming · 4–6 PM" in client.get("/api/students/branches", headers=h).json["branches"]   # old records stay
    tally = next(c for c in client.get("/api/courses", headers=h).json["courses"] if c["name"] == "Tally")
    assert client.delete(f"/api/courses/{tally['id']}", headers=h).status_code == 200


def test_course_price_fills_the_fee(client, auth):
    h = hub_login(client)
    client.post("/api/courses", json={"name": "Python", "price": 6000}, headers=h)
    register(client, h, details={**HUB_DETAILS, "courses": ["Python"]})
    prices = {c["name"]: c["price"] for c in client.get("/api/courses", headers=h).json["courses"]}
    r = client.post("/api/fees", json={"title": "Python course fee", "amount": prices["Python"],
                                       "due_date": "2026-12-31", "course": "Python"}, headers=h)
    assert r.status_code == 200 and r.json["added"] == 1
    fee = client.get("/api/fees", headers=h).json["fees"][0]
    assert (fee["amount"], fee["course"]) == (6000, "Python")


def test_messages_inbox_and_whatsapp_go_to_the_right_database(client, auth, sent, monkeypatch):
    import inbox
    import notify
    import wa_chats
    from models import Message, WaIncoming, db
    from orgs import as_org
    h = hub_login(client)
    client.post("/api/courses", json={"name": "Python"}, headers=h)
    register(client, auth)                                                              # college, parent ravi@
    register(client, h, name="Riya Sahu", details={**HUB_DETAILS, "roll_no": "AIH-2", "parent_phone": "9123456780",
                                                   "student_email": "riya@student.in", "courses": ["Python"]})
    with as_org("ithub"):
        notify.enqueue([{"channel": "whatsapp", "kind": "test", "to": "+919123456780", "body": "IT Hub test"}])
    notify.process_queue()                                                              # works through both queues
    assert ("+919123456780", "IT Hub test") in sent["whatsapp"]
    with db("ithub") as s:
        assert s.query(Message).filter(Message.status == "sent").count() == 1
    with db("college") as s:
        assert s.query(Message).count() == 0
    m = inbox.parent_map()
    assert m["ravi@example.com"][0][1] == "college" and m["riya@student.in"][0][1] == "ithub"
    # an incoming WhatsApp from the IT Hub student's number is filed in the IT Hub database
    import config
    r = client.post("/api/whatsapp/incoming", json={"id": "w1", "phone": "919123456780", "text": "Hi", "name": "Riya"},
                    headers={"X-Bridge-Token": config.WA_BRIDGE_TOKEN})
    assert r.status_code == 200 and r.json["stored"], r.json
    with db("ithub") as s:
        assert s.query(WaIncoming).count() == 1
    with db("college") as s:
        assert s.query(WaIncoming).count() == 0
    chats = client.get("/api/whatsapp/chats", headers=h).json["chats"]
    assert len(chats) == 1 and client.get("/api/whatsapp/chats", headers=auth).json["chats"] == []
    _ = monkeypatch, wa_chats


def test_move_old_it_hub_records_out_of_the_college_database(client, auth):
    """Installs that used the first IT Hub version have IT Hub rows in the college database."""
    import manage
    from datetime import date
    from werkzeug.security import generate_password_hash
    from models import Admin, AttendanceRecord, Setting, Student, db
    sid = register(client, auth).json["id"]                                             # a college student stays
    with db("college") as s:                                                            # old-style IT Hub rows
        s.add(Admin(username="hub@aakansha.in", password_hash=generate_password_hash("hub-pass-77"), org="ithub"))
        st = Student(org="ithub", name="Riya Sahu", roll_no="AIH-1", courses=["Python"], consent=True)
        s.add(st)
        s.flush()
        s.add(AttendanceRecord(org="ithub", course="Python", day=date.today(), student_name="Riya Sahu",
                               student_id=st.id, status="Present", time="10:00 AM"))
        s.add(Setting(key="ithub:courses", value={"v": ["Python"]}))
    assert manage.move_ithub_data() >= 3
    with db("college") as s:
        assert [x.id for x in s.query(Student)] == [sid]
        assert s.query(Admin).filter(Admin.org == "ithub").count() == 0
        assert s.query(AttendanceRecord).filter(AttendanceRecord.org == "ithub").count() == 0
        assert s.get(Setting, "ithub:courses") is None
    with db("ithub") as s:
        assert [x.name for x in s.query(Student)] == ["Riya Sahu"]
        assert s.get(Setting, "courses").value == {"v": ["Python"]}
    h = hub_login(client)                                                               # the moved account works
    assert [c["name"] for c in client.get("/api/courses", headers=h).json["courses"]] == ["Python"]
    assert [x["name"] for x in client.get("/api/students", headers=h).json["students"]] == ["Riya Sahu"]
    assert manage.move_ithub_data() == 0                                                # safe to run again
    _ = DETAILS


def test_batches_per_course_and_attendance_per_batch(client, auth):
    """Batch timings: the admin's list, one batch per course, and a separate register for each batch."""
    import attendance
    from datetime import date
    from orgs import as_org
    from test_ithub import hub_login as login_hub
    h = login_hub(client)
    for name in ("Java", "Python"):
        client.post("/api/courses", json={"name": name}, headers=h)
    r = client.put("/api/courses/batches", json={"batches": ["Evening 4–6", "6–8 PM", "Evening 4–6"]}, headers=h)
    assert r.status_code == 200 and r.json["batches"] == ["Evening 4–6", "6–8 PM"]
    base = {**HUB_DETAILS, "courses": ["Java", "Python"], "student_phone": "9000012345"}
    r = register(client, h, details={**base, "batches": {"Java": "Evening 4–6"}})
    assert r.status_code == 400 and "batch timing for Python" in r.json["message"]
    r = register(client, h, details={**base, "batches": {"Java": "Evening 4–6", "Python": "Morning"}})
    assert r.status_code == 400 and "isn't one of the batch timings" in r.json["message"]
    a = register(client, h, details={**base, "batches": {"Java": "Evening 4–6", "Python": "6–8 PM"}}).json["id"]
    register(client, h, name="Riya Sahu", details={**base, "roll_no": "AIH-2", "courses": ["Java"],
                                                    "batches": {"Java": "6–8 PM"}})
    st = next(x for x in client.get("/api/students", headers=h).json["students"] if x["id"] == a)
    assert st["batches"] == {"Java": "Evening 4–6", "Python": "6–8 PM"}
    assert client.get("/api/students/branches", headers=h).json["branches"] == [
        "Java · Evening 4–6", "Java · 6–8 PM", "Python · Evening 4–6", "Python · 6–8 PM"]
    # one register per batch: Java 4–6 has only Dhanish, Java 6–8 only Riya
    with as_org("ithub"):
        attendance.mark_present(date.today(), "Dhanish Kumar", "4:05 PM", course="Java · Evening 4–6")
        attendance.finalize_day(date.today())
    early = client.get("/api/attendance/today?course=Java%20%C2%B7%20Evening%204%E2%80%936", headers=h).json["records"]
    late = client.get("/api/attendance/today?course=Java%20%C2%B7%206%E2%80%938%20PM", headers=h).json["records"]
    assert [(x["Name"], x["Status"]) for x in early] == [("Dhanish Kumar", "Present")]
    assert [(x["Name"], x["Status"]) for x in late] == [("Riya Sahu", "Absent")]
    # a teacher given one batch sees only that batch; one given the whole course sees all of it
    from test_ithub import hub_login
    t1 = hub_login(client, "j1@aakansha.in", "java-early-9", role="teacher", courses=["Java · Evening 4–6"])
    t2 = hub_login(client, "j2@aakansha.in", "java-all-99", role="teacher", courses=["Java"])
    assert [x["name"] for x in client.get("/api/students", headers=t1).json["students"]] == ["Dhanish Kumar"]
    assert client.get("/api/students/branches", headers=t1).json["branches"] == ["Java · Evening 4–6"]
    assert sorted(x["name"] for x in client.get("/api/students", headers=t2).json["students"]) == ["Dhanish Kumar", "Riya Sahu"]
    r = client.post("/api/start-attendance", json={"course": "Java · 6–8 PM"}, headers=t1)
    assert r.status_code == 403
    # the admin can assign whole courses or single batches
    assert "Java · 6–8 PM" in client.get("/api/students/branches", headers=h).json["team"]
    # teachers can't change the batch list
    assert client.put("/api/courses/batches", json={"batches": ["x"]}, headers=t2).status_code == 403
    # the student page shows each course in the student's own batch
    r = client.post("/api/parent/login", json={"reg_no": "AIH-001", "name": "Dhanish Kumar",
                                               "phone": "9000012345", "org": "ithub"})
    assert r.status_code == 200, r.json
    s = {"Authorization": "Bearer " + r.json["token"]}
    cards = {c["course"]: c for c in client.get("/api/parent/attendance", headers=s).json["courses"]}
    assert set(cards) == {"Java · Evening 4–6", "Python · 6–8 PM"}
    assert cards["Java · Evening 4–6"]["recent"][0]["status"] == "Present"

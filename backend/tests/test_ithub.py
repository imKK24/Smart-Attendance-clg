"""Aakansha IT Hub: its own login page, its own data, courses and per-course attendance."""
from datetime import date

import numpy as np
from werkzeug.security import generate_password_hash

from test_api import DETAILS, register
from test_batch4 import class_photo

HUB_DETAILS = {**DETAILS, "branch": "", "roll_no": "AIH-001", "courses": ["Python"],
               # each course's batch (only the ticked courses' entries are used)
               "batches": {"Python": "4–6 PM", "Tally": "6–8 PM", "Web design": "4–6 PM", "Python programming": "4–6 PM"}}


def hub_login(client, username="hub@aakansha.in", password="hub-pass-77", role="admin", courses=None):
    """An IT Hub account, logged in on the IT Hub page."""
    from models import Admin, db
    with db("ithub") as s:            # IT Hub accounts live in the IT Hub database
        if not s.query(Admin).filter(Admin.username == username).first():
            s.add(Admin(username=username, password_hash=generate_password_hash(password), role=role,
                        org="ithub", branches=courses or []))
    r = client.post("/api/auth/login", json={"username": username, "password": password, "org": "ithub"})
    assert r.status_code == 200, r.json
    return {"Authorization": "Bearer " + r.json["token"]}


def hub_ready(client):
    h = hub_login(client)
    for name, price in (("Python", 6000), ("Tally", 4500), ("Web design", 8000)):
        r = client.post("/api/courses", json={"name": name, "price": price, "duration": "3 months"}, headers=h)
        assert r.status_code == 200, r.json
    return h


def hub_student(name, courses, roll):
    """An IT Hub student with a face that won't match the test photo."""
    from models import Student, db
    with db("ithub") as s:
        st = Student(org="ithub", name=name, roll_no=roll, courses=courses, units=list(courses), consent=True,
                     face_encoding=np.random.default_rng(len(name)).normal(0, 1, 128).astype(np.float64).tobytes())
        s.add(st)
        s.flush()
        return st.id


# ---------- login pages ----------
def test_each_organisation_logs_in_on_its_own_page(client, auth):
    hub_login(client)
    r = client.post("/api/auth/login", json={"username": "hub@aakansha.in", "password": "hub-pass-77"})
    assert r.status_code == 403 and "IT Hub login page" in r.json["message"]
    r = client.post("/api/auth/login", json={"username": "admin", "password": "secret-pass-1", "org": "ithub"})
    assert r.status_code == 403 and "college login page" in r.json["message"]
    me = client.get("/api/auth/me", headers=hub_login(client)).json["user"]
    assert me["org"] == "ithub" and me["org_name"] == "Aakansha IT Hub" and me["unit"] == "course"


# ---------- separate data ----------
def test_students_are_separate_both_ways(client, auth):
    h = hub_ready(client)
    college_id = register(client, auth).json["id"]
    r = register(client, h, details=HUB_DETAILS)                     # same name, same face: allowed in the IT Hub
    assert r.status_code == 200, r.json
    hub_id = r.json["id"]
    assert [x["name"] for x in client.get("/api/students", headers=auth).json["students"]] == ["Dhanish Kumar"]
    hub_list = client.get("/api/students", headers=h).json["students"]
    assert len(hub_list) == 1 and hub_list[0]["id"] == hub_id and hub_list[0]["courses"] == ["Python"]
    # Separate databases: each numbers its own students. A number that exists only in the
    # college database finds nothing from the IT Hub side, and the other way round.
    other_id = register(client, auth, name="Krishna Sharma", details={**DETAILS, "roll_no": "2301201099"}).json["id"]
    assert other_id != hub_id
    assert client.put(f"/api/students/{other_id}", json={"class_name": "x"}, headers=h).status_code == 404
    assert client.delete(f"/api/students/{other_id}", headers=h).status_code == 404
    from conftest import media
    assert client.get(f"/api/students/{other_id}/photo?token={media(client, h)}").status_code == 404
    # and the same number on each side is each side's own student
    assert college_id == hub_id == 1
    client.put(f"/api/students/{hub_id}", json={"class_name": "Evening"}, headers=h)
    college_one = next(x for x in client.get("/api/students", headers=auth).json["students"] if x["id"] == 1)
    assert college_one["class_name"] == DETAILS["class_name"]                 # the college's student untouched
    # the rows really are in different databases
    from models import Student, db
    with db("college") as s:
        assert sorted(x.name for x in s.query(Student)) == ["Dhanish Kumar", "Krishna Sharma"]
        assert {x.org for x in s.query(Student)} == {"college"}
    with db("ithub") as s:
        assert [(x.name, x.org) for x in s.query(Student)] == [("Dhanish Kumar", "ithub")]


def test_courses_are_required_and_checked(client, auth):
    h = hub_ready(client)
    r = register(client, h, details={**HUB_DETAILS, "courses": []})
    assert r.status_code == 400 and "course" in r.json["message"]
    r = register(client, h, details={**HUB_DETAILS, "courses": ["Cooking"]})
    assert r.status_code == 400 and "Not in the course list" in r.json["message"]
    assert register(client, h, details={**HUB_DETAILS, "courses": ["Python", "Tally"]}).status_code == 200
    assert client.get("/api/students/branches", headers=h).json["branches"] == [
        "Python · 4–6 PM", "Python · 6–8 PM", "Tally · 4–6 PM", "Tally · 6–8 PM", "Web design · 4–6 PM", "Web design · 6–8 PM"]
    assert client.post("/api/courses", json={"name": "X"}, headers=auth).status_code == 400   # college: no courses


def test_trainer_only_sees_own_courses(client, auth):
    h = hub_ready(client)
    hub_student("Asha Patel", ["Python"], "AIH-1")
    hub_student("Bikash Das", ["Tally"], "AIH-2")
    hub_student("Chitra Rao", ["Python", "Tally"], "AIH-3")
    t = hub_login(client, "trainer@aakansha.in", "train-pass-55", role="teacher", courses=["Tally"])
    names = sorted(x["name"] for x in client.get("/api/students", headers=t).json["students"])
    assert names == ["Bikash Das", "Chitra Rao"]
    assert client.get("/api/students/branches", headers=t).json["branches"] == ["Tally · 4–6 PM", "Tally · 6–8 PM"]
    r = register(client, t, details={**HUB_DETAILS, "courses": ["Python"]})
    assert r.status_code == 403
    _ = h


# ---------- attendance per course ----------
def test_attendance_is_per_course(client, auth):
    import attendance
    from orgs import as_org
    h = hub_ready(client)
    hub_student("Asha Patel", ["Python", "Tally"], "AIH-1")
    hub_student("Bikash Das", ["Python"], "AIH-2")
    hub_student("Chitra Rao", ["Tally"], "AIH-3")
    register(client, auth)                                           # a college student
    today = date.today()
    with as_org("ithub"):
        attendance.mark_present(today, "Asha Patel", "10:00 AM", course="Python")
        attendance.finalize_day(today)                               # only Python had a class today
    py = client.get("/api/attendance/today?course=Python", headers=h).json
    assert {r["Name"]: r["Status"] for r in py["records"]} == {"Asha Patel": "Present", "Bikash Das": "Absent"}
    assert client.get("/api/attendance-dates?course=Tally", headers=h).json["dates"] == []   # no Tally class today
    live = client.get("/api/attendance/today?course=Tally", headers=h).json
    assert {r["Name"]: r["Status"] for r in live["records"]} == {"Asha Patel": "Absent", "Chitra Rao": "Absent"}
    # the college register doesn't see any of it
    college = client.get("/api/attendance/today", headers=auth).json
    assert [r["Name"] for r in college["records"]] == ["Dhanish Kumar"]
    assert client.get("/api/attendance-dates", headers=auth).json["dates"] == []
    assert client.get("/api/attendance-dates?course=Python", headers=h).json["dates"] == [str(today)]


def test_class_photo_for_one_course(client, auth):
    h = hub_ready(client)
    sid = register(client, h, details={**HUB_DETAILS, "courses": ["Python"]}).json["id"]
    hub_student("Bikash Das", ["Python"], "AIH-2")
    hub_student("Chitra Rao", ["Tally"], "AIH-3")
    r = client.post("/api/photo-attendance/analyze", headers=h, content_type="multipart/form-data",
                    data={"photos": [(class_photo(), "c.jpg")]})
    assert r.status_code == 400 and "course" in r.json["message"]
    r = client.post("/api/photo-attendance/analyze", headers=h, content_type="multipart/form-data",
                    data={"course": "Python", "photos": [(class_photo(), "c.jpg")]})
    assert r.status_code == 200, r.json
    sess = r.json["session"]
    assert {x["name"]: x["found"] for x in sess["students"]} == {"Dhanish Kumar": True, "Bikash Das": False}
    assert client.post(f"/api/photo-attendance/{sess['id']}/save", json={"present_ids": [sid]}, headers=h).status_code == 200
    py = client.get("/api/attendance/today?course=Python", headers=h).json
    assert {r["Name"]: r["Status"] for r in py["records"]} == {"Dhanish Kumar": "Present", "Bikash Das": "Absent"}
    assert client.get(f"/api/photo-attendance/{sess['id']}", headers=auth).status_code == 404   # college can't open it
    assert client.get(f"/api/photo-attendance?day={date.today()}", headers=auth).json["sessions"] == []


def test_live_camera_needs_a_course_and_is_shared_fairly(client, auth, monkeypatch):
    import camera
    h = hub_ready(client)
    hub_student("Asha Patel", ["Python"], "AIH-1")
    assert client.post("/api/start-attendance", json={}, headers=h).status_code == 400
    assert client.post("/api/start-attendance", json={"course": "Tally"}, headers=h).json["message"].startswith("No students")
    monkeypatch.setattr(camera, "run_attendance_camera", lambda course="": None)
    r = client.post("/api/start-attendance", json={"course": "Python"}, headers=h)
    assert r.status_code == 200 and r.json["course"] == "Python"
    camera.camera_state.update(active=True)                          # pretend it's still running
    try:
        busy = client.get("/api/camera-status", headers=auth).json
        assert busy["busy"] and "Aakansha IT Hub" in busy["message"]
        register(client, auth)
        r = client.post("/api/start-attendance", json={}, headers=auth)
        assert r.status_code == 400 and "Aakansha IT Hub" in r.json["message"]
        assert client.post("/api/stop-attendance", headers=auth).status_code == 403
        assert client.get("/api/camera-status", headers=h).json["course"] == "Python"
    finally:
        camera.camera_state.update(active=False, org="college", course="")


# ---------- everything else is separate too ----------
def test_holidays_exams_fees_settings_team_are_separate(client, auth):
    h = hub_ready(client)
    hub_student("Asha Patel", ["Python"], "AIH-1")
    register(client, auth)
    client.post("/api/holidays", json={"title": "Diwali", "start_date": "2026-11-08", "end_date": "2026-11-09"}, headers=auth)
    assert client.get("/api/holidays", headers=h).json["holidays"] == []
    r = client.post("/api/exams", json={"name": "Python test 1", "subjects": [{"name": "Theory", "max": 50}]}, headers=h)
    assert r.status_code == 400                                      # IT Hub tests need a course
    r = client.post("/api/exams", json={"name": "Python test 1", "course": "Python",
                                        "subjects": [{"name": "Theory", "max": 50}]}, headers=h)
    assert r.status_code == 200 and r.json["exam"]["course"] == "Python"
    assert client.get("/api/exams", headers=auth).json["exams"] == []
    r = client.post("/api/fees", json={"title": "Python course fee", "amount": 6000, "due_date": "2026-12-01",
                                       "course": "Python"}, headers=h)
    assert r.status_code == 200 and r.json["added"] == 1
    assert client.get("/api/fees", headers=auth).json["fees"] == []
    # settings: each its own; Gmail stays with the college
    client.post("/api/reports/settings", json={"term_start": "2026-07-01", "eligibility_min": 80}, headers=h)
    assert client.get("/api/reports/settings", headers=auth).json["eligibility_min"] == 75
    client.post("/api/settings", json={"gmail": "office@college.edu", "sender_name": "Principal"}, headers=auth)
    client.post("/api/settings", json={"gmail": "hacker@x.com", "sender_name": "IT Hub Office"}, headers=h)
    assert client.get("/api/settings", headers=auth).json["gmail"] == "office@college.edu"
    hub_st = client.get("/api/settings", headers=h).json
    assert hub_st["gmail"] == "office@college.edu" and hub_st["sender_name"] == "IT Hub Office" and not hub_st["shared_here"]
    # team
    assert [u["username"] for u in client.get("/api/users", headers=h).json["users"]] == ["hub@aakansha.in"]
    r = client.post("/api/users", json={"username": "trainer@aakansha.in", "password": "train-pass-55",
                                        "role": "teacher", "branches": ["Python"]}, headers=h)
    assert r.status_code == 200
    college_users = [u["username"] for u in client.get("/api/users", headers=auth).json["users"]]
    assert "trainer@aakansha.in" not in college_users
    r = client.post("/api/auth/login", json={"username": "trainer@aakansha.in", "password": "train-pass-55", "org": "ithub"})
    assert r.status_code == 200 and r.json["user"]["org"] == "ithub"


def test_whatsapp_link_and_messages_stay_with_their_organisation(client, auth, sent, monkeypatch):
    import notify
    monkeypatch.setattr(notify, "wa_status", lambda: {"state": "qr", "qr": "data:image/png;base64,QR", "me": None, "error": ""})
    h = hub_ready(client)
    assert client.get("/api/whatsapp/status", headers=h).json["qr"] is None    # only the college admin links it
    assert client.post("/api/whatsapp/logout", headers=h).status_code == 403
    register(client, auth)
    client.post("/api/whatsapp/test", json={"phone": "9876543210"}, headers=auth)
    notify.process_queue()
    assert client.get("/api/messages", headers=h).json["messages"] == []
    assert len(client.get("/api/messages", headers=auth).json["messages"]) >= 1


def test_no_parent_portal_for_it_hub_students(client, auth):
    h = hub_ready(client)
    register(client, h, details={**HUB_DETAILS, "roll_no": "AIH-777"})
    r = client.post("/api/parent/login", json={"reg_no": "AIH-777", "name": "Dhanish Kumar", "phone": "9876543210"})
    assert r.status_code == 401


def test_ready_made_it_hub_admin(client):
    import manage
    made = manage.create_accounts()
    assert "admin@ithub.local" in made
    r = client.post("/api/auth/login", json={"username": "admin@ithub.local", "password": made["admin@ithub.local"],
                                             "org": "ithub"})
    assert r.status_code == 200 and r.json["user"]["org"] == "ithub" and r.json["user"]["must_change"]

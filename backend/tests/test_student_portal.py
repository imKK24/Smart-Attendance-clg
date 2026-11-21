"""Aakansha IT Hub: teachers only see assigned courses; students have their own login."""
from datetime import date, timedelta

from test_api import register
from test_ithub import HUB_DETAILS, hub_login


def hub_setup(client):
    h = hub_login(client)
    for name, price in (("Python", 6000), ("Tally", 4500)):
        client.post("/api/courses", json={"name": name, "price": price}, headers=h)
    r = register(client, h, details={**HUB_DETAILS, "courses": ["Python", "Tally"], "student_phone": "9000012345"})
    assert r.status_code == 200, r.json
    return h, r.json["id"]


def student_login(client, phone="9000012345", reg="AIH-001", name="Dhanish Kumar", org="ithub"):
    return client.post("/api/parent/login", json={"reg_no": reg, "name": name, "phone": phone, "org": org})


# ---------- teachers ----------
def test_teacher_without_a_course_sees_nothing(client, auth):
    h, _ = hub_setup(client)
    t = hub_login(client, "new@aakansha.in", "new-trainer-9", role="teacher", courses=[])
    assert client.get("/api/students", headers=t).json["students"] == []
    assert client.get("/api/students/branches", headers=t).json["branches"] == []
    r = client.post("/api/start-attendance", json={"course": "Python"}, headers=t)
    assert r.status_code == 403 and "No course has been assigned" in r.json["message"]
    assert client.get("/api/attendance/today?course=Python", headers=t).json["records"] == []
    # the college keeps its old rule: a teacher with no branch ticked sees every branch
    from test_batch2 import login
    client.post("/api/users", json={"username": "c@x.edu", "password": "teach-pass-1", "role": "teacher"}, headers=auth)
    register(client, auth)
    assert len(client.get("/api/students", headers=login(client, "c@x.edu", "teach-pass-1")).json["students"]) == 1
    _ = h


def test_teacher_only_works_with_assigned_courses(client, auth):
    h, sid = hub_setup(client)
    t = hub_login(client, "py@aakansha.in", "py-trainer-9", role="teacher", courses=["Python"])
    assert client.get("/api/students/branches", headers=t).json["branches"] == ["Python · 4–6 PM", "Python · 6–8 PM"]
    assert client.get("/api/courses", headers=t).status_code == 403                      # no Courses page
    r = client.post("/api/start-attendance", json={"course": "Tally"}, headers=t)
    assert r.status_code == 403 and "your own courses" in r.json["message"]
    r = client.post("/api/exams", json={"name": "Tally test", "course": "Tally", "subjects": [{"name": "A", "max": 10}]}, headers=t)
    assert r.status_code == 403
    r = client.post("/api/exams", json={"name": "Py test", "course": "Python", "subjects": [{"name": "A", "max": 10}]}, headers=t)
    assert r.status_code == 200
    _ = h, sid


# ---------- student login ----------
def test_student_logs_in_with_own_mobile(client, auth):
    hub_setup(client)
    assert student_login(client, phone="9876543210").status_code == 401                 # the parent's number: no
    assert student_login(client, org="college").status_code == 401                      # not on the college side
    r = student_login(client)
    assert r.status_code == 200 and r.json["user"]["role"] == "student" and r.json["user"]["org"] == "ithub"
    s = {"Authorization": "Bearer " + r.json["token"]}
    me = client.get("/api/parent/me", headers=s).json["student"]
    assert me["courses"] == ["Python", "Tally"] and me["org"] == "ithub"
    assert client.get("/api/students", headers=s).status_code == 403                    # nothing else opens
    # college parents still log in exactly as before
    register(client, auth)
    r = client.post("/api/parent/login", json={"reg_no": "2301201037", "name": "Dhanish Kumar", "phone": "9876543210"})
    assert r.status_code == 200 and r.json["user"]["role"] == "parent"


def test_student_page_attendance_results_fees_and_leave(client, auth):
    import attendance
    from orgs import as_org
    h, sid = hub_setup(client)
    today = date.today()
    with as_org("ithub"):
        attendance.mark_present(today, "Dhanish Kumar", "10:00 AM", course="Python · 4–6 PM")
    client.post("/api/reports/settings", json={"term_start": str(today - timedelta(days=5)), "eligibility_min": 75}, headers=h)
    eid = client.post("/api/exams", json={"name": "Python test 1", "course": "Python",
                                          "subjects": [{"name": "Theory", "max": 50}]}, headers=h).json["exam"]["id"]
    from models import ExamResult, db
    with db("ithub") as s:
        s.add(ExamResult(exam_id=eid, student_id=sid, marks={"Theory": 42}, total=42, max_total=50))
    client.post("/api/fees", json={"title": "Python course fee", "amount": 6000, "due_date": str(today + timedelta(days=20)),
                                   "course": "Python"}, headers=h)
    s = {"Authorization": "Bearer " + student_login(client).json["token"]}
    att = client.get("/api/parent/attendance", headers=s).json
    by_course = {c["course"]: c for c in att["courses"]}
    assert set(by_course) == {"Python · 4–6 PM", "Tally · 6–8 PM"}                       # each in the student's batch
    py = by_course["Python · 4–6 PM"]
    assert py["summary"]["percentage"] == 100 and py["recent"][0]["status"] == "Present"
    assert by_course["Tally · 6–8 PM"]["recent"] == []
    res = client.get("/api/parent/results", headers=s).json["results"]
    assert res[0]["course"] == "Python" and res[0]["total"] == 42
    fee = client.get("/api/parent/fees", headers=s).json["fees"][0]
    assert (fee["course"], fee["balance"]) == ("Python", 6000)
    # leave: sent by the student, seen by Python's teacher and the admin, not by another course's teacher
    r = client.post("/api/parent/leaves", json={"start_date": str(today + timedelta(days=1)), "reason": "Family function"}, headers=s)
    assert r.status_code == 200 and "teacher or the IT Hub admin" in r.json["message"]
    assert r.json["leave"]["source"] == "student"
    py = hub_login(client, "py@aakansha.in", "py-trainer-9", role="teacher", courses=["Python"])
    web = hub_login(client, "web@aakansha.in", "web-trainer-9", role="teacher", courses=["Web"])
    assert len(client.get("/api/leaves", headers=py).json["leaves"]) == 1
    assert client.get("/api/leaves", headers=web).json["leaves"] == []
    lid = r.json["leave"]["id"]
    assert client.post(f"/api/leaves/{lid}/decide", json={"status": "approved"}, headers=py).status_code == 200
    assert client.get("/api/parent/leaves", headers=s).json["leaves"][0]["status"] == "approved"
    # the college admin sees none of it
    assert client.get("/api/leaves", headers=auth).json["leaves"] == []

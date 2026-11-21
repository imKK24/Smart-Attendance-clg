"""Parent portal (read-only + leave), quick / secure liveness, registration-number wording."""
from datetime import date, timedelta

from test_api import DETAILS, register
from test_batch1 import weekdays_back


def parent_login(client, reg="2301201037", name="Dhanish Kumar", phone="98765 43210"):
    return client.post("/api/parent/login", json={"reg_no": reg, "name": name, "phone": phone})


def test_parent_login_needs_all_three(client, auth):
    register(client, auth)                                   # reg 2301201037, parent +919876543210
    assert parent_login(client, phone="9999999999").status_code == 401           # right reg + name, wrong phone
    assert parent_login(client, name="Someone Else").status_code == 401
    assert parent_login(client, reg="").status_code == 400
    r = parent_login(client, name="  dhanish   KUMAR ", phone="+91 98765-43210")   # spacing, case, +91 don't matter
    assert r.status_code == 200 and r.json["user"]["role"] == "parent"


def test_parent_lockout(client, auth):
    register(client, auth)
    for _ in range(5):
        parent_login(client, phone="1111111111")
    assert parent_login(client).status_code == 429


def test_parent_sees_only_their_child(client, auth, sent):
    import attendance
    dh = register(client, auth).json["id"]
    register(client, auth, name="Krishna Sharma", details={**DETAILS, "roll_no": "2301201043", "parent_phone": "9123456780"})
    for i, d in enumerate(weekdays_back(4)):
        if i != 1:
            attendance.mark_present(d, "Dhanish Kumar", "09:00:00 AM")
        attendance.finalize_day(d)
    p = {"Authorization": "Bearer " + parent_login(client).json["token"]}

    me = client.get("/api/parent/me", headers=p).json["student"]
    assert me["name"] == "Dhanish Kumar" and me["reg_no"] == "2301201037"
    att = client.get("/api/parent/attendance", headers=p).json
    assert att["summary"]["present"] == 3 and att["summary"]["absent"] == 1 and att["summary"]["percentage"] == 75.0
    assert len(att["recent"]) == 4

    # a parent token can't open anything else
    for url in ("/api/students", "/api/attendance/today", "/api/leaves", "/api/alerts", "/api/auth/me"):
        assert client.get(url, headers=p).status_code == 403, url
    # and staff tokens can't open the parent pages
    assert client.get("/api/parent/me", headers=auth).status_code == 403

    # exam results: only this child's marks
    eid = client.post("/api/exams", json={"name": "Mid-term 1", "subjects": [{"name": "Maths", "max": 100}]}, headers=auth).json["exam"]["id"]
    import io
    client.post(f"/api/exams/{eid}/upload", headers=auth, content_type="multipart/form-data",
                data={"file": (io.BytesIO(b"Registration No,Name,Maths\n2301201037,,81\n2301201043,,64\n"), "m.csv")})
    res = client.get("/api/parent/results", headers=p).json["results"]
    assert len(res) == 1 and res[0]["marks"] == {"Maths": 81}

    # apply for leave -> waiting for the teacher
    tomorrow = date.today() + timedelta(days=1)
    r = client.post("/api/parent/leaves", json={"start_date": str(tomorrow), "reason": "Doctor's appointment"}, headers=p)
    assert r.status_code == 200
    assert client.post("/api/parent/leaves", json={"start_date": str(tomorrow), "reason": "Again please"}, headers=p).status_code == 409
    assert client.post("/api/parent/leaves", json={"start_date": str(tomorrow), "reason": "x"}, headers=p).status_code == 400
    staff = client.get("/api/leaves?status=pending", headers=auth).json
    assert staff["pending"] == 1 and staff["leaves"][0]["source"] == "parent" and staff["leaves"][0]["student_id"] == dh
    lid = staff["leaves"][0]["id"]
    client.post(f"/api/leaves/{lid}/decide", json={"status": "approved"}, headers=auth)
    assert client.get("/api/parent/leaves", headers=p).json["leaves"][0]["status"] == "approved"

    client.post("/api/fees", json={"title": "Tuition", "amount": 45000, "due_date": str(tomorrow)}, headers=auth)
    fees = client.get("/api/parent/fees", headers=p).json["fees"]
    assert len(fees) == 1 and fees[0]["balance"] == 45000

    # student removed -> the parent's login stops working
    client.delete(f"/api/students/{dh}", headers=auth)
    assert client.get("/api/parent/me", headers=p).status_code == 401


def test_liveness_mode(client, auth):
    assert client.get("/api/liveness-mode", headers=auth).json["mode"] == "quick"
    assert client.post("/api/liveness-mode", json={"mode": "fast"}, headers=auth).status_code == 400
    assert client.post("/api/liveness-mode", json={"mode": "secure"}, headers=auth).json["mode"] == "secure"
    client.post("/api/users", json={"username": "t@college.edu", "password": "teach-pass-1", "role": "teacher"}, headers=auth)
    from test_batch2 import login
    t = login(client, "t@college.edu", "teach-pass-1")
    assert client.post("/api/liveness-mode", json={"mode": "quick"}, headers=t).status_code == 403
    assert client.get("/api/liveness-mode", headers=t).json["mode"] == "secure"


def test_messages_say_registration_number(client, auth, sent):
    import notify
    register(client, auth)
    client.post("/api/fees", json={"title": "Tuition", "amount": 100, "due_date": str(date.today())}, headers=auth)
    client.post("/api/fees/remind", json={"title": "Tuition", "channels": ["whatsapp"]}, headers=auth)
    notify.process_queue()
    assert "(Reg. No 2301201037)" in sent["whatsapp"][0][1] and "Roll" not in sent["whatsapp"][0][1]

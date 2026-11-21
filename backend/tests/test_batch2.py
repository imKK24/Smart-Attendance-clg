"""Batch 2: teacher accounts with roles, charts, students at risk."""
from conftest import image
from test_api import DETAILS, register
from test_batch1 import weekdays_back


def login(client, username, password):
    """Log in; accounts made by an admin must set their own password first
    (the new one is password + '-own')."""
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.json
    h = {"Authorization": f"Bearer {r.json['token']}"}
    if r.json["user"].get("must_change"):
        r = client.post("/api/auth/password", json={"current": password, "new": password + "-own"}, headers=h)
        assert r.status_code == 200, r.json
        h = {"Authorization": f"Bearer {r.json['token']}"}
    return h


def two_branches(client, auth):
    a = register(client, auth).json["id"]                                    # CSE
    b = register(client, auth, name="Shubham Sharma",
                 details={**DETAILS, "roll_no": "2301201073", "branch": "IT", "parent_email": "rakesh@example.com"}).json["id"]
    return a, b


def test_teacher_sees_only_their_branch(client, auth):
    import attendance
    cse_id, it_id = two_branches(client, auth)
    r = client.post("/api/users", json={"username": "it.teacher", "password": "teach-pass-1", "role": "teacher",
                                       "full_name": "IT Teacher", "branches": ["IT"]}, headers=auth)
    assert r.status_code == 200
    t = login(client, "it.teacher", "teach-pass-1")
    me = client.get("/api/auth/me", headers=t).json["user"]
    assert me["role"] == "teacher" and me["branches"] == ["IT"]

    assert [s["name"] for s in client.get("/api/students", headers=t).json["students"]] == ["Shubham Sharma"]
    assert [r["Name"] for r in client.get("/api/attendance/today", headers=t).json["records"]] == ["Shubham Sharma"]
    assert client.put(f"/api/students/{cse_id}", json={"address": "x"}, headers=t).status_code == 404
    assert client.put(f"/api/students/{it_id}", json={"branch": "CSE"}, headers=t).status_code == 403
    assert client.post("/api/leaves", json={"student_id": cse_id, "start_date": "2026-11-20", "reason": "x"}, headers=t).status_code == 400

    # registering: branch is filled in automatically when the teacher has one branch
    r = client.post("/api/register", json={"name": "New Student", "image": image("face.jpg"), "consent": True,
                                           "details": {"roll_no": "99"}}, headers=t)
    assert r.status_code == 200, r.json
    names = {s["name"]: s["branch"] for s in client.get("/api/students", headers=auth).json["students"]}
    assert names["New Student"] == "IT"

    # admin-only actions
    for method, url, body in [("post", "/api/settings", {}), ("get", "/api/users", None), ("post", "/api/holidays", {}),
                              ("delete", f"/api/students/{it_id}", None), ("post", "/api/reports/settings", {})]:
        res = getattr(client, method)(url, json=body, headers=t) if body is not None else getattr(client, method)(url, headers=t)
        assert res.status_code == 403, url
    assert client.get("/api/settings", headers=t).status_code == 200    # reading is fine

    d = weekdays_back(1)[0]
    attendance.finalize_day(d)
    month = d.strftime("%Y-%m")
    assert {r["name"] for r in client.get(f"/api/reports/monthly?month={month}", headers=t).json["rows"]} == {"New Student", "Shubham Sharma"}

    # switching the account off logs it out
    uid = next(u["id"] for u in client.get("/api/users", headers=auth).json["users"] if u["username"] == "it.teacher")
    client.put(f"/api/users/{uid}", json={"active": False}, headers=auth)
    assert client.get("/api/students", headers=t).status_code == 401
    assert client.post("/api/auth/login", json={"username": "it.teacher", "password": "teach-pass-1-own"}).status_code == 403


def test_last_admin_is_protected(client, auth):
    me = client.get("/api/users", headers=auth).json
    my_id = me["me"]
    assert client.put(f"/api/users/{my_id}", json={"role": "teacher"}, headers=auth).status_code == 400
    assert client.delete(f"/api/users/{my_id}", headers=auth).status_code == 400
    r = client.post("/api/users", json={"username": "second", "password": "another-pass-9", "role": "admin"}, headers=auth)
    sid = r.json["user"]["id"]
    assert r.json["user"]["branches"] == []
    assert client.delete(f"/api/users/{sid}", headers=auth).status_code == 200
    assert client.post("/api/users", json={"username": "a b", "password": "x" * 8}, headers=auth).status_code == 400


def test_charts_and_at_risk(client, auth):
    import attendance
    cse_id, it_id = two_branches(client, auth)
    days = weekdays_back(20)
    for i, d in enumerate(days):
        attendance.mark_present(d, "Dhanish Kumar", "09:00:00 AM")
        if i < 10 or i == 12:                       # Shubham: fine at first, then mostly absent
            attendance.mark_present(d, "Shubham Sharma", "09:00:00 AM")
        attendance.finalize_day(d)

    c = client.get("/api/analytics?days=60", headers=auth).json
    assert len(c["trend"]) == 20 and c["average"] == round(31 / 40 * 100, 1)
    br = {b["branch"]: b["percentage"] for b in c["branches"]}
    assert br == {"CSE": 100.0, "IT": 55.0}
    assert c["weekday"] and len(c["months"]) >= 6
    assert any("IT has the lowest" in n for n in c["notes"])

    # a bad exam result adds to the risk
    eid = client.post("/api/exams", json={"name": "Mid-term 1", "subjects": [{"name": "Maths", "max": 100}]}, headers=auth).json["exam"]["id"]
    import io
    csv_data = "Roll No,Name,Maths\n2301201037,,85\n2301201073,,30\n"
    client.post(f"/api/exams/{eid}/upload", headers=auth, content_type="multipart/form-data",
                data={"file": (io.BytesIO(csv_data.encode()), "m.csv")})

    risk = client.get("/api/analytics/at-risk", headers=auth).json
    assert [r["name"] for r in risk["students"]] == ["Shubham Sharma"]
    s = risk["students"][0]
    assert s["level"] == "high"
    text = " | ".join(s["reasons"])
    assert "Below the 75% minimum" in text and "Absent 7 class days in a row" in text
    assert "Attendance fell from 100% to 10%" in text and "Scored 30% in Mid-term 1" in text


def test_login_role_switch_and_default_accounts(client, auth):
    import manage
    made = manage.create_accounts()
    apw, tpw = made["admin@attendai.local"], made["teacher@attendai.local"]
    assert apw != "Admin@2026" and len(apw) == 14                       # random, not the published one
    ok_admin = client.post("/api/auth/login", json={"username": "ADMIN@attendai.local", "password": apw, "role": "admin"})
    assert ok_admin.status_code == 200 and ok_admin.json["user"]["role"] == "admin" and ok_admin.json["user"]["must_change"]
    wrong = client.post("/api/auth/login", json={"username": "admin@attendai.local", "password": apw, "role": "teacher"})
    assert wrong.status_code == 403 and "Admin account" in wrong.json["message"]
    t = client.post("/api/auth/login", json={"username": "teacher@attendai.local", "password": tpw, "role": "teacher"})
    assert t.status_code == 200 and t.json["user"]["role"] == "teacher"
    assert client.post("/api/auth/login", json={"username": "teacher@attendai.local", "password": tpw,
                                                "role": "admin"}).status_code == 403
    manage.create_accounts()   # running it twice changes nothing
    assert sum(u["username"].endswith("@attendai.local") for u in client.get("/api/users", headers=auth).json["users"]) == 2

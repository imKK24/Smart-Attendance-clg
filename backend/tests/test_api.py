import io
from datetime import date, timedelta

from conftest import image, media

DETAILS = {
    "roll_no": "2301201037", "branch": "CSE", "class_name": "6th sem",
    "parent_name": "Ravi Kumar", "parent_relation": "Father", "parent_phone": "98765 43210",
    "parent_email": "ravi@example.com", "address": "Plot 12, Bhubaneswar",
    "qualifications": [{"course": "Class 12", "board": "CHSE Odisha", "year": "2023", "score": "88%"}, {"course": ""}],
    "achievements": [{"title": "Hackathon winner", "year": "2025", "details": "Smart India Hackathon"}],
}


def register(client, auth, name="Dhanish Kumar", details=None, **extra):
    body = {"name": name, "image": image("face.jpg"), "details": details or DETAILS, "consent": True, **extra}
    return client.post("/api/register", json=body, headers=auth)


# ---------------- auth ----------------
def test_login_flow(client):
    assert client.get("/api/auth/status").json["setup_needed"] is True
    assert client.get("/api/students").status_code == 401
    r = client.post("/api/auth/setup", json={"username": "admin", "password": "short"})
    assert r.status_code == 400
    r = client.post("/api/auth/setup", json={"username": "admin", "password": "secret-pass-1"})
    assert r.status_code == 200
    assert client.post("/api/auth/setup", json={"username": "x2", "password": "secret-pass-2"}).status_code == 409
    assert client.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "admin", "password": "secret-pass-1"})
    token = r.json["token"]
    assert client.get("/api/students", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/api/students", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_login_lockout(client, auth):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "bad"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": "secret-pass-1"})
    assert r.status_code == 429


# ---------------- students ----------------
def test_register_and_profile(client, auth):
    r = register(client, auth)
    assert r.status_code == 200, r.json
    st = client.get("/api/students", headers=auth).json["students"][0]
    assert st["parent_phone"] == "+919876543210"          # 10 digits get +91
    assert st["roll_no"] == "2301201037" and st["has_face"] and st["consent"]
    assert len(st["qualifications"]) == 1                   # empty row dropped
    assert st["achievements"][0]["title"] == "Hackathon winner"
    token = media(client, auth)
    assert client.get(f"/api/students/{st['id']}/photo?token={token}").status_code == 200

    assert register(client, auth).status_code == 409                       # same name
    r = register(client, auth, name="Other Student")                        # same roll no
    assert r.status_code == 409 and "registration number" in r.json["message"]
    assert register(client, auth, name="Ok Name", overwrite=True).status_code == 409

    r = client.put(f"/api/students/{st['id']}", json={"parent_phone": "+44 7700 900123", "branch": "IT"}, headers=auth)
    assert r.status_code == 200
    st = client.get("/api/students", headers=auth).json["students"][0]
    assert st["parent_phone"] == "+447700900123" and st["branch"] == "IT" and st["roll_no"] == "2301201037"
    assert client.get("/api/students/branches", headers=auth).json["branches"] == ["IT"]
    assert client.delete(f"/api/students/{st['id']}", headers=auth).status_code == 200


def test_register_rejects_bad_input(client, auth):
    assert register(client, auth, name="../etc").status_code == 400
    assert register(client, auth, details={**DETAILS, "parent_email": "nope"}).status_code == 400
    assert register(client, auth, details={**DETAILS, "parent_phone": "123"}).status_code == 400
    r = client.post("/api/register", json={"name": "A B", "image": image("face.jpg"), "details": {}}, headers=auth)
    assert r.status_code == 400 and "consent" in r.json["message"]
    r = client.post("/api/register", json={"name": "A B", "image": image("no_face.jpg"), "consent": True}, headers=auth)
    assert r.status_code == 422 and "No face" in r.json["message"]
    r = client.post("/api/register", json={"name": "A B", "image": image("two_faces.jpg"), "consent": True}, headers=auth)
    assert r.status_code == 422 and "More than one" in r.json["message"]


def test_face_matches_itself(client, auth):
    """The saved encoding identifies the same face (what the camera does)."""
    import numpy as np
    import face_recognition as fr
    import camera
    register(client, auth)
    encs, names = camera.load_known()
    probe = fr.face_encodings(fr.load_image_file(str(__import__("pathlib").Path(__file__).parent / "fixtures/face.jpg")))[0]
    assert names == ["Dhanish Kumar"]
    assert fr.face_distance(encs, probe)[0] < camera.MATCH_DISTANCE
    assert np.asarray(encs).shape == (1, 128)


# ---------------- attendance + absence alerts ----------------
def test_attendance_and_alerts(client, auth, sent):
    import attendance
    import notify
    register(client, auth)
    register(client, auth, name="Krishna Sharma", details={**DETAILS, "roll_no": "2301201043", "parent_phone": "",
                                                            "parent_email": "k.parent@example.com"})
    client.post("/api/settings", json={"gmail": "teacher@gmail.com", "app_password": "abcd efgh ijkl mnop",
                                       "threshold": 3, "alert_channels": ["whatsapp", "email"]}, headers=auth)
    today = date.today()
    days = [today - timedelta(days=n) for n in (4, 3, 2, 1)]
    attendance.mark_present(days[0], "Krishna Sharma", "09:00:00 AM")
    for d in days:
        attendance.finalize_day(d)
    attendance.finalize_day(days[-1])                     # running twice adds nothing
    r = client.get(f"/api/attendance/{days[-1]}", headers=auth).json
    assert r["total"] == 2 and r["present_count"] == 0

    alerts = client.get("/api/alerts", headers=auth).json
    by = {a["name"]: a for a in alerts["students"]}
    assert by["Dhanish Kumar"]["days"] == 4 and by["Dhanish Kumar"]["due"]
    assert by["Krishna Sharma"]["days"] == 3 and by["Krishna Sharma"]["due"]

    # a holiday in the middle is skipped when counting
    r = client.post("/api/holidays", json={"title": "Puja", "start_date": str(days[1]), "end_date": str(days[1])}, headers=auth)
    assert r.status_code == 200
    by = {a["name"]: a for a in client.get("/api/alerts", headers=auth).json["students"]}
    assert by["Krishna Sharma"]["days"] == 2 and not by["Krishna Sharma"]["due"]

    notify.run_auto_alerts()
    notify.process_queue()
    assert [to for to, _ in sent["whatsapp"]] == ["+919876543210"]
    assert "absent for *3 days in a row*" in sent["whatsapp"][0][1]
    assert [m["To"] for m in sent["email"]] == ["ravi@example.com"]
    alerts = client.get("/api/alerts", headers=auth).json
    assert alerts["due_count"] == 0
    a = next(x for x in alerts["students"] if x["name"] == "Dhanish Kumar")
    assert a["alerted"] and a["sent_channels"] == ["email", "whatsapp"]

    # marking present again breaks the streak
    attendance.mark_present(days[-1], "Dhanish Kumar", "10:00:00 AM")
    names = [x["name"] for x in client.get("/api/alerts", headers=auth).json["students"]]
    assert "Dhanish Kumar" not in names

    csv_text = client.get(f"/api/attendance/{days[-1]}/export", headers=auth).data.decode("utf-8-sig")
    assert csv_text.splitlines()[0] == "Name,Registration No,Date,Time,Status"
    assert "Dhanish Kumar,2301201037" in csv_text
    hist = client.get("/api/history", headers=auth).json["history"]
    assert [h["date"] for h in hist][-1] == str(days[-1])


def test_today_fills_absent_and_holiday(client, auth):
    register(client, auth)
    client.post("/api/holidays", json={"title": "Diwali", "start_date": str(date.today())}, headers=auth)
    r = client.get("/api/attendance/today", headers=auth).json
    assert r["records"][0]["Status"] == "Absent" and r["holiday"] == "Diwali"


# ---------------- messages ----------------
def test_failed_whatsapp_then_retry(client, auth, sent):
    import notify
    client.post("/api/whatsapp/test", json={"phone": "+91 0000000000"}, headers=auth)
    notify.process_queue()
    st = client.get("/api/messages/status", headers=auth).json
    assert st["failed_total"] == 1 and "not on WhatsApp" in st["last"]["error"]
    assert client.post("/api/messages/retry", headers=auth).json["queued"] == 1


def test_holiday_and_event_broadcast(client, auth, sent):
    import notify
    register(client, auth)
    hid = client.post("/api/holidays", json={"title": "Diwali", "start_date": "2026-11-08", "end_date": "2026-11-10",
                                             "note": "Classes resume on 11 Nov."}, headers=auth).json["holiday"]["id"]
    r = client.post(f"/api/holidays/{hid}/notify", json={"channels": ["whatsapp", "email"]}, headers=auth)
    assert r.json["queued"] == 1      # Gmail not set up, so WhatsApp only
    notify.process_queue()
    text = sent["whatsapp"][0][1]
    assert "*Holiday notice: Diwali*" in text and "from Sun 08 Nov 2026 to Tue 10 Nov 2026" in text
    eid = client.post("/api/events", json={"title": "Sports day", "date": "2026-12-01", "time": "09:30"},
                      headers=auth).json["event"]["id"]
    r = client.post(f"/api/events/{eid}/notify", json={"channels": ["whatsapp"], "to_parents": True,
                                                       "to_students": False}, headers=auth)
    assert r.json["queued"] == 1


# ---------------- exams ----------------
def test_exam_upload_and_publish(client, auth, sent):
    import notify
    register(client, auth)
    register(client, auth, name="Krishna Sharma", details={**DETAILS, "roll_no": "2301201043",
                                                            "parent_phone": "9123456780"})
    r = client.post("/api/exams", json={"name": "Mid-term 1", "exam_date": "2026-11-10",
                                        "subjects": [{"name": "Maths", "max": 100}, {"name": "Physics", "max": 50}]},
                    headers=auth)
    eid = r.json["exam"]["id"]
    assert client.post("/api/exams", json={"name": "X", "subjects": [{"name": "A", "max": 0}]}, headers=auth).status_code == 400

    token = media(client, auth)
    tpl = client.get(f"/api/exams/{eid}/template?token={token}")
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(tpl.data)).active
    assert [c.value for c in ws[1]] == ["Registration No", "Name", "Maths (/100)", "Physics (/50)"]

    csv_data = ("Roll No,Name,Maths (/100),Physics (/50)\n"
                "2301201037,Dhanish Kumar,78,AB\n"
                ",krishna sharma,91.5,49\n"
                "999,Nobody,10,10\n"
                "2301201037,Dhanish Kumar,120,10\n")
    r = client.post(f"/api/exams/{eid}/upload", headers=auth, content_type="multipart/form-data",
                    data={"file": (io.BytesIO(csv_data.encode()), "marks.csv")})
    assert r.status_code == 200, r.json
    assert r.json["saved"] == 2 and len(r.json["unmatched"]) == 1 and len(r.json["problems"]) == 1

    res = {x["name"]: x for x in client.get(f"/api/exams/{eid}", headers=auth).json["results"]}
    assert res["Dhanish Kumar"]["marks"] == {"Maths": 78, "Physics": "AB"} and res["Dhanish Kumar"]["total"] == 78
    assert res["Krishna Sharma"]["percentage"] == 93.7

    r = client.post(f"/api/exams/{eid}/publish", json={"channels": ["whatsapp"]}, headers=auth)
    assert r.json["queued"] == 2
    notify.process_queue()
    texts = {to: t for to, t in sent["whatsapp"]}
    assert "Maths: 78/100" in texts["+919876543210"] and "Physics: Absent/50" in texts["+919876543210"]
    assert "Total: 140.5/150 (93.7%)" in texts["+919123456780"]
    assert client.post(f"/api/exams/{eid}/publish", json={"channels": ["whatsapp"]}, headers=auth).status_code == 400

    bad = client.post(f"/api/exams/{eid}/upload", headers=auth, content_type="multipart/form-data",
                      data={"file": (io.BytesIO(b"hello"), "marks.txt")})
    assert bad.status_code == 400


# ---------------- inbox ----------------
class FakeIMAP:
    """Just enough of imaplib.IMAP4_SSL for inbox.sync()."""
    MAILS = {
        b"7": (b"From: Ravi Kumar <Ravi@Example.com>\r\nMessage-ID: <m7@mail>\r\nSubject: Leave for Dhanish\r\n"
               b"Date: Mon, 16 Nov 2026 08:15:00 +0530\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
               b"Dhanish has fever, he will be absent today.\r\n"),
        b"8": (b"From: shop@spam.com\r\nMessage-ID: <m8@mail>\r\nSubject: Sale\r\n\r\nBuy now\r\n"),
    }

    def __init__(self, *a, **k):
        pass

    def login(self, user, pw):
        return "OK", [b"ok"]

    def select(self, box, readonly=False):
        assert readonly
        return "OK", [b"2"]

    def uid(self, cmd, *args):
        if cmd == "search":
            return "OK", [b"7 8"]
        ids, what = args
        out = []
        for uid in ids.split(","):
            raw = self.MAILS[uid.encode()]
            part = raw.split(b"\r\n\r\n")[0] + b"\r\n\r\n" if "HEADER" in what else raw
            out += [(b"1 (UID " + uid.encode() + b" BODY[] {%d}" % len(part), part), b")"]
        return "OK", out

    def logout(self):
        pass


def test_inbox_sync_and_reply(client, auth, sent, monkeypatch):
    import inbox
    import notify
    register(client, auth)
    client.post("/api/settings", json={"gmail": "teacher@gmail.com", "app_password": "abcdefghijklmnop"}, headers=auth)
    monkeypatch.setattr(inbox.imaplib, "IMAP4_SSL", FakeIMAP)
    r = client.post("/api/inbox/sync", headers=auth)
    assert r.json["new"] == 1, r.json
    assert client.post("/api/inbox/sync", headers=auth).json["new"] == 0   # no duplicates
    box = client.get("/api/inbox", headers=auth).json
    assert box["unread"] == 1
    mail = box["mails"][0]
    assert mail["from_email"] == "ravi@example.com" and mail["children"][0]["name"] == "Dhanish Kumar"
    full = client.get(f"/api/inbox/{mail['id']}", headers=auth).json
    assert "fever" in full["mail"]["body"]
    assert client.get("/api/inbox", headers=auth).json["unread"] == 0

    client.post(f"/api/inbox/{mail['id']}/reply", json={"text": "Get well soon."}, headers=auth)
    notify.process_queue()
    msg = sent["email"][0]
    assert msg["Subject"] == "Re: Leave for Dhanish" and msg["In-Reply-To"] == "<m7@mail>"
    full = client.get(f"/api/inbox/{mail['id']}", headers=auth).json
    assert full["mail"]["replied_at"] and full["replies"][0]["status"] == "sent"


def test_settings_password_is_encrypted(client, auth):
    from models import Setting, db
    client.post("/api/settings", json={"gmail": "t@gmail.com", "app_password": "abcdefghijklmnop"}, headers=auth)
    with db() as s:
        stored = s.get(Setting, "app_password").value["v"]
    assert "abcdefghijklmnop" not in stored
    r = client.get("/api/settings", headers=auth).json
    assert r["configured"] and r["password_set"] and "app_password" not in r

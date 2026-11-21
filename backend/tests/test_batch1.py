"""Batch 1: several photos, eligibility %, monthly register, leave applications."""
import base64
import io
from datetime import date, timedelta

import cv2
import numpy as np

from conftest import HERE, image, media
from test_api import DETAILS, register


def mirrored_photo():
    img = cv2.imread(str(HERE / "fixtures" / "face.jpg"))
    ok_, buf = cv2.imencode(".jpg", cv2.flip(img, 1))
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def weekdays_back(n):
    """The last n weekdays before today, oldest first."""
    out, d = [], date.today()
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out[::-1]


def test_extra_photos(client, auth, monkeypatch):
    import camera
    import config
    import faces
    sid = register(client, auth).json["id"]
    r = client.post(f"/api/students/{sid}/faces", json={"image": mirrored_photo(), "label": "Turned left"}, headers=auth)
    assert r.status_code == 200, r.json
    r = client.post(f"/api/students/{sid}/faces", json={"image": image("no_face.jpg")}, headers=auth)
    assert r.status_code == 422
    listed = client.get(f"/api/students/{sid}/faces", headers=auth).json
    assert len(listed["faces"]) == 1 and listed["faces"][0]["label"] == "Turned left"
    fid = listed["faces"][0]["id"]
    token = media(client, auth)
    assert client.get(f"/api/students/{sid}/faces/{fid}/photo?token={token}").status_code == 200

    encs, names = camera.load_known()
    assert names == ["Dhanish Kumar", "Dhanish Kumar"]     # main + extra photo

    # a photo of somebody else is refused
    monkeypatch.setattr(faces, "encoding_of", lambda frame: (np.full(128, 0.5), None))
    r = client.post(f"/api/students/{sid}/faces", json={"image": mirrored_photo()}, headers=auth)
    assert r.status_code == 422 and "doesn't look like" in r.json["message"]

    folder = config.KNOWN_FACES_DIR / "extra" / str(sid)
    assert any(folder.iterdir())
    client.delete(f"/api/students/{sid}", headers=auth)
    assert not folder.exists()                               # extra photos deleted with the student


def test_leave_flow(client, auth, sent):
    import attendance
    import notify
    sid = register(client, auth).json["id"]
    d1, d2, d3 = weekdays_back(3)
    for d in (d1, d2, d3):
        attendance.finalize_day(d)                           # absent three days
    assert client.get("/api/alerts", headers=auth).json["due_count"] == 1

    r = client.post("/api/leaves", json={"student_id": sid, "start_date": str(d2), "end_date": str(d3),
                                         "reason": "Fever"}, headers=auth)
    lid = r.json["leave"]["id"]
    assert r.json["leave"]["status"] == "pending"
    overlap = client.post("/api/leaves", json={"student_id": sid, "start_date": str(d3), "reason": "x"}, headers=auth)
    assert overlap.status_code == 409

    r = client.post(f"/api/leaves/{lid}/decide", json={"status": "approved", "notify": ["whatsapp"]}, headers=auth)
    assert r.json["queued"] == 1
    day = client.get(f"/api/attendance/{d3}", headers=auth).json
    assert day["records"][0]["Status"] == "Leave" and day["leave_count"] == 1 and day["absent_count"] == 0
    alerts = client.get("/api/alerts", headers=auth).json
    assert alerts["due_count"] == 0 and alerts["students"][0]["days"] == 1   # only d1 still counts
    notify.process_queue()
    assert "has been approved" in sent["whatsapp"][0][1]

    # future leave: the day is filled in as Leave when the register is saved
    future = date.today() + timedelta(days=3)
    client.post("/api/leaves", json={"student_id": sid, "start_date": str(future), "reason": "Wedding",
                                     "approve": True}, headers=auth)
    attendance.finalize_day(future)
    assert client.get(f"/api/attendance/{future}", headers=auth).json["records"][0]["Status"] == "Leave"

    # rejecting puts the days back to Absent
    client.post(f"/api/leaves/{lid}/decide", json={"status": "rejected"}, headers=auth)
    assert client.get(f"/api/attendance/{d3}", headers=auth).json["records"][0]["Status"] == "Absent"
    assert client.get("/api/leaves?status=pending", headers=auth).json["pending"] == 0
    assert client.delete(f"/api/leaves/{lid}", headers=auth).status_code == 200


def test_eligibility_and_monthly(client, auth):
    import attendance
    register(client, auth)
    register(client, auth, name="Krishna Sharma", details={**DETAILS, "roll_no": "2301201043", "branch": "IT"})
    days = weekdays_back(8)
    for i, d in enumerate(days):
        attendance.mark_present(d, "Dhanish Kumar", "09:00:00 AM")
        if i < 5:
            attendance.mark_present(d, "Krishna Sharma", "09:01:00 AM")
        attendance.finalize_day(d)
    client.post("/api/holidays", json={"title": "Puja", "start_date": str(days[0])}, headers=auth)

    r = client.post("/api/reports/settings", json={"term_start": str(days[0]), "eligibility_min": 75}, headers=auth)
    assert r.status_code == 200
    e = client.get("/api/reports/eligibility", headers=auth).json
    assert e["days"] == 7 and e["below"] == 1                 # the holiday isn't counted
    k = next(x for x in e["rows"] if x["name"] == "Krishna Sharma")
    assert (k["present"], k["absent"], k["percentage"], k["eligible"]) == (4, 3, 57.1, False)
    assert k["need"] == 5                                     # (4+5)/(7+5) = 75%
    dh = next(x for x in e["rows"] if x["name"] == "Dhanish Kumar")
    assert dh["percentage"] == 100.0 and dh["can_miss"] == 2
    it = client.get("/api/reports/eligibility?branch=IT", headers=auth).json
    assert [x["name"] for x in it["rows"]] == ["Krishna Sharma"]

    month = days[-1].strftime("%Y-%m")
    m = client.get(f"/api/reports/monthly?month={month}", headers=auth).json
    assert len(m["rows"]) == 2 and m["columns"]
    token = media(client, auth)
    x = client.get(f"/api/reports/monthly/export?month={month}&token={token}")
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(x.data)).active
    assert ws["A2"].value == "Registration No" and ws["B4"].value in ("Dhanish Kumar", "Krishna Sharma")
    y = client.get(f"/api/reports/eligibility/export?token={token}")
    assert load_workbook(io.BytesIO(y.data)).active["H2"].value == "Eligible"
    assert client.get("/api/reports/monthly?month=2026-13", headers=auth).status_code == 400

"""Class-photo attendance (phone photos as evidence) and IP camera links."""
import http.server
import io
import threading
from datetime import date
from functools import partial

import cv2
import numpy as np

from conftest import HERE, media
from test_api import DETAILS, register
from test_batch2 import login


def class_photo():
    """A 'class photo': the registered face twice (same person twice in one photo)."""
    face = cv2.imread(str(HERE / "fixtures" / "face.jpg"))
    canvas = np.full((900, 1600, 3), 200, np.uint8)
    h, w = face.shape[:2]
    canvas[100:100 + h, 150:150 + w] = face
    canvas[400:400 + h, 900:900 + w] = face
    okay, buf = cv2.imencode(".jpg", canvas)
    return io.BytesIO(buf.tobytes())


def add_student_without_face(name, branch, roll):
    from models import Student, db
    with db() as s:
        st = Student(name=name, branch=branch, roll_no=roll, consent=True,
                     face_encoding=np.random.default_rng(1).normal(0, 1, 128).astype(np.float64).tobytes())
        s.add(st)
        s.flush()
        return st.id


def test_class_photo_attendance(client, auth):
    dh = register(client, auth).json["id"]                                   # CSE, real face
    kr = add_student_without_face("Krishna Sharma", "CSE", "43")             # CSE, a different face
    add_student_without_face("Shubham Sharma", "IT", "73")                   # other branch

    r = client.post("/api/photo-attendance/analyze", headers=auth, content_type="multipart/form-data",
                    data={"day": str(date.today()), "branch": "CSE", "photos": [(class_photo(), "class.jpg")]})
    assert r.status_code == 200, r.json
    sess = r.json["session"]
    named = [f for f in sess["faces"] if f["student_id"]]
    assert len(sess["faces"]) == 2 and len(named) == 1 and named[0]["name"] == "Dhanish Kumar"   # one face per student per photo
    assert named[0]["confidence"] > 50
    found = {x["name"]: x["found"] for x in sess["students"]}
    assert found == {"Dhanish Kumar": True, "Krishna Sharma": False}          # IT student isn't in this class

    token = media(client, auth)
    assert client.get(f"/api/photo-attendance/{sess['id']}/photo/1?token={token}").status_code == 200

    r = client.post(f"/api/photo-attendance/{sess['id']}/save", json={"present_ids": [dh]}, headers=auth)
    assert r.status_code == 200 and "1 present" in r.json["message"]
    day = client.get("/api/attendance/today", headers=auth).json
    rows = {x["Name"]: x for x in day["records"]}
    assert rows["Dhanish Kumar"]["Status"] == "Present" and rows["Dhanish Kumar"]["Source"] == "photo"
    assert rows["Krishna Sharma"]["Status"] == "Absent"
    from models import AttendanceRecord, db
    with db() as s:   # the IT student was not marked absent by a CSE photo
        assert not s.query(AttendanceRecord).filter_by(student_name="Shubham Sharma").count()

    ev = client.get(f"/api/photo-attendance?day={date.today()}", headers=auth).json["sessions"]
    assert len(ev) == 1 and ev[0]["present_ids"] == [dh]

    client.post("/api/users", json={"username": "it@college.edu", "password": "teach-pass-1", "role": "teacher", "branches": ["IT"]}, headers=auth)
    t = login(client, "it@college.edu", "teach-pass-1")
    assert client.get(f"/api/photo-attendance/{sess['id']}", headers=t).status_code == 404
    assert client.post("/api/photo-attendance/analyze", headers=t, content_type="multipart/form-data",
                       data={"branch": "CSE", "photos": [(class_photo(), "c.jpg")]}).status_code == 403
    assert client.delete(f"/api/photo-attendance/{sess['id']}", headers=t).status_code == 403
    assert client.delete(f"/api/photo-attendance/{sess['id']}", headers=auth).status_code == 200
    _ = kr


def test_photo_rejects_bad_input(client, auth):
    register(client, auth)
    r = client.post("/api/photo-attendance/analyze", headers=auth, content_type="multipart/form-data",
                    data={"branch": "CSE", "photos": [(io.BytesIO(b"not an image"), "x.jpg")]})
    assert r.status_code == 400
    r = client.post("/api/photo-attendance/analyze", headers=auth, content_type="multipart/form-data",
                    data={"branch": "Mech", "photos": [(class_photo(), "c.jpg")]})
    assert r.status_code == 400 and "No students" in r.json["message"]


def serve_clip(tmp_path):
    """A local HTTP server streaming a short video: stands in for an IP camera."""
    face = cv2.imread(str(HERE / "fixtures" / "face.jpg"))
    frame = cv2.resize(face, (1280, 720))
    out = cv2.VideoWriter(str(tmp_path / "clip.avi"), cv2.VideoWriter_fourcc(*"MJPG"), 10, (1280, 720))
    for _ in range(40):
        out.write(frame)
    out.release()
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/clip.avi"


def test_ip_camera_links(client, auth, tmp_path, monkeypatch):
    import camera
    import config
    monkeypatch.setattr(config, "ALLOW_LOCAL_CAMERAS", True)   # the test stream runs on this computer
    srv, url = serve_clip(tmp_path)
    try:
        assert client.post("/api/ip-cameras/test", json={"url": "ftp://x"}, headers=auth).status_code == 400
        r = client.post("/api/ip-cameras/test", json={"url": url}, headers=auth)
        assert r.status_code == 200, r.json
        assert r.json["width"] == 1280 and r.json["image"].startswith("data:image/jpeg")
        bad = client.post("/api/ip-cameras/test", json={"url": "http://127.0.0.1:9/none"}, headers=auth)
        assert bad.status_code == 502

        r = client.post("/api/ip-cameras", json={"name": "Room 204 door", "kind": "wired", "url": url}, headers=auth)
        cam = r.json["camera"]
        assert client.post("/api/ip-cameras", json={"name": "Again", "url": url}, headers=auth).status_code == 409
        r = client.post("/api/ip-cameras", json={"name": "Tapo", "kind": "wifi",
                                                 "url": "rtsp://admin:secret@192.168.1.20:554/stream1"}, headers=auth)
        assert r.json["camera"]["link"] == "rtsp://admin:•••@192.168.1.20:554/stream1"   # password never sent back

        from models import Setting, db
        with db() as s:
            assert "secret" not in str(s.get(Setting, "ip_cameras").value)              # stored encrypted

        listed = client.get("/api/cameras", headers=auth).json["cameras"]
        assert any(c.get("ip") and c["name"] == "Room 204 door" for c in listed)
        assert client.post("/api/camera-source", json={"camera": cam["value"]}, headers=auth).status_code == 200
        assert client.post("/api/camera-source", json={"camera": "ip:nope"}, headers=auth).status_code == 400

        cap, idx, _ = camera.pick_camera(cam["value"])     # what the live loop does
        okay, frame = cap.read()
        cap.release()
        assert okay and frame.shape[1] == 1280 and idx == cam["value"]

        client.post("/api/users", json={"username": "t@college.edu", "password": "teach-pass-1", "role": "teacher"}, headers=auth)
        t = login(client, "t@college.edu", "teach-pass-1")
        assert client.get("/api/ip-cameras", headers=t).status_code == 403
        assert client.delete(f"/api/ip-cameras/{cam['id']}", headers=auth).status_code == 200
        from common import get_settings
        assert get_settings()["camera"] == "default"        # deleting the chosen camera falls back to the laptop
    finally:
        srv.shutdown()


def test_attendance_methods(client, auth):
    assert client.get("/api/attendance-methods", headers=auth).json["methods"] == ["camera", "photo"]
    assert client.post("/api/attendance-methods", json={"methods": []}, headers=auth).status_code == 400
    assert client.post("/api/attendance-methods", json={"methods": ["photo"]}, headers=auth).json["methods"] == ["photo"]
    assert client.get("/api/attendance-methods", headers=auth).json["methods"] == ["photo"]
    _ = DETAILS

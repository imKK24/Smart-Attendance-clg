"""Faster camera start, and the light picture for people watching over the internet."""
import time

import cv2
from conftest import HERE, image, media

from test_api import DETAILS


class FakeCamera:
    """Shows the test face like a webcam would."""
    def __init__(self):
        self.frame = cv2.imread(str(HERE / "fixtures" / "face.jpg"))
        self.released = False

    def read(self):
        time.sleep(0.02)
        return True, self.frame.copy()

    def release(self):
        self.released = True


def test_start_frame_and_stop(client, auth, monkeypatch):
    import camera
    r = client.post("/api/register", json={"name": "Dhanish Kumar", "image": image("face.jpg"),
                                           "details": DETAILS, "consent": True}, headers=auth)
    assert r.status_code == 200, r.json
    fake = FakeCamera()
    monkeypatch.setattr(camera, "pick_camera", lambda setting: (fake, 0, ""))

    camera.face_models()                                  # what warm_up() does at server start
    t0 = time.time()
    assert client.post("/api/start-attendance", json={}, headers=auth).status_code == 200
    while camera.camera_state["frame_id"] == 0 and time.time() - t0 < 20:
        time.sleep(0.05)
    assert camera.camera_state["frame_id"] > 0, camera.camera_state["message"]
    assert time.time() - t0 < 10                          # models were already loaded

    token = media(client, auth)
    r = client.get(f"/api/camera-frame?token={token}&after=-1")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"
    first = int(r.headers["X-Frame-Id"])
    small = cv2.imdecode(__import__("numpy").frombuffer(r.data, "uint8"), cv2.IMREAD_COLOR)
    assert small.shape[1] == camera.LITE_WIDTH               # small picture for slow connections
    r = client.get(f"/api/camera-frame?token={token}&after={first}")
    assert r.status_code == 200 and int(r.headers["X-Frame-Id"]) > first   # always a newer one
    assert client.get("/api/camera-frame").status_code == 401             # needs a login

    assert client.post("/api/stop-attendance", headers=auth).status_code == 200
    assert fake.released
    assert client.get(f"/api/camera-frame?token={token}").status_code == 204


def test_face_models_load_once(monkeypatch):
    import camera
    camera.face_models()
    calls = []
    import dlib
    monkeypatch.setattr(dlib, "shape_predictor", lambda p: calls.append(p))
    camera.face_models()
    assert calls == []

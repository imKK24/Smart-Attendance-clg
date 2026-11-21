"""Proxy protection: approved devices, college network, location."""
import pytest
from test_api import register
from test_batch2 import login

KEY = "k" * 40
COLLEGE = (26.144500, 91.736200)             # any point; the test only measures distance from it


@pytest.fixture()
def teacher(client, auth):
    register(client, auth)
    r = client.post("/api/users", json={"username": "cam.teacher", "password": "teach-pass-1", "role": "teacher",
                                       "full_name": "Cam Teacher", "branches": []}, headers=auth)
    assert r.status_code == 200, r.json
    return login(client, "cam.teacher", "teach-pass-1")


def start(client, h, ip="203.0.113.9", key=KEY, loc=None):
    headers = {**h, "X-Device-Key": key, "X-Device-Name": "Chrome on Android"}
    if loc:
        headers["X-Location"] = ",".join(str(x) for x in loc)
    return client.post("/api/start-attendance", json={}, headers=headers, environ_base={"REMOTE_ADDR": ip})


@pytest.fixture(autouse=True)
def no_camera(monkeypatch):
    import camera
    monkeypatch.setattr(camera, "run_attendance_camera", lambda course="": camera.camera_state.update(active=False))


def test_off_by_default(client, teacher):
    assert start(client, teacher).status_code == 200


def test_device_needs_approval(client, auth, teacher):
    assert client.put("/api/attendance-guard", json={"devices": True}, headers=teacher).status_code == 403   # admin only
    assert client.put("/api/attendance-guard", json={"devices": True}, headers=auth).status_code == 200
    assert client.get("/api/attendance-guard/needs", headers=teacher).json["devices"] is True

    r = start(client, teacher)
    assert r.status_code == 403 and r.json["guard"] == "device" and "sent to the admin" in r.json["message"]
    devs = client.get("/api/attendance-guard", headers=auth).json["devices"]
    assert devs[0]["label"] == "Chrome on Android" and devs[0]["status"] == "pending" and devs[0]["username"] == "cam.teacher"
    assert "key" not in str(devs[0]).lower().replace("key_hash", "")          # the key itself is never stored or shown
    assert start(client, teacher).json["message"].startswith("This device is waiting")

    assert client.post(f"/api/devices/{devs[0]['id']}/approve", headers=teacher).status_code == 403
    assert client.post(f"/api/devices/{devs[0]['id']}/approve", headers=auth).status_code == 200
    assert start(client, teacher).status_code == 200
    assert start(client, teacher, key="z" * 40).status_code == 403            # another phone isn't approved
    assert start(client, auth).status_code == 200                             # admins are never blocked

    client.delete(f"/api/devices/{devs[0]['id']}", headers=auth)
    assert start(client, teacher).status_code == 403


def test_college_network_only(client, auth, teacher):
    client.put("/api/attendance-guard", json={"network": True}, headers=auth)
    r = start(client, teacher, ip="203.0.113.9")                              # from home, over the internet
    assert r.status_code == 403 and r.json["guard"] == "network"
    assert start(client, teacher, ip="192.168.1.45").status_code == 200       # college Wi-Fi
    assert client.put("/api/attendance-guard", json={"networks": ["not-an-ip"]}, headers=auth).status_code == 400
    client.put("/api/attendance-guard", json={"networks": ["203.0.113.0/24"]}, headers=auth)   # college's public IP
    assert start(client, teacher, ip="203.0.113.9").status_code == 200


def test_location(client, auth, teacher):
    assert client.put("/api/attendance-guard", json={"location": True}, headers=auth).status_code == 400   # no point yet
    client.put("/api/attendance-guard", json={"location": True, "lat": COLLEGE[0], "lng": COLLEGE[1], "radius": 200},
               headers=auth)
    assert client.get("/api/attendance-guard/needs", headers=teacher,
                      environ_base={"REMOTE_ADDR": "203.0.113.9"}).json["location"] is True
    r = start(client, teacher)
    assert r.status_code == 403 and "Allow location" in r.json["message"]
    assert start(client, teacher, loc=(COLLEGE[0] + 0.0005, COLLEGE[1], 30)).status_code == 200    # ~55 m away
    r = start(client, teacher, loc=(COLLEGE[0] + 0.05, COLLEGE[1], 30))                           # ~5.6 km away
    assert r.status_code == 403 and "5.6 km" in r.json["message"]
    r = start(client, teacher, loc=(COLLEGE[0], COLLEGE[1], 3000))
    assert r.status_code == 403 and "too vague" in r.json["message"]
    assert start(client, teacher, ip="192.168.1.45").status_code == 200       # on the college network: no GPS needed


def test_class_photo_is_guarded_too(client, auth, teacher):
    client.put("/api/attendance-guard", json={"network": True}, headers=auth)
    r = client.post("/api/photo-attendance/analyze", headers=teacher, data={},
                    environ_base={"REMOTE_ADDR": "203.0.113.9"})
    assert r.status_code == 403 and r.json["guard"] == "network"

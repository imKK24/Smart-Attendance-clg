"""IP cameras bound to their MAC address."""
import pytest


@pytest.fixture()
def lan(monkeypatch):
    """A pretend local network: {ip: mac}."""
    import ipcams
    net = {"192.168.1.20": "A4:2B:B0:05:E1:0C"}
    monkeypatch.setattr(ipcams, "arp_table", lambda: dict(net))
    monkeypatch.setattr(ipcams, "touch", lambda ip, timeout=0.4: ip in net)
    monkeypatch.setattr(ipcams, "check_url", lambda url: None)
    return net


def test_saved_camera_is_bound_and_followed(client, auth, lan):
    import ipcams
    r = client.post("/api/ip-cameras", json={"name": "Room 204", "kind": "wired",
                                              "url": "rtsp://admin:pw@192.168.1.20:554/stream1"}, headers=auth)
    assert r.status_code == 200 and "A4:2B:B0:05:E1:0C" in r.json["message"]
    cam_id = r.json["camera"]["id"]
    assert client.get("/api/ip-cameras", headers=auth).json["cameras"][0]["mac"] == "A4:2B:B0:05:E1:0C"

    # the same camera again (another name) is refused
    r = client.post("/api/ip-cameras", json={"name": "Copy", "url": "rtsp://admin:pw@192.168.1.20:554/stream2"}, headers=auth)
    assert r.status_code == 409

    with client.application.app_context():
        cam, url = ipcams.find(cam_id)
        assert ipcams.bound_url(cam, url) == url                   # same device: used as it is

        # router restart: the camera got a new address
        lan.pop("192.168.1.20")
        lan["192.168.1.33"] = "A4:2B:B0:05:E1:0C"
        assert ipcams.bound_url(cam, url) == "rtsp://admin:pw@192.168.1.33:554/stream1"
        cam, url = ipcams.find(cam_id)
        assert "192.168.1.33" in url                                # link saved for next time

        # someone plugs another device in at that address
        lan["192.168.1.33"] = "11:22:33:44:55:66"
        with pytest.raises(RuntimeError, match="different device"):
            ipcams.bound_url(cam, url)

        # camera switched off
        lan.pop("192.168.1.33")
        with pytest.raises(RuntimeError, match="wasn't found"):
            ipcams.bound_url(cam, url)


def test_binding_can_be_skipped_and_remote_cameras_are_not_bound(client, auth, lan):
    r = client.post("/api/ip-cameras", json={"name": "No bind", "url": "rtsp://192.168.1.20/x", "bind_mac": False}, headers=auth)
    assert r.status_code == 200 and r.json["camera"]["mac"] == ""
    r = client.post("/api/ip-cameras", json={"name": "Other site", "url": "rtsp://8.8.8.8/x"}, headers=auth)
    assert r.status_code == 200 and r.json["camera"]["mac"] == "" and "couldn't be bound" in r.json["message"]


def test_arp_formats():
    from ipcams import parse_arp
    assert parse_arp("  192.168.1.20          a4-2b-b0-05-e1-0c     dynamic") == {"192.168.1.20": "A4:2B:B0:05:E1:0C"}
    assert parse_arp("? (192.168.1.20) at a4:2b:b0:5:e1:c on en0") == {"192.168.1.20": "A4:2B:B0:05:E1:0C"}
    assert parse_arp("  192.168.1.255   ff-ff-ff-ff-ff-ff   static") == {}

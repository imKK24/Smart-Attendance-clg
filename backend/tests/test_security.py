"""Security fixes: each test is an attack that used to work and now must fail."""
import io
from datetime import date

from conftest import media
from test_api import DETAILS, register
from test_batch1 import mirrored_photo
from test_batch2 import login


def teacher(client, auth, branch="IT"):
    client.post("/api/users", json={"username": "it@x.edu", "password": "teach-pass-1", "role": "teacher",
                                    "branches": [branch]}, headers=auth)
    return login(client, "it@x.edu", "teach-pass-1")


# 1 ---------------------------------------------------------------------------
def test_published_passwords_no_longer_work_as_is(client, auth):
    from werkzeug.security import generate_password_hash
    import auth as auth_mod
    from models import Admin, db
    with db() as s:   # an account made with the old fixed password (an existing install)
        s.add(Admin(username="admin@attendai.local", password_hash=generate_password_hash("Admin@2026"), role="admin"))
    auth_mod.retire_known_passwords()          # runs on every start
    r = client.post("/api/auth/login", json={"username": "admin@attendai.local", "password": "Admin@2026"})
    h = {"Authorization": "Bearer " + r.json["token"]}
    assert r.json["user"]["must_change"] is True
    blocked = client.get("/api/students", headers=h)
    assert blocked.status_code == 403 and blocked.json["must_change"]
    again = client.post("/api/auth/password", json={"current": "Admin@2026", "new": "Teacher@2026"}, headers=h)
    assert again.status_code == 400                                     # can't pick the other published one
    r = client.post("/api/auth/password", json={"current": "Admin@2026", "new": "my-own-secret-9"}, headers=h)
    assert r.status_code == 200
    assert client.get("/api/students", headers={"Authorization": "Bearer " + r.json["token"]}).status_code == 200


def test_admin_made_accounts_set_their_own_password(client, auth):
    client.post("/api/users", json={"username": "t@x.edu", "password": "temp-pass-1", "role": "teacher"}, headers=auth)
    r = client.post("/api/auth/login", json={"username": "t@x.edu", "password": "temp-pass-1"})
    assert r.json["user"]["must_change"]
    h = {"Authorization": "Bearer " + r.json["token"]}
    assert client.get("/api/students", headers=h).status_code == 403
    assert client.post("/api/auth/password", json={"current": "temp-pass-1", "new": "temp-pass-1"}, headers=h).status_code == 400


# 2 ---------------------------------------------------------------------------
def test_teacher_cannot_see_whatsapp_qr(client, auth, monkeypatch):
    import notify
    monkeypatch.setattr(notify, "wa_status", lambda: {"state": "qr", "qr": "data:image/png;base64,QR", "me": None, "error": ""})
    t = teacher(client, auth)
    st = client.get("/api/whatsapp/status", headers=t).json
    assert st["state"] == "qr" and st["qr"] is None                      # still knows it's unlinked
    assert client.get("/api/whatsapp/status", headers=auth).json["qr"] == "data:image/png;base64,QR"


# 3 ---------------------------------------------------------------------------
def test_message_log_and_camera_list_limited_to_branch(client, auth, sent):
    import camera
    import notify
    register(client, auth)                                               # CSE student
    client.post("/api/whatsapp/test", json={"phone": "9876543210"}, headers=auth)
    client.post("/api/alerts/send", json={"id": 1, "channels": ["whatsapp"]}, headers=auth)
    notify.process_queue()
    t = teacher(client, auth)                                            # IT teacher
    assert client.get("/api/messages", headers=t).json["messages"] == []
    assert client.get("/api/messages/status", headers=t).json["last"] is None
    assert len(client.get("/api/messages", headers=auth).json["messages"]) >= 1
    camera.camera_state["recent"] = [{"name": "Dhanish Kumar", "time": "09:00"}]
    try:
        assert client.get("/api/camera-status", headers=t).json["recent"] == []
        assert client.get("/api/camera-status", headers=auth).json["recent"][0]["name"] == "Dhanish Kumar"
    finally:
        camera.camera_state["recent"] = []


# 4 ---------------------------------------------------------------------------
def test_extra_face_photo_limited_to_branch(client, auth):
    sid = register(client, auth).json["id"]                              # CSE
    fid = client.post(f"/api/students/{sid}/faces", json={"image": mirrored_photo()}, headers=auth).json["face"]["id"]
    t = teacher(client, auth)
    mt = client.post("/api/auth/media-token", headers=t).json["token"]
    assert client.get(f"/api/students/{sid}/faces/{fid}/photo?token={mt}").status_code == 404
    assert client.get(f"/api/students/{sid}/faces/{fid}/photo?token={media(client, auth)}").status_code == 200


# 5 ---------------------------------------------------------------------------
def test_login_token_not_accepted_in_links(client, auth):
    sid = register(client, auth).json["id"]
    full = auth["Authorization"][7:]
    assert client.get(f"/api/students/{sid}/photo?token={full}").status_code == 401        # login token in a URL
    mt = media(client, auth)
    assert client.get(f"/api/students/{sid}/photo?token={mt}").status_code == 200
    assert client.get("/api/students", headers={"Authorization": f"Bearer {mt}"}).status_code == 401  # media token as login
    assert client.get(f"/api/settings?token={mt}").status_code == 401                         # media token on other routes


# 6 ---------------------------------------------------------------------------
def test_password_change_and_logout_end_old_sessions(client, auth):
    other_device = dict(auth)
    mt = media(client, auth)
    r = client.post("/api/auth/password", json={"current": "secret-pass-1", "new": "brand-new-pass"}, headers=auth)
    new = {"Authorization": "Bearer " + r.json["token"]}
    assert client.get("/api/students", headers=other_device).status_code == 401
    assert client.get("/api/students", headers=new).status_code == 200
    sid = register(client, new).json["id"]
    assert client.get(f"/api/students/{sid}/photo?token={mt}").status_code == 401             # old media links too
    client.post("/api/auth/logout", headers=new)
    assert client.get("/api/students", headers=new).status_code == 401


def test_admin_reset_of_teacher_password_logs_them_out(client, auth):
    t = teacher(client, auth)
    uid = next(u["id"] for u in client.get("/api/users", headers=auth).json["users"] if u["username"] == "it@x.edu")
    client.put(f"/api/users/{uid}", json={"password": "reset-by-admin"}, headers=auth)
    assert client.get("/api/students", headers=t).status_code == 401


# 7 ---------------------------------------------------------------------------
def test_registration_number_cannot_be_a_formula(client, auth):
    r = register(client, auth, details={**DETAILS, "roll_no": '=HYPERLINK("http://evil","x")'})
    assert r.status_code == 400 and "Registration number" in r.json["message"]
    assert register(client, auth, details={**DETAILS, "roll_no": "23/CSE-01"}).status_code == 200
    from common import safe_cell
    assert safe_cell("=1+1") == "'=1+1" and safe_cell("@cmd") == "'@cmd" and safe_cell("2301201037") == "2301201037"
    import attendance
    attendance.finalize_day(date.today())
    csv_text = client.get(f"/api/attendance/{date.today()}/export?token={media(client, auth)}").data.decode("utf-8-sig")
    assert "23/CSE-01" in csv_text


# 8 ---------------------------------------------------------------------------
def test_switched_off_account_not_revealed_without_password(client, auth):
    teacher(client, auth)
    uid = next(u["id"] for u in client.get("/api/users", headers=auth).json["users"] if u["username"] == "it@x.edu")
    client.put(f"/api/users/{uid}", json={"active": False}, headers=auth)
    r = client.post("/api/auth/login", json={"username": "it@x.edu", "password": "wrong"})
    assert r.status_code == 401 and r.json["message"] == "Wrong username or password."
    r = client.post("/api/auth/login", json={"username": "nobody@x.edu", "password": "wrong"})
    assert r.json["message"] == "Wrong username or password."


# 10 --------------------------------------------------------------------------
def test_xml_bomb_xlsx_is_refused(client, auth):
    import zipfile
    import openpyxl.xml
    assert openpyxl.xml.DEFUSEDXML, "pip install defusedxml (it's in requirements.txt)"
    register(client, auth)
    eid = client.post("/api/exams", json={"name": "T", "subjects": [{"name": "Maths", "max": 100}]}, headers=auth).json["exam"]["id"]
    bomb = ('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
            + "".join(f'<!ENTITY {c} "{("&" + p + ";") * 10}">' for p, c in zip("abcdefgh", "bcdefghi"))
            + ']><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
              '<row><c t="inlineStr"><is><t>&i;</t></is></c></row></sheetData></worksheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        z.writestr("xl/worksheets/sheet1.xml", bomb)
    r = client.post(f"/api/exams/{eid}/upload", headers=auth, content_type="multipart/form-data",
                    data={"file": (io.BytesIO(buf.getvalue()), "bomb.xlsx")})
    assert r.status_code == 400                                          # refused, server still fine
    assert client.get("/api/health").status_code == 200


# Round 2 ----------------------------------------------------------------------
def test_one_account_locked_even_from_many_computers(client, auth):
    import auth as auth_mod
    for i in range(5):   # five different computers, one guess each
        client.post("/api/auth/login", json={"username": "admin@test.local", "password": f"guess-{i}"},
                    environ_base={"REMOTE_ADDR": f"10.0.0.{i + 1}"})
    r = client.post("/api/auth/login", json={"username": "admin@test.local", "password": "secret-pass-1"},
                    environ_base={"REMOTE_ADDR": "10.0.0.99"})
    assert r.status_code == 429
    first = auth_mod._failures["user:admin@test.local"][1]
    auth_mod._failures["user:admin@test.local"] = (0, 0, 1)        # lock ran out
    for i in range(5):
        client.post("/api/auth/login", json={"username": "admin@test.local", "password": f"again-{i}"},
                    environ_base={"REMOTE_ADDR": "10.0.1.1"})
    second = auth_mod._failures["user:admin@test.local"][1]
    import time
    assert second - time.time() > 100 and first - time.time() < 70   # the second lock is twice as long


def test_parent_guessing_locked_per_registration_number(client, auth):
    register(client, auth)
    for i in range(5):
        client.post("/api/parent/login", json={"reg_no": "2301201037", "name": "Dhanish Kumar", "phone": f"90000000{i:02d}"},
                    environ_base={"REMOTE_ADDR": f"10.2.0.{i + 1}"})
    r = client.post("/api/parent/login", json={"reg_no": "2301201037", "name": "Dhanish Kumar", "phone": "9876543210"},
                    environ_base={"REMOTE_ADDR": "10.2.0.50"})
    assert r.status_code == 429


def test_parent_login_is_short(client, auth):
    import jwt
    import time
    import config
    register(client, auth)
    r = client.post("/api/parent/login", json={"reg_no": "2301201037", "name": "Dhanish Kumar", "phone": "9876543210"})
    exp = jwt.decode(r.json["token"], config.SECRET_KEY, algorithms=["HS256"])["exp"]
    assert exp - time.time() <= 2 * 3600 + 5


def test_weak_passwords_refused(client, auth):
    for bad in ["password123", "11111111", "aaaabbbb", "admin@test.local-1", "short"]:
        r = client.post("/api/auth/password", json={"current": "secret-pass-1", "new": bad}, headers=auth)
        assert r.status_code == 400, bad
    r = client.post("/api/users", json={"username": "ravi@x.edu", "password": "12345678", "role": "teacher"}, headers=auth)
    assert r.status_code == 400


def test_huge_picture_refused_without_eating_memory(client, auth):
    import base64
    import struct
    import zlib
    w = h = 20000                                    # 400 megapixels, only ~400 KB on disk
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    z = zlib.compressobj(9)
    row = b"\x00" + b"\x00" * w
    body = b"".join(z.compress(row) for _ in range(h)) + z.flush()
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", body) + chunk(b"IEND", b""))
    r = register(client, auth, image="data:image/png;base64," + base64.b64encode(png).decode())
    assert r.status_code == 400
    assert client.get("/api/health").status_code == 200


def test_camera_link_cannot_point_at_the_server(client, auth):
    for url in ["http://127.0.0.1:5000/api/settings", "http://localhost:5432/", "http://169.254.169.254/latest/meta-data/",
                "rtsp://0.0.0.0/x", "http://[::1]:5000/"]:
        r = client.post("/api/ip-cameras/test", json={"url": url}, headers=auth)
        assert r.status_code == 400 and "server itself" in r.json["message"], url


def test_safety_headers(client, auth):
    r = client.get("/api/students", headers=auth)
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"

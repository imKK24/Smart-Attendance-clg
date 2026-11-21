"""Test setup. Uses separate test databases (attendai_test and, for Aakansha
IT Hub, attendai_test_ithub). With XAMPP's MySQL running they are created
automatically, so just run:   pytest
For PostgreSQL set TEST_DATABASE_URL=postgresql+psycopg2://USER:PASS@localhost:5432/attendai_test

face.jpg is cropped from scikit-image's 'astronaut' sample (a public-domain NASA photo).
"""
import base64
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "mysql+pymysql://root:@localhost:3306/attendai_test")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "KNOWN_FACES_DIR", tmp_path / "faces")
    monkeypatch.setattr(config, "ATTENDANCE_DIR", tmp_path / "records")
    monkeypatch.setattr(config, "COURSE_IMAGES_DIR", tmp_path / "courses")
    (tmp_path / "faces").mkdir()
    (tmp_path / "records").mkdir()
    (tmp_path / "courses").mkdir()
    from models import ENGINES, Base, ensure_database
    for org, eng in ENGINES.items():  # both organisations' test databases start empty
        ensure_database(org)
        Base.metadata.drop_all(eng)
    from app import create_app
    application = create_app(start_background=False)
    import auth
    auth._failures.clear()
    import parent
    parent._failures.clear()
    import notify
    monkeypatch.setattr(notify.time, "sleep", lambda s: None)   # no WhatsApp spacing in tests
    yield application
    for eng in ENGINES.values():
        eng.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth(client):
    r = client.post("/api/auth/setup", json={"username": "admin", "password": "secret-pass-1"})
    assert r.status_code == 200, r.json
    return {"Authorization": f"Bearer {r.json['token']}"}


def media(client, auth):
    """The short view-only token that <img> and download links use."""
    return client.post("/api/auth/media-token", headers=auth).json["token"]


def image(name):
    return "data:image/jpeg;base64," + base64.b64encode((HERE / "fixtures" / name).read_bytes()).decode()


@pytest.fixture()
def sent(monkeypatch):
    """Capture WhatsApp and Gmail sends instead of really sending."""
    import notify
    out = {"whatsapp": [], "email": []}

    def fake_wa(to, text):
        if to.endswith("0000000000"):
            raise RuntimeError("This number is not on WhatsApp.")
        out["whatsapp"].append((to, text))

    class FakeSMTP:
        def send_message(self, msg):
            out["email"].append(msg)

    class FakeCM:
        def __init__(self, st):
            pass

        def __enter__(self):
            return FakeSMTP()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(notify, "wa_send", fake_wa)
    monkeypatch.setattr(notify, "open_smtp", FakeCM)
    return out

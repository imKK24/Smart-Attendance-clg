"""Going online: one address for app + API, safe first setup, real visitor IPs."""


def test_built_app_served_on_same_address(app, tmp_path, monkeypatch):
    import config
    from app import create_app
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app-123.js").write_text("console.log(1)")
    monkeypatch.setattr(config, "FRONTEND_DIST", dist)
    c = create_app(start_background=False).test_client()
    home = c.get("/")
    assert home.status_code == 200 and b"root" in home.data
    assert "default-src 'self'" in home.headers["Content-Security-Policy"]
    assert c.get("/students/deep/link").data == home.data                 # page refresh on any screen works
    assert "max-age=31536000" in c.get("/assets/app-123.js").headers["Cache-Control"]
    api404 = c.get("/api/does-not-exist")
    assert api404.status_code in (401, 404) and api404.is_json            # API stays JSON
    assert c.get("/api/health").headers["Content-Security-Policy"].startswith("default-src 'none'")


def test_first_admin_only_from_this_pc(client):
    r = client.post("/api/auth/setup", json={"username": "boss", "password": "very-secret-9"},
                    environ_base={"REMOTE_ADDR": "203.0.113.7"})
    assert r.status_code == 403
    r = client.post("/api/auth/setup", json={"username": "boss", "password": "very-secret-9"})
    assert r.status_code == 200


def test_visitor_ip_from_tunnel(monkeypatch, tmp_path):
    """Dev server path (python app.py) with BEHIND_TUNNEL=1: X-Forwarded-For is the visitor."""
    import auth
    import config
    from app import create_app
    from models import Base, engine
    Base.metadata.drop_all(engine)
    monkeypatch.setattr(config, "BEHIND_TUNNEL", True)
    c = create_app(start_background=False).test_client()
    auth._failures.clear()
    for i in range(5):
        c.post("/api/auth/login", json={"username": f"u{i}@x", "password": "bad-guess"},
               headers={"X-Forwarded-For": f"198.51.100.{i}"})
    r = c.post("/api/auth/login", json={"username": "other@x", "password": "bad-guess"},
               headers={"X-Forwarded-For": "198.51.100.99"})
    assert r.status_code == 401                         # a different visitor isn't locked out
    assert "ip:198.51.100.0" in auth._failures
    engine.dispose()


def test_production_server_settings():
    import inspect
    import serve
    src = inspect.getsource(serve)
    assert "trusted_proxy=\"127.0.0.1\"" in src and "clear_untrusted_proxy_headers=True" in src


def test_camera_shows_why_it_stopped(app, monkeypatch):
    """face_recognition calls quit() when its models can't load: the page must say so,
    not just 'Camera stopped'."""
    import camera

    def models_missing():
        raise SystemExit("Please install face_recognition_models")
    monkeypatch.setattr(camera, "load_known", models_missing)
    camera.camera_state.update(active=True, status="starting", message="")
    camera.run_attendance_camera()
    assert camera.camera_state["status"] == "error"
    assert "Camera stopped" not in camera.camera_state["message"]
    assert camera.camera_state["active"] is False

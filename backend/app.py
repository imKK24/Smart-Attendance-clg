# ============================================================
#  FILE: app.py  -  AttendAI REST API (Flask + PostgreSQL)
#  RUN : python app.py        ->  http://localhost:5000
#
#  Needs PostgreSQL running (see README). Tables are created on the
#  first start. Open the React app and create the admin account.
# ============================================================
import sys

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS
from sqlalchemy.exc import OperationalError

from models import DatabaseMissing

import config


APP_CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
           "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
           "frame-ancestors 'none'")


def create_app(start_background=True, proxy_fix=True):
    import analytics
    import attendance
    import auth
    import camera
    import content
    import faces
    import fees
    import leaves
    import inbox
    import guard
    import ipcams
    import notify
    import parent
    import photo_attendance
    import reports
    import courses
    import students
    import users
    import wa_chats
    from models import create_tables

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024  # up to 5 phone photos at a time
    # Only your own React app may call the API from a browser.
    CORS(app, origins=config.FRONTEND_ORIGINS, expose_headers=["Content-Disposition", "X-Frame-Id"])

    if config.BEHIND_TUNNEL and proxy_fix:   # serve.py lets Waitress do this instead
        if config.HOST in ("127.0.0.1", "localhost", "::1"):
            # Trust exactly one forwarding step: the tunnel program on this PC.
            from werkzeug.middleware.proxy_fix import ProxyFix
            app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
        else:
            print("BEHIND_TUNNEL=1 is ignored because HOST isn't 127.0.0.1: anyone on the network could fake their IP.")

    @app.after_request
    def safety_headers(resp):
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")   # a photo is never run as a script
        h.setdefault("X-Frame-Options", "DENY")             # no other site can frame the app
        h.setdefault("Referrer-Policy", "no-referrer")      # link tokens never leak to other sites
        if request.path.startswith("/api/"):
            h.setdefault("Content-Security-Policy", "default-src 'none'; img-src 'self'; frame-ancestors 'none'")
        else:   # the React app: only its own files; camera and photos stay on this site
            h.setdefault("Content-Security-Policy", APP_CSP)
        if request.is_secure:   # reached over https (the tunnel): browsers must never fall back to http
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        if resp.mimetype == "application/json" or "attachment" in h.get("Content-Disposition", ""):
            h["Cache-Control"] = "no-store"                 # student data isn't kept in browser caches
        return resp

    create_tables()
    auth.retire_known_passwords()
    app.before_request(auth.check_request)
    for module in (auth, students, courses, attendance, camera, notify, content, inbox, faces, reports, leaves, users, analytics, wa_chats, fees, ipcams, photo_attendance, parent, guard):
        app.register_blueprint(module.bp)

    @app.get("/api/health")
    def health():
        # "you" = the address the server sees for you. Through the tunnel it must be
        # your real internet IP, not 127.0.0.1 (deploy/README-DEPLOY.md, step 5).
        return jsonify(success=True, you=request.remote_addr)

    # ── the built React app, on the same address as the API ──
    dist = config.FRONTEND_DIST
    if (dist / "index.html").is_file():
        @app.get("/")
        @app.get("/<path:path>")
        def frontend(path=""):
            if path.startswith("api/"):
                abort(404)
            if path and (dist / path).is_file():
                resp = send_from_directory(dist, path)
                if path.startswith("assets/"):     # file names change on every build
                    resp.cache_control.max_age, resp.cache_control.public = 31536000, True
                return resp
            resp = send_from_directory(dist, "index.html")
            resp.cache_control.no_cache = True     # always get the newest version
            return resp

    @app.errorhandler(404)
    def not_found(_e):
        if not request.path.startswith("/api/") and not (config.FRONTEND_DIST / "index.html").is_file():
            return ("AttendAI API is running. Build the app first: cd frontend, then npm run build.", 404)
        return jsonify(success=False, message="Not found."), 404

    @app.errorhandler(413)
    def too_big(_e):
        return jsonify(success=False, message="That file is too big."), 413

    @app.errorhandler(OperationalError)
    def db_down(_e):
        return jsonify(success=False, message="The database isn't reachable. Is PostgreSQL running?"), 503

    @app.errorhandler(500)
    def crashed(_e):
        return jsonify(success=False, message="Something went wrong on the server. Check the terminal."), 500

    if start_background:
        notify.start_worker()
        inbox.start_auto_sync()
        fees.start_auto_reminders()
        camera.warm_up()          # face models + camera list ready before the first Start
    return app


if __name__ == "__main__":
    if config.already_running():
        print(config.ALREADY_RUNNING_HELP)
        sys.exit(1)
    try:
        application = create_app()
    except DatabaseMissing as exc:
        print("\n" + str(exc))
        sys.exit(1)
    except OperationalError as exc:
        print("\nCan't connect to PostgreSQL.")
        print("  DATABASE_URL =", config.DATABASE_URL.split("@")[-1])
        print("  Start PostgreSQL and create the database (see README.md, step 2).")
        print("  Details:", str(exc.orig).strip().splitlines()[0] if exc.orig else exc)
        sys.exit(1)
    print("=" * 50)
    print(f"   AttendAI API running at: http://localhost:{config.PORT}")
    print("   (development server: for real use run  python serve.py)")
    print("=" * 50)
    # debug=False: the reloader would start a second process that fights over the webcam.
    application.run(host=config.HOST, port=config.PORT, debug=False, threaded=True)

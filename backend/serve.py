# ============================================================
#  FILE: serve.py  -  AttendAI for real use (production server)
#  RUN : python serve.py      ->  http://localhost:5000
#
#  Same app as `python app.py`, but on Waitress, a proper web server for
#  Windows and Linux: many people at once, no development warnings.
#  It also serves the built React app (frontend/dist), so the whole of
#  AttendAI is on one address. The tunnel publishes that address online.
# ============================================================
import sys

from sqlalchemy.exc import OperationalError
from waitress import serve

import config
from app import create_app
from models import DatabaseMissing


def main():
    if config.already_running():
        print(config.ALREADY_RUNNING_HELP)
        sys.exit(1)
    try:
        application = create_app(proxy_fix=False)
    except DatabaseMissing as exc:
        print("\n" + str(exc))
        sys.exit(1)
    except OperationalError as exc:
        print("Can't connect to PostgreSQL. Is it running?  Details:", exc.orig or exc)
        sys.exit(1)
    if not (config.FRONTEND_DIST / "index.html").is_file():
        print("Note: frontend/dist not found. Run  npm run build  in the frontend folder.")
    print("=" * 56)
    print(f"  AttendAI running at  http://localhost:{config.PORT}")
    if config.PUBLIC_URL:
        print(f"  Online at            {config.PUBLIC_URL}")
    print("  Stop with Ctrl+C")
    print("=" * 56)
    # threads: each live camera view keeps one busy, so leave plenty for everyone else.
    tunnel = {}
    if config.BEHIND_TUNNEL:
        if config.HOST in ("127.0.0.1", "localhost"):
            # The tunnel program runs on this PC and adds the visitor's real IP.
            # Trust exactly that one step; a faked header from anyone else is dropped.
            tunnel = dict(trusted_proxy="127.0.0.1", trusted_proxy_count=1,
                          trusted_proxy_headers="x-forwarded-for x-forwarded-proto",
                          clear_untrusted_proxy_headers=True)
        else:
            print("BEHIND_TUNNEL=1 ignored: HOST must be 127.0.0.1 when a tunnel is used.")
    serve(application, host=config.HOST, port=config.PORT, threads=32,
          connection_limit=200, channel_timeout=120, ident="AttendAI", **tunnel)


if __name__ == "__main__":
    main()

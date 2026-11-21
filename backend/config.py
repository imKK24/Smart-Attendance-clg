"""Settings that come from the environment (.env file) and folder paths."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv


def _pkg_resources_fallback():
    """face_recognition_models finds its model files with pkg_resources, which
    setuptools 82+ no longer includes. Without it, face_recognition prints
    'Please install face_recognition_models' and stops the program. This adds
    the one function it needs, so the camera works with any setuptools."""
    try:
        __import__("pkg_resources")
        return
    except ImportError:
        pass
    import importlib.util
    import sys
    import types

    def resource_filename(package, resource):
        spec = importlib.util.find_spec(package)
        return os.path.join(os.path.dirname(spec.origin), *resource.split("/"))

    shim = types.ModuleType("pkg_resources")
    shim.resource_filename = resource_filename
    sys.modules["pkg_resources"] = shim


_pkg_resources_fallback()

# A tiny PNG can claim to be 100,000 x 100,000 pixels and eat all the memory when
# opened. OpenCV refuses anything bigger than this (40 megapixels: any phone is fine).
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(40_000_000))

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env")

KNOWN_FACES_DIR = BASE_DIR / "known_faces"          # student photos
COURSE_IMAGES_DIR = BASE_DIR / "course_images"      # Aakansha IT Hub course pictures
ATTENDANCE_DIR = BASE_DIR / "attendance_records"    # daily CSV copies (open in Excel)
DATA_DIR = BASE_DIR / "data"                         # secret key, WhatsApp token
for d in (KNOWN_FACES_DIR, COURSE_IMAGES_DIR, ATTENDANCE_DIR, DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Two separate databases, one per organisation (see orgs.py):
#   DATABASE_URL        Seemanta Engineering College   (database "attendai")
#   ITHUB_DATABASE_URL  Aakansha IT Hub                (database "attendai_ithub")
# XAMPP's MySQL: user root, no password, port 3306 (the default below).
# PostgreSQL still works: postgresql+psycopg2://USER:PASS@localhost:5432/attendai
DATABASE_URL = os.environ.get("DATABASE_URL", "mysql+pymysql://root:@localhost:3306/attendai")


def _sibling_db(url, suffix):
    """Same server and login, database name + suffix: .../attendai -> .../attendai_ithub"""
    head, _, tail = url.rpartition("/")
    name, q, query = tail.partition("?")
    return f"{head}/{name}{suffix}{q}{query}"


ITHUB_DATABASE_URL = os.environ.get("ITHUB_DATABASE_URL") or _sibling_db(DATABASE_URL, "_ithub")

FRONTEND_ORIGINS = [o.strip() for o in os.environ.get(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000",
).split(",") if o.strip()]

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))

# The 68-point landmark model. If the file isn't next to app.py we use the copy
# that ships inside the face_recognition_models package, so no manual download.
PREDICTOR_FILE = BASE_DIR / "shape_predictor_68_face_landmarks.dat"


def predictor_path():
    if PREDICTOR_FILE.is_file():
        return str(PREDICTOR_FILE)
    try:
        import face_recognition_models
        return face_recognition_models.pose_predictor_model_location()
    except Exception:
        return None


def _secret_from_file(name, env_key, nbytes=32):
    """Use the env var if set, else a random value saved once in data/."""
    value = os.environ.get(env_key, "").strip()
    if value:
        return value
    path = DATA_DIR / name
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(nbytes)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


SECRET_KEY = _secret_from_file("secret.key", "SECRET_KEY")
# Shared secret between this API and the WhatsApp bridge (whatsapp-bridge/
# reads the same file when WA_BRIDGE_TOKEN isn't set).
WA_BRIDGE_TOKEN = _secret_from_file("bridge.token", "WA_BRIDGE_TOKEN", 24)
WA_BRIDGE_URL = os.environ.get("WA_BRIDGE_URL", "http://127.0.0.1:5100").rstrip("/")

TOKEN_HOURS = int(os.environ.get("TOKEN_HOURS", "12"))
# Parents usually open the portal on a shared or family phone: keep their login short.
PARENT_TOKEN_HOURS = int(os.environ.get("PARENT_TOKEN_HOURS", "2"))
# Camera links to this same computer (127.0.0.1 / localhost) are refused, because
# they can be used to reach the database and other services. Set to 1 only if you
# run a camera relay program (e.g. go2rtc, MediaMTX) on this same computer.
ALLOW_LOCAL_CAMERAS = os.environ.get("ALLOW_LOCAL_CAMERAS", "0") == "1"

def already_running():
    """True if an AttendAI server already answers on this port. On Windows two
    programs can both listen on port 5000, and then requests land on either one
    at random (e.g. the camera starts in one and the page asks the other)."""
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2) as r:
            return bool(json.loads(r.read().decode() or "{}").get("success"))
    except Exception:
        return False


ALREADY_RUNNING_HELP = (
    f"AttendAI is already running on port {PORT} (probably the background copy started by setup.bat).\n"
    f"  * To use it: open http://localhost:{PORT}\n"
    "  * To run this copy instead: double-click deploy\\windows\\stop-attendai.bat first, then start this again.")


# ── Going online (see deploy/README-DEPLOY.md) ──
# The built React app (npm run build). When it exists, the API also serves it,
# so the whole of AttendAI is on one address: http://localhost:5000
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
# 1 when a tunnel (Tailscale Funnel / Cloudflare) forwards visitors to this PC.
# The tunnel tells us each visitor's real IP; without this every visitor would
# look like 127.0.0.1 and one person's wrong passwords would lock out everyone.
BEHIND_TUNNEL = os.environ.get("BEHIND_TUNNEL", "0") == "1"
# The public address, e.g. https://attendai-pc.tail1234.ts.net (used in messages).
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")

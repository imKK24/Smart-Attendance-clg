"""IP cameras (wired or Wi-Fi) by link: RTSP or HTTP. Admin only.

Typical links (see the Camera links help in the app):
  TP-Link Tapo       rtsp://USER:PASS@192.168.1.20:554/stream1
  CP Plus / Dahua    rtsp://USER:PASS@192.168.1.20:554/cam/realmonitor?channel=1&subtype=0
  Hikvision          rtsp://USER:PASS@192.168.1.20:554/Streaming/Channels/101
  Android IP Webcam  http://192.168.1.5:8080/video
"""
import base64
import os
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

# RTSP over TCP is far more reliable than UDP on school Wi-Fi. Must be set
# before OpenCV opens the first stream.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import ipaddress  # noqa: E402
import re  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

import cv2  # noqa: E402

import config  # noqa: E402
from flask import Blueprint, request  # noqa: E402

from common import clean_text, decrypt_text, encrypt_text, fail, get_settings, ok, update_settings  # noqa: E402

bp = Blueprint("ipcams", __name__, url_prefix="/api")
SCHEMES = ("rtsp", "rtsps", "http", "https")
OPEN_TIMEOUT_MS = 7000
MAX_CAMS = 20


def check_url(url):
    """Return an error message, or None if the link looks usable."""
    try:
        u = urlsplit(url)
    except ValueError:
        return "That link can't be read."
    if u.scheme not in SCHEMES:
        return "The link must start with rtsp:// or http:// (see the examples)."
    if not u.hostname:
        return "The link needs the camera's address, e.g. rtsp://192.168.1.20:554/stream1"
    if not config.ALLOW_LOCAL_CAMERAS and blocked_host(u.hostname):
        return "That address points at this server itself, not a camera. Use the camera's own IP address."
    return None


def blocked_host(host):
    """True for addresses that are never a camera: this computer (127.x, localhost),
    'any' (0.0.0.0) and link-local 169.254.x (where cloud servers keep their keys).
    Stops the camera tester from being used to poke at services on the server."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, ValueError):
        return False          # can't resolve now: the open will simply fail
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            continue
        ip = getattr(ip, "ipv4_mapped", None) or ip
        if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast:
            return True
    return False


def masked(url):
    """rtsp://admin:secret@1.2.3.4/x  ->  rtsp://admin:•••@1.2.3.4/x"""
    u = urlsplit(url)
    if u.password:
        host = u.hostname + (f":{u.port}" if u.port else "")
        return urlunsplit((u.scheme, f"{u.username}:•••@{host}", u.path, u.query, ""))
    return url


# ---------------- MAC binding ----------------
# A camera's IP address can change (router restart) and anyone can plug another
# device in at that address. Its MAC address belongs to the camera itself, so a
# saved camera remembers its MAC: before each use the server checks the device at
# that address is the same camera, and finds it again if it moved.
# Works for cameras on this computer's own network (same router / switch): MAC
# addresses don't travel further than that.
MAC_RE = re.compile(r"([0-9a-f]{1,2}(?:[:-][0-9a-f]{1,2}){5})", re.I)
IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
CAMERA_PORTS = (554, 80)


def norm_mac(text):
    """'a4-2b-b0-5-e1-c' / 'a4:2b:b0:05:e1:0c' -> 'A4:2B:B0:05:E1:0C' (None if not a real one)."""
    parts = re.split(r"[:-]", str(text or "").strip())
    if len(parts) != 6 or not all(re.fullmatch(r"[0-9a-fA-F]{1,2}", p) for p in parts):
        return None
    mac = ":".join(p.zfill(2).upper() for p in parts)
    return None if mac in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00") else mac


def parse_arp(text):
    """{ip: mac} from 'arp -a' (Windows, macOS) or /proc/net/arp (Linux)."""
    table = {}
    for line in text.splitlines():
        ip, mac = IP_RE.search(line), MAC_RE.search(line)
        if ip and mac and norm_mac(mac.group(1)):
            table.setdefault(ip.group(1), norm_mac(mac.group(1)))
    return table


def arp_table():
    """The devices this computer has talked to on the local network."""
    if os.name != "nt" and os.path.exists("/proc/net/arp"):
        with open("/proc/net/arp", encoding="ascii", errors="ignore") as f:
            return parse_arp(f.read())
    cmd = ["arp", "-a"] if os.name == "nt" else ["arp", "-an"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000 if os.name == "nt" else 0).stdout   # no console window
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_arp(out)


def touch(ip, timeout=0.4):
    """Talk to the address once so it shows up in the ARP table."""
    for port in CAMERA_PORTS:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def host_ip(url):
    """The camera's address if the link points at the local network (the only case MACs work for)."""
    host = urlsplit(url).hostname or ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        except (OSError, ValueError, UnicodeError):
            return None
    from guard import is_lan
    return str(ip) if ip.version == 4 and is_lan(str(ip)) and not ip.is_loopback else None


def mac_at(ip):
    touch(ip)
    return arp_table().get(ip)


def find_mac(mac, near_ip):
    """Look for the camera on the local network (the 254 addresses around its old one)."""
    found = sorted(i for i, m in arp_table().items() if m == mac)
    if found:
        return found[0]
    net = ipaddress.ip_network(f"{near_ip}/24", strict=False)
    with ThreadPoolExecutor(max_workers=64) as pool:
        list(pool.map(lambda h: touch(str(h), 0.3), net.hosts()))
    found = sorted(i for i, m in arp_table().items() if m == mac)
    return found[0] if found else None


def with_host(url, ip):
    u = urlsplit(url)
    login = u.netloc.rsplit("@", 1)[0] + "@" if "@" in u.netloc else ""
    return urlunsplit((u.scheme, f"{login}{ip}" + (f":{u.port}" if u.port else ""), u.path, u.query, u.fragment))


def bound_url(cam, url):
    """The link to open for a saved camera, after checking its MAC. Raises RuntimeError
    if the device at that address isn't the saved camera and the camera can't be found."""
    mac, ip = cam.get("mac"), host_ip(url)
    if not mac or not ip:
        return url
    now_mac = mac_at(ip)
    if now_mac == mac:
        return url
    new_ip = find_mac(mac, ip)
    if new_ip:
        new_url = with_host(url, new_ip)
        cams = saved()
        for c in cams:
            if c["id"] == cam["id"]:
                c["url"] = encrypt_text(new_url)
        update_settings(ip_cameras=cams)
        print(f"IP camera '{cam['name']}' moved from {ip} to {new_ip}; its link was updated.")
        return new_url
    if now_mac:
        raise RuntimeError(f"A different device is now at {ip}, not the camera '{cam['name']}' "
                           f"(expected {mac}, found {now_mac}). For safety it isn't used. "
                           "If the camera was replaced, remove it and add it again.")
    raise RuntimeError(f"The camera '{cam['name']}' ({mac}) wasn't found on the network. "
                       "Check that it is switched on and connected to the college network.")


def saved():
    return get_settings().get("ip_cameras") or []


def find(cam_id):
    cam = next((c for c in saved() if c["id"] == cam_id), None)
    return (cam, decrypt_text(cam["url"])) if cam else (None, "")


def open_stream(url):
    """Open an RTSP/HTTP stream with timeouts, so a wrong link fails in seconds, not minutes."""
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS,
                                                cv2.CAP_PROP_READ_TIMEOUT_MSEC, OPEN_TIMEOUT_MS])
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


class LatestFrameReader:
    """Reads a network stream in its own thread and keeps only the newest frame.
    Without this, recognition (slower than the camera) falls further and further
    behind and the live view lags by many seconds."""

    def __init__(self, cap):
        self.cap, self.frame, self.stamp, self.running = cap, None, 0.0, True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="ip-camera-reader")
        self.thread.start()

    def _loop(self):
        while self.running:
            okay, frame = self.cap.read()
            if okay and frame is not None:
                with self.lock:
                    self.frame, self.stamp = frame, time.time()
            else:
                time.sleep(0.05)

    def read(self, wait=6.0):
        """(ok, frame). Waits a little for the first frame / a stalled stream."""
        end = time.time() + wait
        while time.time() < end:
            with self.lock:
                if self.frame is not None and time.time() - self.stamp < wait:
                    return True, self.frame.copy()
            time.sleep(0.03)
        return False, None

    def release(self):
        self.running = False
        self.thread.join(timeout=2)
        self.cap.release()


def snapshot(url):
    """(jpeg data-url, width, height) or raises RuntimeError with a friendly reason."""
    cap = open_stream(url)
    if cap is None:
        raise RuntimeError("Couldn't connect. Check the address, user name and password, and that the camera "
                           "is on the same network as this computer.")
    try:
        frame = None
        for _ in range(15):          # first frames of some streams are grey
            okay, f = cap.read()
            if okay and f is not None:
                frame = f
                if f.mean() > 8:
                    break
        if frame is None:
            raise RuntimeError("Connected, but no picture came through. Try the camera's main stream link.")
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (640, int(h * 640 / w))) if w > 640 else frame
        okay, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode(), w, h
    finally:
        cap.release()


def cam_json(c):
    return {"id": c["id"], "name": c["name"], "kind": c.get("kind", "wifi"), "link": masked(decrypt_text(c["url"])),
            "value": f"ip:{c['id']}", "mac": c.get("mac") or ""}


# ---------------- API (admin only, see auth.ADMIN_ONLY) ----------------
@bp.get("/ip-cameras")
def list_ip():
    return ok(cameras=[cam_json(c) for c in saved()])


@bp.post("/ip-cameras/test")
def test_ip():
    d = request.get_json(silent=True) or {}
    url = str(d.get("url") or "").strip()
    if d.get("id"):
        _, url = find(d["id"])
    error = check_url(url) if url else "Enter the camera link."
    if error:
        return fail(error)
    try:
        image, w, h = snapshot(url)
    except RuntimeError as e:
        return fail(str(e), 502)
    note = "" if w >= 1280 else "Low resolution. Use the camera's main stream (not the sub stream) for better recognition."
    ip = host_ip(url)
    mac = arp_table().get(ip) if ip else None      # the stream just talked to it, so it's in the table
    return ok(f"Connected: {w}×{h}", image=image, width=w, height=h, note=note, mac=mac or "")


@bp.post("/ip-cameras")
def add_ip():
    d = request.get_json(silent=True) or {}
    name = clean_text(d.get("name"), 60)
    url = str(d.get("url") or "").strip()
    kind = d.get("kind") if d.get("kind") in ("wired", "wifi") else "wifi"
    if not name:
        return fail("Give the camera a name, e.g. Room 204 door.")
    error = check_url(url)
    if error:
        return fail(error)
    cams = saved()
    if len(cams) >= MAX_CAMS:
        return fail(f"At most {MAX_CAMS} IP cameras.")
    if any(decrypt_text(c["url"]) == url for c in cams):
        return fail("This camera link is already saved.", 409)
    cam = {"id": uuid.uuid4().hex[:8], "name": name, "kind": kind, "url": encrypt_text(url)}
    msg = f"{name} saved"
    if d.get("bind_mac", True):
        ip = host_ip(url)
        mac = mac_at(ip) if ip else None
        if mac:
            if any(c.get("mac") == mac for c in cams):
                return fail(f"The camera with MAC {mac} is already saved under another name.", 409)
            cam["mac"] = mac
            msg += f" and bound to its MAC address {mac}"
        else:
            msg += (". It couldn't be bound to a MAC address (the camera isn't on this computer's own network, "
                    "or didn't answer). It still works by its address")
    update_settings(ip_cameras=cams + [cam])
    return ok(msg + ".", camera=cam_json(cam))


@bp.delete("/ip-cameras/<cam_id>")
def delete_ip(cam_id):
    cams = saved()
    kept = [c for c in cams if c["id"] != cam_id]
    if len(kept) == len(cams):
        return fail("Camera not found.", 404)
    update_settings(ip_cameras=kept)
    if get_settings().get("camera") == f"ip:{cam_id}":
        update_settings(camera="default")
    return ok("Camera removed")


# ---------------- which ways of taking attendance are on ----------------
METHODS = ("camera", "photo")


@bp.get("/attendance-methods")
def get_methods():
    return ok(methods=[m for m in get_settings().get("attendance_methods") or METHODS if m in METHODS])


@bp.post("/attendance-methods")
def set_methods():
    chosen = [m for m in (request.get_json(silent=True) or {}).get("methods") or [] if m in METHODS]
    if not chosen:
        return fail("Keep at least one way of taking attendance switched on.")
    update_settings(attendance_methods=chosen)
    return ok("Saved", methods=chosen)

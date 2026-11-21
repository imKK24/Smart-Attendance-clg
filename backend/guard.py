"""Proxy protection for taking attendance (live camera and class photo).

The admin can switch on any of these, separately for the college and the IT Hub:
  devices   a teacher's phone / laptop must be approved by the admin once.
            Browsers never reveal a MAC address, so each browser keeps a random
            device key instead (see api.js); only its hash is stored here.
  network   only from the college network: this computer's own network
            (192.168.x / 10.x ...) or the public addresses the admin added.
  location  when not on the college network, the phone's location must be
            within the set distance of the college.
They apply to teachers. Admins set the rules, so they are never locked out.
Nothing here is unbeatable (a fake-GPS app can lie about location), but
together they stop the everyday "marked it from home" proxy.
"""
import hashlib
import ipaddress
import math
import re

from flask import Blueprint, g, request

from common import clean_text, fail, get_settings, ok, update_settings
from models import Device, db, now

bp = Blueprint("guard", __name__, url_prefix="/api")

DEFAULT = {"devices": False, "network": False, "networks": [], "location": False,
           "lat": None, "lng": None, "radius": 200}
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
MAX_ACCURACY = 1000        # metres: a location vaguer than this proves nothing


def rules():
    return {**DEFAULT, **(get_settings().get("attendance_guard") or {})}


# ---------------- network ----------------
def visitor_ip():
    return request.remote_addr or ""


# Local network ranges (what a router hands out) and the server PC itself.
LAN = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
                                          "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10")]


def is_lan(ip):
    """On the same network as the server (or the server PC itself)."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    a = getattr(a, "ipv4_mapped", None) or a
    return any(a in n for n in LAN if n.version == a.version)


def in_networks(ip, nets):
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for n in nets or []:
        try:
            if a in ipaddress.ip_network(n, strict=False):
                return True
        except ValueError:
            continue
    return False


def on_college_network(r=None):
    ip = visitor_ip()
    return is_lan(ip) or in_networks(ip, (r or rules())["networks"])


# ---------------- location ----------------
def distance_m(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def sent_location():
    """(lat, lng, accuracy) from the X-Location header, or None."""
    try:
        lat, lng, acc = (float(x) for x in request.headers.get("X-Location", "").split(","))
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180 and 0 <= acc < 100000):
        return None
    return lat, lng, acc


# ---------------- devices ----------------
def device_hash():
    key = request.headers.get("X-Device-Key", "")
    return hashlib.sha256(key.encode()).hexdigest() if KEY_RE.match(key) else None


def device_label():
    name = clean_text(request.headers.get("X-Device-Name"), 80)
    return name or "Unknown device"


def check_device():
    h = device_hash()
    if not h:
        return "This browser has no device key. Reload the page and try again."
    with db() as s:
        dev = s.query(Device).filter(Device.key_hash == h).first()
        if dev is None:
            s.add(Device(key_hash=h, username=g.admin_name, label=device_label(), last_ip=visitor_ip()[:45]))
            return (f"This device ({device_label()}) isn't approved for taking attendance yet. "
                    "It has been sent to the admin: ask them to approve it on Take attendance > Proxy protection.")
        if dev.username != g.admin_name:
            return "This device was approved for another teacher. Each teacher needs their own device approved."
        if dev.status != "approved":
            return "This device is waiting for the admin's approval (Take attendance > Proxy protection)."
        dev.last_seen, dev.last_ip = now(), visitor_ip()[:45]
    return None


# ---------------- the check ----------------
def check():
    """None if this request may take attendance, else a fail() response."""
    if g.get("role", "admin") == "admin":
        return None
    r = rules()
    if r["devices"]:
        problem = check_device()
        if problem:
            return fail(problem, 403, guard="device")
    on_net = on_college_network(r)
    if r["network"] and not on_net and not r["location"]:
        return fail("Attendance can only be taken from the college network (college Wi-Fi or LAN).", 403, guard="network")
    if r["location"] and not on_net and r["lat"] is not None:
        loc = sent_location()
        if not loc:
            return fail("Allow location access in your browser: attendance from outside the college network "
                        "needs your location.", 403, guard="location")
        lat, lng, acc = loc
        if acc > MAX_ACCURACY:
            return fail(f"Your location is too vague (±{round(acc)} m). Turn on GPS / precise location and try again.",
                        403, guard="location")
        dist = distance_m(lat, lng, r["lat"], r["lng"])
        if dist > r["radius"] + min(acc, 150):
            return fail(f"You seem to be {_far(dist)} from the college. Attendance can only be taken at the college.",
                        403, guard="location")
    return None


def _far(m):
    return f"{m / 1000:.1f} km" if m >= 1000 else f"{round(m)} m"


# ---------------- API ----------------
@bp.get("/attendance-guard/needs")
def needs():
    """What this browser must send before taking attendance (any logged-in staff)."""
    r = rules()
    teacher = g.get("role", "admin") != "admin"
    return ok(location=bool(teacher and r["location"] and r["lat"] is not None and not on_college_network(r)),
              devices=bool(teacher and r["devices"]))


def device_json(d):
    return {"id": d.id, "username": d.username, "label": d.label, "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "last_seen": d.last_seen.isoformat() if d.last_seen else None, "last_ip": d.last_ip}


@bp.get("/attendance-guard")
def get_guard():
    with db() as s:
        devices = [device_json(d) for d in s.query(Device).order_by(Device.status.desc(), Device.created_at.desc())]
    ip = visitor_ip()
    return ok(rules=rules(), devices=devices, my_ip=ip, my_ip_is_lan=is_lan(ip))


@bp.put("/attendance-guard")
def put_guard():
    d = request.get_json(silent=True) or {}
    r = rules()
    for k in ("devices", "network", "location"):
        if k in d:
            r[k] = bool(d[k])
    if "networks" in d:
        nets = []
        for n in d["networks"] or []:
            n = str(n).strip()
            try:
                ipaddress.ip_network(n, strict=False)
            except ValueError:
                return fail(f"'{n}' isn't an IP address or range (e.g. 49.36.12.80 or 49.36.12.0/24).")
            nets.append(n)
        r["networks"] = list(dict.fromkeys(nets))[:20]
    if "lat" in d or "lng" in d:
        try:
            lat, lng = float(d.get("lat")), float(d.get("lng"))
            assert -90 <= lat <= 90 and -180 <= lng <= 180
        except (TypeError, ValueError, AssertionError):
            return fail("The college location isn't valid.")
        r["lat"], r["lng"] = round(lat, 6), round(lng, 6)
    if "radius" in d:
        try:
            r["radius"] = max(50, min(5000, int(d["radius"])))
        except (TypeError, ValueError):
            return fail("The distance must be a number of metres.")
    if r["location"] and r["lat"] is None:
        return fail("Set the college location first (press 'Use my location' while at the college).")
    update_settings(attendance_guard=r)
    return ok("Proxy protection saved.", rules=r)


@bp.post("/devices/<int:did>/approve")
def approve(did):
    with db() as s:
        dev = s.get(Device, did)
        if not dev:
            return fail("Device not found.", 404)
        dev.status, dev.approved_at = "approved", now()
        return ok(f"{dev.label} approved for {dev.username}.")


@bp.delete("/devices/<int:did>")
def remove(did):
    with db() as s:
        dev = s.get(Device, did)
        if not dev:
            return fail("Device not found.", 404)
        s.delete(dev)
    return ok("Device removed. It can't take attendance until it's approved again.")

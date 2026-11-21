"""Live attendance camera: random challenge liveness + face recognition.

WAIT       face the camera -> identify who it is (must be a registered student)
CHALLENGE  do CHALLENGE_STEPS random actions (blink twice / turn left /
           turn right / open mouth). The order is random every time, so a
           recorded video or a photo can't know what will be asked.
VERIFY     look straight again -> identify a second time. It must be the
           SAME person as at the start.
After MAX_FAILS failures the camera locks for LOCKOUT_SECONDS.
"""
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from flask import Blueprint, Response, request

import attendance
import config
from common import fail, get_settings, ok, update_settings
from models import Student, db
from orgs import as_org, current_org, org_name, uses_courses

bp = Blueprint("camera", __name__, url_prefix="/api")

EAR_THRESHOLD = 0.25
MATCH_DISTANCE = 0.5     # stricter than face_recognition's 0.6 default: fewer wrong matches
MESSAGE_HOLD = 3
CHALLENGES = ["blink", "left", "right", "mouth"]
PROMPTS = {
    "blink": "Blink twice",
    "left": "Turn your head toward the left side of the screen",
    "right": "Turn your head toward the right side of the screen",
    "mouth": "Open your mouth wide",
}
CHALLENGE_STEPS, BLINKS_REQUIRED = 2, 2
CHALLENGE_TIMEOUT, ATTEMPT_TIMEOUT, VERIFY_TIMEOUT = 7, 25, 6
NEUTRAL_HOLD, MIN_FACE_WIDTH = 0.6, 100
MAX_FAILS, LOCKOUT_SECONDS = 3, 15
TURN_LEFT_MAX, TURN_RIGHT_MIN, TURN_NEUTRAL = 0.37, 0.63, (0.42, 0.58)
MOUTH_OPEN_MIN, MOUTH_CLOSED_MAX = 0.35, 0.20
HOLD_FRAMES = 3
MAX_CAMERA_INDEX = 5

state_lock = threading.Lock()
camera_thread = None
camera_state = {
    "active": False, "status": "idle", "message": "", "jpeg": None, "frame_id": 0,
    "marked_count": 0, "last_marked": None, "recent": [], "camera": None,
    "org": "college", "course": "",   # who is using the camera now (one session at a time)
}


def set_status(status, message):
    camera_state["status"], camera_state["message"] = status, message


def ascii_text(text):
    return text.encode("ascii", "replace").decode("ascii")


# ---------------- camera selection ----------------
_cam_cache = {"time": 0.0, "list": []}


def camera_label(index):
    try:
        return Path(f"/sys/class/video4linux/video{index}/name").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


_last_good = {"index": None}      # the camera that worked last time is tried first


def open_working(index):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if os.name == "nt" else cv2.VideoCapture(index)
    if cap.isOpened():
        if os.name == "nt":
            # Windows: asking for MJPG first makes 1280x720 open in well under a
            # second instead of several (raw video at that size is slow over USB).
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)     # always the newest frame, not an old queued one
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        for _ in range(3):
            okay, frame = cap.read()
            if okay and frame is not None:
                return cap
            time.sleep(0.15)
    cap.release()
    return None


def looks_infrared(frame):
    """Windows Hello IR cameras give a grey image. Colour channels are equal."""
    if frame is None or frame.ndim < 3:
        return True
    small = cv2.resize(frame, (64, 48)).astype(np.int16)
    if small.mean() < 25:  # a dark room also looks grey: don't call that infrared
        return False
    return float(np.abs(small[:, :, 0] - small[:, :, 1]).mean() + np.abs(small[:, :, 1] - small[:, :, 2]).mean()) < 2.0


def probe_cameras():
    found, missing = [], 0
    for i in range(MAX_CAMERA_INDEX):
        cap = open_working(i)
        if cap is None:
            missing += 1
            if missing >= 2 and i >= 1:     # numbers have no gaps in practice: stop early
                break
            continue
        missing = 0
        okay, frame = cap.read()
        cap.release()
        h, w = frame.shape[:2] if okay else (0, 0)
        found.append({"index": i, "name": camera_label(i) or ("Laptop camera" if i == 0 else f"Camera {i}"),
                      "builtin": i == 0, "width": w, "height": h, "infrared": bool(okay and looks_infrared(frame))})
    return found


def get_cameras(refresh=False):
    if camera_state["active"]:
        return _cam_cache["list"]
    if refresh or not _cam_cache["list"] or time.time() - _cam_cache["time"] > 60:
        _cam_cache.update(list=probe_cameras(), time=time.time())
    return _cam_cache["list"]


def pick_camera(setting):
    """(capture, index, note). 'default' = the laptop's own camera (index 0);
    if that fails, the first other colour camera. 'ip:<id>' = a saved IP camera."""
    note = ""
    if isinstance(setting, str) and setting.startswith("ip:"):
        import ipcams
        cam, url = ipcams.find(setting[3:])
        if not cam:
            raise RuntimeError("The chosen IP camera was deleted. Pick another camera on the Live camera page.")
        url = ipcams.bound_url(cam, url)     # same camera as when it was saved (MAC check)
        cap = ipcams.open_stream(url)
        if cap is None:
            raise RuntimeError(f"Couldn't connect to the IP camera '{cam['name']}'. Check that it is switched on "
                               "and on the same network, then use Test on the Camera links page.")
        return ipcams.LatestFrameReader(cap), setting, ""
    order = list(range(MAX_CAMERA_INDEX))
    if isinstance(setting, int):
        order = [setting] + [i for i in order if i != setting]
    elif _last_good["index"] is not None:     # "default": what worked last time first
        order = [_last_good["index"]] + [i for i in order if i != _last_good["index"]]
    infrared = None
    for n, i in enumerate(order):
        cap = open_working(i)
        if not cap:
            continue
        okay, frame = cap.read()
        if okay and looks_infrared(frame):
            cap.release()
            infrared = infrared if infrared is not None else i
            continue
        if n and isinstance(setting, int):
            note = f"Camera {setting} wasn't usable, so camera {i} is used."
        elif i != 0 and setting == "default":
            note = "The laptop camera didn't open, so another camera is used."
        _last_good["index"] = i
        return cap, i, note
    if infrared is not None:  # only an infrared camera: better than nothing
        cap = open_working(infrared)
        if cap:
            return cap, infrared, "Only an infrared (Windows Hello) camera was found. Recognition will be weaker."
    return None, None, note


# ---------------- face models (loaded once) ----------------
_models = {}
_models_lock = threading.Lock()


def face_models():
    """dlib's detector and landmark model, loaded once per server start (they are
    ~100 MB, so loading them at every Start was most of the wait)."""
    with _models_lock:
        if not _models:
            import dlib
            import face_recognition  # noqa: F401 - loads the recognition model too
            pred = config.predictor_path()
            if not pred:
                raise RuntimeError("Face landmark model missing. Run: pip install face_recognition_models")
            _models["detector"] = dlib.get_frontal_face_detector()
            _models["predictor"] = dlib.shape_predictor(pred)
        return _models["detector"], _models["predictor"]


def warm_up():
    """At server start, in the background: load the face models and look for cameras,
    so the first Start attendance doesn't wait for either."""
    def run():
        t0 = time.time()
        try:
            face_models()
        except (Exception, SystemExit) as exc:   # noqa: BLE001 - reported again when someone presses Start
            print(f"  Face models not loaded yet: {exc}")
            return
        if not camera_state["active"]:
            try:
                get_cameras(refresh=True)
            except Exception:   # noqa: BLE001 - no camera is fine (IP cameras / photos)
                pass
        print(f"  Camera ready ({time.time() - t0:.1f} s).")
    threading.Thread(target=run, daemon=True, name="camera-warm-up").start()


# ---------------- recognition loop ----------------
def load_known(course=""):
    """Encodings from the database; older students without one get it computed once.
    Only this organisation's students (IT Hub: only those in the course)."""
    import face_recognition
    encodings, names = [], []
    with db() as s:
        for st in attendance.org_students(s, course).order_by(Student.name):
            enc = None
            if st.face_encoding:
                enc = np.frombuffer(st.face_encoding, dtype=np.float64)
            elif st.photo_file and (config.KNOWN_FACES_DIR / st.photo_file).is_file():
                found = face_recognition.face_encodings(
                    face_recognition.load_image_file(str(config.KNOWN_FACES_DIR / st.photo_file)))
                if found:
                    enc = found[0]
                    st.face_encoding = enc.astype(np.float64).tobytes()
            if enc is not None and enc.shape == (128,):
                encodings.append(enc)
                names.append(st.name)
        # Extra photos (other angles, glasses, light): each is one more encoding
        # for the same name, so the closest one wins.
        from models import StudentFace
        allowed = set(names) | {st.name for st in attendance.org_students(s, course)}
        for face, name in (s.query(StudentFace, Student.name).join(Student, Student.id == StudentFace.student_id)
                           .filter(Student.org == current_org())):
            if name not in allowed:
                continue
            enc = np.frombuffer(face.encoding, dtype=np.float64)
            if enc.shape == (128,):
                encodings.append(enc)
                names.append(name)
    return encodings, names


def run_attendance_camera(course=""):
    cap = None
    day = attendance.today()
    session_open = False
    try:
        import face_recognition
        from imutils import face_utils
        from scipy.spatial import distance

        # Open the camera and load the faces at the same time (both take a moment).
        opened, org = {}, current_org()

        def open_cam():
            try:
                with as_org(org):     # a new thread doesn't inherit the organisation
                    opened["result"] = pick_camera(get_settings()["camera"])
            except Exception as exc:   # noqa: BLE001 - raised below, in this thread
                opened["error"] = exc
        opener = threading.Thread(target=open_cam, daemon=True)
        set_status("starting", "Opening the camera...")
        opener.start()
        detector, predictor = face_models()
        known_encodings, known_names = load_known(course)
        opener.join()
        if not known_names:
            if "result" in opened and opened["result"][0] is not None:
                opened["result"][0].release()
            raise RuntimeError("No usable student photos. Register students with a clear face first.")
        l_start, l_end = face_utils.FACIAL_LANDMARKS_IDXS["left_eye"]
        r_start, r_end = face_utils.FACIAL_LANDMARKS_IDXS["right_eye"]
        rng = random.SystemRandom()

        def ear(eye):
            a, b = distance.euclidean(eye[1], eye[5]), distance.euclidean(eye[2], eye[4])
            c = distance.euclidean(eye[0], eye[3])
            return (a + b) / (2.0 * c) if c else 1.0

        def mouth_ratio(shape):
            width = distance.euclidean(shape[60], shape[64])
            return distance.euclidean(shape[62], shape[66]) / width if width else 0.0

        def yaw_ratio(shape):
            span = float(shape[16][0] - shape[0][0])
            return (shape[30][0] - shape[0][0]) / span if span > 0 else 0.5

        def identify(frame, rect):
            small = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            loc = (max(rect.top() // 2, 0), rect.right() // 2, rect.bottom() // 2, max(rect.left() // 2, 0))
            encs = face_recognition.face_encodings(rgb, [loc])
            if not encs:
                return None
            dists = face_recognition.face_distance(known_encodings, encs[0])
            idx = int(np.argmin(dists))
            return known_names[idx] if dists[idx] < MATCH_DISTANCE else None

        already_marked = attendance.present_names(day, course)   # only Present counts as done

        liveness = get_settings().get("liveness_mode", "quick")
        if "error" in opened:
            raise opened["error"]
        cap, cam_index, cam_note = opened["result"]
        if cap is None:
            raise RuntimeError("No working camera found. Close other apps using it (Zoom, Teams) and try again.")
        if isinstance(cam_index, str):      # an IP camera
            import ipcams
            ipc, _ = ipcams.find(cam_index[3:])
            camera_state["camera"] = {"index": cam_index, "builtin": False, "ip": True, "note": cam_note,
                                      "name": f"{ipc['name']} ({'wired' if ipc.get('kind') == 'wired' else 'Wi-Fi'} IP camera)"}
        else:
            camera_state["camera"] = {"index": cam_index, "builtin": cam_index == 0,
                                      "name": camera_label(cam_index) or ("Laptop camera" if cam_index == 0 else f"Camera {cam_index}"),
                                      "note": cam_note}
        session_open = True

        state, who, plan, step, ref = "WAIT", None, [], 0, None
        prog, prompt_text = {}, ""
        steady_since = no_face_since = None
        attempt_start = step_start = verify_start = 0.0
        fails, lock_until, hold_until = 0, 0.0, 0.0

        def say(status, message, hold=0):
            nonlocal hold_until
            set_status(status, message)
            hold_until = time.time() + hold if hold else 0

        def begin_wait():
            nonlocal state, who, plan, step, steady_since, no_face_since
            state, who, plan, step = "WAIT", None, [], 0
            steady_since = no_face_since = None
            set_status("liveness", "Look straight at the camera.")

        def start_step():
            nonlocal step_start, prompt_text
            prog.clear()
            prog.update(armed=False, blinks=0, closed=False, hold=0)
            step_start = time.time()
            prompt_text = PROMPTS[plan[step]] if len(plan) == 1 else f"Step {step + 1} of {len(plan)}: {PROMPTS[plan[step]]}"
            set_status("challenge", prompt_text)

        def failed(reason):
            nonlocal fails, lock_until
            fails += 1
            begin_wait()
            if fails >= MAX_FAILS:
                lock_until = time.time() + LOCKOUT_SECONDS
                say("spoof", f"Too many failed checks. Wait {LOCKOUT_SECONDS} seconds.", LOCKOUT_SECONDS)
            else:
                say("spoof", reason, MESSAGE_HOLD)

        def mark(name):
            nonlocal fails
            stamp_ = datetime.now().strftime("%I:%M:%S %p")
            attendance.mark_present(day, name, stamp_, course=course)
            already_marked.add(name)
            camera_state["marked_count"] += 1
            camera_state["last_marked"] = name
            camera_state["recent"] = ([{"name": name, "time": stamp_}] + camera_state["recent"])[:12]
            fails = 0
            begin_wait()
            say("marked", f"{name} marked present.", MESSAGE_HOLD)

        begin_wait()
        while camera_state["active"]:
            okay, frame = cap.read()      # an IP camera reader waits up to 6 s for a frame
            if not okay:
                raise RuntimeError("Lost connection to the camera." + (" Check the IP camera's network." if isinstance(cam_index, str) else ""))
            frame = cv2.flip(frame, 1)
            if frame.shape[1] > 960:
                frame = cv2.resize(frame, (960, int(frame.shape[0] * 960 / frame.shape[1])))
            h, w = frame.shape[:2]
            now = time.time()

            if hold_until and now > hold_until:
                hold_until = 0
                if state == "WAIT":
                    set_status("liveness", "Look straight at the camera.")
            if lock_until and now > lock_until:
                lock_until, fails = 0.0, 0

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector(gray)

            if now < lock_until or (state == "WAIT" and hold_until):
                pass
            elif len(faces) == 0:
                steady_since = None
                if state != "WAIT":
                    no_face_since = no_face_since or now
                    if now - no_face_since > 1.5:
                        failed("Face lost during the check. Please try again.")
            elif len(faces) > 1:
                if state == "WAIT":
                    steady_since = None
                    set_status("liveness", "One person at a time, please.")
                else:
                    failed("More than one face in view. Please try again.")
            else:
                no_face_since = None
                face = faces[0]
                shape = face_utils.shape_to_np(predictor(gray, face))
                left_eye, right_eye = shape[l_start:l_end], shape[r_start:r_end]
                avg_ear = (ear(left_eye) + ear(right_eye)) / 2.0
                yaw, mouth = yaw_ratio(shape), mouth_ratio(shape)
                neutral = TURN_NEUTRAL[0] <= yaw <= TURN_NEUTRAL[1] and mouth <= MOUTH_CLOSED_MAX
                fw = face.width()
                center = ((face.left() + face.right()) / 2.0, (face.top() + face.bottom()) / 2.0)
                cv2.drawContours(frame, [cv2.convexHull(left_eye)], -1, (0, 255, 0), 1)
                cv2.drawContours(frame, [cv2.convexHull(right_eye)], -1, (0, 255, 0), 1)

                if state == "WAIT":
                    if fw < MIN_FACE_WIDTH:
                        steady_since = None
                        set_status("liveness", "Move closer to the camera.")
                    elif not neutral:
                        steady_since = None
                        set_status("liveness", "Look straight at the camera.")
                    else:
                        steady_since = steady_since or now
                        if now - steady_since >= NEUTRAL_HOLD:
                            set_status("recognizing", "Identifying face...")
                            name = identify(frame, face)
                            steady_since = None
                            if name is None:
                                say("unknown", "Face not recognised. Please try again.", MESSAGE_HOLD)
                            elif name in already_marked:
                                say("marked", f"{name} is already marked present.", MESSAGE_HOLD)
                            else:
                                who = name
                                plan = (["blink"] if liveness == "quick"          # quick: just blink twice
                                        else rng.sample(CHALLENGES, CHALLENGE_STEPS))  # secure: 2 random actions
                                step, ref, attempt_start = 0, (center[0], center[1], fw), now
                                state = "CHALLENGE"
                                start_step()

                elif state == "CHALLENGE":
                    ch = plan[step]
                    drifted = (abs(center[0] - ref[0]) > 0.8 * ref[2] or abs(center[1] - ref[1]) > 0.8 * ref[2]
                               or not 0.6 <= fw / ref[2] <= 1.6)
                    if drifted:
                        failed("Please stay in front of the camera and try again.")
                    elif now - attempt_start > ATTEMPT_TIMEOUT or (prog["armed"] and now - step_start > CHALLENGE_TIMEOUT):
                        failed("Time ran out. Please try again.")
                    elif not prog["armed"]:
                        if neutral:
                            prog["armed"], step_start = True, now
                            set_status("challenge", prompt_text)
                        else:
                            set_status("challenge", "Look straight ahead. Then: " + PROMPTS[ch].lower())
                    else:
                        turned_left, turned_right = yaw < TURN_LEFT_MAX, yaw > TURN_RIGHT_MIN
                        mouth_open = mouth > MOUTH_OPEN_MIN
                        if (turned_left and ch != "left") or (turned_right and ch != "right") or (mouth_open and ch != "mouth"):
                            failed("That was not the action asked for. Please try again.")
                        else:
                            done = False
                            if ch == "blink":
                                if avg_ear < EAR_THRESHOLD:
                                    prog["closed"] = True
                                elif prog["closed"]:
                                    prog["blinks"] += 1
                                    prog["closed"] = False
                                done = prog["blinks"] >= BLINKS_REQUIRED
                            else:
                                hit = {"left": turned_left, "right": turned_right, "mouth": mouth_open}[ch]
                                prog["hold"] = prog["hold"] + 1 if hit else 0
                                done = prog["hold"] >= HOLD_FRAMES
                            if done:
                                step += 1
                                if step < len(plan):
                                    start_step()
                                else:
                                    state, verify_start, steady_since = "VERIFY", now, None
                                    set_status("recognizing", "Look straight at the camera to finish.")
                else:
                    if now - verify_start > VERIFY_TIMEOUT:
                        failed("Verification timed out. Please try again.")
                    elif fw < MIN_FACE_WIDTH or not neutral:
                        steady_since = None
                    else:
                        steady_since = steady_since or now
                        if now - steady_since >= 0.4:
                            if identify(frame, face) == who:
                                mark(who)
                            else:
                                failed("The face changed during the check. Please try again.")

            cv2.rectangle(frame, (0, 0), (w, 46), (43, 27, 20), -1)
            cv2.putText(frame, ascii_text(camera_state["message"]), (12, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
            okay, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if okay:
                camera_state["jpeg"] = buf.tobytes()
                camera_state["frame_id"] += 1
            if time.time() - _lite["wanted"] < 5:      # someone is watching over the internet
                small = cv2.resize(frame, (LITE_WIDTH, int(h * LITE_WIDTH / w)), interpolation=cv2.INTER_AREA)
                okay, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 60])
                if okay:
                    _lite["jpeg"], _lite["id"] = buf.tobytes(), camera_state["frame_id"]

    except (Exception, SystemExit) as exc:   # face_recognition calls quit() when its models are missing
        msg = str(exc) if isinstance(exc, Exception) and str(exc) else (
            "The face models couldn't load. In the backend folder run: venv\\Scripts\\python.exe -m pip install \"setuptools<82\""
            if isinstance(exc, SystemExit) else exc.__class__.__name__)
        set_status("error", msg)
        print("Attendance camera error:", msg, flush=True)
    finally:
        if cap is not None:
            cap.release()
        if session_open:
            try:
                if uses_courses():   # IT Hub: only this course's students are marked absent
                    with db() as s:
                        ids = [st.id for st in attendance.org_students(s, course)]
                    attendance.finalize_students(day, ids, source="camera", course=course)
                else:
                    attendance.finalize_day(day)
                import notify
                org = current_org()

                def alerts():
                    with as_org(org):
                        notify.run_auto_alerts()
                threading.Thread(target=alerts, daemon=True).start()
            except Exception as exc:
                print("Could not save attendance:", exc)
        camera_state["jpeg"] = None
        _lite["jpeg"] = None
        if camera_state["status"] != "error":
            set_status("idle", "Camera stopped. Attendance saved.")
        camera_state["active"] = False


# ---------------- API ----------------
@bp.post("/start-attendance")
def start():
    global camera_thread
    import guard
    blocked = guard.check()        # proxy protection: approved device / college network / location
    if blocked:
        return blocked
    org = current_org()
    course = ""
    if uses_courses():   # IT Hub: attendance is taken for one course at a time
        from auth import scope
        course = str((request.get_json(silent=True) or {}).get("course") or "").strip()
        from courses import unit_allowed, valid_unit
        if not valid_unit(course):   # "Python · 4–6 PM" (or just "Python" while no batches are set up)
            return fail("Choose the course and batch you are taking attendance for.")
        sc = scope()
        if not unit_allowed(course, sc):
            if not sc:
                return fail("No course has been assigned to you yet. Ask the IT Hub admin.", 403)
            return fail(f"You can only take attendance for your own courses: {', '.join(sc)}.", 403)
    with state_lock:
        if camera_state["active"]:
            if camera_state["org"] != org:
                return fail(f"The camera is being used by {org_name(camera_state['org'])} right now. Try again later.")
            return fail("The camera is already running.")
        with db() as s:
            if not attendance.org_students(s, course).count():
                return fail(f"No students are registered in {course} yet." if course
                            else "Register at least one student first.")
        camera_state.update(active=True, jpeg=None, marked_count=0, last_marked=None, recent=[], camera=None,
                            org=org, course=course)
        set_status("starting", "Loading student faces...")

        def run():
            with as_org(org):   # the camera thread works for the organisation that started it
                run_attendance_camera(course)
        camera_thread = threading.Thread(target=run, daemon=True)
        camera_thread.start()
    return ok("Attendance camera started.", course=course)


def other_org_busy():
    """The camera is running for the other organisation: they mustn't see or stop it."""
    return camera_state["active"] and camera_state["org"] != current_org()


@bp.post("/stop-attendance")
def stop():
    if other_org_busy():
        return fail(f"The camera is being used by {org_name(camera_state['org'])}.", 403)
    camera_state["active"] = False
    thread = camera_thread
    if thread and thread.is_alive():
        thread.join(timeout=15)
    return ok("Camera stopped. Attendance saved.")


@bp.get("/camera-status")
def status():
    if other_org_busy():
        return ok(active=False, status="busy", busy=True, marked_count=0, last_marked=None, recent=[], camera=None,
                  message=f"The camera is being used by {org_name(camera_state['org'])} right now.")
    return ok(course=camera_state["course"], active=camera_state["active"], status=camera_state["status"], message=camera_state["message"],
              marked_count=camera_state["marked_count"], last_marked=camera_state["last_marked"],
              recent=visible_recent(), camera=camera_state["camera"])


def visible_recent():
    """Teachers only see the names of their own students in 'Marked this session'."""
    from auth import scope, scope_query
    if scope() is None:
        return list(camera_state["recent"])
    with db() as s:
        mine = {st.name for st in scope_query(s.query(Student))}
    return [r for r in camera_state["recent"] if r["name"] in mine]


# Viewers over the internet ask for one small picture at a time (see Live.jsx):
# each answer is the newest frame, so the picture can be slower but never falls behind.
LITE_WIDTH = 480
_lite = {"wanted": 0.0, "jpeg": None, "id": -1}


@bp.get("/camera-frame")
def camera_frame():
    if other_org_busy():
        return fail("The camera is being used by the other organisation.", 403)
    _lite["wanted"] = time.time()
    after = request.args.get("after", type=int, default=-1)
    deadline = time.time() + 3
    while camera_state["active"] and (_lite["jpeg"] is None or _lite["id"] == after) and time.time() < deadline:
        time.sleep(0.03)
    if not camera_state["active"] or _lite["jpeg"] is None:
        return Response(status=204)
    resp = Response(_lite["jpeg"], mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Frame-Id"] = str(_lite["id"])
    return resp


@bp.get("/video-feed")
def video_feed():
    if other_org_busy():
        return fail("The camera is being used by the other organisation.", 403)

    def generate():
        last_id = -1
        while camera_state["active"]:
            jpeg, frame_id = camera_state["jpeg"], camera_state["frame_id"]
            if jpeg is None or frame_id == last_id:
                time.sleep(0.03)
                continue
            last_id = frame_id
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

    resp = Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.get("/liveness-mode")
def get_liveness():
    return ok(mode=get_settings().get("liveness_mode", "quick"))


@bp.post("/liveness-mode")
def set_liveness():
    mode = (request.get_json(silent=True) or {}).get("mode")
    if mode not in ("quick", "secure"):
        return fail("Choose quick or secure.")
    if camera_state["active"]:
        return fail("Stop the camera first, then change this.")
    update_settings(liveness_mode=mode)
    return ok("Quick: students blink twice." if mode == "quick" else "Secure: students do 2 random actions.", mode=mode)


@bp.get("/cameras")
def cameras():
    import ipcams
    cams = get_cameras(refresh=request.args.get("refresh") == "1")
    ip = [{"index": c["value"], "name": c["name"], "kind": c["kind"], "ip": True} for c in map(ipcams.cam_json, ipcams.saved())]
    return ok(cameras=cams + ip, selected=get_settings()["camera"], busy=camera_state["active"])


@bp.post("/camera-source")
def camera_source():
    value = (request.get_json(silent=True) or {}).get("camera", "default")
    if isinstance(value, str) and value.startswith("ip:"):
        import ipcams
        if not ipcams.find(value[3:])[0]:
            return fail("That IP camera isn't saved.")
    elif value != "default":
        try:
            value = int(value)
        except (TypeError, ValueError):
            return fail("Invalid camera.")
        if not 0 <= value < MAX_CAMERA_INDEX:
            return fail("Invalid camera.")
    update_settings(camera=value)
    return ok("Camera choice saved")

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import StudentForm, { EMPTY_STUDENT, formProblems } from "../StudentForm";
import { isHub, unitBatch, unitCourse } from "../org";
import { Field, Icon, PageHead, Tick } from "../ui";

// Several photos = better recognition. The first one is the main photo.
export const ANGLES = ["Looking straight", "Turned a little left", "Turned a little right", "With glasses (if worn)", "Other light"];
const MAX_PHOTOS = ANGLES.length;

export const shrink = (url, max = 960) => new Promise((resolve) => {
  const img = new Image();
  img.onload = () => {
    const s = Math.min(1, max / Math.max(img.width, img.height));
    const c = document.createElement("canvas");
    c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    resolve(c.toDataURL("image/jpeg", 0.92));
  };
  img.onerror = () => resolve(null);
  img.src = url;
});

export default function RegisterPage({ camActive, onSaved, toast, askConfirm, branches, classes, countryCode, course }) {
  const [name, setName] = useState("");
  // IT Hub: start with the course picked in the sidebar ticked
  // IT Hub: start with the course and batch picked in the menu ticked
  const [details, setDetails] = useState(() => (isHub() && course
    ? { ...EMPTY_STUDENT, courses: [unitCourse(course)], batches: unitBatch(course) ? { [unitCourse(course)]: unitBatch(course) } : {} }
    : EMPTY_STUDENT));
  const [consent, setConsent] = useState(false);
  const [live, setLive] = useState(false);
  const [shots, setShots] = useState([]);          // [{ src, label }]
  const [saving, setSaving] = useState(false);
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [lastSaved, setLastSaved] = useState("");
  const video = useRef(null);
  const stream = useRef(null);
  const fileRef = useRef(null);
  const nameRef = useRef(null);

  const stopStream = useCallback(() => {
    if (stream.current) stream.current.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setLive(false);
  }, []);
  useEffect(() => () => { if (stream.current) stream.current.getTracks().forEach((t) => t.stop()); }, []);
  useEffect(() => {
    if (live && video.current && stream.current) video.current.srcObject = stream.current;
  }, [live, deviceId]);

  // The laptop's own camera is the default. Other cameras can be picked from the list.
  const openCam = async (id) => {
    if (!navigator.mediaDevices?.getUserMedia) { toast("This browser can't open the camera. Upload photos instead.", "bad"); return; }
    try {
      if (stream.current) stream.current.getTracks().forEach((t) => t.stop());
      const s = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, ...(id ? { deviceId: { exact: id } } : { facingMode: "user" }) },
        audio: false,
      });
      stream.current = s;
      setDevices((await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput"));
      setDeviceId(s.getVideoTracks()[0].getSettings().deviceId || id || "");
      setLive(true);
    } catch {
      toast("Camera access was blocked or the camera is busy. Allow it in the browser, or upload photos.", "bad");
    }
  };

  const nextLabel = ANGLES[shots.length] || "Extra photo";
  const addShot = (src) => setShots((list) => (list.length >= MAX_PHOTOS ? list : [...list, { src, label: ANGLES[list.length] || "" }]));

  const capture = () => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    const c = document.createElement("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    const ctx = c.getContext("2d");
    ctx.translate(c.width, 0); ctx.scale(-1, 1); // mirrored, like the live attendance feed
    ctx.drawImage(v, 0, 0);
    addShot(c.toDataURL("image/jpeg", 0.92));
    if (shots.length + 1 >= MAX_PHOTOS) stopStream();   // camera stays on for the next angle
  };

  const onFiles = async (e) => {
    const files = [...(e.target.files || [])].slice(0, MAX_PHOTOS - shots.length);
    e.target.value = "";
    for (const file of files) {
      const url = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(file); });
      const small = await shrink(url);
      if (small) addShot(small); else toast(`${file.name} isn't a readable image.`, "bad");
    }
  };

  const removeShot = (i) => setShots((list) => list.filter((_, j) => j !== i).map((s, j) => ({ ...s, label: ANGLES[j] || "" })));

  const problems = formProblems(details);
  const missing = !name.trim() ? "Enter the student's name." : Object.keys(problems).length ? "Fix the highlighted fields."
    : !shots.length ? "Take or upload at least one photo." : !consent ? "Tick the consent box." : "";

  const save = async (overwrite = false) => {
    if (missing) { toast(missing, "bad"); if (!name.trim()) nameRef.current?.focus(); return; }
    const clean = name.trim();
    setSaving(true);
    const r = await api.post("/register", { name: clean, image: shots[0].src, overwrite, details, consent });
    if (r.exists) {
      setSaving(false);
      askConfirm({ title: `Replace ${clean}'s photo?`, body: "This student is already registered. Saving replaces their main photo and adds the other photos.", label: "Replace photo", onYes: () => save(true) });
      return;
    }
    if (!r.success) { setSaving(false); toast(r.message || "Couldn't save the student.", "bad"); return; }
    // The other angles are checked one by one: each must be the same person.
    const skipped = [];
    for (const shot of shots.slice(1)) {
      const x = await api.post(`/students/${r.id}/faces`, { image: shot.src, label: shot.label });
      if (!x.success) skipped.push(`${shot.label}: ${x.message}`);
    }
    setSaving(false);
    const added = shots.length - skipped.length;
    toast(`${clean} registered with ${added} photo${added === 1 ? "" : "s"}.`);
    if (skipped.length) toast(`Skipped ${skipped.length}: ${skipped.join(" ")}`, "bad");
    setLastSaved(clean);
    // Keep branch and semester: the next student is usually in the same class.
    setName(""); setDetails({ ...EMPTY_STUDENT, branch: details.branch, courses: details.courses || [], batches: details.batches || {}, class_name: details.class_name });
    setConsent(false); setShots([]); stopStream();
    onSaved();
    window.scrollTo(0, 0);
    nameRef.current?.focus();
  };

  const steps = [
    { t: "Name and details", done: !!name.trim() && !Object.keys(problems).length },
    { t: "Photos of the face (3 or more is best)", done: shots.length >= 3, part: shots.length > 0 },
    { t: "Consent form collected", done: consent },
  ];
  const latest = shots[shots.length - 1];

  return (
    <>
      <PageHead title="Register a student" sub="Only the name, one photo and consent are needed. More photos from different angles make recognition more reliable." />
      {lastSaved && <p className="say saved-note"><Tick size={16} /> {lastSaved} was saved. {isHub() ? "Courses and batch timings" : "Branch and semester"} are kept for the next student.</p>}
      <div className="reg register">
        <section className="panel reg-form">
          <Field id="stu-name" label="Student's full name *" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Dhanish Kumar" maxLength={60} autoComplete="off" ref={nameRef} autoFocus />
          <StudentForm value={details} onChange={setDetails} prefix="reg" branches={branches} classes={classes} countryCode={countryCode} />
          <label className="check consent">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
            <span>I have collected the signed consent form for storing this student's face (needed for anyone under 18 from a parent).</span>
          </label>
        </section>

        <div className="reg-side">
          <div className="stage">
            {live && <video ref={video} className="mirror" autoPlay playsInline muted />}
            {!live && latest && <img src={latest.src} alt={`Photo: ${latest.label}`} />}
            {!live && !latest && <div className="stage-empty"><Icon name="camera" size={44} /><p>The camera is off</p></div>}
            {live && (
              <>
                <svg className="guide" viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" aria-hidden="true"><ellipse cx="200" cy="140" rx="82" ry="108" /></svg>
                <span className="stage-hint">Photo {shots.length + 1}: {nextLabel.toLowerCase()}</span>
              </>
            )}
          </div>

          {shots.length > 0 && (
            <ul className="shots" aria-label="Photos taken">
              {shots.map((s, i) => (
                <li key={i}>
                  <img src={s.src} alt="" />
                  <span>{i === 0 ? "Main" : s.label}</span>
                  <button className="icon-btn" aria-label={`Remove photo ${i + 1}`} onClick={() => removeShot(i)}><Icon name="x" size={14} /></button>
                </li>
              ))}
            </ul>
          )}

          <section className="panel pad side-tools">
            {camActive && <p className="note">The attendance camera is running. Stop it to use the webcam here, or upload photos.</p>}
            {live && devices.length > 1 && (
              <div className="field">
                <label htmlFor="cam-sel">Camera</label>
                <select id="cam-sel" value={deviceId} onChange={(e) => openCam(e.target.value)}>
                  {devices.map((d, i) => <option key={d.deviceId} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
                </select>
              </div>
            )}
            <div className="btn-row two">
              {live
                ? <button className="btn primary" onClick={capture}><Icon name="camera" />Capture: {nextLabel.split(" (")[0].toLowerCase()}</button>
                : <button className="btn ghost" onClick={() => openCam()} disabled={camActive || shots.length >= MAX_PHOTOS}>
                  <Icon name="camera" />{shots.length ? "Add another angle" : "Turn on camera"}</button>}
              {live && shots.length > 0
                ? <button className="btn ghost" onClick={stopStream}><Icon name="check" />Done with photos</button>
                : <button className="btn ghost" onClick={() => fileRef.current?.click()} disabled={shots.length >= MAX_PHOTOS}><Icon name="upload" />Upload photos</button>}
              <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={onFiles} />
            </div>
            <ol className="steps">
              {steps.map((s, i) => (
                <li key={s.t} className={s.done ? "done" : s.part ? "now" : ""}>
                  <span className="n">{s.done ? <Tick size={14} /> : i + 1}</span>{s.t}{i === 1 && shots.length > 0 && !s.done ? ` (${shots.length} so far)` : ""}
                </li>
              ))}
            </ol>
            <button className="btn primary wide" onClick={() => save(false)} disabled={saving}>
              <Icon name="check" />{saving ? "Checking the faces…" : "Save student"}
            </button>
            {missing && <p className="muted small center">{missing}</p>}
          </section>
        </div>
      </div>
    </>
  );
}

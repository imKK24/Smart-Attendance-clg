// Attendance from class photos taken on the teacher's phone.
// 1. add photos  2. the app finds and names faces  3. teacher checks the list  4. save (photos kept as evidence)
import { useEffect, useMemo, useRef, useState } from "react";
import { api, mediaUrl, prepareAttendance } from "../api";
import { isHub, unit, unitLower } from "../org";
import { Face, Icon, Tick } from "../ui";
import { fmt, isoToday, plural } from "../util";

const MAX = 5;

function PhotoWithBoxes({ session, index, students, present, onPick }) {
  const faces = session.faces.filter((f) => f.photo === index);
  const [sel, setSel] = useState(null);
  return (
    <div className="pa-photo">
      <img src={mediaUrl(`/photo-attendance/${session.id}/photo/${index + 1}`)} alt={`Class photo ${index + 1}`} />
      {faces.map((f, i) => {
        const [top, right, bottom, left] = f.box;
        const cls = f.student_id ? (present.has(f.student_id) ? "ok" : "off") : f.small ? "small" : "unknown";
        return (
          <button key={i} className={`pa-box ${cls}${sel === i ? " sel" : ""}`} style={{ top: `${top * 100}%`, left: `${left * 100}%`, width: `${(right - left) * 100}%`, height: `${(bottom - top) * 100}%` }}
            onClick={() => setSel(sel === i ? null : i)} aria-label={f.name ? `${f.name}, ${f.confidence}% sure` : "Not recognised. Choose who this is."}>
            <span>{f.name ? `${f.name.split(" ")[0]} ${f.confidence}%` : f.small ? "Too small" : "?"}</span>
          </button>
        );
      })}
      {sel != null && (
        <div className="pa-assign">
          <label htmlFor="pa-who">Who is this?</label>
          <select id="pa-who" autoFocus defaultValue="" onChange={(e) => { if (e.target.value) onPick(Number(e.target.value)); setSel(null); }}>
            <option value="">Choose a student</option>
            {students.filter((s) => !present.has(s.id)).map((s) => <option key={s.id} value={s.id}>{s.name}{s.roll_no ? ` (${s.roll_no})` : ""}</option>)}
          </select>
          <button className="icon-btn" aria-label="Close" onClick={() => setSel(null)}><Icon name="x" size={14} /></button>
        </div>
      )}
    </div>
  );
}

function Review({ session, ids, toast, onDone, onCancel }) {
  const [present, setPresent] = useState(() => new Set(session.students.filter((s) => s.found || s.already === "Present").map((s) => s.id)));
  const [photo, setPhoto] = useState(0);
  const [saving, setSaving] = useState(false);
  const toggle = (id) => setPresent((p) => { const n = new Set(p); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const unknown = session.faces.filter((f) => !f.student_id).length;
  const save = async () => {
    setSaving(true);
    const where = await prepareAttendance();
    if (where) { setSaving(false); toast(where, "bad"); return; }
    const r = await api.post(`/photo-attendance/${session.id}/save`, { present_ids: [...present] });
    setSaving(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) onDone(present.size, session.students.length);
  };
  return (
    <div className="pa-review">
      <section className="panel pad">
        {session.photos > 1 && (
          <div className="seg pa-tabs" role="group" aria-label="Photo">
            {Array.from({ length: session.photos }, (_, i) => (
              <button key={i} className={photo === i ? "on" : ""} aria-pressed={photo === i} onClick={() => setPhoto(i)}>Photo {i + 1}</button>
            ))}
          </div>
        )}
        <PhotoWithBoxes session={session} index={photo} students={session.students} present={present} onPick={(id) => setPresent((p) => new Set(p).add(id))} />
        <p className="muted small pa-legend">
          <span className="key ok" /> recognised <span className="key unknown" /> not recognised, tap it to choose who it is <span className="key small" /> too small to be sure
        </p>
      </section>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>{present.size} of {session.students.length} present</h2>
            <p className="muted small">{fmt(session.day, { weekday: "long", day: "numeric", month: "long" })}{session.branch ? ` · ${session.branch}` : ""}
              {unknown ? ` · ${plural(unknown, "face")} not recognised` : ""}</p>
          </div>
        </div>
        <ul className="pa-list">
          {session.students.map((s) => (
            <li key={s.id}>
              <label className={`check${present.has(s.id) ? " on" : ""}`}>
                <input type="checkbox" checked={present.has(s.id)} onChange={() => toggle(s.id)} />
                <Face name={s.name} id={ids[s.name]} size={32} />
                <span className="pa-name">{s.name}<small>{s.roll_no}</small></span>
                {s.found && <span className="chip ok tiny"><Tick size={12} /> In photo</span>}
                {!s.found && s.already === "Present" && <span className="chip ok tiny">Already present</span>}
                {s.on_leave && <span className="chip warn tiny">On leave</span>}
                {!s.has_face && <span className="chip warn tiny">No face photo</span>}
              </label>
            </li>
          ))}
        </ul>
        <div className="pad pa-actions">
          <button className="btn ghost" onClick={onCancel} disabled={saving}>Start again</button>
          <button className="btn primary" onClick={save} disabled={saving}><Icon name="check" />{saving ? "Saving…" : `Save attendance (${present.size} present)`}</button>
        </div>
      </section>
    </div>
  );
}

export default function PhotoAttendance({ branches, ids, toast, onSaved, course }) {
  const [day, setDay] = useState(isoToday());
  const [branch, setBranch] = useState("");
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [session, setSession] = useState(null);
  const [done, setDone] = useState(null);
  const camRef = useRef(null);
  const galleryRef = useRef(null);
  const previews = useMemo(() => files.map((f) => URL.createObjectURL(f)), [files]);
  useEffect(() => () => previews.forEach((u) => URL.revokeObjectURL(u)), [previews]);
  useEffect(() => { if (!branch && branches.length === 1) setBranch(branches[0]); }, [branches, branch]);
  useEffect(() => { if (isHub() && course) setBranch(course); }, [course]);   // IT Hub: the course picked on the left

  const add = (e) => { const list = [...(e.target.files || [])]; e.target.value = ""; setFiles((f) => [...f, ...list].slice(0, MAX)); };
  const analyze = async () => {
    const form = new FormData();
    form.append("day", day);
    form.append("branch", branch);
    files.forEach((f) => form.append("photos", f));
    setBusy(true);
    const where = await prepareAttendance();          // location, if the admin's proxy protection needs it
    if (where) { setBusy(false); toast(where, "bad"); return; }
    const r = await api.form("/photo-attendance/analyze", form);
    setBusy(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) setSession(r.session);
  };
  const reset = () => { setSession(null); setFiles([]); setDone(null); };

  if (done) {
    return (
      <section className="panel pad pa-done">
        <span className="pa-done-icon"><Tick size={28} /></span>
        <h2 className="h2">Attendance saved</h2>
        <p>{done.present} of {done.total} present. The photos are kept with the day's register as evidence.</p>
        <button className="btn primary" onClick={reset}><Icon name="camera" />Take another class</button>
      </section>
    );
  }
  if (session) return <Review session={session} ids={ids} toast={toast} onCancel={reset} onDone={(present, total) => { setDone({ present, total }); onSaved(); }} />;

  return (
    <div className="reg">
      <section className="panel pad reg-form">
        <h2 className="h2">Class photo</h2>
        <div className="fields">
          <div className="field"><label htmlFor="pa-day">Date</label><input id="pa-day" type="date" value={day} max={isoToday()} onChange={(e) => setDay(e.target.value)} /></div>
          <div className="field"><label htmlFor="pa-branch">{unit()}</label>
            <select id="pa-branch" value={branch} onChange={(e) => setBranch(e.target.value)}>
              {branches.length !== 1 && !isHub() && <option value="">All students</option>}
              {branches.map((b) => <option key={b}>{b}</option>)}
            </select>
          </div>
        </div>
        <div className="btn-row two">
          <button className="btn ghost" onClick={() => camRef.current?.click()} disabled={files.length >= MAX}><Icon name="camera" />Take photo</button>
          <button className="btn ghost" onClick={() => galleryRef.current?.click()} disabled={files.length >= MAX}><Icon name="upload" />Choose photos</button>
          <input ref={camRef} type="file" accept="image/*" capture="environment" hidden onChange={add} />
          <input ref={galleryRef} type="file" accept="image/*" multiple hidden onChange={add} />
        </div>
        {files.length > 0 && (
          <ul className="shots" aria-label="Photos to check">
            {previews.map((u, i) => (
              <li key={u}><img src={u} alt="" /><span>Photo {i + 1}</span>
                <button className="icon-btn" aria-label={`Remove photo ${i + 1}`} onClick={() => setFiles((f) => f.filter((_, j) => j !== i))}><Icon name="x" size={14} /></button>
              </li>
            ))}
          </ul>
        )}
        <button className="btn primary wide" disabled={!files.length || busy} onClick={analyze}>
          <Icon name="search" />{busy ? `Finding faces in ${plural(files.length, "photo")}…` : "Find students in the photos"}
        </button>
        {busy && <p className="muted small center">This takes about 5–15 seconds per photo.</p>}
      </section>
      <section className="panel pad help">
        <h2 className="h2">For the best result</h2>
        <ul className="bullets">
          <li>Ask everyone to look at the phone for a second. Turned or hidden faces are missed.</li>
          <li>Take <strong>2–3 photos</strong> in a big class: front rows, then back rows. Up to {MAX} at a time.</li>
          <li>Stand at the front, phone held up at head height, light behind you, not behind the students.</li>
          <li>Upload the original photo from the phone. A photo forwarded on WhatsApp is compressed and loses detail.</li>
          <li>You'll check the list before anything is saved. Faces the app isn't sure about are marked.</li>
        </ul>
        <p className="muted small">The saved photos show the whole class. They're visible only to admins and teachers of that {unitLower()}.</p>
      </section>
    </div>
  );
}

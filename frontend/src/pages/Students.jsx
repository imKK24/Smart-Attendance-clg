import { useEffect, useRef, useState } from "react";
import { api, mediaUrl } from "../api";
import StudentForm, { formProblems, pickStudent } from "../StudentForm";
import { coursesText, isHub } from "../org";
import { BranchSelect, Chip, Face, Icon, Modal, PageHead, SearchBox } from "../ui";
import { ANGLES, shrink } from "./Register";

// Extra photos (other angles, glasses, light) improve recognition.
function PhotoManager({ student, toast }) {
  const [faces, setFaces] = useState(null);
  const [max, setMax] = useState(6);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);
  const load = async () => { const r = await api.get(`/students/${student.id}/faces`); if (r.success) { setFaces(r.faces); setMax(r.max); } };
  useEffect(() => { load(); }, [student.id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!faces) return null;
  const add = async (e) => {
    const files = [...(e.target.files || [])].slice(0, max - faces.length);
    e.target.value = "";
    setBusy(true);
    for (const [i, file] of files.entries()) {
      const url = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(file); });
      const small = await shrink(url);
      const r = small ? await api.post(`/students/${student.id}/faces`, { image: small, label: ANGLES[faces.length + i + 1] || "Extra photo" })
        : { success: false, message: "Not a readable image." };
      if (!r.success) toast(`${file.name}: ${r.message}`, "bad");
    }
    setBusy(false);
    load();
  };
  const remove = async (fid) => { const r = await api.del(`/students/${student.id}/faces/${fid}`); toast(r.message, r.success ? "ok" : "bad"); load(); };
  return (
    <section>
      <h3 className="h3">Face photos <span className="muted small">({faces.length + 1}, 3 or more is best)</span></h3>
      <ul className="shots in-profile">
        <li><Face name={student.name} id={student.id} size={72} /><span>Main</span></li>
        {faces.map((f) => (
          <li key={f.id}>
            <img src={mediaUrl(`/students/${student.id}/faces/${f.id}/photo`)} alt="" />
            <span>{f.label || "Extra"}</span>
            <button className="icon-btn" aria-label={`Remove ${f.label || "photo"}`} onClick={() => remove(f.id)}><Icon name="x" size={14} /></button>
          </li>
        ))}
        {faces.length < max && (
          <li><button className="add-shot" onClick={() => fileRef.current?.click()} disabled={busy} aria-label="Add photos">
            <Icon name="plus" />{busy ? "Checking…" : "Add"}</button></li>
        )}
      </ul>
      <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={add} />
    </section>
  );
}
import { fmtStamp } from "../util";

function Profile({ student, onClose, onSave, branches, classes, countryCode, toast }) {
  const [editing, setEditing] = useState(false);
  const [d, setD] = useState(pickStudent(student));
  const [saving, setSaving] = useState(false);
  const bad = Object.keys(formProblems(d)).length > 0;
  const save = async () => { setSaving(true); const done = await onSave(student.id, d); setSaving(false); if (done) setEditing(false); };
  const s = student;
  const row = (label, value) => value ? <><dt>{label}</dt><dd>{value}</dd></> : null;
  return (
    <Modal onClose={onClose} wide labelledBy="pf-title">
      <div className="dialog-top">
        <Face name={s.name} id={s.id} size={64} />
        <div>
          <h2 id="pf-title">{s.name}</h2>
          <p>{[s.roll_no && `Reg. ${s.roll_no}`, isHub() ? coursesText(s) : s.branch, isHub() ? "" : s.class_name].filter(Boolean).join(" · ") || "No class details yet"}</p>
        </div>
      </div>
      {editing ? (
        <StudentForm value={d} onChange={setD} prefix="edit" branches={branches} classes={classes} countryCode={countryCode} />
      ) : (
        <div className="profile">
          <dl className="kv">
            {row("Parent", [s.parent_name, s.parent_relation && `(${s.parent_relation})`].filter(Boolean).join(" "))}
            {row("WhatsApp", s.parent_phone && <a href={`https://wa.me/${s.parent_phone.replace("+", "")}`} target="_blank" rel="noreferrer">{s.parent_phone}</a>)}
            {row("Parent email", s.parent_email && <a href={`mailto:${s.parent_email}`}>{s.parent_email}</a>)}
            {row("Other phone", s.alt_phone && <a href={`tel:${s.alt_phone}`}>{s.alt_phone}</a>)}
            {row("Student phone", s.student_phone)}
            {row("Student email", s.student_email)}
            {row("Address", s.address && <span className="pre">{s.address}</span>)}
            {row("Face registered", fmtStamp(s.registered_at))}
          </dl>
          <PhotoManager student={s} toast={toast} />
          {s.qualifications.length > 0 && (
            <>
              <h3 className="h3">Qualifications</h3>
              <table className="mini">
                <thead><tr><th>Course</th><th>Board / university</th><th>Year</th><th>Score</th></tr></thead>
                <tbody>{s.qualifications.map((q, i) => <tr key={i}><td>{q.course}</td><td>{q.board}</td><td>{q.year}</td><td>{q.score}</td></tr>)}</tbody>
              </table>
            </>
          )}
          {s.achievements.length > 0 && (
            <>
              <h3 className="h3">Achievements</h3>
              <ul className="ach">{s.achievements.map((a, i) => <li key={i}><strong>{a.title}</strong>{a.year && <span className="muted"> · {a.year}</span>}{a.details && <p>{a.details}</p>}</li>)}</ul>
            </>
          )}
        </div>
      )}
      <div className="dialog-actions">
        {editing ? (
          <>
            <button className="btn ghost" onClick={() => { setD(pickStudent(student)); setEditing(false); }}>Cancel</button>
            <button className="btn primary" onClick={save} disabled={saving || bad}>{saving ? "Saving…" : "Save details"}</button>
          </>
        ) : (
          <>
            <button className="btn ghost" onClick={onClose}>Close</button>
            <button className="btn primary" onClick={() => setEditing(true)}><Icon name="edit" size={18} />Edit details</button>
          </>
        )}
      </div>
    </Modal>
  );
}

export default function StudentsPage({ students, loading, today, askConfirm, onDelete, onUpdate, go, branches, classes, countryCode, toast, isAdmin, course }) {
  const hub = isHub();
  const [q, setQ] = useState("");
  const [branch, setBranch] = useState(hub ? course || "" : "");   // IT Hub: start with the course picked on the left
  const [open, setOpen] = useState(null);
  const status = Object.fromEntries((today?.records ?? []).map((r) => [r.Name, r.Status]));
  const needle = q.trim().toLowerCase();
  const list = students.filter((s) => (!branch || (hub ? (s.units || s.courses || []).includes(branch) : s.branch === branch)) &&
    (s.name.toLowerCase().includes(needle) || s.roll_no.toLowerCase().includes(needle)));
  const current = students.find((s) => s.id === open);
  return (
    <>
      <PageHead title="Students" sub={`${students.length} registered. Click a card to see or edit their details.`}>
        <BranchSelect value={branch} onChange={setBranch} branches={branches} />
        <SearchBox value={q} onChange={setQ} placeholder="Search name or registration no" />
        <button className="btn primary" onClick={() => go("register")}><Icon name="plus" />Register student</button>
      </PageHead>
      {loading ? <p className="empty">Loading students…</p> : list.length === 0 ? (
        <section className="panel"><div className="empty">
          <p>{students.length ? "No student matches that search." : "No students yet. Add the first one to get started."}</p>
          {!students.length && <button className="btn primary" onClick={() => go("register")}><Icon name="plus" />Register a student</button>}
        </div></section>
      ) : (
        <div className="id-grid">
          {list.map((s) => (
            <article key={s.id} className="id-card">
              <div className="id-photo">
                <Face name={s.name} id={s.id} fill />
                <div className="id-actions">
                  {isAdmin && <button className="icon-btn" aria-label={`Remove ${s.name}`} onClick={() => askConfirm({
                    title: `Remove ${s.name}?`,
                    body: "Everything about this student is erased: details, all photos, attendance history (also in the saved registers and Excel copies), fees, leave, results and messages. This cannot be undone. Download any register you need first.",
                    label: "Remove student", danger: true, onYes: () => onDelete(s.id),
                  })}><Icon name="trash" size={18} /></button>}
                </div>
              </div>
              <button className="id-body as-card" onClick={() => setOpen(s.id)}>
                <h3>{s.name}</h3>
                <p>{[s.roll_no, hub ? coursesText(s) : s.branch, hub ? "" : s.class_name].filter(Boolean).join(" · ")
                  || (hub ? "Add registration no and courses" : "Add registration no and branch")}</p>
                {s.parent_name && <p>Parent: {s.parent_name}</p>}
                <span className="chips">
                  {status[s.name] && <Chip status={status[s.name]} />}
                  {!s.parent_phone && !s.parent_email && <span className="chip warn">No parent contact</span>}
                </span>
              </button>
            </article>
          ))}
        </div>
      )}
      {current && <Profile key={current.id + current.updated_at} student={current} onClose={() => setOpen(null)} onSave={onUpdate}
        branches={branches} classes={classes} countryCode={countryCode} toast={toast} />}
    </>
  );
}

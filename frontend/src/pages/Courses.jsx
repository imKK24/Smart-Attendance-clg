// Aakansha IT Hub: the course catalogue. Admins add courses with a picture, price,
// duration and description; everyone sees the cards. Course names are what students
// join and what attendance, tests and fees are kept by.
import { useEffect, useRef, useState } from "react";
import { api, mediaUrl } from "../api";
import { Field, Icon, Modal, PageHead } from "../ui";
import { inr } from "./Fees";

const EMPTY = { name: "", price: "", duration: "", description: "", active: true };

function CourseForm({ course, onClose, onSaved, toast }) {
  const [f, setF] = useState(course ? { name: course.name, price: String(course.price ?? ""), duration: course.duration,
    description: course.description, active: course.active } : EMPTY);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(course?.has_image ? mediaUrl(`/courses/${course.id}/image`, `&v=${course.image_v}`) : "");
  const [removeImage, setRemoveImage] = useState(false);
  const [saving, setSaving] = useState(false);
  const fileRef = useRef(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  useEffect(() => () => { if (preview.startsWith("blob:")) URL.revokeObjectURL(preview); }, [preview]);

  const pick = (e) => {
    const x = e.target.files?.[0];
    if (!x) return;
    setFile(x); setRemoveImage(false); setPreview(URL.createObjectURL(x));
  };
  const save = async (e) => {
    e.preventDefault();
    const body = new FormData();
    Object.entries({ ...f, price: f.price || "0", active: f.active ? "1" : "0" }).forEach(([k, v]) => body.append(k, v));
    if (file) body.append("image", file);
    if (removeImage) body.append("remove_image", "1");
    setSaving(true);
    const r = course ? await api.formPut(`/courses/${course.id}`, body) : await api.form("/courses", body);
    setSaving(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { onSaved(); onClose(); }
  };

  return (
    <Modal title={course ? `Edit ${course.name}` : "Add a course"} onClose={onClose} wide>
      <form className="course-form" onSubmit={save}>
        <div className="course-pic-edit">
          {preview && !removeImage ? <img src={preview} alt="" /> : <div className="course-pic-empty"><Icon name="image" size={30} /><span>No picture</span></div>}
          <div className="row-btns">
            <button type="button" className="btn ghost" onClick={() => fileRef.current?.click()}><Icon name="upload" size={18} />{preview && !removeImage ? "Change picture" : "Add picture"}</button>
            {preview && !removeImage && <button type="button" className="btn ghost" onClick={() => { setRemoveImage(true); setFile(null); }}>Remove</button>}
          </div>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" hidden onChange={pick} />
          <small className="muted">JPG or PNG, up to 6 MB. A wide picture (landscape) looks best.</small>
        </div>
        <div className="fields">
          <Field id="co-name" wide label="Course name" value={f.name} onChange={set("name")} required maxLength={60} placeholder="e.g. Python programming" autoFocus
            hint={course ? "Renaming keeps its students, attendance, tests and fees." : undefined} />
          <Field id="co-price" label="Price (₹)" type="number" min={0} step="any" inputMode="decimal" value={f.price} onChange={set("price")} placeholder="e.g. 6000"
            hint="Used as the amount when you add this course's fee." />
          <Field id="co-dur" label="Duration" value={f.duration} onChange={set("duration")} maxLength={40} placeholder="e.g. 3 months" />
          <Field id="co-desc" wide as="textarea" rows={5} label="Description" value={f.description} onChange={set("description")} maxLength={2000}
            placeholder="What students learn, who it's for, timings…" />
          <label className="check wide"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} />
            Open for new students <span className="muted small">(switched off: hidden when registering; old records stay)</span></label>
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={saving || !f.name.trim()}>{saving ? "Saving…" : course ? "Save changes" : "Add course"}</button>
        </div>
      </form>
    </Modal>
  );
}

// The batch timings students can be put in (e.g. 4–6 PM, 6–8 PM). Each course a student
// joins gets one of these, and attendance is kept per course and batch.
function Batches({ batches, onSaved, toast }) {
  const [items, setItems] = useState(batches);
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => setItems(batches), [batches]);
  const add = (e) => { e.preventDefault(); const b = text.trim(); if (b && !items.includes(b)) setItems([...items, b]); setText(""); };
  const save = async () => {
    setSaving(true);
    const r = await api.put("/courses/batches", { batches: items });
    setSaving(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) onSaved();
  };
  const changed = JSON.stringify(items) !== JSON.stringify(batches);
  return (
    <section className="panel course-list">
      <div className="panel-head"><h2 className="h2">Batch timings</h2>
        <button className="btn primary" disabled={!changed || saving} onClick={save}>{saving ? "Saving…" : "Save batches"}</button></div>
      <p className="muted small">When registering, each course a student joins gets one of these timings. Attendance is kept separately for each course and batch.</p>
      <div className="course-chips">
        {items.map((b) => (
          <span key={b} className="chip-check on">{b}
            <button className="x" aria-label={`Remove ${b}`} onClick={() => setItems(items.filter((x) => x !== b))}>×</button>
          </span>
        ))}
        {items.length === 0 && <span className="muted small">No batches: students join courses without a timing.</span>}
      </div>
      <form className="row-form" onSubmit={add}>
        <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Evening 4–6 PM" maxLength={30} aria-label="New batch timing" />
        <button className="btn ghost" disabled={!text.trim()}><Icon name="plus" size={18} />Add</button>
      </form>
    </section>
  );
}

export default function CoursesPage({ isAdmin, toast, askConfirm, onChanged, go, setCourse }) {
  const [list, setList] = useState(null);
  const [batches, setBatches] = useState([]);
  const [edit, setEdit] = useState(null);          // null | "new" | course
  const load = async () => { const r = await api.get("/courses"); setList(r.success ? r.courses : []); if (r.success) setBatches(r.batches || []); };
  useEffect(() => { load(); }, []);
  const saved = () => { load(); onChanged(); };
  const remove = (c) => askConfirm({
    title: `Remove ${c.name}?`, body: "The course and its picture are deleted. This only works while no student has joined it.",
    label: "Remove course", danger: true,
    onYes: async () => { const r = await api.del(`/courses/${c.id}`); toast(r.message, r.success ? "ok" : "bad"); if (r.success) saved(); },
  });

  return (
    <>
      <PageHead title="Courses" sub={isAdmin ? "Add each course with a picture, price and description. Students join courses when they're registered."
        : "The courses Aakansha IT Hub offers."}>
        {isAdmin && <button className="btn primary" onClick={() => setEdit("new")}><Icon name="plus" />Add a course</button>}
      </PageHead>
      {isAdmin && list !== null && <Batches batches={batches} onSaved={() => { load(); onChanged(); }} toast={toast} />}
      {list === null ? <p className="empty">Loading courses…</p> : list.length === 0 ? (
        <section className="panel"><div className="empty">
          <p>No courses yet.{isAdmin ? " Add the first one: name, price, a picture and what it covers." : " Ask the IT Hub admin to add them."}</p>
          {isAdmin && <button className="btn primary" onClick={() => setEdit("new")}><Icon name="plus" />Add a course</button>}
        </div></section>
      ) : (
        <div className="course-grid">
          {list.map((c) => (
            <article key={c.id} className={`course-card${c.active ? "" : " off"}`}>
              <div className="course-pic">
                {c.has_image ? <img src={mediaUrl(`/courses/${c.id}/image`, `&v=${c.image_v}`)} alt="" loading="lazy" />
                  : <div className="course-pic-empty" aria-hidden="true"><span>{c.name.slice(0, 1)}</span></div>}
                {!c.active && <span className="chip warn course-off">Not open for new students</span>}
              </div>
              <div className="course-body">
                <h3>{c.name}</h3>
                <p className="course-meta"><strong>{c.price ? inr(c.price) : "Free"}</strong>{c.duration && <> · {c.duration}</>} · {c.students} student{c.students === 1 ? "" : "s"}</p>
                {c.description && <p className="course-desc">{c.description}</p>}
              </div>
              <div className="course-actions">
                <button className="btn ghost" onClick={() => { setCourse(c.name); go("students"); }}>Students</button>
                {isAdmin && <button className="btn ghost" onClick={() => setEdit(c)}><Icon name="edit" size={18} />Edit</button>}
                {isAdmin && c.students === 0 && <button className="icon-btn" aria-label={`Remove ${c.name}`} onClick={() => remove(c)}><Icon name="trash" size={18} /></button>}
              </div>
            </article>
          ))}
        </div>
      )}
      {edit && <CourseForm course={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={saved} toast={toast} />}
    </>
  );
}

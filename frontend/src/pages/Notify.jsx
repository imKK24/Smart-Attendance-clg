import { useEffect, useRef, useState } from "react";
import { api, mediaUrl, setToken } from "../api";
import { isHub } from "../org";
import { ChannelPicker, Face, Field, Icon, PageHead, Segmented, Tick } from "../ui";
import { dateRange, fmt, fmtStamp, isoToday, parseISO, plural } from "../util";

const defaultChannels = (avail) => (avail.wa === "open" || !avail.email ? ["whatsapp", ...(avail.email ? ["email"] : [])] : ["email"]);
const usePicked = (avail) => {
  const [v, setV] = useState(() => defaultChannels(avail));
  return [v.filter((c) => c !== "email" || avail.email), setV];
};

function Progress({ status }) {
  if (!status.running) return null;
  const done = status.sent + status.failed;
  return (
    <div className="say sending" role="status">
      <div>Sending messages: {done} of {status.total}{status.failed ? ` (${status.failed} failed)` : ""}. WhatsApp messages are spaced out a few seconds apart to protect your number.</div>
      <div className="meter"><i style={{ width: `${status.total ? (done / status.total) * 100 : 0}%` }} /></div>
    </div>
  );
}

function SetupHints({ avail, setTab, isAdmin }) {
  if (avail.wa === "open" && avail.email) return null;
  if (isHub()) {   // the IT Hub sends through the college's WhatsApp and Gmail
    return <div className="banner" role="alert">{avail.wa !== "open" && "WhatsApp isn't linked. "}{!avail.email && "Gmail isn't set up. "}
      The IT Hub sends through the college's WhatsApp and Gmail: ask the college admin to set them up.</div>;
  }
  if (!isAdmin) {
    return <div className="banner" role="alert">{avail.wa !== "open" && "WhatsApp isn't linked. "}{!avail.email && "Gmail isn't set up. "}Ask the admin to set it up under Notify.</div>;
  }
  return (
    <div className="banner" role="alert">
      {avail.wa !== "open" && <>WhatsApp isn't linked, so WhatsApp messages will fail. <button className="link" onClick={() => setTab("whatsapp")}>Link WhatsApp</button>. </>}
      {!avail.email && <>Gmail isn't set up, so no emails can be sent. <button className="link" onClick={() => setTab("settings")}>Set up Gmail</button>.</>}
    </div>
  );
}

// ─── ABSENCE ALERTS ───────────────────────────────────────────────────────────
function AlertsTab({ alerts, avail, busy, onSend, ids }) {
  const [ch, setCh] = usePicked(avail);
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <h2>Absence streaks</h2>
          <p className="muted small">Parents are told after {plural(alerts.threshold, "absent day")} in a row. Weekends, days without a register and holidays are skipped.
            {alerts.auto_send ? " Due alerts go out by themselves when you stop the camera." : ""}</p>
        </div>
        <div className="tools">
          <ChannelPicker value={ch} onChange={setCh} status={avail} />
          <button className="btn primary" disabled={busy || !alerts.due_count || !ch.length} onClick={() => onSend(null, ch)}>
            <Icon name="send" size={18} />{alerts.due_count ? `Send ${plural(alerts.due_count, "due alert")}` : "No alerts due"}
          </button>
        </div>
      </div>
      {alerts.students.length ? (
        <ul className="ledger">
          {alerts.students.map((r) => (
            <li key={r.id} className="arow">
              <Face name={r.name} id={ids[r.name]} size={40} />
              <div className="a-main">
                <strong>{r.name}</strong>
                <span className="muted">Absent {plural(r.days, "day")} in a row since {fmt(r.dates[0], { day: "numeric", month: "short" })}</span>
              </div>
              <div className="a-contact">
                {r.parent_phone || r.parent_email ? (
                  <>
                    <span>{r.parent_name || "Parent or guardian"}</span>
                    {r.parent_phone && <a href={`https://wa.me/${r.parent_phone.replace("+", "")}`} target="_blank" rel="noreferrer">{r.parent_phone}</a>}
                    {r.parent_email && <span className="muted">{r.parent_email}</span>}
                  </>
                ) : <span className="chip warn">No parent contact saved</span>}
              </div>
              <div>
                {r.alerted ? <span className="chip ok" title={fmtStamp(r.sent_at)}><Tick /> Sent by {r.sent_channels.join(" + ")}</span>
                  : r.reached ? <span className="chip no">Alert due</span>
                    : <span className="chip warn">{r.days} of {alerts.threshold} days</span>}
              </div>
              <div>
                <button className="btn ghost" disabled={busy || !(r.parent_phone || r.parent_email) || !ch.length} onClick={() => onSend(r.id, ch)}>
                  {r.alerted ? "Send again" : "Send now"}
                </button>
              </div>
            </li>
          ))}
        </ul>
      ) : <p className="empty">No student is on an absence streak.</p>}
    </section>
  );
}

// ─── HOLIDAYS ─────────────────────────────────────────────────────────────────
const EMPTY_HOLIDAY = { title: "", start_date: "", end_date: "", note: "" };

function HolidaysTab({ avail, busy, toast, askConfirm, onQueued }) {
  const [list, setList] = useState([]);
  const [f, setF] = useState(EMPTY_HOLIDAY);
  const [saving, setSaving] = useState(false);
  const [ch, setCh] = usePicked(avail);
  const load = async () => { const r = await api.get("/holidays"); if (r.success) setList(r.holidays); };
  useEffect(() => { load(); }, []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const save = async () => {
    setSaving(true);
    const r = await api.post("/holidays", { ...f, end_date: f.end_date || f.start_date });
    setSaving(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setF(EMPTY_HOLIDAY); load(); }
  };
  const today = isoToday();
  const upcoming = list.filter((h) => h.end_date >= today);
  const past = list.filter((h) => h.end_date < today);
  const card = (h) => (
    <article key={h.id} className="panel ev">
      <div className="ev-date sun"><b>{parseISO(h.start_date).getDate()}</b><span>{fmt(h.start_date, { month: "short" })}</span></div>
      <div className="ev-main">
        <h3>{h.title}</h3>
        <p className="muted">{dateRange(h.start_date, h.end_date)}</p>
        {h.note && <p>{h.note}</p>}
        {h.last_notified_at && <p className="muted small">Sent {fmtStamp(h.last_notified_at)} ({plural(h.last_recipients, "message")})</p>}
      </div>
      <div className="ev-actions">
        <button className="btn primary" disabled={busy || !ch.length} onClick={() => askConfirm({
          title: `Tell parents about ${h.title}?`,
          body: `Every parent with a ${ch.join(" or ")} contact gets a holiday notice.`,
          label: "Send notice", onYes: async () => { const r = await api.post(`/holidays/${h.id}/notify`, { channels: ch }); toast(r.message, r.success ? "ok" : "bad"); if (r.success) { onQueued(); load(); } },
        })}><Icon name="send" size={18} />Notify parents</button>
        <button className="icon-btn" aria-label={`Delete ${h.title}`} onClick={() => askConfirm({
          title: `Delete ${h.title}?`, body: "Those days will count for absence streaks again. Messages already sent can't be recalled.",
          label: "Delete holiday", danger: true, onYes: async () => { const r = await api.del(`/holidays/${h.id}`); toast(r.message, r.success ? "ok" : "bad"); load(); },
        })}><Icon name="trash" size={18} /></button>
      </div>
    </article>
  );
  return (
    <div className="events">
      <section className="panel pad ev-form">
        <h2 className="h2">Add a holiday</h2>
        <div className="fields">
          <Field id="h-title" wide label="Name" value={f.title} onChange={set("title")} placeholder="e.g. Diwali break" maxLength={80} />
          <Field id="h-start" label="First day" type="date" value={f.start_date} onChange={set("start_date")} />
          <Field id="h-end" label="Last day" type="date" min={f.start_date} value={f.end_date} onChange={set("end_date")} hint="Leave empty for one day." />
          <Field id="h-note" wide as="textarea" rows={2} label="Note for parents (optional)" value={f.note} onChange={set("note")} maxLength={600} placeholder="e.g. Classes resume on Monday." />
        </div>
        <button className="btn primary" disabled={saving || !f.title.trim() || !f.start_date} onClick={save}><Icon name="plus" />Save holiday</button>
        <p className="muted small">Holidays are skipped when counting absence streaks.</p>
      </section>
      <section className="ev-list">
        <div className="ev-tools"><ChannelPicker value={ch} onChange={setCh} status={avail} /></div>
        {upcoming.length ? upcoming.map(card) : <section className="panel"><p className="empty">No upcoming holidays.</p></section>}
        {past.length > 0 && <details className="past"><summary className="muted">Past holidays ({past.length})</summary>{past.map(card)}</details>}
      </section>
    </div>
  );
}

// ─── EXAM RESULTS ─────────────────────────────────────────────────────────────
const NEW_EXAM = () => ({ name: "", exam_date: "", subjects: [{ name: "", max: 100 }] });

function ExamDetail({ id, avail, busy, toast, askConfirm, onBack, onQueued }) {
  const [data, setData] = useState(null);
  const [report, setReport] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [ch, setCh] = usePicked(avail);
  const fileRef = useRef(null);
  const load = async () => { const r = await api.get(`/exams/${id}`); setData(r.success ? r : null); };
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!data) return <p className="empty">Loading…</p>;
  const { exam, results, missing } = data;
  const unsent = results.filter((r) => !r.notified_at).length;

  const upload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setUploading(true);
    const r = await api.upload(`/exams/${id}/upload`, file);
    setUploading(false);
    toast(r.message, r.success ? "ok" : "bad");
    setReport(r.success ? r : null);
    load();
  };
  const publish = (onlyNew) => askConfirm({
    title: onlyNew ? `Send ${plural(unsent, "result")}?` : "Send every result again?",
    body: `Each parent gets their own child's marks by ${ch.join(" and ")}.`,
    label: "Send results",
    onYes: async () => { const r = await api.post(`/exams/${id}/publish`, { channels: ch, only_new: onlyNew }); toast(r.message, r.success ? "ok" : "bad"); if (r.success) onQueued(); setTimeout(load, 1500); },
  });

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <button className="link back-link" onClick={onBack}>← All exams</button>
          <h2>{exam.name}</h2>
          <p className="muted small">{exam.exam_date ? fmt(exam.exam_date, { day: "numeric", month: "long", year: "numeric" }) + " · " : ""}{exam.subjects.map((s) => `${s.name} /${s.max}`).join(", ")}</p>
        </div>
        <div className="tools">
          <a className="btn ghost" href={mediaUrl(`/exams/${id}/template`)}><Icon name="download" size={18} />Excel template</a>
          <button className="btn ghost" disabled={uploading} onClick={() => fileRef.current?.click()}><Icon name="upload" size={18} />{uploading ? "Reading…" : "Upload marks"}</button>
          <input ref={fileRef} type="file" accept=".xlsx,.csv" hidden onChange={upload} />
        </div>
      </div>
      <div className="pad exam-steps">
        <ol className="steps inline">
          <li className={results.length ? "done" : "now"}><span className="n">{results.length ? <Tick /> : 1}</span>Download the template, fill in marks (write AB for absent), upload it.</li>
          <li className={exam.published_at && !unsent ? "done" : results.length ? "now" : ""}><span className="n">{exam.published_at && !unsent ? <Tick /> : 2}</span>Send each parent their child's result.</li>
        </ol>
        {report && (report.unmatched.length > 0 || report.problems.length > 0) && (
          <div className="note">
            {report.unmatched.length > 0 && <p><strong>Not matched to a student</strong> (check registration no / name): {report.unmatched.join("; ")}</p>}
            {report.problems.length > 0 && <p><strong>Skipped:</strong> {report.problems.join("; ")}</p>}
          </div>
        )}
        {results.length > 0 && (
          <div className="publish">
            <ChannelPicker value={ch} onChange={setCh} status={avail} />
            <button className="btn primary" disabled={busy || !unsent || !ch.length} onClick={() => publish(true)}><Icon name="send" size={18} />{unsent ? `Send ${plural(unsent, "new result")}` : "All results sent"}</button>
            {!unsent && <button className="btn ghost" disabled={busy || !ch.length} onClick={() => publish(false)}>Send all again</button>}
          </div>
        )}
      </div>
      {results.length ? (
        <div className="table-wrap">
          <table className="marks">
            <thead><tr><th>Registration no</th><th>Name</th>{exam.subjects.map((s) => <th key={s.name}>{s.name}<small>/{s.max}</small></th>)}<th>Total</th><th>%</th><th>Sent</th></tr></thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.id}>
                  <td>{r.roll_no || "–"}</td><td>{r.name}</td>
                  {exam.subjects.map((s) => <td key={s.name} className={r.marks[s.name] === "AB" ? "ab" : ""}>{r.marks[s.name] ?? "–"}</td>)}
                  <td><strong>{r.total}</strong></td><td>{r.percentage}</td>
                  <td>{r.notified_at ? <span className="chip ok tiny" title={fmtStamp(r.notified_at)}><Tick size={12} /></span> : !r.has_contact ? <span className="chip warn tiny">No contact</span> : <span className="muted">–</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="empty">No marks uploaded yet.</p>}
      {missing.length > 0 && results.length > 0 && <p className="muted small pad">No marks for: {missing.map((m) => m.name).join(", ")}</p>}
    </section>
  );
}

function ExamsTab(props) {
  const { toast, askConfirm, courses = [], course } = props;
  const hub = isHub();   // IT Hub: each test is for one course
  const [list, setList] = useState([]);
  const [open, setOpen] = useState(null);
  const [f, setF] = useState(NEW_EXAM);
  const [saving, setSaving] = useState(false);
  const load = async () => { const r = await api.get("/exams"); if (r.success) setList(r.exams); };
  useEffect(() => { load(); }, [open]);
  const setSub = (i, k, v) => setF({ ...f, subjects: f.subjects.map((s, j) => (j === i ? { ...s, [k]: v } : s)) });
  const create = async () => {
    setSaving(true);
    const r = await api.post("/exams", { ...f, ...(hub ? { course: f.course || course } : {}), subjects: f.subjects.filter((s) => s.name.trim()) });
    setSaving(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setF(NEW_EXAM()); setOpen(r.exam.id); }
  };
  if (open) return <ExamDetail id={open} {...props} onBack={() => setOpen(null)} />;
  return (
    <div className="events">
      <section className="panel pad ev-form">
        <h2 className="h2">{hub ? "New test" : "New exam"}</h2>
        <div className="fields">
          <Field id="x-name" wide label={hub ? "Test name" : "Exam name"} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder={hub ? "e.g. Python test 1" : "e.g. Mid-term 1"} maxLength={80} />
          {hub && (
            <Field id="x-course" wide label="Course">
              <select id="x-course" value={f.course || course || ""} onChange={(e) => setF({ ...f, course: e.target.value })}>
                {courses.map((c) => <option key={c}>{c}</option>)}
              </select>
            </Field>
          )}
          <Field id="x-date" wide label={hub ? "Test date (optional)" : "Exam date (optional)"} type="date" value={f.exam_date} onChange={(e) => setF({ ...f, exam_date: e.target.value })} />
        </div>
        <div className="subjects">
          <p className="small"><strong>Subjects and maximum marks</strong></p>
          {f.subjects.map((s, i) => (
            <div className="subj" key={i}>
              <input aria-label={`Subject ${i + 1}`} value={s.name} onChange={(e) => setSub(i, "name", e.target.value)} placeholder="Subject" maxLength={40} />
              <input aria-label={`Max marks for subject ${i + 1}`} type="number" min={1} max={1000} value={s.max} onChange={(e) => setSub(i, "max", e.target.value)} />
              <button className="icon-btn" aria-label={`Remove subject ${i + 1}`} disabled={f.subjects.length === 1} onClick={() => setF({ ...f, subjects: f.subjects.filter((_, j) => j !== i) })}><Icon name="trash" size={16} /></button>
            </div>
          ))}
          <button className="btn ghost small-btn" onClick={() => setF({ ...f, subjects: [...f.subjects, { name: "", max: f.subjects.at(-1)?.max || 100 }] })}><Icon name="plus" size={16} />Add subject</button>
        </div>
        <button className="btn primary" disabled={saving || !f.name.trim() || !f.subjects.some((s) => s.name.trim())} onClick={create}><Icon name="plus" />{hub ? "Create test" : "Create exam"}</button>
      </section>
      <section className="ev-list">
        {list.length ? list.map((e) => (
          <article key={e.id} className="panel ev">
            <div className="ev-date"><Icon name="grade" size={26} /></div>
            <button className="ev-main as-card" onClick={() => setOpen(e.id)}>
              <h3>{e.name}</h3>
              <p className="muted">{e.course ? `${e.course} · ` : ""}{e.exam_date ? fmt(e.exam_date, { day: "numeric", month: "short", year: "numeric" }) + " · " : ""}{plural(e.subjects.length, "subject")} · {e.results_count} with marks</p>
              {e.published_at && <p className="muted small">Results sent {fmtStamp(e.published_at)}</p>}
            </button>
            <div className="ev-actions">
              <button className="btn ghost" onClick={() => setOpen(e.id)}>Open</button>
              <button className="icon-btn" aria-label={`Delete ${e.name}`} onClick={() => askConfirm({
                title: `Delete ${e.name}?`, body: "Its marks are deleted too. Messages already sent can't be recalled.", label: "Delete exam", danger: true,
                onYes: async () => { const r = await api.del(`/exams/${e.id}`); toast(r.message, r.success ? "ok" : "bad"); load(); },
              })}><Icon name="trash" size={18} /></button>
            </div>
          </article>
        )) : <section className="panel"><p className="empty">{hub ? "No tests yet. Create one, then upload the marks sheet." : "No exams yet. Create one, then upload the marks sheet."}</p></section>}
      </section>
    </div>
  );
}

// ─── EVENTS ───────────────────────────────────────────────────────────────────
const EMPTY_EVENT = { title: "", date: "", time: "", venue: "", description: "" };

function EventsTab({ avail, busy, toast, askConfirm, onQueued }) {
  const [list, setList] = useState([]);
  const [f, setF] = useState(EMPTY_EVENT);
  const [saving, setSaving] = useState(false);
  const [ch, setCh] = usePicked(avail);
  const [who, setWho] = useState({ students: true, parents: false });
  const load = async () => { const r = await api.get("/events"); if (r.success) setList(r.events); };
  useEffect(() => { load(); }, []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async () => {
    setSaving(true);
    const r = await api.post("/events", f);
    setSaving(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setF(EMPTY_EVENT); load(); }
  };
  const nobody = !ch.length || (!who.students && !who.parents);
  return (
    <div className="events">
      <section className="panel pad ev-form">
        <h2 className="h2">New event</h2>
        <div className="fields">
          <Field id="ev-title" wide label="Event title" value={f.title} onChange={set("title")} placeholder="e.g. Annual sports day" maxLength={80} />
          <Field id="ev-date" label="Date" type="date" min={isoToday()} value={f.date} onChange={set("date")} />
          <Field id="ev-time" label="Time (optional)" type="time" value={f.time} onChange={set("time")} />
          <Field id="ev-venue" wide label="Venue (optional)" value={f.venue} onChange={set("venue")} maxLength={80} />
          <Field id="ev-desc" wide as="textarea" rows={3} label="Details (optional)" value={f.description} onChange={set("description")} maxLength={1000} placeholder="What students should know or bring" />
        </div>
        <button className="btn primary" disabled={saving || !f.title.trim() || !f.date} onClick={submit}><Icon name="plus" />Save event</button>
      </section>
      <section className="ev-list">
        <div className="ev-tools">
          <fieldset className="channels"><legend>Send to</legend>
            <label className="check"><input type="checkbox" checked={who.students} onChange={(e) => setWho({ ...who, students: e.target.checked })} />Students</label>
            <label className="check"><input type="checkbox" checked={who.parents} onChange={(e) => setWho({ ...who, parents: e.target.checked })} />Parents</label>
          </fieldset>
          <ChannelPicker value={ch} onChange={setCh} status={avail} />
        </div>
        {list.length ? list.map((ev) => (
          <article key={ev.id} className="panel ev">
            <div className="ev-date"><b>{parseISO(ev.date).getDate()}</b><span>{fmt(ev.date, { month: "short" })}</span></div>
            <div className="ev-main">
              <h3>{ev.title}</h3>
              <p className="muted">{fmt(ev.date, { weekday: "long" })}{ev.time ? `, ${ev.time}` : ""}{ev.venue ? `. ${ev.venue}` : ""}</p>
              {ev.description && <p>{ev.description}</p>}
              {ev.last_notified_at && <p className="muted small">Sent {fmtStamp(ev.last_notified_at)} ({plural(ev.last_recipients, "message")})</p>}
            </div>
            <div className="ev-actions">
              <button className="btn primary" disabled={busy || nobody} onClick={() => askConfirm({
                title: `Send "${ev.title}"?`,
                body: `It goes to ${[who.students && "students", who.parents && "parents"].filter(Boolean).join(" and ")} by ${ch.join(" and ")}.`,
                label: "Send", onYes: async () => { const r = await api.post(`/events/${ev.id}/notify`, { channels: ch, to_students: who.students, to_parents: who.parents }); toast(r.message, r.success ? "ok" : "bad"); if (r.success) { onQueued(); load(); } },
              })}><Icon name="send" size={18} />Send</button>
              <button className="icon-btn" aria-label={`Delete ${ev.title}`} onClick={() => askConfirm({
                title: `Delete "${ev.title}"?`, body: "Messages already sent can't be recalled.", label: "Delete event", danger: true,
                onYes: async () => { const r = await api.del(`/events/${ev.id}`); toast(r.message, r.success ? "ok" : "bad"); load(); },
              })}><Icon name="trash" size={18} /></button>
            </div>
          </article>
        )) : <section className="panel"><p className="empty">No events yet.</p></section>}
      </section>
    </div>
  );
}

// ─── WHATSAPP ─────────────────────────────────────────────────────────────────
function WhatsAppTab({ wa, reloadWa, toast, askConfirm, countryCode, onQueued }) {
  const [phone, setPhone] = useState("");
  useEffect(() => { reloadWa(); const t = setInterval(reloadWa, 3000); return () => clearInterval(t); }, [reloadWa]);
  const test = async () => { const r = await api.post("/whatsapp/test", { phone }); toast(r.message, r.success ? "ok" : "bad"); if (r.success) onQueued(); };
  const labels = { open: "Linked", qr: "Waiting for scan", connecting: "Connecting…", starting: "Starting…", logged_out: "Unlinked", offline: "Bridge not running", error: "Problem" };
  return (
    <div className="reg">
      <section className="panel pad wa-card">
        <div className="wa-state"><span className={`dot ${wa.state === "open" ? "ok" : "no"}`} /><strong>{labels[wa.state] || wa.state}</strong></div>
        {wa.state === "open" && (
          <>
            <p>Messages are sent from <strong>+{wa.me?.id}</strong>{wa.me?.name ? ` (${wa.me.name})` : ""}.</p>
            <button className="btn ghost" onClick={() => askConfirm({ title: "Unlink WhatsApp?", body: "Messages stop until you scan a new QR code.", label: "Unlink", danger: true,
              onYes: async () => { const r = await api.post("/whatsapp/logout"); toast(r.message, r.success ? "ok" : "bad"); reloadWa(); } })}>Unlink this computer</button>
          </>
        )}
        {wa.state === "qr" && wa.qr && (
          <div className="qr">
            <img src={wa.qr} alt="WhatsApp QR code. Scan it with the school phone." width={260} height={260} />
            <ol className="steps">
              <li><span className="n">1</span>Open WhatsApp on the school phone.</li>
              <li><span className="n">2</span>Tap <strong>Settings › Linked devices › Link a device</strong>.</li>
              <li><span className="n">3</span>Point the phone at this code. It refreshes by itself.</li>
            </ol>
          </div>
        )}
        {wa.state === "offline" && (
          <div className="note">
            <p>Start the WhatsApp bridge in a second terminal:</p>
            <pre>cd whatsapp-bridge{"\n"}npm install   (first time only){"\n"}npm start</pre>
          </div>
        )}
        {wa.error && wa.state !== "offline" && <p className="note">{wa.error}</p>}
        <div className="wa-test">
          <Field id="wa-phone" label="Send a test message to" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="98765 43210" />
          <button className="btn primary" onClick={test} disabled={!phone.trim() || wa.state !== "open"}><Icon name="send" size={18} />Send test</button>
        </div>
        <p className="muted small">+{countryCode} is added to 10-digit numbers.</p>
      </section>
      <section className="panel pad help">
        <h2 className="h2">Before you use WhatsApp</h2>
        <p>This uses <strong>Baileys</strong>, which talks to WhatsApp Web over a socket. It is free but <strong>not official</strong>. WhatsApp can block numbers that look like they're sending spam.</p>
        <ul className="bullets">
          <li>Use a separate school number, not a personal one.</li>
          <li>Ask parents to save the number, so messages aren't reported.</li>
          <li>Messages are spaced out by a few seconds. Don't lower that gap much (Settings tab).</li>
          <li>Keep the phone charged and online now and then, or the link expires after about 14 days.</li>
        </ul>
        <p className="muted small">If the number gets blocked, Twilio or Meta's WhatsApp Cloud API are the official, paid options.</p>
      </section>
    </div>
  );
}

// ─── LOG ──────────────────────────────────────────────────────────────────────
function LogTab({ status, toast, onQueued }) {
  const [rows, setRows] = useState([]);
  const [show, setShow] = useState("all");
  const load = async () => { const r = await api.get("/messages?limit=150"); if (r.success) setRows(r.messages); };
  useEffect(() => { load(); }, [status.running, status.last?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const list = rows.filter((m) => show === "all" || m.status === show);
  const retry = async () => { const r = await api.post("/messages/retry"); toast(r.message, r.success ? "ok" : "bad"); if (r.queued) onQueued(); };
  const kinds = { absence: "Absence", holiday: "Holiday", result: "Result", event: "Event", reply: "Reply", test: "Test" };
  return (
    <section className="panel">
      <div className="panel-head">
        <Segmented value={show} onChange={setShow} label="Show" options={[{ id: "all", label: "All" }, { id: "failed", label: "Failed", count: status.failed_total }, { id: "queued", label: "Waiting" }]} />
        <button className="btn ghost" disabled={!status.failed_total || status.running} onClick={retry}><Icon name="retake" size={18} />Retry failed</button>
      </div>
      {list.length ? (
        <ul className="log">
          {list.map((m) => (
            <li key={m.id} title={m.body}>
              <span className="muted">{fmtStamp(m.sent_at || m.created_at)}</span>
              <span><span className={`tag ${m.channel}`}>{m.channel === "whatsapp" ? "WhatsApp" : "Email"}</span> {kinds[m.kind] || m.kind} · {m.who}</span>
              <span className="muted to">{m.status === "failed" ? m.error : m.to}</span>
              <span className={`chip tiny ${m.status === "sent" ? "ok" : m.status === "failed" ? "no" : "warn"}`}>{m.status === "sent" ? "Sent" : m.status === "failed" ? "Failed" : "Waiting"}</span>
            </li>
          ))}
        </ul>
      ) : <p className="empty">No messages here.</p>}
    </section>
  );
}

// ─── SETTINGS ─────────────────────────────────────────────────────────────────
function SettingsTab({ settings, onSave, toast }) {
  const [f, setF] = useState(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [pw, setPw] = useState({ current: "", new: "" });
  useEffect(() => {
    setF({ gmail: settings.gmail, app_password: "", sender_name: settings.sender_name, school_name: settings.school_name, threshold: settings.threshold,
      auto_send: settings.auto_send, alert_channels: settings.alert_channels, country_code: settings.country_code, wa_delay: settings.wa_delay });
  }, [settings]);
  if (!f) return null;
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const toggleCh = (c) => setF({ ...f, alert_channels: f.alert_channels.includes(c) ? f.alert_channels.filter((x) => x !== c) : [...f.alert_channels, c] });
  const save = async () => { setSaving(true); await onSave(f); setSaving(false); };
  const test = async () => { setTesting(true); const r = await api.post("/settings/test-email"); setTesting(false); toast(r.message, r.success ? "ok" : "bad"); };
  const changePw = async () => {
    const r = await api.post("/auth/password", pw);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setToken(r.token); setPw({ current: "", new: "" }); }   // keep this device logged in
  };
  return (
    <div className="reg">
      <section className="panel reg-form">
        {settings.shared_here === false ? (
          <fieldset className="fs"><legend>Gmail and WhatsApp</legend>
            <p className="muted">The IT Hub sends through the college's Gmail{settings.gmail ? ` (${settings.gmail})` : ""} and WhatsApp number.
              Only the college admin can change them. Your own name and the IT Hub's name below are used to sign your messages.</p>
          </fieldset>
        ) : (
          <fieldset className="fs"><legend>Gmail (sending and the parent inbox)</legend>
            <div className="fields">
              <Field id="em-gmail" wide label="Gmail address" type="email" value={f.gmail} onChange={set("gmail")} placeholder="teacher@gmail.com" autoComplete="off" />
              <Field id="em-pass" wide label="Gmail App Password" type="password" value={f.app_password} onChange={set("app_password")} autoComplete="new-password"
                placeholder={settings.password_set ? "Saved. Type a new one to replace it" : "16 characters"} hint="Not your normal Gmail password. It's stored encrypted." />
            </div>
          </fieldset>
        )}
        <fieldset className="fs"><legend>How messages are signed</legend>
          <div className="fields">
            <Field id="em-name" label="Your name" value={f.sender_name} onChange={set("sender_name")} maxLength={60} />
            <Field id="em-school" label={isHub() ? "Institute name" : "College / school"} value={f.school_name} onChange={set("school_name")} maxLength={80}
              placeholder={isHub() ? "Aakansha IT Hub" : "Seemanta Engineering College"} />
          </div>
        </fieldset>
        <fieldset className="fs"><legend>Absence alerts</legend>
          <div className="fields">
            <Field id="em-days" label="Alert after this many absent days in a row" type="number" min={1} max={14} value={f.threshold} onChange={set("threshold")} />
            {!isHub() && <Field id="em-cc" label="Country code for phone numbers" value={f.country_code} onChange={set("country_code")} maxLength={3} inputMode="numeric" hint="91 for India" />}
          </div>
          <div className="channels">
            <span className="small"><strong>Send alerts by</strong></span>
            <label className="check"><input type="checkbox" checked={f.alert_channels.includes("whatsapp")} onChange={() => toggleCh("whatsapp")} />WhatsApp</label>
            <label className="check"><input type="checkbox" checked={f.alert_channels.includes("email")} onChange={() => toggleCh("email")} />Email</label>
          </div>
          <label className="check"><input type="checkbox" checked={f.auto_send} onChange={(e) => setF({ ...f, auto_send: e.target.checked })} />Send due alerts automatically when I stop the camera</label>
          <Field id="em-gap" label="Seconds between WhatsApp messages" type="number" min={3} max={60} value={f.wa_delay} onChange={set("wa_delay")} hint="Larger gaps are safer for your number. 6 is a good start." />
        </fieldset>
        <div className="btn-row">
          <button className="btn primary wide" onClick={save} disabled={saving}><Icon name="check" />{saving ? "Saving…" : "Save settings"}</button>
          <button className="btn ghost wide" onClick={test} disabled={testing || !settings.configured}><Icon name="mail" />{testing ? "Sending…" : "Send a test email to myself"}</button>
        </div>
      </section>
      <div className="side-col">
        {!isHub() && (
        <section className="panel pad help">
          <h2 className="h2">Get a free App Password</h2>
          <ol className="steps">
            <li><span className="n">1</span>Turn on 2-Step Verification in your Google account.</li>
            <li><span className="n">2</span><span>Open <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">myaccount.google.com/apppasswords</a> and create one named AttendAI.</span></li>
            <li><span className="n">3</span>Paste the 16 characters here and press Save.</li>
          </ol>
          <p className="muted small">Gmail allows about 500 emails a day. The Inbox reads mail with the same password (IMAP is on by default in Gmail).</p>
        </section>
        )}
        <section className="panel pad">
          <h2 className="h2">Admin password</h2>
          <div className="fields one">
            <Field id="pw-cur" label="Current password" type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" />
            <Field id="pw-new" label="New password" type="password" value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} autoComplete="new-password" hint="At least 8 characters." />
          </div>
          <button className="btn ghost" disabled={!pw.current || pw.new.length < 8} onClick={changePw}>Change password</button>
        </section>
      </div>
    </div>
  );
}

// ─── PAGE ─────────────────────────────────────────────────────────────────────
export default function NotifyPage({ tab, setTab, alerts, settings, msgStatus, wa, reloadWa, onQueued, sendAlerts, saveSettings, askConfirm, toast, ids, isAdmin,
  courses = [], course }) {
  const avail = { wa: wa.state, email: settings.configured };
  const busy = msgStatus.running;
  const common = { avail, busy, toast, askConfirm, onQueued, courses, course };
  if (isHub() && tab === "whatsapp") tab = "alerts";   // the WhatsApp link belongs to the college admin
  const TEACHER_TABS = ["alerts", "exams", "log"];
  if (!isAdmin && !TEACHER_TABS.includes(tab)) tab = "alerts";
  return (
    <>
      <PageHead title="Notify" sub={isHub() ? "Absence alerts, holidays, test results and events go out on WhatsApp and email."
        : "Absence alerts, holidays, exam results and events go to parents on WhatsApp and email."} />
      <div className="tabbar">
        <Segmented value={tab} onChange={setTab} label="Section" options={[
          { id: "alerts", label: "Absence alerts", count: alerts.due_count || undefined },
          { id: "holidays", label: "Holidays" },
          { id: "exams", label: isHub() ? "Test results" : "Exam results" },
          { id: "events", label: "Events" },
          ...(isHub() ? [] : [{ id: "whatsapp", label: "WhatsApp" }]),
          { id: "log", label: "Sent", count: msgStatus.failed_total || undefined },
          { id: "settings", label: "Settings" },
        ].filter((o) => isAdmin || TEACHER_TABS.includes(o.id))} />
      </div>
      <Progress status={msgStatus} />
      {!["whatsapp", "settings", "log"].includes(tab) && <SetupHints avail={avail} setTab={setTab} isAdmin={isAdmin} />}
      {tab === "alerts" && <AlertsTab alerts={alerts} avail={avail} busy={busy} onSend={sendAlerts} ids={ids} />}
      {tab === "holidays" && <HolidaysTab {...common} />}
      {tab === "exams" && <ExamsTab {...common} />}
      {tab === "events" && <EventsTab {...common} />}
      {tab === "whatsapp" && <WhatsAppTab wa={wa} reloadWa={reloadWa} toast={toast} askConfirm={askConfirm} countryCode={settings.country_code} onQueued={onQueued} />}
      {tab === "log" && <LogTab status={msgStatus} toast={toast} onQueued={onQueued} />}
      {tab === "settings" && <SettingsTab settings={settings} onSave={saveSettings} toast={toast} />}
    </>
  );
}

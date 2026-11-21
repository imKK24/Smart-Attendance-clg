// Read-only page for a parent (college) or a student (Aakansha IT Hub): one student's
// attendance, results, leave and fees. The only thing they can change is applying for leave.
import { useEffect, useState } from "react";
import { api } from "../api";
import { isHub } from "../org";
import { Field, Icon, Segmented, Tick } from "../ui";
import { dateRange, fmt, fmtStamp, isoToday, plural } from "../util";
import { inr } from "./Fees";

const MARK = { P: "Present", A: "Absent", L: "Leave", H: "Holiday" };

function Attendance() {
  const [month, setMonth] = useState(isoToday().slice(0, 7));
  const [d, setD] = useState(null);
  useEffect(() => { api.get(`/parent/attendance?month=${month}`).then((r) => r.success && setD(r)); }, [month]);
  if (!d) return <p className="empty">Loading…</p>;
  const s = d.summary;
  const shift = (n) => { const [y, m] = month.split("-").map(Number); const x = new Date(y, m - 1 + n, 1); setMonth(`${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}`); };
  return (
    <>
      <section className={`panel pad pp-hero ${s && !s.eligible ? "low" : ""}`}>
        <span className="muted small">This semester (since {fmt(d.start, { day: "numeric", month: "short" })})</span>
        <b>{s?.percentage ?? "–"}{s?.percentage != null && "%"}</b>
        {s ? (
          <>
            <p>{s.present} present · {s.absent} absent{s.leave ? ` · ${s.leave} on leave` : ""}</p>
            <p className={`chip ${s.eligible ? "ok" : "no"}`}>
              {s.percentage == null ? "No classes yet" : s.eligible
                ? (s.can_miss ? `Above the ${d.minimum}% needed for exams. Can miss ${s.can_miss} more class${s.can_miss === 1 ? "" : "es"} and stay above it.` : `Just at the ${d.minimum}% needed for exams.`)
                : `Below the ${d.minimum}% needed for exams. Must attend the next ${s.need} classes in a row to get back to it.`}
            </p>
          </>
        ) : <p className="muted">No attendance yet.</p>}
      </section>

      <section className="panel">
        <div className="panel-head month-nav">
          <button className="icon-btn" onClick={() => shift(-1)} aria-label="Previous month">‹</button>
          <h2>{new Date(`${month}-01T00:00`).toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</h2>
          <button className="icon-btn" onClick={() => shift(1)} disabled={month >= isoToday().slice(0, 7)} aria-label="Next month">›</button>
        </div>
        {d.days.length ? (
          <ul className="pp-days">
            {d.days.map((day, i) => (
              <li key={day} className={`m-${d.marks[i] || "none"}`} title={`${fmt(day, { weekday: "long", day: "numeric", month: "short" })}: ${MARK[d.marks[i]] || "Not marked"}`}>
                <small>{fmt(day, { weekday: "narrow" })}</small><b>{Number(day.slice(8))}</b><span>{d.marks[i] || "–"}</span>
              </li>
            ))}
          </ul>
        ) : <p className="empty">No classes recorded this month.</p>}
        <p className="muted small pad legend"><span className="m-P">P</span> present <span className="m-A">A</span> absent <span className="m-L">L</span> leave <span className="m-H">H</span> holiday</p>
      </section>
    </>
  );
}

// IT Hub: attendance is kept per course, so one card per course the student joined.
function CourseAttendance() {
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/parent/attendance").then((r) => r.success && setD(r)); }, []);
  if (!d) return <p className="empty">Loading…</p>;
  if (!d.courses.length) return <section className="panel"><p className="empty">You haven't joined a course yet.</p></section>;
  return d.courses.map(({ course, summary: s, recent }) => (
    <section key={course} className={`panel pad pp-hero pp-course ${s && s.percentage != null && !s.eligible ? "low" : ""}`}>
      <span className="muted small">{course} · since {fmt(d.start, { day: "numeric", month: "short" })}</span>
      <b>{s?.percentage ?? "–"}{s?.percentage != null && "%"}</b>
      {s && s.percentage != null ? (
        <>
          <p>{s.present} present · {s.absent} absent{s.leave ? ` · ${s.leave} on leave` : ""}</p>
          <p className={`chip ${s.eligible ? "ok" : "no"}`}>
            {s.eligible
              ? (s.can_miss ? `Above the ${d.minimum}% needed. You can miss ${s.can_miss} more class${s.can_miss === 1 ? "" : "es"} and stay above it.` : `Just at the ${d.minimum}% needed.`)
              : `Below the ${d.minimum}% needed. Attend the next ${s.need} classes in a row to get back to it.`}
          </p>
        </>
      ) : <p className="muted">No classes yet.</p>}
      {recent.length > 0 && (
        <ul className="pp-recent">
          {recent.map((r) => (
            <li key={r.date} className={`m-${r.status[0]}`} title={`${fmt(r.date, { weekday: "long", day: "numeric", month: "short" })}: ${r.status}`}>
              <span>{fmt(r.date, { day: "numeric", month: "short" })}</span><b>{r.status}</b>
            </li>
          ))}
        </ul>
      )}
    </section>
  ));
}

function Results() {
  const [list, setList] = useState(null);
  useEffect(() => { api.get("/parent/results").then((r) => setList(r.success ? r.results : [])); }, []);
  if (!list) return <p className="empty">Loading…</p>;
  if (!list.length) return <section className="panel"><p className="empty">{isHub() ? "No test results yet." : "No exam results yet."}</p></section>;
  return list.map((x) => (
    <section key={x.exam + x.date} className="panel pad pp-result">
      <div className="pp-result-head">
        <h2 className="h2">{x.exam}{x.course && <span className="muted small"> · {x.course}</span>}</h2>
        <span className="muted">{x.date ? fmt(x.date, { day: "numeric", month: "short", year: "numeric" }) : ""}</span>
      </div>
      <table className="mini">
        <tbody>
          {x.subjects.filter((s) => x.marks[s.name] !== undefined).map((s) => (
            <tr key={s.name}><td>{s.name}</td><td className={x.marks[s.name] === "AB" ? "ab" : ""}>{x.marks[s.name] === "AB" ? "Absent" : x.marks[s.name]} / {s.max}</td></tr>
          ))}
          <tr className="total"><td>Total</td><td>{x.total} / {x.max_total} ({x.percentage}%)</td></tr>
        </tbody>
      </table>
    </section>
  ));
}

function Leave({ toast }) {
  const [list, setList] = useState([]);
  const [f, setF] = useState({ start_date: "", end_date: "", reason: "" });
  const [busy, setBusy] = useState(false);
  const load = async () => { const r = await api.get("/parent/leaves"); if (r.success) setList(r.leaves); };
  useEffect(() => { load(); }, []);
  const send = async (e) => {
    e.preventDefault();
    setBusy(true);
    const r = await api.post("/parent/leaves", { ...f, end_date: f.end_date || f.start_date });
    setBusy(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setF({ start_date: "", end_date: "", reason: "" }); load(); }
  };
  const label = { pending: ["warn", "Waiting"], approved: ["ok", "Approved"], rejected: ["no", "Not approved"] };
  return (
    <>
      <form className="panel pad pp-apply" onSubmit={send}>
        <h2 className="h2">Apply for leave</h2>
        <div className="fields">
          <Field id="pp-from" label="First day" type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} required />
          <Field id="pp-to" label="Last day" type="date" min={f.start_date} value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} hint="Empty = one day." />
          <Field id="pp-why" wide as="textarea" rows={3} label="Reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} maxLength={500} required
            placeholder="e.g. Fever, the doctor advised two days of rest" />
        </div>
        <button className="btn primary" disabled={busy || !f.start_date || f.reason.trim().length < 5}><Icon name="send" size={18} />{busy ? "Sending…" : isHub() ? "Send to your teacher" : "Send to the class teacher"}</button>
      </form>
      <section className="panel">
        <div className="panel-head"><h2>Leave records</h2></div>
        {list.length ? (
          <ul className="pp-leaves">
            {list.map((lv) => (
              <li key={lv.id}>
                <div><strong>{dateRange(lv.start_date, lv.end_date)}</strong> <span className="muted">· {plural(lv.days, "day")}</span>
                  <p className="pre">{lv.reason}</p>
                  {lv.note && <p className="small"><strong>Teacher's note:</strong> {lv.note}</p>}
                  <p className="muted small">{lv.source === "parent" ? "Applied by you" : "Recorded by the college"} · {fmtStamp(lv.created_at)}</p>
                </div>
                <span className={`chip ${label[lv.status][0]}`}>{label[lv.status][1]}</span>
              </li>
            ))}
          </ul>
        ) : <p className="empty">No leave yet.</p>}
      </section>
    </>
  );
}

function Fees() {
  const [list, setList] = useState(null);
  useEffect(() => { api.get("/parent/fees").then((r) => setList(r.success ? r.fees : [])); }, []);
  if (!list) return <p className="empty">Loading…</p>;
  if (!list.length) return <section className="panel"><p className="empty">No fees are listed.</p></section>;
  const label = { paid: ["ok", "Paid"], overdue: ["no", "Overdue"], due_soon: ["warn", "Due soon"], partial: ["warn", "Part paid"], unpaid: ["", "Not paid"] };
  return (
    <section className="panel">
      <ul className="pp-leaves">
        {list.map((x) => (
          <li key={x.title}>
            <div><strong>{x.title}</strong>{x.course && <span className="muted small"> · {x.course}</span>}
              <p>{x.balance ? `${inr(x.balance)} due by ${fmt(x.due_date, { day: "numeric", month: "short", year: "numeric" })}` : `Paid ${inr(x.amount)}${x.paid_on ? ` on ${fmt(x.paid_on, { day: "numeric", month: "short" })}` : ""}`}</p>
              {x.paid_amount > 0 && x.balance > 0 && <p className="muted small">Paid so far: {inr(x.paid_amount)} of {inr(x.amount)}</p>}
            </div>
            <span className={`chip ${label[x.status][0]}`}>{label[x.status][1]}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function ParentPortal({ onLogout }) {
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("attendance");
  const [toasts, setToasts] = useState([]);
  const toast = (msg, kind = "ok") => { const id = Date.now(); setToasts((t) => [...t, { id, msg, kind }]); setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000); };
  useEffect(() => { api.get("/parent/me").then((r) => (r.success ? setMe(r.student) : r.status === 401 || r.status === 403 ? onLogout() : null)); }, [onLogout]);
  if (!me) return <main className="pp"><p className="empty">Loading…</p></main>;
  return (
    <main className="pp">
      <header className="pp-top">
        <span className="brand-mark"><Tick size={18} /></span>
        <div className="grow">
          <strong>{me.name}</strong>
          <small>{[me.reg_no && `Reg. No ${me.reg_no}`, isHub() ? (me.courses || []).join(", ") : me.branch, me.class_name].filter(Boolean).join(" · ")}</small>
        </div>
        <button className="btn ghost small-btn" onClick={onLogout}><Icon name="logout" size={16} />Log out</button>
      </header>
      <div className="pp-body">
        {me.school && <p className="muted small">{me.school} · {isHub() ? "Student view" : "Parent view"} (read only)</p>}
        <div className="tabbar">
          <Segmented value={tab} onChange={setTab} label="Section" options={[
            { id: "attendance", label: "Attendance" }, { id: "results", label: "Results" },
            { id: "leave", label: "Leave" }, { id: "fees", label: "Fees" },
          ]} />
        </div>
        {tab === "attendance" && (isHub() ? <CourseAttendance /> : <Attendance />)}
        {tab === "results" && <Results />}
        {tab === "leave" && <Leave toast={toast} />}
        {tab === "fees" && <Fees />}
      </div>
      <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={`toast${t.kind === "bad" ? " bad" : ""}`}>{t.msg}</div>)}</div>
    </main>
  );
}

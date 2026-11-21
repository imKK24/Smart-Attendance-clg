// Admin only: fees per student, payments, and WhatsApp / email reminders to parents.
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { isHub, unit } from "../org";
import { ChannelPicker, Face, Field, Icon, PageHead, SearchBox, Segmented } from "../ui";
import { fmt, fmtStamp, isoToday, plural } from "../util";

export const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const STATUS = {
  paid: ["ok", "Paid"], overdue: ["no", "Overdue"], due_soon: ["warn", "Due soon"],
  partial: ["warn", "Part paid"], unpaid: ["", "Not paid"],
};
const EMPTY = { title: "", amount: "", due_date: "", branch: "", class_name: "" };

function Settings({ avail, toast }) {
  const [s, setS] = useState(null);
  useEffect(() => { api.get("/fees/settings").then((r) => r.success && setS(r)); }, []);
  if (!s) return null;
  const save = async (patch) => {
    const next = { ...s, ...patch };
    setS(next);
    const r = await api.post("/fees/settings", next);
    toast(r.message, r.success ? "ok" : "bad");
  };
  return (
    <section className="panel pad fee-auto">
      <label className="check"><input type="checkbox" checked={s.fee_auto} onChange={(e) => save({ fee_auto: e.target.checked })} />
        <strong>Send reminders automatically</strong></label>
      <p className="muted small">Once a day after 9 AM, while the server is running.</p>
      <div className="fields">
        <Field id="fa-before" label="First reminder, days before due" type="number" min={0} max={30} value={s.fee_days_before}
          onChange={(e) => setS({ ...s, fee_days_before: e.target.value })} onBlur={() => save({})} />
        <Field id="fa-repeat" label="Then repeat every (days)" type="number" min={1} max={30} value={s.fee_repeat_days}
          onChange={(e) => setS({ ...s, fee_repeat_days: e.target.value })} onBlur={() => save({})} />
      </div>
      <ChannelPicker value={s.fee_channels} onChange={(fee_channels) => save({ fee_channels })} status={avail} />
      {s.fee_auto && <p className="muted small">{s.due_today ? `${plural(s.due_today, "student")} will be reminded at the next daily check.` : "Nobody needs a reminder today."}</p>}
    </section>
  );
}

function PayCell({ fee, onPay }) {
  const [amount, setAmount] = useState("");
  const [open, setOpen] = useState(false);
  if (fee.status === "paid") return null;
  if (!open) return <button className="btn ghost small-btn" onClick={() => setOpen(true)}>Part payment</button>;
  return (
    <form className="part-pay" onSubmit={(e) => { e.preventDefault(); onPay(fee, { amount }); setOpen(false); setAmount(""); }}>
      <input type="number" min={1} max={fee.balance} step="any" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="₹" aria-label="Amount paid" autoFocus />
      <button className="btn primary small-btn" disabled={!amount}>Add</button>
      <button type="button" className="icon-btn" aria-label="Cancel" onClick={() => setOpen(false)}><Icon name="x" size={14} /></button>
    </form>
  );
}

export default function FeesPage({ students, branches, classes, ids, toast, askConfirm, avail, onQueued, course }) {
  const hub = isHub();   // IT Hub: a fee is for the students of one course
  const [data, setData] = useState({ fees: [], groups: [] });
  const [open, setOpen] = useState("");
  const [f, setF] = useState(EMPTY);
  const [show, setShow] = useState("all");
  const [q, setQ] = useState("");
  const [ch, setCh] = useState(() => (avail.wa === "open" || !avail.email ? ["whatsapp", ...(avail.email ? ["email"] : [])] : ["email"]));
  const load = async () => { const r = await api.get("/fees"); if (r.success) setData(r); };
  useEffect(() => { load(); }, []);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  // IT Hub: the course's price and name fill in the fee (you can still change them)
  const [prices, setPrices] = useState({});
  useEffect(() => {
    if (hub) api.get("/courses").then((r) => r.success && setPrices(Object.fromEntries(r.courses.map((c) => [c.name, c.price]))));
  }, [hub]);
  const fillFromCourse = (name, x) => ({
    ...x, branch: name,
    amount: prices[name] ? String(prices[name]) : x.amount,
    title: !x.title || Object.keys(prices).some((c) => x.title === `${c} course fee`) ? (name ? `${name} course fee` : x.title) : x.title,
  });
  useEffect(() => {
    if (hub && course && (!f.branch || (!f.amount && prices[f.branch]))) setF((x) => fillFromCourse(x.branch || course, x));
  }, [hub, course, f.branch, f.amount, prices]); // eslint-disable-line react-hooks/exhaustive-deps
  const matches = useMemo(() => students.filter((s) => (!f.branch || (hub ? (s.courses || []).includes(f.branch) : s.branch === f.branch))
    && (!f.class_name || s.class_name === f.class_name)).length, [students, f.branch, f.class_name, hub]);
  const create = async () => {
    const body = hub ? { ...f, branch: "", course: f.branch, amount: Number(f.amount) } : { ...f, amount: Number(f.amount) };
    const r = await api.post("/fees", body);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setOpen(f.title.trim()); setF(EMPTY); load(); }
  };
  const pay = async (fee, body) => { const r = await api.post(`/fees/${fee.id}/pay`, body); toast(r.message, r.success ? "ok" : "bad"); load(); };
  const remind = (body, n) => askConfirm({
    title: `Send ${plural(n, "reminder")}?`, body: `Parents get the amount due and the due date by ${ch.join(" and ")}.`, label: "Send",
    onYes: async () => { const r = await api.post("/fees/remind", { ...body, channels: ch }); toast(r.message, r.success ? "ok" : "bad"); if (r.success) { onQueued(); setTimeout(load, 3000); } },
  });

  const group = data.groups.find((g) => g.title === open);
  const rows = data.fees.filter((x) => x.title === open && (show === "all" || (show === "unpaid" ? x.status !== "paid" : x.status === show))
    && (!q || `${x.name} ${x.roll_no}`.toLowerCase().includes(q.toLowerCase())));
  const unpaidCount = data.fees.filter((x) => x.title === open && x.status !== "paid").length;
  const overdueCount = data.fees.filter((x) => x.title === open && x.status === "overdue").length;

  if (group) {
    return (
      <>
        <PageHead title={group.title} sub={`Due ${fmt(group.due_date, { day: "numeric", month: "long", year: "numeric" })} · ${inr(group.collected)} of ${inr(group.total)} collected`}>
          <button className="btn ghost" onClick={() => setOpen("")}>← All fees</button>
        </PageHead>
        <section className="panel">
          <div className="panel-head">
            <Segmented value={show} onChange={setShow} label="Show" options={[
              { id: "all", label: "All", count: group.students }, { id: "unpaid", label: "Not paid", count: unpaidCount },
              { id: "overdue", label: "Overdue", count: overdueCount }, { id: "paid", label: "Paid", count: group.paid },
            ]} />
            <div className="tools">
              <SearchBox value={q} onChange={setQ} placeholder="Name or registration no" />
              <ChannelPicker value={ch} onChange={setCh} status={avail} />
              <button className="btn primary" disabled={!unpaidCount || !ch.length} onClick={() => remind({ title: group.title }, unpaidCount)}>
                <Icon name="send" size={18} />Remind {unpaidCount} unpaid
              </button>
            </div>
          </div>
          <div className="table-wrap">
            <table className="marks fees">
              <thead><tr><th>Student</th><th>Amount</th><th>Paid</th><th>Balance</th><th>Status</th><th>Reminders</th><th /></tr></thead>
              <tbody>
                {rows.map((x) => (
                  <tr key={x.id}>
                    <td><span className="fee-who"><Face name={x.name} id={ids[x.name]} size={30} /><span>{x.name}<small>{[x.roll_no, x.course || x.branch].filter(Boolean).join(" · ")}</small></span></span></td>
                    <td>{inr(x.amount)}</td>
                    <td>{inr(x.paid_amount)}{x.paid_on && <small className="muted"> on {fmt(x.paid_on, { day: "numeric", month: "short" })}</small>}</td>
                    <td><strong>{inr(x.balance)}</strong></td>
                    <td><span className={`chip tiny ${STATUS[x.status][0]}`}>{STATUS[x.status][1]}</span></td>
                    <td className="muted small">{x.reminders_sent ? `${x.reminders_sent} · last ${fmtStamp(x.last_reminded_at)}` : x.has_contact ? "None yet" : "No contact"}</td>
                    <td>
                      <span className="fee-actions">
                        {x.status !== "paid" && <button className="btn ghost small-btn" onClick={() => pay(x, { full: true })}><Icon name="check" size={16} />Paid in full</button>}
                        <PayCell fee={x} onPay={pay} />
                        {x.status !== "paid" && x.has_contact && <button className="btn ghost small-btn" disabled={!ch.length} onClick={() => remind({ ids: [x.id] }, 1)}>Remind</button>}
                        {x.paid_amount > 0 && <button className="link small" onClick={async () => { await api.post(`/fees/${x.id}/undo`); load(); }}>Undo payment</button>}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!rows.length && <p className="empty">No one here.</p>}
        </section>
        <p className="gap-top">
          <button className="link" onClick={() => askConfirm({
            title: `Delete "${group.title}" for everyone?`, body: "All payments recorded for this fee are deleted too.", label: "Delete fee", danger: true,
            onYes: async () => { const r = await api.post("/fees/delete-title", { title: group.title }); toast(r.message, r.success ? "ok" : "bad"); setOpen(""); load(); },
          })}>Delete this fee</button>
        </p>
      </>
    );
  }

  return (
    <>
      <PageHead title="Fees" sub={hub ? "Add a course fee for everyone in a course at once, mark who has paid, and send reminders on WhatsApp or email."
        : "Add a fee for a whole class at once, mark who has paid, and remind parents on WhatsApp or email."} />
      <div className="events">
        <div className="side-col">
          <section className="panel pad ev-form">
            <h2 className="h2">Add a fee</h2>
            <div className="fields">
              <Field id="fee-title" wide label="Fee name" value={f.title} onChange={set("title")} placeholder={hub ? "e.g. Python course fee" : "e.g. Semester 6 tuition"} maxLength={80} />
              <Field id="fee-amt" label="Amount (₹)" type="number" min={1} value={f.amount} onChange={set("amount")} inputMode="decimal" />
              <Field id="fee-due" label="Due date" type="date" min={isoToday()} value={f.due_date} onChange={set("due_date")} />
              <Field id="fee-branch" label={unit()}>
                <select id="fee-branch" value={f.branch} onChange={hub ? (e) => setF(fillFromCourse(e.target.value, f)) : set("branch")}>
                  <option value="">{hub ? "Every student" : "All branches"}</option>{branches.map((b) => <option key={b}>{b}</option>)}
                </select>
              </Field>
              <Field id="fee-class" label={hub ? "Batch / timing" : "Semester / section"}>
                <select id="fee-class" value={f.class_name} onChange={set("class_name")}>
                  <option value="">All</option>{classes.map((b) => <option key={b}>{b}</option>)}
                </select>
              </Field>
            </div>
            <button className="btn primary" disabled={!f.title.trim() || !(Number(f.amount) > 0) || !f.due_date || !matches} onClick={create}>
              <Icon name="plus" />Add for {plural(matches, "student")}
            </button>
          </section>
          <Settings avail={avail} toast={toast} />
        </div>
        <section className="ev-list">
          {data.groups.length ? data.groups.map((g) => {
            const pct = g.total ? Math.round((g.collected / g.total) * 100) : 0;
            return (
              <article key={g.title} className="panel ev fee-card">
                <div className="ev-date"><b>{Number(g.due_date.slice(8))}</b><span>{fmt(g.due_date, { month: "short" })}</span></div>
                <button className="ev-main as-card" onClick={() => { setOpen(g.title); setShow("all"); setQ(""); }}>
                  <h3>{g.title}</h3>
                  <p className="muted">{inr(g.collected)} of {inr(g.total)} collected · {g.paid} of {g.students} paid</p>
                  <span className="fee-bar" aria-label={`${pct}% collected`}><i style={{ width: `${pct}%` }} /></span>
                  {g.overdue > 0 && <span className="chip no tiny">{g.overdue} overdue</span>}
                </button>
                <div className="ev-actions">
                  <button className="btn ghost" onClick={() => { setOpen(g.title); setShow(g.overdue ? "overdue" : "unpaid"); }}>Open</button>
                </div>
              </article>
            );
          }) : <section className="panel"><p className="empty">No fees yet. Add one on the left: it's created for every matching student at once.</p></section>}
        </section>
      </div>
    </>
  );
}

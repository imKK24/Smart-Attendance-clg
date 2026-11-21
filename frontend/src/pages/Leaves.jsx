import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ChannelPicker, Face, Field, Icon, PageHead, Segmented } from "../ui";
import { dateRange, fmtStamp, plural } from "../util";

const EMPTY = { student_id: "", start_date: "", end_date: "", reason: "", inbox_id: null, approve: true };

export default function LeavesPage({ students, ids, toast, askConfirm, draft, clearDraft, onChanged, avail, onQueued, go }) {
  const [list, setList] = useState([]);
  const [pending, setPending] = useState(0);
  const [show, setShow] = useState("pending");
  const [f, setF] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [notify, setNotify] = useState(() => (avail.wa === "open" || !avail.email ? ["whatsapp"] : ["email"]));
  const sorted = useMemo(() => [...students].sort((a, b) => a.name.localeCompare(b.name)), [students]);

  const load = async () => {
    const r = await api.get(`/leaves${show === "all" ? "" : `?status=${show}`}`);
    if (r.success) { setList(r.leaves); setPending(r.pending); }
  };
  useEffect(() => { load(); }, [show]); // eslint-disable-line react-hooks/exhaustive-deps

  // Coming from an email in the Inbox: fill the form with it.
  useEffect(() => {
    if (!draft) return;
    setF({ ...EMPTY, approve: false, student_id: draft.student_id ? String(draft.student_id) : "", reason: draft.reason || "", inbox_id: draft.inbox_id || null });
    clearDraft();
  }, [draft, clearDraft]);

  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const save = async () => {
    setSaving(true);
    const r = await api.post("/leaves", { ...f, student_id: Number(f.student_id), end_date: f.end_date || f.start_date });
    setSaving(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setF(EMPTY); setShow(f.approve ? "approved" : "pending"); load(); onChanged(); }
  };
  const decide = async (lv, status) => {
    const r = await api.post(`/leaves/${lv.id}/decide`, { status, notify: lv.has_contact ? notify : [] });
    toast(r.message, r.success ? "ok" : "bad");
    if (r.queued) onQueued();
    load(); onChanged();
  };
  const remove = (lv) => askConfirm({
    title: `Delete this leave for ${lv.name}?`, body: lv.status === "approved" ? "Those days go back to Absent." : "The request is removed.",
    label: "Delete", danger: true, onYes: async () => { const r = await api.del(`/leaves/${lv.id}`); toast(r.message, r.success ? "ok" : "bad"); load(); onChanged(); },
  });

  return (
    <>
      <PageHead title="Leave" sub="Approved leave shows as Leave instead of Absent. It doesn't trigger absence alerts and doesn't lower exam eligibility." />
      <div className="events">
        <section className="panel pad ev-form">
          <h2 className="h2">{f.inbox_id ? "Leave from a parent's email" : "Record a leave"}</h2>
          {f.inbox_id && <p className="note small">Filled in from the email. Check the student and dates. <button className="link" onClick={() => go("inbox", f.inbox_id)}>Open the email</button></p>}
          <div className="fields">
            <Field id="lv-student" wide label="Student">
              <select id="lv-student" value={f.student_id} onChange={set("student_id")}>
                <option value="">Choose a student</option>
                {sorted.map((s) => <option key={s.id} value={s.id}>{s.name}{s.roll_no ? ` (${s.roll_no})` : ""}</option>)}
              </select>
            </Field>
            <Field id="lv-from" label="First day" type="date" value={f.start_date} onChange={set("start_date")} />
            <Field id="lv-to" label="Last day" type="date" min={f.start_date} value={f.end_date} onChange={set("end_date")} hint="Empty = one day." />
            <Field id="lv-reason" wide as="textarea" rows={3} label="Reason" value={f.reason} onChange={set("reason")} maxLength={500} placeholder="e.g. Fever, doctor advised 2 days rest" />
          </div>
          <label className="check"><input type="checkbox" checked={f.approve} onChange={set("approve")} />Approve now</label>
          <button className="btn primary" disabled={saving || !f.student_id || !f.start_date || !f.reason.trim()} onClick={save}>
            <Icon name="check" />{f.approve ? "Save and approve" : "Save as pending"}
          </button>
          <p className="muted small">Leave can be for past days (absent rows change to Leave) or future days.</p>
        </section>

        <section className="ev-list">
          <div className="ev-tools">
            <Segmented value={show} onChange={setShow} label="Show" options={[
              { id: "pending", label: "Waiting", count: pending || undefined },
              { id: "approved", label: "Approved" }, { id: "rejected", label: "Rejected" }, { id: "all", label: "All" },
            ]} />
            <ChannelPicker value={notify} onChange={setNotify} status={avail} />
          </div>
          {list.length ? list.map((lv) => (
            <article key={lv.id} className="panel ev leave">
              <Face name={lv.name} id={ids[lv.name]} size={48} />
              <div className="ev-main">
                <h3>{lv.name} <span className="muted small">{lv.roll_no}</span></h3>
                <p><strong>{dateRange(lv.start_date, lv.end_date)}</strong> <span className="muted">· {plural(lv.days, "day")}</span></p>
                <p className="pre">{lv.reason}</p>
                <p className="muted small">
                  {lv.source === "parent" ? "Applied by the parent online" : lv.source === "student" ? "Applied by the student online" : lv.source === "email" ? <>From a parent's email{lv.inbox_id && <> · <button className="link" onClick={() => go("inbox", lv.inbox_id)}>open</button></>}</> : "Added by admin"}
                  {lv.decided_at && ` · ${lv.status} ${fmtStamp(lv.decided_at)}`}
                </p>
              </div>
              <div className="ev-actions">
                {lv.status === "pending" ? (
                  <>
                    <button className="btn primary" onClick={() => decide(lv, "approved")}><Icon name="check" size={18} />Approve</button>
                    <button className="btn ghost" onClick={() => decide(lv, "rejected")}>Reject</button>
                  </>
                ) : <span className={`chip ${lv.status === "approved" ? "ok" : "no"}`}>{lv.status === "approved" ? "Approved" : "Rejected"}</span>}
                <button className="icon-btn" aria-label={`Delete leave for ${lv.name}`} onClick={() => remove(lv)}><Icon name="trash" size={18} /></button>
              </div>
            </article>
          )) : <section className="panel"><p className="empty">{show === "pending" ? "No leave requests waiting." : "Nothing here."}</p></section>}
          {notify.length > 0 && <p className="muted small">When you approve or reject, the parent is told by {notify.map((c) => (c === "whatsapp" ? "WhatsApp" : "email")).join(" and ")}.</p>}
        </section>
      </div>
    </>
  );
}

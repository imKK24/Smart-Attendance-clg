import { useEffect, useState } from "react";
import { api } from "../api";
import { Face, Icon, PageHead, SearchBox, Segmented, Tick } from "../ui";
import { ago, fmtStamp } from "../util";
import WaChats from "./WaChats";

function MailView({ id, ids, onBack, toast, onChanged, go }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const load = async () => {
    const r = await api.get(`/inbox/${id}`);
    setData(r.success ? r : { error: r.message });
    onChanged();
  };
  useEffect(() => { setData(null); setText(""); load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Refresh while a reply is still being sent
  const pending = data?.replies?.some((r) => r.status === "queued");
  useEffect(() => {
    if (!pending) return undefined;
    const t = setTimeout(load, 2000);
    return () => clearTimeout(t);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  if (!data) return <section className="panel pad mail-view"><p className="muted">Loading…</p></section>;
  if (data.error) return <section className="panel pad mail-view"><p className="muted">{data.error}</p></section>;
  const m = data.mail;
  const send = async () => {
    setSending(true);
    const r = await api.post(`/inbox/${id}/reply`, { text });
    setSending(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setText(""); load(); }
  };
  return (
    <section className="panel mail-view" aria-label="Email">
      <div className="mv-head">
        <button className="btn ghost back" onClick={onBack}>← All emails</button>
        <h2>{m.subject}</h2>
        <p><strong>{m.from_name || m.from_email}</strong> <span className="muted">&lt;{m.from_email}&gt; · {fmtStamp(m.received_at)}</span></p>
        {m.children.length > 0 && (
          <div className="chips">{m.children.map((c) => (
            <span key={c.id} className="chip kid"><Face name={c.name} id={ids[c.name]} size={20} />Parent of {c.name}{c.roll_no && ` (${c.roll_no})`}</span>
          ))}</div>
        )}
      </div>
      <div className="mv-actions">
        <button className="btn ghost" onClick={() => go("leaves", { student_id: m.children.length === 1 ? m.children[0].id : "", inbox_id: m.id, reason: `${m.subject}\n\n${m.body}`.slice(0, 500) })}>
          <Icon name="calendar" size={18} />Record as leave
        </button>
      </div>
      <div className="mv-body">{m.body || <span className="muted">(This email has no text.)</span>}</div>
      {data.replies.map((r, i) => (
        <div key={i} className={`my-reply${r.status === "failed" ? " failed" : ""}`}>
          <p className="muted small">
            {r.status === "sent" ? <><Tick size={12} /> You replied {fmtStamp(r.sent_at)}</> : r.status === "queued" ? "Sending…" : `Not sent: ${r.error}`}
          </p>
          <div className="pre">{r.body}</div>
        </div>
      ))}
      <div className="reply-box">
        <label htmlFor="reply" className="small muted">Reply to {m.from_name || m.from_email}</label>
        <textarea id="reply" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="Write your reply…" maxLength={10000} />
        <div className="reply-actions">
          <button className="btn primary" onClick={send} disabled={sending || !text.trim()}><Icon name="send" size={18} />{sending ? "Sending…" : "Send reply"}</button>
        </div>
      </div>
    </section>
  );
}

export default function InboxPage({ inbox, reload, openId, setOpenId, ids, toast, go, chats, reloadChats, waState, openPhone, setOpenPhone, channel, setChannel }) {
  const [show, setShow] = useState("all");
  const [q, setQ] = useState("");
  const [checking, setChecking] = useState(false);

  const check = async () => {
    setChecking(true);
    const r = await api.post("/inbox/sync");
    setChecking(false);
    toast(r.message, r.success ? "ok" : "bad");
    reload();
  };

  const needle = q.trim().toLowerCase();
  const list = inbox.mails.filter((m) => (show === "all" || !m.is_read) && (!needle ||
    [m.from_name, m.from_email, m.subject, m.preview, ...m.children.map((c) => c.name)].join(" ").toLowerCase().includes(needle)));

  const tabs = (
    <div className="tabbar">
      <Segmented value={channel} onChange={setChannel} label="Channel" options={[
        { id: "email", icon: "mail", label: "Email", count: inbox.unread || undefined },
        { id: "whatsapp", icon: "chat", label: "WhatsApp", count: chats.unread || undefined },
      ]} />
    </div>
  );
  if (channel === "whatsapp") {
    return (
      <>
        <PageHead title="Inbox" sub="WhatsApp messages from parents whose number is saved on a student. Your replies go from the school's WhatsApp." />
        {tabs}
        <WaChats chats={chats} reload={reloadChats} ids={ids} toast={toast} waState={waState} go={go} openPhone={openPhone} setOpenPhone={setOpenPhone} />
      </>
    );
  }

  return (
    <>
      <PageHead title="Inbox" sub="Emails from parents whose address is saved on a student. Replies go out from your Gmail in the same thread.">
        <button className="btn ghost" onClick={check} disabled={checking || !inbox.configured}><Icon name="retake" size={18} />{checking ? "Checking…" : "Check Gmail now"}</button>
      </PageHead>
      {tabs}
      {!inbox.configured && (
        <div className="banner" role="alert">Gmail isn't set up yet. <button className="link" onClick={() => go("notify:settings")}>Set up Gmail</button> (the same App Password is used to read and send).</div>
      )}
      {inbox.sync?.error && <div className="banner" role="alert">{inbox.sync.error}</div>}
      <div className={`inbox${openId ? " reading" : ""}`}>
        <section className="panel mail-list">
          <div className="panel-head">
            <Segmented value={show} onChange={setShow} label="Show" options={[{ id: "all", label: "All" }, { id: "unread", label: "Unread", count: inbox.unread }]} />
            <SearchBox value={q} onChange={setQ} placeholder="Search emails" />
          </div>
          {list.length ? (
            <ul className="mails">
              {list.map((m) => (
                <li key={m.id}>
                  <button className={`${m.is_read ? "" : "unread"}${openId === m.id ? " on" : ""}`} onClick={() => setOpenId(m.id)} aria-current={openId === m.id || undefined}>
                    {m.children[0] ? <Face name={m.children[0].name} id={ids[m.children[0].name]} size={38} /> : <span className="face" style={{ width: 38, height: 38 }} />}
                    <span className="ml-main">
                      <span className="ml-top"><strong>{m.from_name || m.from_email}</strong><span className="mm-time">{ago(m.received_at)}</span></span>
                      <span className="ml-subj">{m.subject}</span>
                      <span className="ml-prev">{m.children.length ? `Parent of ${m.children.map((c) => c.name).join(", ")} · ` : ""}{m.preview}</span>
                    </span>
                    {m.replied_at && <span className="chip ok tiny" title={`Replied ${fmtStamp(m.replied_at)}`}><Tick size={12} /></span>}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">{inbox.mails.length ? "No emails match." : "No parent emails yet. Make sure parents' email addresses are saved on the Students page."}</p>
          )}
          <p className="muted small sync-line">{inbox.sync?.last_sync ? `Last checked ${ago(inbox.sync.last_sync)}. Gmail is checked every 5 minutes.` : "Gmail is checked every 5 minutes."}</p>
        </section>
        {openId ? <MailView id={openId} ids={ids} onBack={() => setOpenId(null)} toast={toast} onChanged={reload} go={go} />
          : <section className="panel mail-view empty-view"><p className="empty">Pick an email to read and reply.</p></section>}
      </div>
    </>
  );
}

// WhatsApp conversations with parents: their replies come in through the bridge,
// you answer from here. Only numbers saved on a student appear.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Face, Icon, SearchBox } from "../ui";
import { ago, fmtStamp } from "../util";

const KIND = { photo: "📷 Photo", video: "🎬 Video", voice: "🎤 Voice note", document: "📄 Document", sticker: "Sticker", location: "📍 Location", other: "Message" };
const label = (m) => m.text || KIND[m.kind] || "Message";
const pathOf = (phone) => phone.replace(/\D/g, "");

function Chat({ phone, ids, toast, onBack, onChanged }) {
  const [data, setData] = useState(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef(null);
  const load = async () => {
    const r = await api.get(`/whatsapp/chats/${pathOf(phone)}`);
    setData(r.success ? r : { error: r.message });
    onChanged();
  };
  useEffect(() => { setData(null); load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, [phone]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [data?.messages?.length]);

  if (!data) return <section className="panel mail-view"><p className="empty">Loading…</p></section>;
  if (data.error) return <section className="panel mail-view"><p className="empty">{data.error}</p></section>;
  const send = async (e) => {
    e.preventDefault();
    setSending(true);
    const r = await api.post(`/whatsapp/chats/${pathOf(phone)}/reply`, { text });
    setSending(false);
    if (!r.success) { toast(r.message, "bad"); return; }
    setText("");
    setTimeout(load, 1500);
  };
  return (
    <section className="panel mail-view wa-chat" aria-label={`Chat with ${data.name}`}>
      <div className="mv-head">
        <button className="btn ghost back" onClick={onBack}>← All chats</button>
        <h2>{data.name}</h2>
        <p className="muted">{data.phone} · {data.role}</p>
        <div className="chips">{data.students.map((s) => (
          <span key={s.id} className="chip kid"><Face name={s.name} id={ids[s.name]} size={20} />{s.name}{s.roll_no && ` (${s.roll_no})`}</span>
        ))}</div>
      </div>
      <ol className="bubbles">
        {data.messages.map((m, i) => (
          <li key={i} className={`bubble ${m.dir}${m.status === "failed" ? " failed" : ""}`}>
            {m.dir === "out" && m.kind !== "chat" && <span className="bubble-tag">{m.kind === "absence" ? "Absence alert" : m.kind === "fee" ? "Fee reminder" : m.kind === "result" ? "Exam result" : m.kind === "leave" ? "Leave" : m.kind}</span>}
            <span className="bubble-text">{label(m)}</span>
            <span className="bubble-time">
              {fmtStamp(m.at)}{m.dir === "out" && (m.status === "sent" ? " ✓" : m.status === "queued" ? " · sending" : ` · not sent: ${m.error}`)}
            </span>
          </li>
        ))}
        <li ref={end} aria-hidden="true" />
      </ol>
      <form className="wa-reply" onSubmit={send}>
        <label htmlFor="wa-text" className="sr-only">Reply on WhatsApp</label>
        <textarea id="wa-text" rows={2} value={text} onChange={(e) => setText(e.target.value)} placeholder="Reply on WhatsApp…" maxLength={3000}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && text.trim()) { e.preventDefault(); send(e); } }} />
        <button className="btn primary" disabled={sending || !text.trim()}><Icon name="send" size={18} />Send</button>
      </form>
    </section>
  );
}

export default function WaChats({ chats, reload, ids, toast, waState, go, openPhone, setOpenPhone }) {
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const list = chats.chats.filter((c) => !needle || [c.name, c.phone, c.wa_name, c.last_text, ...c.students.map((s) => s.name)].join(" ").toLowerCase().includes(needle));
  return (
    <>
      {waState !== "open" && <div className="banner" role="alert">WhatsApp isn't linked right now, so new replies can't come in and yours can't go out. <button className="link" onClick={() => go("notify:whatsapp")}>Open WhatsApp settings</button></div>}
      <div className={`inbox${openPhone ? " reading" : ""}`}>
        <section className="panel mail-list">
          <div className="panel-head"><SearchBox value={q} onChange={setQ} placeholder="Search chats" /></div>
          {list.length ? (
            <ul className="mails">
              {list.map((c) => (
                <li key={c.phone}>
                  <button className={`${c.unread ? "unread" : ""}${openPhone === c.phone ? " on" : ""}`} onClick={() => setOpenPhone(c.phone)}>
                    {c.students[0] ? <Face name={c.students[0].name} id={ids[c.students[0].name]} size={38} /> : <span className="face" style={{ width: 38, height: 38 }} />}
                    <span className="ml-main">
                      <span className="ml-top"><strong>{c.name}</strong><span className="mm-time">{ago(c.last_at)}</span></span>
                      <span className="ml-subj">{c.role}</span>
                      <span className="ml-prev">{c.last_dir === "out" ? "You: " : ""}{(/^\[(\w+)\]$/.exec(c.last_text) && KIND[/^\[(\w+)\]$/.exec(c.last_text)[1]]) || c.last_text}</span>
                    </span>
                    {c.unread > 0 && <b className="count" aria-label={`${c.unread} unread`}>{c.unread}</b>}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="empty">{chats.chats.length ? "No chat matches." : "No WhatsApp messages from parents yet. When a parent replies to an alert, it shows up here."}</p>}
          <button className="link sync-line" onClick={reload}>Refresh</button>
        </section>
        {openPhone ? <Chat phone={openPhone} ids={ids} toast={toast} onBack={() => setOpenPhone(null)} onChanged={reload} />
          : <section className="panel mail-view empty-view"><p className="empty">Pick a chat to read and reply.</p></section>}
      </div>
    </>
  );
}

import { unitLower, unitsLower } from "./org";
import { useEffect, useState } from "react";
import { mediaUrl } from "./api";
import { timeOf } from "./util";

// ─── ICONS ────────────────────────────────────────────────────────────────────
const ICONS = {
  shield: "M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3zM9 12l2 2 4-4",
  pin: "M12 21s-6-5.6-6-11a6 6 0 1112 0c0 5.4-6 11-6 11zM12 12.5a2.5 2.5 0 100-5 2.5 2.5 0 000 5",
  image: "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 9.5a1.5 1.5 0 100-.01",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  home: "M4 4h7v7H4zM13 4h7v4h-7zM13 11h7v9h-7zM4 14h7v6H4z",
  book: "M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3V4zM9 8h6M9 12h6",
  users: "M16 20v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 11a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM21 20v-1a4 4 0 00-3-3.9M16 4.1a3.5 3.5 0 010 6.8",
  plus: "M12 5v14M5 12h14",
  camera: "M4 8h3l2-3h6l2 3h3v11H4zM12 17a3.5 3.5 0 100-7 3.5 3.5 0 000 7z",
  x: "M6 6l12 12M18 6L6 18",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  download: "M12 4v11M7 11l5 5 5-5M5 20h14",
  search: "M11 18a7 7 0 100-14 7 7 0 000 14zM20 20l-4-4",
  upload: "M12 16V5M7 9l5-5 5 5M5 20h14",
  play: "M7 4l13 8-13 8z",
  stop: "M6 6h12v12H6z",
  eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM12 15a3 3 0 100-6 3 3 0 000 6z",
  user: "M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0",
  check: "M5 12.5l4.5 4.5L19 7.5",
  retake: "M20 11a8 8 0 10-2.3 5.7M20 4v7h-7",
  edit: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
  mail: "M3 6h18v12H3zM3 7l9 6 9-6",
  inbox: "M3 13l3-8h12l3 8v6H3zM3 13h5l1 2h6l1-2h5",
  bell: "M6 17v-6a6 6 0 1112 0v6l2 2H4zM10 21h4",
  chat: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5",
  send: "M4 12l16-8-6 16-2.5-6.5z",
  logout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10",
  sun: "M12 16a4 4 0 100-8 4 4 0 000 8zM12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  grade: "M4 19V5M4 19h16M8 15v-4M12 15V8M16 15v-6",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  fee: "M7 4h10M7 8h10M7 4c5 0 5 8 0 8h0l8 8",
};
export const Icon = ({ name, size = 20 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={ICONS[name]} />
  </svg>
);
export const Tick = ({ size = 14 }) => (
  <svg className="tick" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4.5 12.5l5 5L19.5 7" />
  </svg>
);

// ─── SMALL COMPONENTS ─────────────────────────────────────────────────────────
let PHOTO_VER = Date.now();
export const refreshPhotos = () => { PHOTO_VER = Date.now(); };

export function Face({ name, id, size = 40, fill = false }) {
  const [bad, setBad] = useState(false);
  const src = id ? mediaUrl(`/students/${id}/photo`, `&v=${PHOTO_VER}`) : "";
  useEffect(() => setBad(false), [src]);   // retry when the link token is renewed
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  const initials = name.split(" ").filter(Boolean).map((n) => n[0]).join("").slice(0, 2).toUpperCase();
  const style = fill ? {} : { width: size, height: size, fontSize: size * 0.38 };
  const cls = `face${fill ? " fill" : ""}`;
  if (bad || !id) {
    return <span className={cls} style={{ ...style, background: `hsl(${hue} 60% 90%)`, color: `hsl(${hue} 50% 26%)` }}>{initials}</span>;
  }
  return <img className={cls} style={style} alt="" onError={() => setBad(true)} src={src} />;
}

export const Chip = ({ status }) =>
  status === "Present" ? <span className="chip ok"><Tick /> Present</span>
    : status === "Leave" ? <span className="chip warn"><Icon name="calendar" size={14} /> Leave</span>
      : <span className="chip no"><Icon name="x" size={14} /> Absent</span>;

export const PageHead = ({ title, sub, children }) => (
  <header className="head">
    <div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>
    {children && <div className="head-actions">{children}</div>}
  </header>
);

export const Segmented = ({ value, onChange, options, label }) => (
  <div className="seg" role="group" aria-label={label}>
    {options.map((o) => (
      <button key={o.id} className={value === o.id ? "on" : ""} aria-pressed={value === o.id} onClick={() => onChange(o.id)}>
        {o.icon && <Icon name={o.icon} size={16} />}{o.label}{o.count !== undefined && <b>{o.count}</b>}
      </button>
    ))}
  </div>
);

export const SearchBox = ({ value, onChange, placeholder = "Search by name" }) => (
  <label className="search">
    <Icon name="search" size={18} />
    <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder} />
  </label>
);

export const Field = ({ id, label, hint, error, wide, as = "input", children, ...input }) => {
  const Tag = as;
  return (
    <div className={`field${wide ? " wide" : ""}${error ? " has-error" : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children || <Tag id={id} aria-invalid={!!error} aria-describedby={error || hint ? `${id}-help` : undefined} {...input} />}
      {(error || hint) && <small id={`${id}-help`} className={error ? "err" : ""}>{error || hint}</small>}
    </div>
  );
};

export const BranchSelect = ({ value, onChange, branches }) => (
  branches.length > 1 ? (
    <select className="select" value={value} onChange={(e) => onChange(e.target.value)} aria-label={`Filter by ${unitLower()}`}>
      <option value="">All {unitsLower()}</option>
      {branches.map((b) => <option key={b} value={b}>{b}</option>)}
    </select>
  ) : null
);

export function Modal({ title, onClose, wide, children, labelledBy = "modal-title" }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="scrim" onClick={onClose}>
      <div className={`dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby={labelledBy} onClick={(e) => e.stopPropagation()}>
        {title && <h2 id={labelledBy}>{title}</h2>}
        {children}
      </div>
    </div>
  );
}

// Which ways to send: WhatsApp and/or email. Shows why one isn't available.
export function ChannelPicker({ value, onChange, status }) {
  const toggle = (c) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c]);
  return (
    <fieldset className="channels">
      <legend>Send by</legend>
      <label className="check"><input type="checkbox" checked={value.includes("whatsapp")} onChange={() => toggle("whatsapp")} />
        WhatsApp {status.wa !== "open" && <span className="muted small">(not linked yet)</span>}</label>
      <label className="check"><input type="checkbox" checked={value.includes("email")} onChange={() => toggle("email")} disabled={!status.email} />
        Email {!status.email && <span className="muted small">(set up Gmail first)</span>}</label>
    </fieldset>
  );
}

// The register: one row per student, ruled lines with a red margin.
export function RosterPanel({ title, records, emptyText, ids, branchOf, branches = [] }) {
  const [q, setQ] = useState("");
  const [f, setF] = useState("all");
  const [branch, setBranch] = useState("");
  const scoped = records.filter((r) => !branch || branchOf?.[r.Name] === branch);
  const present = scoped.filter((r) => r.Status === "Present").length;
  const needle = q.trim().toLowerCase();
  const list = scoped.filter((r) =>
    (f === "all" || (f === "present" ? r.Status === "Present" : r.Status !== "Present")) &&
    (r.Name.toLowerCase().includes(needle) || (r.RollNo || "").toLowerCase().includes(needle))
  );
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <div className="tools">
          <BranchSelect value={branch} onChange={setBranch} branches={branches} />
          <Segmented value={f} onChange={setF} label="Show" options={[
            { id: "all", label: "All", count: scoped.length },
            { id: "present", label: "Present", count: present },
            { id: "absent", label: "Absent", count: scoped.length - present },
          ]} />
          <SearchBox value={q} onChange={setQ} placeholder="Search name or registration no" />
        </div>
      </div>
      {list.length ? (
        <ul className="ledger">
          {list.map((r) => (
            <li key={r.Name} className="row">
              <Face name={r.Name} id={ids?.[r.Name]} size={40} />
              <span className="row-name">{r.Name}{r.RollNo && <small className="roll">{r.RollNo}</small>}</span>
              <span className="row-time">{timeOf(r.Time)}</span>
              <Chip status={r.Status} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="empty">{records.length ? "No one matches that search or filter." : emptyText}</p>
      )}
    </section>
  );
}

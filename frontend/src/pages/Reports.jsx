import { useEffect, useState } from "react";
import { api, mediaUrl } from "../api";
import { isHub } from "../org";
import { BranchSelect, Face, Icon, PageHead, SearchBox, Segmented } from "../ui";
import { fmt, isoToday, plural } from "../util";
import Insights from "./Insights";

const qs = (o) => Object.entries(o).filter(([, v]) => v !== "" && v != null).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
const thisMonth = () => isoToday().slice(0, 7);

// ─── ELIGIBILITY ──────────────────────────────────────────────────────────────
function Eligibility({ branches, ids, toast, isAdmin, course }) {
  const [cfg, setCfg] = useState(null);           // saved term start + minimum
  const [from, setFrom] = useState("");
  const [to, setTo] = useState(isoToday());
  const [pick, setBranch] = useState("");
  const branch = isHub() ? course || "" : pick;   // IT Hub: the course picked on the left
  const [show, setShow] = useState("all");
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);

  useEffect(() => { api.get("/reports/settings").then((r) => { if (r.success) { setCfg(r); setFrom(r.term_start); } }); }, []);
  useEffect(() => {
    if (!cfg) return;
    api.get(`/reports/eligibility?${qs({ from, to, branch })}`).then((r) => setData(r.success ? r : { error: r.message }));
  }, [cfg, from, to, branch]);

  const saveCfg = async (patch) => {
    const next = { ...cfg, ...patch };
    const r = await api.post("/reports/settings", next);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setCfg(next); if ("term_start" in patch) setFrom(patch.term_start); }
  };

  if (!cfg) return <p className="empty">Loading…</p>;
  const rows = (data?.rows || []).filter((r) => (show === "all" || !r.eligible) &&
    (r.name.toLowerCase().includes(q.toLowerCase()) || r.roll_no.includes(q)));

  return (
    <>
      <section className="panel pad report-bar">
        <label className="field">Semester started
          <input type="date" value={cfg.term_start} max={isoToday()} disabled={!isAdmin} onChange={(e) => saveCfg({ term_start: e.target.value })} />
        </label>
        <label className="field">Minimum attendance %
          <input type="number" min={1} max={100} value={cfg.eligibility_min} disabled={!isAdmin} onChange={(e) => setCfg({ ...cfg, eligibility_min: e.target.value })}
            onBlur={() => saveCfg({ eligibility_min: cfg.eligibility_min })} />
        </label>
        <label className="field">From
          <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label className="field">To
          <input type="date" value={to} max={isoToday()} onChange={(e) => setTo(e.target.value)} />
        </label>
      </section>

      {data?.error && <p className="banner">{data.error}</p>}
      {data && !data.error && (
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>{data.below ? `${plural(data.below, "student")} below ${data.minimum}%` : `Everyone is at or above ${data.minimum}%`}</h2>
              <p className="muted small">{plural(data.days, "class day")} from {fmt(data.start, { day: "numeric", month: "short" })} to {fmt(data.end, { day: "numeric", month: "short", year: "numeric" })}. Holidays and approved leave don't count against a student.</p>
            </div>
            <div className="tools">
              <BranchSelect value={branch} onChange={setBranch} branches={branches} />
              <Segmented value={show} onChange={setShow} label="Show" options={[{ id: "all", label: "All" }, { id: "below", label: "Below minimum", count: data.below }]} />
              <SearchBox value={q} onChange={setQ} placeholder="Name or registration no" />
              <a className="btn ghost" href={mediaUrl("/reports/eligibility/export", `&${qs({ from, to, branch })}`)}><Icon name="download" size={18} />Excel</a>
            </div>
          </div>
          {rows.length ? (
            <ul className="elig">
              {rows.map((r) => (
                <li key={r.id} className={r.eligible ? "" : "low"}>
                  <Face name={r.name} id={ids[r.name]} size={38} />
                  <div className="el-name"><strong>{r.name}</strong><span className="muted small">{[r.roll_no, r.branch].filter(Boolean).join(" · ")}</span></div>
                  <div className="el-bar" aria-hidden="true">
                    <i style={{ width: `${r.percentage ?? 0}%` }} />
                    <b style={{ left: `${data.minimum}%` }} />
                  </div>
                  <strong className="el-pct">{r.percentage == null ? "–" : `${r.percentage}%`}</strong>
                  <span className="muted small el-count">{r.present} present · {r.absent} absent{r.leave ? ` · ${r.leave} leave` : ""}</span>
                  <span className={`chip ${r.eligible ? "ok" : "no"}`}>
                    {r.percentage == null ? "No classes yet" : r.eligible ? (r.can_miss ? `Can miss ${r.can_miss}` : "Eligible") : `Needs ${r.need} more class${r.need === 1 ? "" : "es"} in a row`}
                  </span>
                </li>
              ))}
            </ul>
          ) : <p className="empty">{data.rows.length ? "No one matches." : "No attendance saved in this period yet."}</p>}
        </section>
      )}
    </>
  );
}

// ─── MONTHLY REGISTER ─────────────────────────────────────────────────────────
function Monthly({ branches, course }) {
  const [month, setMonth] = useState(thisMonth());
  const [pick, setBranch] = useState("");
  const branch = isHub() ? course || "" : pick;
  const [data, setData] = useState(null);
  const [minPct, setMinPct] = useState(75);
  useEffect(() => { api.get("/reports/settings").then((r) => r.success && setMinPct(Number(r.eligibility_min) || 75)); }, []);
  useEffect(() => { api.get(`/reports/monthly?${qs({ month, branch })}`).then((r) => setData(r.success ? r : { error: r.message })); }, [month, branch]);
  const shift = (n) => { const [y, m] = month.split("-").map(Number); const d = new Date(y, m - 1 + n, 1); setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`); };
  const title = new Date(`${month}-01T00:00`).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
  return (
    <section className="panel">
      <div className="panel-head">
        <div className="month-nav">
          <button className="icon-btn" onClick={() => shift(-1)} aria-label="Previous month">‹</button>
          <h2>{title}</h2>
          <button className="icon-btn" onClick={() => shift(1)} disabled={month >= thisMonth()} aria-label="Next month">›</button>
        </div>
        <div className="tools">
          <BranchSelect value={branch} onChange={setBranch} branches={branches} />
          <a className="btn primary" href={mediaUrl("/reports/monthly/export", `&${qs({ month, branch })}`)}><Icon name="download" size={18} />Download Excel</a>
        </div>
      </div>
      {data?.error && <p className="empty">{data.error}</p>}
      {data && !data.error && (data.columns.length ? (
        <>
          <div className="table-wrap">
            <table className="register">
              <thead>
                <tr><th className="stick">Student</th>{data.columns.map((d) => <th key={d}><span>{fmt(d, { weekday: "narrow" })}</span>{Number(d.slice(8))}</th>)}<th>P</th><th>A</th><th>L</th><th>%</th></tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id}>
                    <th className="stick">{r.name}{r.roll_no && <small>{r.roll_no}</small>}</th>
                    {r.marks.map((m, i) => <td key={i} className={`m-${m || "none"}`}>{m}</td>)}
                    <td>{r.present}</td><td>{r.absent}</td><td>{r.leave}</td>
                    <td><strong className={r.percentage != null && r.percentage < minPct ? "lowpct" : ""}>{r.percentage ?? "–"}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small pad legend"><span className="m-P">P</span> present <span className="m-A">A</span> absent <span className="m-L">L</span> approved leave <span className="m-H">H</span> holiday. Only days with a saved register are shown.</p>
        </>
      ) : <p className="empty">No attendance was saved in {title}.</p>)}
    </section>
  );
}

export default function ReportsPage({ branches, ids, toast, go, isAdmin, course }) {
  const [tab, setTab] = useState("insights");
  return (
    <>
      <PageHead title={isHub() && course && tab !== "insights" ? `Reports · ${course}` : "Reports"}
        sub={isHub() ? "Trends, students who need attention, eligibility and the month-wise register, per course."
          : "Trends and students who need attention, exam eligibility, and the month-wise register the university asks for."} />
      <div className="tabbar">
        <Segmented value={tab} onChange={setTab} label="Report" options={[{ id: "insights", label: "Insights" }, { id: "eligibility", label: "Exam eligibility" }, { id: "monthly", label: "Monthly register" }]} />
      </div>
      {tab === "insights" && <Insights branches={branches} ids={ids} go={go} />}
      {tab === "eligibility" && <Eligibility branches={isHub() ? [] : branches} ids={ids} toast={toast} isAdmin={isAdmin} course={course} />}
      {tab === "monthly" && <Monthly branches={isHub() ? [] : branches} course={course} />}
    </>
  );
}

// Charts (attendance trend, weekday, branch, month) and the "students at risk" list.
// Every chart is one series in the brand blue, drawn as plain SVG: no chart library.
import { useEffect, useState } from "react";
import { api } from "../api";
import { unitLower } from "../org";
import { BranchSelect, Face, Icon } from "../ui";
import { fmt } from "../util";

const W = 640, H = 220, PAD = { l: 36, r: 12, t: 12, b: 26 };

function DataTable({ caption, head, rows }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
    </table>
  );
}

function Grid({ minimum }) {
  const y = (v) => PAD.t + (1 - v / 100) * (H - PAD.t - PAD.b);
  return (
    <g>
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} className="grid-line" />
          <text x={PAD.l - 8} y={y(v) + 4} className="axis-text" textAnchor="end">{v}</text>
        </g>
      ))}
      {minimum != null && (
        <g>
          <line x1={PAD.l} x2={W - PAD.r} y1={y(minimum)} y2={y(minimum)} className="min-line" />
          <text x={W - PAD.r} y={y(minimum) - 5} className="axis-text" textAnchor="end">{minimum}% minimum</text>
        </g>
      )}
    </g>
  );
}

function TrendChart({ data, minimum }) {
  const [hover, setHover] = useState(null);
  const pts = data.filter((d) => d.percentage != null);
  if (pts.length < 2) return <p className="empty">The trend appears after two days with a saved register.</p>;
  const x = (i) => PAD.l + (i / (pts.length - 1)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - v / 100) * (H - PAD.t - PAD.b);
  const path = pts.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d.percentage).toFixed(1)}`).join(" ");
  const step = Math.ceil(pts.length / 6);
  const h = hover != null ? pts[hover] : null;
  return (
    <div className="chart-box">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Daily attendance, ${pts.length} class days, from ${pts[0].percentage}% to ${pts.at(-1).percentage}%`}
        onMouseLeave={() => setHover(null)}>
        <Grid minimum={minimum} />
        <path d={path} className="trend-line" />
        {pts.map((d, i) => i % step === 0 && (
          <text key={d.date} x={x(i)} y={H - 6} className="axis-text" textAnchor="middle">{fmt(d.date, { day: "numeric", month: "short" })}</text>
        ))}
        {h && <line x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={H - PAD.b} className="crosshair" />}
        {h && <circle cx={x(hover)} cy={y(h.percentage)} r={5} className="trend-dot" />}
        {pts.map((d, i) => (   // invisible hit areas, wider than the line
          <rect key={d.date} x={x(i) - (W / pts.length) / 2} y={PAD.t} width={W / pts.length} height={H - PAD.t - PAD.b}
            fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {h && (
        <div className="tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <strong>{h.percentage}%</strong> {fmt(h.date, { weekday: "short", day: "numeric", month: "short" })}<br />
          <span>{h.present} of {h.total} present</span>
        </div>
      )}
      <DataTable caption="Daily attendance" head={["Date", "Attendance %", "Present", "Counted"]}
        rows={pts.map((d) => [d.date, d.percentage, d.present, d.total])} />
    </div>
  );
}

function Bars({ items, label, value, sub, caption, minimum }) {
  const shown = items.filter((d) => value(d) != null);
  if (!shown.length) return <p className="empty">No data yet.</p>;
  return (
    <div className="vbars" role="img" aria-label={`${caption}: ${shown.map((d) => `${label(d)} ${value(d)}%`).join(", ")}`}>
      {minimum != null && <i className="vbars-min" style={{ bottom: `${26 + 1.6 * minimum}px` }} aria-hidden="true" />}
      {items.map((d) => (
        <div className="vbar" key={label(d)} title={value(d) == null ? `${label(d)}: no classes` : `${label(d)}: ${value(d)}%${sub ? ` (${sub(d)})` : ""}`}>
          <span className="vbar-val">{value(d) == null ? "" : `${Math.round(value(d))}%`}</span>
          <span className="vbar-track">{value(d) != null && <span className="vbar-fill" style={{ height: `${value(d)}%` }} />}</span>
          <span className="vbar-label">{label(d)}</span>
        </div>
      ))}
      <DataTable caption={caption} head={["", "Attendance %"]} rows={items.map((d) => [label(d), value(d) ?? "–"])} />
    </div>
  );
}

function BranchBars({ items, minimum }) {
  if (!items.length) return <p className="empty">No data yet.</p>;
  return (
    <ul className="hbars" aria-label="Attendance by branch">
      {items.map((b) => (
        <li key={b.branch} title={`${b.branch}: ${b.percentage}% (${b.students} students)`}>
          <span className="hb-label">{b.branch}<small>{b.students} students</small></span>
          <span className="hb-track">
            <span className="hb-fill" style={{ width: `${b.percentage}%` }} />
            {minimum != null && <i style={{ left: `${minimum}%` }} aria-hidden="true" />}
          </span>
          <span className="hb-val">{b.percentage}%</span>
        </li>
      ))}
    </ul>
  );
}

export function AtRiskList({ students, ids, go, limit }) {
  const list = limit ? students.slice(0, limit) : students;
  if (!list.length) return <p className="empty">No student needs attention right now.</p>;
  return (
    <ul className="risk">
      {list.map((r) => (
        <li key={r.id} className={r.level}>
          <Face name={r.name} id={ids[r.name]} size={40} />
          <div className="risk-main">
            <strong>{r.name} <span className="muted small">{[r.roll_no, r.branch].filter(Boolean).join(" · ")}</span></strong>
            <ul className="reasons">{r.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
          </div>
          <span className={`chip ${r.level === "high" ? "no" : "warn"}`}>
            <Icon name={r.level === "high" ? "bell" : "eye"} size={14} />{r.level === "high" ? "Act now" : "Watch"}
          </span>
          <div className="risk-contact">
            {r.parent_phone && <a className="btn ghost small-btn" href={`https://wa.me/${r.parent_phone.replace("+", "")}`} target="_blank" rel="noreferrer">WhatsApp parent</a>}
            {go && <button className="btn ghost small-btn" onClick={() => go("students")}>Profile</button>}
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function Insights({ branches, ids, go }) {
  const [days, setDays] = useState(60);
  const [branch, setBranch] = useState("");
  const [data, setData] = useState(null);
  const [risk, setRisk] = useState(null);
  const [minimum, setMinimum] = useState(75);
  useEffect(() => { api.get("/reports/settings").then((r) => r.success && setMinimum(Number(r.eligibility_min) || 75)); }, []);
  useEffect(() => {
    const q = `days=${days}${branch ? `&branch=${encodeURIComponent(branch)}` : ""}`;
    api.get(`/analytics?${q}`).then((r) => setData(r.success ? r : null));
    api.get(`/analytics/at-risk${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`).then((r) => setRisk(r.success && r.students ? r : { students: [] }));
  }, [days, branch]);

  return (
    <>
      <div className="insight-bar">
        <div className="seg" role="group" aria-label="Period">
          {[[30, "30 days"], [60, "60 days"], [120, "4 months"], [365, "1 year"]].map(([v, l]) => (
            <button key={v} className={days === v ? "on" : ""} aria-pressed={days === v} onClick={() => setDays(v)}>{l}</button>
          ))}
        </div>
        <BranchSelect value={branch} onChange={setBranch} branches={branches} />
      </div>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Students needing attention {risk?.students.length ? <span className="muted">({risk.students.length})</span> : null}</h2>
            <p className="muted small">Low or falling attendance, absent several days in a row, or weak or falling exam marks.</p>
          </div>
        </div>
        {risk ? <AtRiskList students={risk.students} ids={ids} go={go} /> : <p className="empty">Loading…</p>}
      </section>

      {data && (
        <>
          <div className="kpis">
            <div className="panel pad"><span className="muted small">Average attendance</span><b>{data.average ?? "–"}{data.average != null && "%"}</b><span className="muted small">{data.days} class days</span></div>
            {data.notes.length > 0 && (
              <div className="panel pad notes"><span className="muted small">What stands out</span>
                <ul>{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
              </div>
            )}
          </div>
          <section className="panel pad chart">
            <h2 className="h2">Attendance each class day</h2>
            <TrendChart data={data.trend} minimum={minimum} />
          </section>
          <div className="chart-grid">
            <section className="panel pad chart">
              <h2 className="h2">By weekday</h2>
              <Bars items={data.weekday} label={(d) => d.day} value={(d) => d.percentage} caption="Attendance by weekday" minimum={minimum} />
            </section>
            <section className="panel pad chart">
              <h2 className="h2">Last 6 months</h2>
              <Bars items={data.months} label={(d) => d.label} value={(d) => d.percentage} caption="Attendance by month" minimum={minimum} />
            </section>
          </div>
          {data.branches.length > 1 && (
            <section className="panel pad chart">
              <h2 className="h2">By {unitLower()}</h2>
              <BranchBars items={data.branches} minimum={minimum} />
            </section>
          )}
        </>
      )}
    </>
  );
}

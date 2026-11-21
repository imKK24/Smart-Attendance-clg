import { useEffect, useState } from "react";
import { api, mediaUrl } from "../api";
import { isHub } from "../org";
import { Icon, PageHead, RosterPanel } from "../ui";
import { fmt, parseISO } from "../util";

function Evidence({ day, course }) {
  const [list, setList] = useState([]);
  useEffect(() => {
    const c = isHub() && course ? `&course=${encodeURIComponent(course)}` : "";
    api.get(`/photo-attendance?day=${day}${c}`).then((r) => setList(r.success ? r.sessions : []));
  }, [day, course]);
  if (!list.length) return null;
  return (
    <section className="panel pad evidence">
      <h2 className="h2">Class photos (evidence)</h2>
      {list.map((s) => (
        <div key={s.id} className="ev-row">
          <p className="muted small">{s.branch || "All students"} · saved {s.saved_at?.slice(11, 16)} by {s.taken_by || "–"} · {s.present_ids.length} present</p>
          <div className="ev-thumbs">
            {Array.from({ length: s.photos }, (_, i) => (
              <a key={i} href={mediaUrl(`/photo-attendance/${s.id}/photo/${i + 1}`)} target="_blank" rel="noreferrer">
                <img src={mediaUrl(`/photo-attendance/${s.id}/photo/${i + 1}`)} alt={`Class photo ${i + 1}`} />
              </a>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

export default function AttendancePage({ dates, today, go, ids, branchOf, branches, course }) {
  const cq = isHub() ? `?course=${encodeURIComponent(course || "")}` : "";
  const [sel, setSel] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const livePresent = today?.present_count;

  useEffect(() => { if ((!sel || !dates.includes(sel)) && dates.length) setSel(dates[0]); }, [dates, sel]);

  useEffect(() => {
    if (!sel) return undefined;
    let live = true;
    setLoading(true);
    api.get(`/attendance/${sel}${cq}`).then((r) => {
      if (!live) return;
      setData(r.success ? r : null);
      setLoading(false);
    });
    return () => { live = false; };
  }, [sel, livePresent, cq]);

  const showSpinner = loading && (!data || data.date !== sel);

  return (
    <>
      <PageHead title={isHub() && course ? `Attendance · ${course}` : "Attendance"}
        sub={isHub() ? "Pick a class day to see who was in. Change the course in the menu on the left." : "Pick a day to see who was in."}>
        {sel && <a className="btn ghost" href={mediaUrl(`/attendance/${sel}/export`, cq ? `&${cq.slice(1)}` : "")}><Icon name="download" />Export for Excel</a>}
      </PageHead>

      {dates.length === 0 ? (
        <section className="panel"><div className="empty">
          <p>No attendance has been saved yet.</p>
          <button className="btn primary" onClick={() => go("live")}><Icon name="camera" />Go to live camera</button>
        </div></section>
      ) : (
        <>
          <div className="days">
            {dates.map((d) => (
              <button key={d} className={`daychip${d === sel ? " on" : ""}`} aria-pressed={d === sel} onClick={() => setSel(d)}>
                <span className="wk">{fmt(d, { weekday: "short" })}</span>
                <span className="dy">{parseISO(d).getDate()}</span>
                <span className="mo">{fmt(d, { month: "short" })}</span>
              </button>
            ))}
          </div>
          {showSpinner && <p className="empty">Loading…</p>}
          {!showSpinner && data && (
            <>
              {data.holiday && <p className="note">This day is marked as a holiday ({data.holiday}), so it isn't counted for absence alerts.</p>}
              <div className="summary">
                <div><b>{data.present_count}</b><span>present</span></div>
                <div><b>{data.absent_count}</b><span>absent</span></div>
                <div><b>{data.percentage}%</b><span>attendance</span></div>
              </div>
              <Evidence day={sel} course={course} />
              <RosterPanel key={sel} title={fmt(sel, { weekday: "long", day: "numeric", month: "long" })} records={data.records}
                ids={ids} branchOf={branchOf} branches={branches} emptyText="This register is empty." />
            </>
          )}
          {!showSpinner && !data && <p className="empty">Couldn't load this day. Check that the server is running.</p>}
        </>
      )}
    </>
  );
}

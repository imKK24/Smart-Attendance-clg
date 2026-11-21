import { useEffect, useState } from "react";
import { api } from "../api";
import { isHub } from "../org";
import { Face, Icon, PageHead, RosterPanel } from "../ui";
import { AtRiskList } from "./Insights";

function AttentionPanel({ ids, go, online }) {
  const [risk, setRisk] = useState(null);
  useEffect(() => { if (online) api.get("/analytics/at-risk").then((r) => r.success && setRisk(r)); }, [online]);
  if (!risk?.students?.length) return null;
  return (
    <section className="panel attention">
      <div className="panel-head">
        <div>
          <h2>Needs attention</h2>
          <p className="muted small">{risk.students.length} student{risk.students.length === 1 ? "" : "s"} with low or falling attendance or marks.</p>
        </div>
        <button className="btn ghost" onClick={() => go("reports")}><Icon name="chart" size={18} />See insights</button>
      </div>
      <AtRiskList students={risk.students} ids={ids} limit={3} />
    </section>
  );
}
import { ago, fmt, isoToday, plural } from "../util";

function MailPanel({ inbox, go, ids }) {
  const mails = inbox.mails.slice(0, 5);
  return (
    <section className="panel mailpanel">
      <div className="panel-head">
        <div>
          <h2>{isHub() ? "Emails" : "Parent emails"}</h2>
          <p className="muted small">{!inbox.configured ? (isHub() ? "The college admin hasn't set up Gmail yet." : "Set up Gmail to see parents' emails here.")
            : inbox.unread ? `${plural(inbox.unread, "unread email")}` : "You're all caught up."}</p>
        </div>
        {(inbox.configured || !isHub()) && (
          <button className="btn ghost" onClick={() => go(inbox.configured ? "inbox" : "notify:settings")}>
            <Icon name="inbox" size={18} />{inbox.configured ? "Open inbox" : "Set up Gmail"}
          </button>
        )}
      </div>
      {mails.length ? (
        <ul className="mini-mail">
          {mails.map((m) => (
            <li key={m.id}>
              <button className={m.is_read ? "" : "unread"} onClick={() => go("inbox", m.id)}>
                {m.children[0] ? <Face name={m.children[0].name} id={ids[m.children[0].name]} size={36} /> : <span className="face" style={{ width: 36, height: 36 }} />}
                <span className="mm-main">
                  <strong>{m.from_name || m.from_email}{m.children.length > 0 && <span className="muted"> · parent of {m.children.map((c) => c.name).join(", ")}</span>}</strong>
                  <span className="mm-sub">{m.subject}</span>
                </span>
                <span className="mm-time">{ago(m.received_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : <p className="empty">{inbox.configured ? "No emails from parents in the last 30 days." : "No emails yet."}</p>}
    </section>
  );
}

export default function Dashboard({ today, history, students, online, cam, busy, go, onStart, inbox, ids, branchOf, branches }) {
  const hr = new Date().getHours();
  const hello = hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening";
  const records = today?.records ?? [];
  const total = today?.total ?? students.length;
  const present = today?.present_count ?? 0;
  const sub = !online ? "The server is offline, so today's numbers can't load."
    : total === 0 ? "No students are registered yet."
      : isHub() && today?.course ? `${present} of ${total} students are in ${today.course} today.`
        : `${present} of ${total} students are in today.`;
  const todayISO = isoToday();

  return (
    <>
      <PageHead title={hello} sub={sub}>
        {students.length === 0 ? (
          <button className="btn primary" onClick={() => go("register")}><Icon name="plus" />Register a student</button>
        ) : cam.active ? (
          <button className="btn primary" onClick={() => go("live")}><Icon name="camera" />Open live camera</button>
        ) : (
          <button className="btn primary" onClick={onStart} disabled={busy || !online}><Icon name="play" />Start attendance</button>
        )}
      </PageHead>

      {today?.holiday && <div className="banner"><Icon name="sun" size={18} /> Today is a holiday: <strong>{today.holiday}</strong>. It's skipped when counting absences.</div>}

      <div className="dash-top">
        <section className="panel hero">
          <p className="muted">{new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}</p>
          <div className="rate"><span className="rate-num">{today?.percentage ?? 0}</span><span className="rate-pct">%</span></div>
          <p className="rate-cap">of students are present</p>
          <div className="boxes" aria-label="One box per student. Green means present.">
            {records.map((r, i) => (
              <span key={r.Name} title={`${r.Name}: ${r.Status}`} className={`box ${r.Status === "Present" ? "in" : "out"}`} style={{ "--i": i }} />
            ))}
          </div>
          <dl className="facts">
            <div><dt>Registered</dt><dd>{students.length}</dd></div>
            <div><dt>Present</dt><dd className="g">{present}</dd></div>
            <div><dt>Absent</dt><dd className="r">{today?.absent_count ?? 0}</dd></div>
          </dl>
        </section>

        <section className="panel history">
          <h2>Last 7 sessions</h2>
          <p className="sub">Attendance rate for each day with a saved register</p>
          {history.length ? (
            <div className="bars">
              {history.map((h) => (
                <div className="bar-col" key={h.date}>
                  <span className="bar-val">{h.percentage}%</span>
                  <div className="bar-track"><div className={`bar${h.date === todayISO ? " is-today" : ""}`} style={{ height: `${Math.max(h.percentage, 3)}%` }} /></div>
                  <span className="bar-day">{fmt(h.date, { weekday: "short" })}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="empty">History appears after your first attendance session.</p>
          )}
        </section>
      </div>

      <AttentionPanel ids={ids} go={go} online={online} />
      <MailPanel inbox={inbox} go={go} ids={ids} />

      <RosterPanel title="Today's register" records={records} ids={ids} branchOf={branchOf} branches={branches} emptyText="Register students to see them here." />
    </>
  );
}

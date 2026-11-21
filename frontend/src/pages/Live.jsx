import { useEffect, useState } from "react";
import { mediaUrl } from "../api";
import { Face, Icon, PageHead, Tick } from "../ui";

const FLOW = [
  { id: "liveness", icon: "user", t: "Face the camera", d: "Look straight so you can be identified" },
  { id: "challenge", icon: "eye", t: "Prove you're live", d: "Do the random actions it asks for" },
  { id: "marked", icon: "check", t: "Marked", d: "Saved to today's register" },
];
const STEP_OF = { liveness: 0, recognizing: 0, unknown: 0, challenge: 1, spoof: 1, marked: 2 };

// On the server PC or the college network the camera streams smoothly. Over the
// internet a continuous stream piles up and falls further behind, so remote
// viewers fetch one small, always-newest picture at a time instead.
const PRIVATE = /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[?::1\]?$)/;
const REMOTE = typeof window !== "undefined" && !PRIVATE.test(window.location.hostname);

function LiteFeed({ feedKey }) {
  const [src, setSrc] = useState("");
  useEffect(() => {
    let alive = true, after = -1, url = "";
    (async () => {
      while (alive) {
        try {
          const r = await fetch(mediaUrl("/camera-frame", `&after=${after}&k=${feedKey}`), { cache: "no-store" });
          if (r.status === 200) {
            after = Number(r.headers.get("X-Frame-Id") ?? after);
            const next = URL.createObjectURL(await r.blob());
            if (!alive) { URL.revokeObjectURL(next); break; }
            if (url) URL.revokeObjectURL(url);
            url = next; setSrc(next);
          } else {
            await new Promise((ok) => setTimeout(ok, r.status === 204 ? 300 : 1500));
          }
        } catch {
          await new Promise((ok) => setTimeout(ok, 1500));   // network hiccup: try again
        }
      }
    })();
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [feedKey]);
  return src ? <img src={src} alt="Live camera feed (light mode for the internet)" /> : <div className="stage-overlay">Connecting to the camera…</div>;
}

function CameraPicker({ cam, cameras, selected, loading, onChange, onRefresh, isAdmin, onManageIp }) {
  const value = String(selected ?? "default");
  const missing = selected !== "default" && !cameras.some((c) => String(c.index) === value);
  const local = cameras.filter((c) => !c.ip && !c.builtin);
  const ip = cameras.filter((c) => c.ip);
  const kind = (c) => (c.builtin ? "laptop" : c.infrared ? "infrared, not for faces" : "USB");
  let hint;
  if (loading) hint = "Looking for cameras…";
  else if (cam.active && cam.camera) hint = `Using ${cam.camera.name}.`;
  else if (!cameras.length) hint = "No camera found. Plug one in, then press refresh.";
  else hint = "The laptop camera is used unless you pick another one.";
  return (
    <section className="panel pad cam-pick">
      <div className="cam-pick-top">
        <label htmlFor="cam-src">Camera</label>
        <button className="icon-btn" onClick={onRefresh} disabled={cam.active || loading} aria-label="Look for cameras again"><Icon name="retake" size={18} /></button>
      </div>
      <select id="cam-src" value={value} disabled={cam.active}
        onChange={(e) => { const v = e.target.value; onChange(v === "default" || v.startsWith("ip:") ? v : Number(v)); }}>
        <option value="default">Laptop camera (default)</option>
        {local.length > 0 && <optgroup label="USB cameras">
          {local.map((c) => <option key={c.index} value={c.index} disabled={c.infrared}>{c.name} ({kind(c)})</option>)}
        </optgroup>}
        {ip.length > 0 && <optgroup label="IP cameras">
          {ip.map((c) => <option key={c.index} value={c.index}>{c.name} ({c.kind === "wired" ? "wired" : "Wi-Fi"})</option>)}
        </optgroup>}
        {missing && <option value={value}>Saved camera (not found)</option>}
      </select>
      {isAdmin && <button className="link small" onClick={onManageIp} disabled={cam.active}>+ Add or test an IP camera (wired / Wi-Fi)</button>}
      <p className="muted small">{hint}</p>
      {cam.camera?.note && <p className="note">{cam.camera.note}</p>}
    </section>
  );
}

function CameraTips() {
  return (
    <details className="panel pad tips">
      <summary><strong>Getting good recognition</strong></summary>
      <ul>
        <li>Light the faces from the front. A window behind the student causes most misses.</li>
        <li>Put the camera at eye level, about 50–80 cm from the student.</li>
        <li>One student at a time. Glasses are fine; masks are not.</li>
        <li>A 1080p USB webcam with autofocus works better than most laptop cameras. See the camera guide in the README.</li>
      </ul>
    </details>
  );
}

export default function LivePage({ cam, busy, feedKey, onStart, onStop, cameras, camSetting, camsLoading, onPickCamera, onLoadCameras, ids, holiday, isAdmin, onManageIp, header = true, liveness = "secure" }) {
  const flow = liveness === "quick"
    ? FLOW.map((s) => (s.id === "challenge" ? { ...s, t: "Blink twice", d: "Two normal blinks, looking at the camera" } : s))
    : FLOW;
  useEffect(() => { if (!cam.active) onLoadCameras(false); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const step = cam.active ? STEP_OF[cam.status] : undefined;
  const warn = ["spoof", "unknown", "error"].includes(cam.status);
  const message = cam.message || (liveness === "quick"
    ? "Start the camera when students are ready. Each student looks at the camera and blinks twice."
    : "Start the camera when students are ready. Each student follows two random instructions, so photos and videos can't pass.");
  return (
    <>
      {header && <PageHead title="Live camera" sub="Each student faces the camera and follows two random instructions, like turning their head. Attendance is saved when they pass." />}
      <div className="live-actions">
        {cam.active
          ? <button className="btn stop" onClick={onStop} disabled={busy}><Icon name="stop" size={18} />{busy ? "Saving…" : "Stop and save"}</button>
          : <button className="btn primary" onClick={onStart} disabled={busy}><Icon name="play" size={18} />{busy ? "Starting…" : "Start attendance"}</button>}
      </div>
      {holiday && !cam.active && <p className="note gap-bottom">Today is marked as a holiday ({holiday}). You can still take attendance; the day won't count for absence alerts.</p>}

      <div className="live">
        <div className="stage">
          {cam.active ? (
            <>
              {REMOTE ? <LiteFeed feedKey={feedKey} /> : <img src={mediaUrl("/video-feed", `&k=${feedKey}`)} alt="Live camera feed" />}
              <span className="live-badge"><i />Live</span>
              {cam.status === "starting" && <div className="stage-overlay">Starting the camera…</div>}
            </>
          ) : (
            <div className="stage-empty"><Icon name="camera" size={44} /><p>The camera is off</p></div>
          )}
        </div>

        <div className="side-col">
          <CameraPicker cam={cam} cameras={cameras} selected={camSetting} loading={camsLoading} onChange={onPickCamera} onRefresh={() => onLoadCameras(true)}
            isAdmin={isAdmin} onManageIp={onManageIp} />
          {cam.active && cam.camera?.ip && <p className="note small">IP camera: the students can't see this screen, so put a monitor or TV facing them, or read the instructions out.</p>}
          <div className={`say${warn ? " warn" : ""}${cam.status === "challenge" ? " big" : ""}`} role="status">{message}</div>
          <section className="panel pad">
            <ul className="flow">
              {flow.map((s, i) => (
                <li key={s.id} className={step === i ? "now" : ""}>
                  <span className="ic"><Icon name={s.icon} size={18} /></span>
                  <div><strong>{s.t}</strong><small>{s.d}</small></div>
                </li>
              ))}
            </ul>
          </section>
          <section className="panel">
            <div className="panel-head"><h2>Marked this session</h2><span className="muted">{cam.recent?.length ?? 0}</span></div>
            {cam.recent?.length ? (
              <ul className="recent">
                {cam.recent.map((r) => (
                  <li key={r.name}><Face name={r.name} id={ids[r.name]} size={34} /><span className="row-name">{r.name}</span><span className="t">{r.time}</span><Tick size={18} /></li>
                ))}
              </ul>
            ) : <p className="empty">No one has been marked yet.</p>}
          </section>
          <CameraTips />
        </div>
      </div>
    </>
  );
}

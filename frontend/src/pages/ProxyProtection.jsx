// Admin: rules that stop attendance being taken from home (backend guard.py).
// They apply to teachers; admins are never blocked.
import { useEffect, useState } from "react";
import { api } from "../api";
import { Icon, Modal } from "../ui";

const when = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "never");

export default function ProxyProtection({ onClose, toast }) {
  const [data, setData] = useState(null);
  const [r, setR] = useState(null);
  const [net, setNet] = useState("");
  const [locating, setLocating] = useState(false);
  const load = async () => {
    const res = await api.get("/attendance-guard");
    if (res.success) { setData(res); setR(res.rules); } else toast(res.message, "bad");
  };
  useEffect(() => { load(); }, []);   // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (patch) => {
    const res = await api.put("/attendance-guard", { ...r, ...patch });
    toast(res.message, res.success ? "ok" : "bad");
    if (res.success) setR(res.rules);
  };
  const here = () => {
    if (!navigator.geolocation) { toast("This browser can't share its location.", "bad"); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => { setLocating(false); setR({ ...r, lat: +p.coords.latitude.toFixed(6), lng: +p.coords.longitude.toFixed(6) });
        toast(`Location found (±${Math.round(p.coords.accuracy)} m). Press Save to keep it.`); },
      () => { setLocating(false); toast("Couldn't get the location. Allow location for this site and turn on GPS.", "bad"); },
      { enableHighAccuracy: true, timeout: 20000 });
  };
  const act = async (call, d) => { const res = await call(d); toast(res.message, res.success ? "ok" : "bad"); load(); };

  if (!data || !r) return <Modal title="Proxy protection" onClose={onClose} wide labelledBy="pp-title"><p className="empty">Loading…</p></Modal>;
  const pending = data.devices.filter((d) => d.status !== "approved");
  const approved = data.devices.filter((d) => d.status === "approved");
  return (
    <Modal title="Proxy protection" onClose={onClose} wide labelledBy="pp-title">
      <p className="muted">Stops teachers taking attendance from home. These rules apply to teachers (live camera and class photo); admins are never blocked.</p>

      <section className="pp-rule">
        <label className="check"><input type="checkbox" checked={r.devices} onChange={(e) => save({ devices: e.target.checked })} />
          <strong>Only approved devices</strong></label>
        <p className="muted small">Each teacher's phone or laptop must be approved here once. Its first try appears below as "Waiting".</p>
        {pending.length > 0 && <h4 className="h4">Waiting for approval</h4>}
        <ul className="ipc-list">
          {[...pending, ...approved].map((d) => (
            <li key={d.id}>
              <span className={`tag ${d.status === "approved" ? "email" : "whatsapp"}`}>{d.status === "approved" ? "Approved" : "Waiting"}</span>
              <span className="grow"><strong>{d.label}</strong>
                <small className="muted">{d.username} · first seen {when(d.created_at)} · last used {when(d.last_seen)}{d.last_ip ? ` · ${d.last_ip}` : ""}</small></span>
              {d.status !== "approved" && <button className="btn primary small-btn" onClick={() => act((x) => api.post(`/devices/${x}/approve`), d.id)}>Approve</button>}
              <button className="icon-btn" aria-label={`Remove ${d.label}`} onClick={() => act((x) => api.del(`/devices/${x}`), d.id)}><Icon name="trash" size={16} /></button>
            </li>
          ))}
          {data.devices.length === 0 && <li className="muted small">No devices yet. A teacher's device appears here the first time they try to take attendance.</li>}
        </ul>
      </section>

      <section className="pp-rule">
        <label className="check"><input type="checkbox" checked={r.network} onChange={(e) => save({ network: e.target.checked })} />
          <strong>Only from the college network</strong></label>
        <p className="muted small">Phones and laptops on the college Wi-Fi or LAN are always allowed. If teachers open the public link
          while on college Wi-Fi, add the college's internet address too. {r.location && "With the location rule on, teachers outside the network may still take attendance if their location is at the college."}</p>
        <p className="small">You are on: <span className="mono">{data.my_ip}</span> {data.my_ip_is_lan ? "(the college network)" : "(over the internet)"}</p>
        <div className="course-chips">
          {r.networks.map((n) => <span key={n} className="chip-check on mono">{n}
            <button className="x" aria-label={`Remove ${n}`} onClick={() => save({ networks: r.networks.filter((x) => x !== n) })}>×</button></span>)}
        </div>
        <form className="row-form" onSubmit={(e) => { e.preventDefault(); if (net.trim()) { save({ networks: [...r.networks, net.trim()] }); setNet(""); } }}>
          <input className="input" value={net} onChange={(e) => setNet(e.target.value)} placeholder="College internet address, e.g. 49.36.12.80" aria-label="Allowed address" />
          <button className="btn ghost" disabled={!net.trim()}>Add</button>
          {!data.my_ip_is_lan && !r.networks.includes(data.my_ip) &&
            <button type="button" className="btn ghost" onClick={() => save({ networks: [...r.networks, data.my_ip] })}>Add the network I'm on now</button>}
        </form>
      </section>

      <section className="pp-rule">
        <label className="check"><input type="checkbox" checked={r.location} disabled={r.lat === null && !r.location}
          onChange={(e) => save({ location: e.target.checked })} /><strong>Only at the college (phone location)</strong></label>
        <p className="muted small">When a teacher isn't on the college network, their phone's GPS must be within the distance below.
          On the college network no location is asked. (A fake-GPS app can still cheat; combine with approved devices.)</p>
        <div className="row-form">
          <span className="small">{r.lat !== null ? <>College point: <span className="mono">{r.lat}, {r.lng}</span></> : "College location not set yet."}</span>
          <button type="button" className="btn ghost" disabled={locating} onClick={here}><Icon name="pin" size={16} />{locating ? "Finding…" : "Use my location (stand at the college)"}</button>
        </div>
        <label className="small pp-radius">Allowed distance:
          <input className="input" type="number" min="50" max="5000" step="50" value={r.radius} onChange={(e) => setR({ ...r, radius: e.target.value })} /> metres</label>
        <div className="dialog-actions"><button className="btn primary" disabled={r.lat === null} onClick={() => save({ lat: r.lat, lng: r.lng, radius: Number(r.radius) })}>Save location</button></div>
      </section>
    </Modal>
  );
}

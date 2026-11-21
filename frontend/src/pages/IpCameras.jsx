// Admin only: add IP cameras (wired or Wi-Fi) by their link, test them, remove them.
import { useEffect, useState } from "react";
import { api } from "../api";
import { Field, Icon, Modal } from "../ui";

// Common stream links. USER / PASS / IP are filled in from the form.
const BRANDS = [
  { id: "tapo", name: "TP-Link Tapo", url: "rtsp://{user}:{pass}@{ip}:554/stream1",
    tip: "In the Tapo app: camera > Settings > Advanced > Camera account. Use that user name and password here, not your TP-Link login." },
  { id: "cpplus", name: "CP Plus / Dahua", url: "rtsp://{user}:{pass}@{ip}:554/cam/realmonitor?channel=1&subtype=0",
    tip: "Use the camera's admin user. subtype=0 is the sharp main stream." },
  { id: "hik", name: "Hikvision / Prama", url: "rtsp://{user}:{pass}@{ip}:554/Streaming/Channels/101",
    tip: "101 = main stream of channel 1." },
  { id: "android", name: "Phone: Android \"IP Webcam\" app", url: "http://{ip}:8080/video",
    tip: "Install IP Webcam, tap \"Start server\", and type the IP address it shows. Keep the phone on charge." },
  { id: "custom", name: "Other camera: paste the link", url: "" },
];
const fill = (tpl, f) => tpl.replace("{user}", encodeURIComponent(f.user)).replace("{pass}", encodeURIComponent(f.pass)).replace("{ip}", f.ip.trim());

export default function IpCameras({ onClose, onChanged, toast }) {
  const [cams, setCams] = useState([]);
  const [f, setF] = useState({ name: "", kind: "wired", brand: "tapo", ip: "", user: "", pass: "", url: "", bind: true });
  const [test, setTest] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = async () => { const r = await api.get("/ip-cameras"); if (r.success) setCams(r.cameras); };
  useEffect(() => { load(); }, []);
  const brand = BRANDS.find((b) => b.id === f.brand);
  const url = brand.url ? (f.ip.trim() ? fill(brand.url, f) : "") : f.url.trim();
  const set = (k) => (e) => { setF({ ...f, [k]: e.target.value }); setTest(null); };

  const runTest = async (body) => {
    setBusy(true);
    const r = await api.post("/ip-cameras/test", body);
    setBusy(false);
    setTest(r);
    if (!r.success) toast(r.message, "bad");
  };
  const save = async () => {
    const r = await api.post("/ip-cameras", { name: f.name, kind: f.kind, url, bind_mac: f.bind });
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setF({ ...f, name: "", ip: "", pass: "", url: "" }); setTest(null); load(); onChanged(); }
  };
  const remove = async (c) => { const r = await api.del(`/ip-cameras/${c.id}`); toast(r.message, r.success ? "ok" : "bad"); load(); onChanged(); };

  return (
    <Modal title="IP camera links" onClose={onClose} wide labelledBy="ipc-title">
      <p className="muted">Wired (network cable / PoE) or Wi-Fi cameras on the same network as this computer. The password is stored encrypted and never shown again.</p>
      {cams.length > 0 && (
        <ul className="ipc-list">
          {cams.map((c) => (
            <li key={c.id}>
              <span className={`tag ${c.kind === "wired" ? "email" : "whatsapp"}`}>{c.kind === "wired" ? "Wired" : "Wi-Fi"}</span>
              <span className="grow"><strong>{c.name}</strong><small className="muted">{c.link}</small>
                <small className={c.mac ? "ok-text" : "muted"}>{c.mac ? `Bound to MAC ${c.mac}` : "Not bound to a MAC address"}</small></span>
              <button className="btn ghost small-btn" disabled={busy} onClick={() => runTest({ id: c.id })}>Test</button>
              <button className="icon-btn" aria-label={`Remove ${c.name}`} onClick={() => remove(c)}><Icon name="trash" size={16} /></button>
            </li>
          ))}
        </ul>
      )}
      <h3 className="h3">Add a camera</h3>
      <div className="fields">
        <Field id="ipc-name" label="Name" value={f.name} onChange={set("name")} placeholder="e.g. Room 204 door" maxLength={60} />
        <Field id="ipc-kind" label="Connection">
          <select id="ipc-kind" value={f.kind} onChange={set("kind")}>
            <option value="wired">Wired (network cable / PoE)</option>
            <option value="wifi">Wi-Fi</option>
          </select>
        </Field>
        <Field id="ipc-brand" wide label="Camera make">
          <select id="ipc-brand" value={f.brand} onChange={set("brand")}>{BRANDS.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</select>
        </Field>
        {brand.url ? (
          <>
            <Field id="ipc-ip" label="Camera IP address" value={f.ip} onChange={set("ip")} placeholder="192.168.1.20" hint="Find it in the camera's app or your router's device list." />
            {brand.url.includes("{user}") && <>
              <Field id="ipc-user" label="User name" value={f.user} onChange={set("user")} autoComplete="off" />
              <Field id="ipc-pass" label="Password" type="password" value={f.pass} onChange={set("pass")} autoComplete="new-password" />
            </>}
          </>
        ) : (
          <Field id="ipc-url" wide label="Stream link" value={f.url} onChange={set("url")} placeholder="rtsp://user:password@192.168.1.20:554/..." hint="Look for 'RTSP' or 'ONVIF' in the camera's manual." />
        )}
      </div>
      {brand.tip && <p className="note small">{brand.tip}</p>}
      {url && <p className="muted small mono">Link: {url.replace(/:[^:@/]*@/, ":•••@")}</p>}
      <label className="check"><input type="checkbox" checked={f.bind} onChange={(e) => setF({ ...f, bind: e.target.checked })} />
        Bind to this camera's MAC address: only this exact camera is used, and it's found again if its IP address changes</label>
      {test?.success && (
        <div className="ipc-test">
          <img src={test.image} alt="Picture from the camera" />
          <div><strong>{test.message}</strong>{test.note && <p className="small">{test.note}</p>}
            <p className="small">{test.mac ? <>MAC address: <span className="mono">{test.mac}</span></> : "MAC address: not visible from this computer (different network)."}</p></div>
        </div>
      )}
      <div className="dialog-actions">
        <button className="btn ghost" disabled={!url || busy} onClick={() => runTest({ url })}>{busy ? "Connecting…" : "Test connection"}</button>
        <button className="btn primary" disabled={!url || !f.name.trim() || busy} onClick={save}><Icon name="plus" size={18} />Save camera</button>
      </div>
    </Modal>
  );
}

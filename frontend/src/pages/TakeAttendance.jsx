// One page for both ways of taking attendance. Admins switch each way on or off;
// for each class, the teacher picks one of the ways that are on.
import { useEffect, useState } from "react";
import { api } from "../api";
import { isHub } from "../org";
import { Icon, PageHead, Segmented } from "../ui";
import IpCameras from "./IpCameras";
import ProxyProtection from "./ProxyProtection";
import LivePage from "./Live";
import PhotoAttendance from "./PhotoAttendance";

const LABEL = { camera: "Live camera", photo: "Class photo" };
const SUB = {
  camera: "Each student faces the camera (laptop, USB or IP camera) and proves they're live. Attendance is saved when they pass.",
  photo: "Take 1–3 photos of the class on your phone. The app finds every face, you check the list, and the photos are kept as evidence.",
};

export default function TakeAttendance({ methods, setMethods, isAdmin, toast, liveProps, photoProps, onCamerasChanged }) {
  const [mode, setMode] = useState(methods[0] || "camera");
  const [ipOpen, setIpOpen] = useState(false);
  const [guardOpen, setGuardOpen] = useState(false);
  const [liveness, setLiveness] = useState("quick");
  useEffect(() => { api.get("/liveness-mode").then((r) => r.success && setLiveness(r.mode)); }, []);
  const pickLiveness = async (mode) => {
    const r = await api.post("/liveness-mode", { mode });
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) setLiveness(r.mode);
  };
  const current = methods.includes(mode) ? mode : methods[0];
  const toggle = async (m) => {
    const next = methods.includes(m) ? methods.filter((x) => x !== m) : [...methods, m];
    const r = await api.post("/attendance-methods", { methods: next });
    if (!r.success) { toast(r.message, "bad"); return; }
    setMethods(r.methods);
    toast(`${LABEL[m]} ${next.includes(m) ? "switched on" : "switched off"}`);
  };
  return (
    <>
      <PageHead title={isHub() && photoProps?.course ? `Take attendance · ${photoProps.course}` : "Take attendance"}
        sub={isHub() ? `${SUB[current]} Only students of this course are checked; change the course in the menu on the left.` : SUB[current]} />
      <div className="method-bar">
        {methods.length > 1 && (
          <Segmented value={current} onChange={setMode} label="How" options={methods.map((m) => ({ id: m, label: LABEL[m], icon: m === "camera" ? "camera" : "upload" }))} />
        )}
        {isAdmin && (
          <fieldset className="channels method-switch">
            <legend>Ways switched on</legend>
            {["camera", "photo"].map((m) => (
              <label key={m} className="check"><input type="checkbox" checked={methods.includes(m)} onChange={() => toggle(m)} />{LABEL[m]}</label>
            ))}
          </fieldset>
        )}
        {isAdmin && <button className="btn ghost" onClick={() => setGuardOpen(true)}><Icon name="shield" size={18} />Proxy protection</button>}
      </div>
      {current === "camera" && isAdmin && (
        <div className="liveness-bar">
          <span className="small"><strong>Liveness check</strong></span>
          <Segmented value={liveness} onChange={pickLiveness} label="Liveness check" options={[
            { id: "quick", label: "Quick: blink twice" }, { id: "secure", label: "Secure: 2 random actions" },
          ]} />
          <span className="muted small">{liveness === "quick" ? "Fastest. A video of the student blinking could pass." : "Blocks photos and videos. For exams or when proxies are suspected."}</span>
        </div>
      )}
      {current === "camera" && <LivePage {...liveProps} header={false} isAdmin={isAdmin} liveness={liveness} onManageIp={() => setIpOpen(true)} />}
      {current === "photo" && <PhotoAttendance {...photoProps} toast={toast} />}
      {guardOpen && <ProxyProtection onClose={() => setGuardOpen(false)} toast={toast} />}
      {ipOpen && <IpCameras onClose={() => setIpOpen(false)} onChanged={onCamerasChanged} toast={toast} />}
    </>
  );
}

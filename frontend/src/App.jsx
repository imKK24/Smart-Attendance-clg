import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./App.css";
import "./batch1.css";
import "./batch2.css";
import "./batch3.css";
import "./batch4.css";
import "./batch5.css";
import "./ithub.css";
import { api, getToken, prepareAttendance, refreshMediaToken, setToken, tokenKind, whenLoggedOut, whenMustChange } from "./api";
import AttendancePage from "./pages/Attendance";
import Dashboard from "./pages/Dashboard";
import FeesPage from "./pages/Fees";
import InboxPage from "./pages/Inbox";
import TakeAttendance from "./pages/TakeAttendance";
import LeavesPage from "./pages/Leaves";
import Login from "./pages/Login";
import ParentPortal from "./pages/ParentPortal";
import SetPassword from "./pages/SetPassword";
import NotifyPage from "./pages/Notify";
import RegisterPage from "./pages/Register";
import ReportsPage from "./pages/Reports";
import StudentsPage from "./pages/Students";
import CoursesPage from "./pages/Courses";
import TeamPage from "./pages/Team";
import { isHub, orgSub, orgTitle, setHubLists, setOrg, unitCourse } from "./org";
import { Icon, Tick, refreshPhotos } from "./ui";
import { plural } from "./util";

const NAV = [
  { id: "dashboard", icon: "home", label: "Dashboard" },
  { id: "attendance", icon: "book", label: "Attendance" },
  { id: "students", icon: "users", label: "Students" },
  { id: "courses", icon: "grid", label: "Courses", hub: true, admin: true },
  { id: "register", icon: "plus", label: "Register" },
  { id: "live", icon: "camera", label: "Take attendance" },
  { id: "leaves", icon: "calendar", label: "Leave" },
  { id: "reports", icon: "chart", label: "Reports" },
  { id: "inbox", icon: "inbox", label: "Inbox" },
  { id: "notify", icon: "bell", label: "Notify" },
  { id: "fees", icon: "fee", label: "Fees", admin: true },
  { id: "team", icon: "user", label: "Team", admin: true },
];
const IDLE_CAM = { active: false, status: "idle", message: "", marked_count: 0, recent: [], camera: null };
const IDLE_MSG = { running: false, total: 0, sent: 0, failed: 0, queued: 0, failed_total: 0, last: null };
const NO_INBOX = { mails: [], unread: 0, configured: false, sync: {} };

export default function App() {
  // { username, full_name, role: "admin" | "teacher", branches }
  // A portal login (college parent / IT Hub student) opens the one-student page.
  const [user, setUser] = useState(getToken() ? { username: "…", role: tokenKind() === "parent" ? (isHub() ? "student" : "parent") : "" } : null);
  const [notice, setNotice] = useState("");
  useEffect(() => whenLoggedOut((msg) => { setUser(null); setNotice(msg || ""); }), []);
  useEffect(() => whenMustChange(() => setUser((u) => (u ? { ...u, must_change: true } : u))), []);
  if (user?.org) setOrg(user.org);   // college or Aakansha IT Hub: labels, colours, courses
  if (!user) return <Login notice={notice} onDone={(u) => { setNotice(""); setUser(u); }} />;
  if (user.role === "parent" || user.role === "student") return <ParentPortal onLogout={() => { setToken(""); setUser(null); }} />;
  if (user.must_change) return <SetPassword user={user} onDone={setUser} onLogout={() => { setToken(""); setUser(null); }} />;
  return <Shell user={user} setUser={setUser} />;
}

function Shell({ user, setUser }) {
  const [page, setPage] = useState("dashboard");
  const [notifyTab, setNotifyTab] = useState("alerts");
  const [openMail, setOpenMail] = useState(null);
  const [leaveDraft, setLeaveDraft] = useState(null);
  const [inboxChannel, setInboxChannel] = useState("email");
  const [openPhone, setOpenPhone] = useState(null);
  const [chats, setChats] = useState({ chats: [], unread: 0 });
  const [methods, setMethods] = useState(["camera", "photo"]);
  const [leavesPending, setLeavesPending] = useState(0);
  const [online, setOnline] = useState(false);
  const [students, setStudents] = useState([]);
  const [studentsLoading, setStudentsLoading] = useState(true);
  const [today, setToday] = useState(null);
  const [dates, setDates] = useState([]);
  const [history, setHistory] = useState([]);
  const [cam, setCam] = useState(IDLE_CAM);
  const [cameras, setCameras] = useState([]);
  const [camsLoading, setCamsLoading] = useState(false);
  const [settings, setSettings] = useState({ configured: false, gmail: "", password_set: false, sender_name: "", school_name: "", threshold: 3,
    auto_send: true, alert_channels: ["whatsapp", "email"], country_code: "91", wa_delay: 6, camera: "default" });
  const [alerts, setAlerts] = useState({ students: [], due_count: 0, threshold: 3 });
  const [inbox, setInbox] = useState(NO_INBOX);
  const [msgStatus, setMsgStatus] = useState(IDLE_MSG);
  const [wa, setWa] = useState({ state: "offline", qr: null, me: null, error: "" });
  const [busy, setBusy] = useState(false);
  const [mediaKey, setMediaKey] = useState(0);
  const [mediaReady, setMediaReady] = useState(false);   // first view-only pass fetched (or tried)
  const [feedKey, setFeedKey] = useState(0);
  const [toasts, setToasts] = useState([]);
  const [confirm, setConfirm] = useState(null);
  const markedRef = useRef(0);
  const onlineRef = useRef(false);

  const toast = useCallback((msg, kind = "ok") => {
    if (!msg) return;
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);
  const askConfirm = useCallback((c) => setConfirm(c), []);
  const go = useCallback((target, extra) => {
    const [p, sub] = target.split(":");
    if (p === "notify" && sub) setNotifyTab(sub);
    if (p === "inbox") { setOpenMail(extra ?? null); if (sub) setInboxChannel(sub); }
    if (p === "leaves") setLeaveDraft(extra ?? null);
    setPage(p);
    window.scrollTo(0, 0);
  }, []);

  // ── derived lookups ──
  const ids = useMemo(() => Object.fromEntries(students.map((s) => [s.name, s.id])), [students]);
  const branchOf = useMemo(() => Object.fromEntries(students.map((s) => [s.name, s.branch])), [students]);
  // IT Hub: courses (from its course list) take the place of branches everywhere.
  const hub = isHub();
  const [courseList, setCourseList] = useState([]);      // courses this user may see
  const [allCourses, setAllCourses] = useState([]);      // every course the IT Hub offers
  const [myCourses, setMyCourses] = useState([]);        // courses this user can register students into
  const [teamUnits, setTeamUnits] = useState([]);        // whole courses and Course · Batch, for Team
  const [course, setCourseState] = useState(() => { try { return localStorage.getItem("attendai_hub_course") || ""; } catch { return ""; } });
  const setCourse = useCallback((c) => { setCourseState(c); try { localStorage.setItem("attendai_hub_course", c); } catch { /* private mode */ } }, []);
  const cq = hub ? `?course=${encodeURIComponent(course)}` : "";
  const studentBranches = useMemo(() => [...new Set(students.map((s) => s.branch).filter(Boolean))].sort(), [students]);
  const branches = hub ? courseList : studentBranches;
  const classes = useMemo(() => [...new Set(students.map((s) => s.class_name).filter(Boolean))].sort(), [students]);

  // ── loaders ──
  const loadStudents = useCallback(async () => {
    const r = await api.get("/students");
    if (r.success) { refreshPhotos(); setStudents(r.students ?? []); }
    setStudentsLoading(false);
  }, []);
  const loadToday = useCallback(async () => { const r = await api.get(`/attendance/today${cq}`); if (r.success) setToday(r); }, [cq]);
  const loadDates = useCallback(async () => { const r = await api.get(`/attendance-dates${cq}`); if (r.success) setDates(r.dates ?? []); }, [cq]);
  const loadHistory = useCallback(async () => { const r = await api.get(`/history${cq}`); if (r.success) setHistory(r.history ?? []); }, [cq]);
  const loadCourses = useCallback(async () => {
    if (!isHub()) return;
    const r = await api.get("/students/branches");
    if (r.success) {
      setCourseList(r.branches ?? []); setAllCourses(r.courses ?? []); setMyCourses(r.my_courses ?? []); setTeamUnits(r.team ?? []);
      setHubLists({ courses: r.my_courses ?? [], batches: r.batches ?? [] });
    }
  }, []);
  const loadSettings = useCallback(async () => { const r = await api.get("/settings"); if (r.success) setSettings(r); }, []);
  const loadAlerts = useCallback(async () => { const r = await api.get("/alerts"); if (r.success) setAlerts({ students: [], due_count: 0, threshold: 3, ...r }); }, []);
  const loadInbox = useCallback(async () => { const r = await api.get("/inbox?limit=150"); if (r.success) setInbox({ ...NO_INBOX, ...r }); }, []);
  const loadMsg = useCallback(async () => { const r = await api.get("/messages/status"); if (r.success) setMsgStatus(r); }, []);
  const loadMethods = useCallback(async () => { const r = await api.get("/attendance-methods"); if (r.success && r.methods?.length) setMethods(r.methods); }, []);
  const loadChats = useCallback(async () => { const r = await api.get("/whatsapp/chats"); if (r.success) setChats({ chats: r.chats ?? [], unread: r.unread ?? 0 }); }, []);
  const loadLeaves = useCallback(async () => { const r = await api.get("/leaves?status=pending"); if (r.success) setLeavesPending(r.pending); }, []);
  const loadWa = useCallback(async () => { const r = await api.get("/whatsapp/status"); if (r.success) setWa(r); }, []);
  const loadCam = useCallback(async () => {
    const r = await api.get("/camera-status");
    if (r.success) { markedRef.current = r.marked_count ?? 0; setCam({ ...IDLE_CAM, ...r }); }
  }, []);
  const loadCameras = useCallback(async (refresh) => {
    setCamsLoading(true);
    const r = await api.get(`/cameras${refresh ? "?refresh=1" : ""}`);
    if (r.success) setCameras(r.cameras ?? []);
    setCamsLoading(false);
  }, []);
  const loadAll = useCallback(() => {
    api.get("/auth/me").then((r) => { if (r.success && r.user) setUser(r.user); });
    loadStudents(); loadToday(); loadDates(); loadHistory(); loadCam(); loadCourses();
    loadSettings(); loadAlerts(); loadInbox(); loadMsg(); loadWa(); loadLeaves(); loadChats(); loadMethods();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadMethods, setUser, loadStudents, loadCam, loadCourses, loadSettings, loadAlerts, loadInbox, loadMsg, loadWa, loadLeaves, loadChats]);

  // ── IT Hub: keep a valid course picked, and reload the register when it changes ──
  useEffect(() => {
    if (hub && courseList.length && !courseList.includes(course)) setCourse(courseList[0]);
  }, [hub, courseList, course, setCourse]);
  useEffect(() => {
    if (onlineRef.current) { loadToday(); loadDates(); loadHistory(); }
  }, [loadToday, loadDates, loadHistory]);

  // ── server connection: check every 5s, reload everything when it comes back ──
  useEffect(() => {
    let alive = true;
    const ping = async () => {
      const r = await api.get("/health");
      if (!alive) return;
      if (r.success && !onlineRef.current) loadAll();
      if (!r.success) setStudentsLoading(false);
      onlineRef.current = r.success;
      setOnline(r.success);
    };
    ping();
    const id = setInterval(ping, 5000);
    return () => { alive = false; clearInterval(id); };
  }, [loadAll]);

  // ── view-only token for photos and downloads: get one now, renew every 10 minutes ──
  useEffect(() => {
    if (!online) return undefined;
    let alive = true;
    const renew = async () => {
      const got = await refreshMediaToken();
      if (!alive) return;
      if (got) setMediaKey((k) => k + 1);
      setMediaReady(true);
    };
    renew();
    const id = setInterval(renew, 10 * 60 * 1000);
    return () => { alive = false; clearInterval(id); };
  }, [online]);

  // ── slow background refresh: inbox, WhatsApp link, message counts ──
  useEffect(() => {
    if (!online) return undefined;
    const id = setInterval(() => { loadInbox(); loadWa(); loadMsg(); loadChats(); }, 30000);
    return () => clearInterval(id);
  }, [online, loadInbox, loadWa, loadMsg, loadChats]);

  // ── poll the camera while it is running ──
  useEffect(() => {
    if (!cam.active) return undefined;
    const id = setInterval(async () => {
      const r = await api.get("/camera-status");
      if (!r.success) return;
      setCam(r);
      if (r.marked_count !== markedRef.current) { markedRef.current = r.marked_count; loadToday(); loadHistory(); }
      if (!r.active) {
        loadToday(); loadHistory(); loadDates(); loadAlerts();
        setTimeout(loadMsg, 2500);
        if (r.status === "error") toast(r.message, "bad");
      }
    }, 1200);
    return () => clearInterval(id);
  }, [cam.active, loadToday, loadHistory, loadDates, loadAlerts, loadMsg, toast]);

  // ── poll the message queue while it is sending ──
  useEffect(() => {
    if (!msgStatus.running) return undefined;
    const id = setInterval(async () => {
      const r = await api.get("/messages/status");
      if (!r.success) return;
      setMsgStatus(r);
      if (!r.running) {
        toast(r.failed ? `Sent ${r.sent}, ${r.failed} failed. See the Sent tab.` : `Sent ${plural(r.sent, "message")}`, r.failed ? "bad" : "ok");
        loadAlerts(); loadInbox();
      }
    }, 1500);
    return () => clearInterval(id);
  }, [msgStatus.running, loadAlerts, loadInbox, toast]);

  // ── Esc closes the confirm dialog ──
  useEffect(() => {
    if (!confirm) return undefined;
    const onKey = (e) => e.key === "Escape" && setConfirm(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirm]);

  // ── actions ──
  const onQueued = useCallback(() => { setMsgStatus((m) => ({ ...m, running: true })); loadMsg(); }, [loadMsg]);
  const startCam = async () => {
    setBusy(true);
    const where = await prepareAttendance();          // location, if the admin's proxy protection needs it
    if (where) { setBusy(false); toast(where, "bad"); return false; }
    const r = await api.post("/start-attendance", hub ? { course } : {});
    setBusy(false);
    if (!r.success) { toast(r.message, "bad"); return false; }
    markedRef.current = 0;
    setFeedKey((k) => k + 1);
    setCam({ ...IDLE_CAM, active: true, status: "starting", message: "Loading student faces..." });
    return true;
  };
  const stopCam = async () => {
    setBusy(true);
    const r = await api.post("/stop-attendance");
    setBusy(false);
    if (!r.success) { toast(r.message, "bad"); return; }
    setCam((c) => ({ ...c, active: false, status: "idle", message: "Camera stopped. Attendance saved." }));
    toast("Attendance saved");
    loadToday(); loadHistory(); loadDates(); loadAlerts();
    setTimeout(onQueued, 2500); // absence alerts may have started sending
  };
  const pickCamera = async (value) => {
    const r = await api.post("/camera-source", { camera: value });
    if (r.success) setSettings((s) => ({ ...s, camera: value })); else toast(r.message, "bad");
  };
  const deleteStudent = async (id) => {
    const r = await api.del(`/students/${id}`);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { loadStudents(); loadToday(); loadAlerts(); }
  };
  const updateStudent = async (id, details) => {
    const r = await api.put(`/students/${id}`, details);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { loadStudents(); loadAlerts(); }
    return r.success;
  };
  const sendAlerts = async (id, channels) => {
    const r = await api.post("/alerts/send", { id, channels });
    toast(r.message, r.success ? "ok" : "bad");
    if (r.queued) onQueued();
  };
  const saveSettings = async (form) => {
    const r = await api.post("/settings", form);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { loadSettings(); loadAlerts(); loadInbox(); }
  };
  const clearLeaveDraft = useCallback(() => setLeaveDraft(null), []);
  // Logging out ends this login on every device (the server stops accepting the old token).
  const logout = async () => { await api.post("/auth/logout"); setToken(""); setUser(null); };

  const badge = { notify: alerts.due_count, inbox: inbox.unread + chats.unread, leaves: leavesPending };
  const isAdmin = user.role === "admin";
  const nav = NAV.filter((n) => (!n.admin || isAdmin) && (!n.hub || hub));

  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <div className="brand">
          <span className="brand-mark"><Tick size={20} /></span>
          <div><strong>{orgTitle()}</strong><small>{orgSub()}</small></div>
        </div>
        {hub && courseList.length > 0 && (
          <label className="course-pick">
            <span>Course</span>
            <select value={course} onChange={(e) => setCourse(e.target.value)} disabled={cam.active} aria-label="Course you are working on">
              {courseList.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        )}
        <ul className="nav">
          {nav.map((n) => (
            <li key={n.id}>
              <button aria-current={page === n.id ? "page" : undefined} onClick={() => go(n.id)}>
                <Icon name={n.icon} /><span>{n.label}</span>
                {n.id === "live" && cam.active && <i className="live-dot" role="img" aria-label="Camera running" />}
                {badge[n.id] > 0 && <b className="badge" aria-label={`${badge[n.id]} new`}>{badge[n.id]}</b>}
              </button>
            </li>
          ))}
        </ul>
        <div className="server">
          <i className={`dot ${online ? "ok" : "no"}`} />
          <div className="grow"><strong>{online ? "Server connected" : "Server offline"}</strong><small>{online ? `${user.full_name || user.username} · ${isAdmin ? "Admin" : "Teacher"}` : "Server not reachable"}</small></div>
          <button className="icon-btn on-blue" onClick={logout} aria-label="Log out" title="Log out"><Icon name="logout" size={18} /></button>
        </div>
      </nav>

      <main className="main" data-media={mediaKey}>
        {!online && <div className="banner" role="alert">Can't reach the server. On the AttendAI computer, start it again (<code>python serve.py</code>). This page reconnects by itself.</div>}
        {(mediaReady || !online) && <>
        {hub && online && !studentsLoading && allCourses.length === 0 && (
          <div className="banner info" role="status">
            {isAdmin ? <>Add the IT Hub's courses first (Python, Tally, …). <button className="link" onClick={() => go("courses")}>Open Courses</button></>
              : "No courses have been set up yet. Ask the IT Hub admin to add them."}
          </div>
        )}
        {hub && online && !isAdmin && allCourses.length > 0 && courseList.length === 0 && (
          <div className="banner info" role="status">No course has been assigned to you yet. Ask the IT Hub admin to tick your courses on the Team page.</div>
        )}

        {page === "dashboard" && <Dashboard today={today} history={history} students={students} online={online} cam={cam} busy={busy} go={go}
          onStart={async () => { if (await startCam()) go("live"); }} inbox={inbox} ids={ids} branchOf={branchOf} branches={hub ? [] : branches} />}
        {page === "team" && isAdmin && <TeamPage branches={hub ? teamUnits : branches} toast={toast} askConfirm={askConfirm} />}
        {page === "attendance" && <AttendancePage dates={dates} today={today} go={go} ids={ids} branchOf={branchOf} branches={hub ? [] : branches} course={course} />}
        {page === "students" && <StudentsPage students={students} loading={studentsLoading} today={today} askConfirm={askConfirm} onDelete={deleteStudent}
          onUpdate={updateStudent} go={go} branches={branches} classes={classes} countryCode={settings.country_code} toast={toast} isAdmin={isAdmin} course={course} />}
        {page === "courses" && hub && isAdmin && <CoursesPage isAdmin={isAdmin} toast={toast} askConfirm={askConfirm} onChanged={loadCourses} go={go}
          setCourse={(c) => setCourse(courseList.find((u) => unitCourse(u) === c) || c)} />}
        {page === "register" && <RegisterPage camActive={cam.active} onSaved={() => { loadStudents(); loadToday(); loadAlerts(); }} toast={toast}
          askConfirm={askConfirm} branches={branches} classes={classes} countryCode={settings.country_code} course={course} />}
        {page === "live" && <TakeAttendance methods={methods} setMethods={setMethods} isAdmin={isAdmin} toast={toast} onCamerasChanged={() => loadCameras(true)}
          liveProps={{ cam, busy, feedKey, onStart: startCam, onStop: stopCam, cameras, camSetting: settings.camera, camsLoading,
            onPickCamera: pickCamera, onLoadCameras: loadCameras, ids, holiday: today?.holiday }}
          photoProps={{ branches, ids, course, onSaved: () => { loadToday(); loadHistory(); loadDates(); loadAlerts(); setTimeout(onQueued, 2500); } }} />}
        {page === "leaves" && <LeavesPage students={students} ids={ids} toast={toast} askConfirm={askConfirm} draft={leaveDraft} clearDraft={clearLeaveDraft}
          onChanged={() => { loadLeaves(); loadToday(); loadAlerts(); }} avail={{ wa: wa.state, email: settings.configured }} onQueued={onQueued} go={go} />}
        {page === "reports" && <ReportsPage branches={branches} ids={ids} toast={toast} go={go} isAdmin={isAdmin} course={course} />}
        {page === "inbox" && <InboxPage inbox={inbox} reload={loadInbox} openId={openMail} setOpenId={setOpenMail} ids={ids} toast={toast} go={go}
          chats={chats} reloadChats={loadChats} waState={wa.state} openPhone={openPhone} setOpenPhone={setOpenPhone} channel={inboxChannel} setChannel={setInboxChannel} />}
        {page === "fees" && isAdmin && <FeesPage students={students} branches={hub ? allCourses : branches} course={hub ? unitCourse(course) : course} classes={classes} ids={ids} toast={toast} askConfirm={askConfirm}
          avail={{ wa: wa.state, email: settings.configured }} onQueued={onQueued} />}
        {page === "notify" && <NotifyPage tab={notifyTab} setTab={setNotifyTab} alerts={alerts} settings={settings} msgStatus={msgStatus} wa={wa} reloadWa={loadWa}
          onQueued={onQueued} sendAlerts={sendAlerts} saveSettings={saveSettings} askConfirm={askConfirm} toast={toast} ids={ids} isAdmin={isAdmin}
          courses={hub ? myCourses : branches} course={hub ? unitCourse(course) : course} />}
        </>}
      </main>

      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast${t.kind === "bad" ? " bad" : ""}`}>{t.msg}</div>)}
      </div>

      {confirm && (
        <div className="scrim" onClick={() => setConfirm(null)}>
          <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dlg-title" onClick={(e) => e.stopPropagation()}>
            <h2 id="dlg-title">{confirm.title}</h2>
            <p>{confirm.body}</p>
            <div className="dialog-actions">
              <button className="btn ghost" onClick={() => setConfirm(null)}>Cancel</button>
              <button className={`btn ${confirm.danger ? "danger" : "primary"}`} autoFocus onClick={() => { const yes = confirm.onYes; setConfirm(null); yes(); }}>{confirm.label}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

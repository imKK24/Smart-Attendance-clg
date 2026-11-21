import { useEffect, useState } from "react";
import { api, setToken } from "../api";
import { isHub, onHubPage, orgSub, orgTitle, unitsLower } from "../org";
import { Field, Segmented, Tick } from "../ui";

export default function Login({ onDone, notice }) {
  const hub = onHubPage();          // /it-hub: Aakansha IT Hub's own login page (no parents, no first setup)
  const [setup, setSetup] = useState(null); // null = still checking
  const [f, setF] = useState({ username: "", password: "", confirm: "", reg_no: "", name: "", phone: "" });
  const [role, setRole] = useState("admin");
  const [error, setError] = useState(notice || "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    const check = async () => {
      const r = await api.get("/auth/status");
      if (!live) return;
      if (r.offline) { setSetup(false); setError("Can't reach the server. Start it with: python app.py"); setTimeout(check, 4000); return; }
      setSetup(!!r.setup_needed && !hub);
      setError((e) => (e.startsWith("Can't reach") ? "" : e));
    };
    check();
    return () => { live = false; };
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (setup && f.password !== f.confirm) { setError("The two passwords don't match."); return; }
    setBusy(true);
    const portal = role === "parent" || role === "student";   // college parents / IT Hub students
    const r = portal && !setup
      ? await api.post("/parent/login", { reg_no: f.reg_no, name: f.name, phone: f.phone, org: hub ? "ithub" : "college" })
      : await api.post(setup ? "/auth/setup" : "/auth/login",
        { username: f.username.trim(), password: f.password, ...(setup ? {} : { role, org: hub ? "ithub" : "college" }) });
    setBusy(false);
    if (!r.success) { setError(r.message || "Couldn't log in."); return; }
    setToken(r.token);
    onDone(r.user || { username: r.username, role: "" });
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  return (
    <main className="login">
      <form className="panel login-card" onSubmit={submit}>
        <div className="brand dark">
          <span className="brand-mark"><Tick size={20} /></span>
          <div><strong>{orgTitle()}</strong><small>{orgSub()}</small></div>
        </div>
        <h1>{setup ? "Create the admin account" : "Log in"}</h1>
        {hub && <p className="muted small org-switch">College staff and parents: <a href="/">log in here</a></p>}
        {!setup && setup !== null && (
          <Segmented value={role} onChange={(v) => { setRole(v); setError(""); }} label="Log in as" options={[
            { id: "admin", label: "Admin" }, { id: "teacher", label: "Teacher" },
            hub ? { id: "student", label: "Student" } : { id: "parent", label: "Parent" },
          ]} />
        )}
        <p className="muted">{setup ? "This is the first start. The account you create here is the only way into the dashboard."
          : role === "admin" ? (isHub() ? "Admins manage the IT Hub: courses, students, fees, holidays and the team."
            : "Admins manage everything: settings, WhatsApp, holidays, events and the team.")
            : role === "teacher" ? (hub ? "Teachers see only the courses the admin assigned them." : `Teachers see only the students of their own ${unitsLower()}.`)
              : role === "student" ? "See your attendance for each course, your test results and fees, and apply for leave."
                : "See your child's attendance, results and leave, and apply for leave. Use the mobile number you gave the college."}</p>
        {error && <p className="say warn" role="alert">{error}</p>}
        {role === "student" && !setup ? (
          <>
            <Field id="pl-reg" label="Your registration number" value={f.reg_no} onChange={set("reg_no")} autoComplete="off" required autoFocus placeholder="e.g. AIH-001" />
            <Field id="pl-name" label="Your full name" value={f.name} onChange={set("name")} autoComplete="name" required placeholder="As registered at the IT Hub" />
            <Field id="pl-phone" label="Your mobile number" type="tel" inputMode="tel" value={f.phone} onChange={set("phone")} autoComplete="tel" required
              placeholder="98765 43210" hint="The number you gave Aakansha IT Hub when you joined." />
          </>
        ) : role === "parent" && !setup ? (
          <>
            <Field id="pl-reg" label="Student's registration number" value={f.reg_no} onChange={set("reg_no")} autoComplete="off" required autoFocus placeholder="e.g. 2301201037" />
            <Field id="pl-name" label="Student's full name" value={f.name} onChange={set("name")} autoComplete="off" required placeholder="As registered at the college" />
            <Field id="pl-phone" label="Your mobile number" type="tel" inputMode="tel" value={f.phone} onChange={set("phone")} autoComplete="tel" required
              placeholder="98765 43210" hint="The number the college sends alerts to." />
          </>
        ) : (
          <>
            <Field id="lg-user" label="Email or username" value={f.username} onChange={set("username")} autoComplete="username" required minLength={3} autoFocus />
            <Field id="lg-pass" label="Password" type="password" value={f.password} onChange={set("password")} autoComplete={setup ? "new-password" : "current-password"}
              required minLength={setup ? 8 : 1} hint={setup ? "At least 8 characters." : undefined} />
          </>
        )}
        {setup && <Field id="lg-conf" label="Type the password again" type="password" value={f.confirm} onChange={set("confirm")} autoComplete="new-password" required />}
        <button className="btn primary wide" disabled={busy || setup === null}>{busy ? "Please wait…" : setup ? "Create account" : `Log in as ${role === "admin" ? "Admin" : role === "teacher" ? "Teacher" : role === "student" ? "Student" : "Parent"}`}</button>
        {!setup && setup !== null && role !== "parent" && role !== "student" && <p className="muted small">Forgot it? {hub ? "Ask the IT Hub admin to reset it."
          : <>In the backend folder run <code>python manage.py reset-password admin</code></>}</p>}
        {!hub && <p className="muted small org-switch">Aakansha IT Hub staff: <a href="/it-hub">log in here</a></p>}
      </form>
    </main>
  );
}

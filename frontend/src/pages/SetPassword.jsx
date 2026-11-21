// Shown instead of the dashboard when an account must choose its own password:
// accounts the admin created, ready-made accounts, or a password the admin reset.
import { useState } from "react";
import { api, setToken } from "../api";
import { orgSub, orgTitle } from "../org";
import { Field, Tick } from "../ui";

export default function SetPassword({ user, onDone, onLogout }) {
  const [f, setF] = useState({ current: "", new: "", confirm: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async (e) => {
    e.preventDefault();
    if (f.new !== f.confirm) { setError("The two new passwords don't match."); return; }
    setBusy(true);
    const r = await api.post("/auth/password", { current: f.current, new: f.new });
    setBusy(false);
    if (!r.success) { setError(r.message); return; }
    setToken(r.token);
    onDone(r.user);
  };
  return (
    <main className="login">
      <form className="panel login-card" onSubmit={submit}>
        <div className="brand dark">
          <span className="brand-mark"><Tick size={20} /></span>
          <div><strong>{orgTitle()}</strong><small>{orgSub()}</small></div>
        </div>
        <h1>Choose your own password</h1>
        <p className="muted">Hi {user.full_name || user.username}. Your first password was given to you by someone else, so set a new one that only you know.</p>
        {error && <p className="say warn" role="alert">{error}</p>}
        <Field id="sp-cur" label="Password you just used" type="password" value={f.current} onChange={set("current")} autoComplete="current-password" required autoFocus />
        <Field id="sp-new" label="New password" type="password" value={f.new} onChange={set("new")} autoComplete="new-password" required minLength={8} hint="At least 8 characters. Not a common password, and not your login name." />
        <Field id="sp-conf" label="New password again" type="password" value={f.confirm} onChange={set("confirm")} autoComplete="new-password" required />
        <button className="btn primary wide" disabled={busy || f.new.length < 8}>{busy ? "Saving…" : "Save and continue"}</button>
        <button type="button" className="link small" onClick={onLogout}>Log out</button>
      </form>
    </main>
  );
}

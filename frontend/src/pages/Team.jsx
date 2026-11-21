// Admin only: add teachers, pick which branches they see, switch accounts off.
import { useEffect, useState } from "react";
import { api } from "../api";
import { isHub, SEP, unitLower, units, unitsLower } from "../org";
import { Field, Icon, Modal, PageHead } from "../ui";

const EMPTY = { username: "", full_name: "", password: "", role: "teacher", branches: [] };

function BranchPicker({ value, onChange, branches }) {
  const [extra, setExtra] = useState("");
  const all = [...new Set([...branches, ...value])].sort();
  const toggle = (b) => onChange(value.includes(b) ? value.filter((x) => x !== b) : [...value, b]);
  return (
    <fieldset className="channels branch-pick">
      <legend>{units()} they can see</legend>
      {all.map((b) => <label key={b} className={`check${isHub() && b.includes(SEP) ? " sub" : ""}`}><input type="checkbox" checked={value.includes(b)} onChange={() => toggle(b)} />
        {isHub() && !b.includes(SEP) && all.some((x) => x.startsWith(b + SEP)) ? <><b>{b}</b>&nbsp;(all batches)</> : b}</label>)}
      {!isHub() && (   // IT Hub courses come from the course list on the Students page
        <span className="add-branch">
          <input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="Other branch" aria-label="Add another branch" maxLength={60} />
          <button type="button" className="btn ghost small-btn" disabled={!extra.trim()} onClick={() => { onChange([...new Set([...value, extra.trim()])]); setExtra(""); }}>Add</button>
        </span>
      )}
      <small className="muted">{value.length ? `Only students in ${value.join(", ")}.` : (isHub() ? "No course ticked: they see nothing until you tick their courses." : `No ${unitLower()} ticked: they see every ${unitLower()}.`)}</small>
    </fieldset>
  );
}

function UserForm({ value, onChange, branches, isNew }) {
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="fields">
      {isNew && <Field id="u-name" label="Login email" type="email" value={value.username} onChange={set("username")} autoComplete="off" maxLength={60} hint="They log in with this, e.g. deepika@college.edu" />}
      <Field id="u-full" label="Full name" value={value.full_name} onChange={set("full_name")} maxLength={80} />
      <Field id="u-pass" label={isNew ? "Password" : "New password (optional)"} type="password" value={value.password} onChange={set("password")} autoComplete="new-password" hint="At least 8 characters." />
      <Field id="u-role" label="Role">
        <select id="u-role" value={value.role} onChange={set("role")}>
          <option value="teacher">Teacher: their {unitsLower()} only</option>
          <option value="admin">Admin: everything, including settings</option>
        </select>
      </Field>
      {value.role === "teacher" && <div className="field wide"><BranchPicker value={value.branches} onChange={(branches) => onChange({ ...value, branches })} branches={branches} /></div>}
    </div>
  );
}

export default function TeamPage({ branches, toast, askConfirm }) {
  const [users, setUsers] = useState([]);
  const [me, setMe] = useState(null);
  const [f, setF] = useState(EMPTY);
  const [edit, setEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  const load = async () => { const r = await api.get("/users"); if (r.success) { setUsers(r.users); setMe(r.me); } };
  useEffect(() => { load(); }, []);

  const create = async () => {
    setSaving(true);
    const r = await api.post("/users", f);
    setSaving(false);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setF(EMPTY); load(); }
  };
  const update = async (u, patch) => {
    const r = await api.put(`/users/${u.id}`, patch);
    toast(r.message, r.success ? "ok" : "bad");
    if (r.success) { setEdit(null); load(); }
    return r.success;
  };

  return (
    <>
      <PageHead title="Team" sub={`Give each teacher their own login. Teachers only see students in their ${unitsLower()} and can't change settings, ${isHub() ? "fees" : "WhatsApp"}, holidays or events.${isHub() ? " IT Hub staff log in at /it-hub." : ""}`} />
      <div className="events">
        <section className="panel pad ev-form">
          <h2 className="h2">Add a person</h2>
          <UserForm value={f} onChange={setF} branches={branches} isNew />
          <button className="btn primary" disabled={saving || !f.username.trim() || f.password.length < 8} onClick={create}><Icon name="plus" />Create login</button>
          <p className="muted small">Tell them their login email and this first password yourself. At their first login they must choose their own password, so you won't know it.</p>
        </section>
        <section className="ev-list">
          {users.map((u) => (
            <article key={u.id} className={`panel ev user${u.active ? "" : " off"}`}>
              <span className="avatar" aria-hidden="true">{(u.full_name || u.username).slice(0, 2).toUpperCase()}</span>
              <div className="ev-main">
                <h3>{u.full_name || u.username} {u.id === me && <span className="muted small">(you)</span>}</h3>
                <p className="muted">{u.username} · {u.role === "admin" ? "Admin" : u.branches.length ? `Teacher: ${u.branches.join(", ")}` : (isHub() ? "Teacher: no course assigned yet" : `Teacher: all ${unitsLower()}`)}</p>
                {!u.active && <span className="chip no">Switched off</span>}
              </div>
              <div className="ev-actions">
                <button className="btn ghost" onClick={() => setEdit({ ...u, password: "" })}><Icon name="edit" size={18} />Edit</button>
                {u.id !== me && (
                  <button className="btn ghost" onClick={() => update(u, { active: !u.active })}>{u.active ? "Switch off" : "Switch on"}</button>
                )}
                {u.id !== me && (
                  <button className="icon-btn" aria-label={`Delete ${u.username}`} onClick={() => askConfirm({
                    title: `Delete ${u.username}?`, body: "They can't log in any more. Attendance they took stays.", label: "Delete", danger: true,
                    onYes: async () => { const r = await api.del(`/users/${u.id}`); toast(r.message, r.success ? "ok" : "bad"); load(); },
                  })}><Icon name="trash" size={18} /></button>
                )}
              </div>
            </article>
          ))}
        </section>
      </div>
      {edit && (
        <Modal title={`Edit ${edit.username}`} onClose={() => setEdit(null)} wide labelledBy="u-edit">
          <UserForm value={edit} onChange={setEdit} branches={branches} />
          <div className="dialog-actions">
            <button className="btn ghost" onClick={() => setEdit(null)}>Cancel</button>
            <button className="btn primary" onClick={() => update(edit, { full_name: edit.full_name, role: edit.role, branches: edit.branches, ...(edit.password ? { password: edit.password } : {}) })}>Save</button>
          </div>
        </Modal>
      )}
    </>
  );
}

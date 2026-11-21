// The student details form, used both when registering and when editing.
import { hubBatches, hubCourses, isHub } from "./org";
import { Field, Icon } from "./ui";
import { emailProblem, phoneProblem } from "./util";

export const EMPTY_STUDENT = {
  roll_no: "", branch: "", courses: [], batches: {}, class_name: "", student_phone: "", student_email: "",
  parent_name: "", parent_relation: "", parent_phone: "", parent_email: "", alt_phone: "",
  address: "", qualifications: [], achievements: [],
};
export const pickStudent = (s) => Object.fromEntries(Object.keys(EMPTY_STUDENT).map((k) => [k, s[k] ?? EMPTY_STUDENT[k]]));

const QUAL_PRESETS = ["Class 10", "Class 12", "Diploma", "B.Tech", "B.Sc", "M.Tech"];
const RELATIONS = ["Father", "Mother", "Guardian", "Other"];
const EMPTY_QUAL = { course: "", board: "", year: "", score: "" };
const EMPTY_ACH = { title: "", year: "", details: "" };

export function formProblems(v) {
  const out = {};
  for (const k of ["parent_phone", "alt_phone", "student_phone"]) { const p = phoneProblem(v[k]); if (p) out[k] = p; }
  for (const k of ["parent_email", "student_email"]) { const p = emailProblem(v[k]); if (p) out[k] = p; }
  return out;
}

function Rows({ items, onChange, fields, empty, addLabel, prefix, cols }) {
  const set = (i, k, val) => onChange(items.map((it, j) => (j === i ? { ...it, [k]: val } : it)));
  return (
    <div className="rows">
      {items.map((it, i) => (
        <div className="row-item" key={i} style={{ "--cols": cols }}>
          {fields.map((f) => (
            <Field key={f.k} id={`${prefix}-${i}-${f.k}`} label={f.label} value={it[f.k]} maxLength={f.max}
              onChange={(e) => set(i, f.k, e.target.value)} placeholder={f.ph} list={f.list} inputMode={f.inputMode} />
          ))}
          <button type="button" className="icon-btn" aria-label={`Remove row ${i + 1}`} onClick={() => onChange(items.filter((_, j) => j !== i))}>
            <Icon name="trash" size={16} />
          </button>
        </div>
      ))}
      <button type="button" className="btn ghost small-btn" onClick={() => onChange([...items, { ...empty }])}>
        <Icon name="plus" size={16} />{addLabel}
      </button>
    </div>
  );
}

export default function StudentForm({ value, onChange, prefix, branches = [], classes = [], countryCode = "91" }) {
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value });
  const errs = formProblems(value);
  const quickAdd = (course) => {
    if (value.qualifications.some((q) => q.course === course)) return;
    onChange({ ...value, qualifications: [...value.qualifications, { ...EMPTY_QUAL, course }] });
  };
  const phoneHint = `10-digit number. +${countryCode} is added for you.`;

  return (
    <div className="sform">
      <datalist id={`${prefix}-branches`}>{branches.map((b) => <option key={b} value={b} />)}</datalist>
      <datalist id={`${prefix}-classes`}>{classes.map((b) => <option key={b} value={b} />)}</datalist>
      <datalist id={`${prefix}-courses`}>{QUAL_PRESETS.map((b) => <option key={b} value={b} />)}</datalist>

      <fieldset className="fs">
        <legend>Student</legend>
        <div className="fields">
          <Field id={`${prefix}-roll`} label="Registration number" value={value.roll_no} onChange={set("roll_no")} maxLength={30} placeholder="e.g. 2301201037" autoComplete="off" />
          {isHub()
            ? <CoursePicker id={`${prefix}-courses-pick`} value={value.courses || []} batchOf={value.batches || {}} options={hubCourses()} batches={hubBatches()}
                onChange={(courses, batches) => onChange({ ...value, courses, batches })} />
            : <Field id={`${prefix}-branch`} label="Branch" value={value.branch} onChange={set("branch")} maxLength={60} placeholder="e.g. CSE" list={`${prefix}-branches`} />}
          {!isHub() && (   // the IT Hub picks a batch timing per course above instead of typing one
            <Field id={`${prefix}-class`} label="Semester / section" value={value.class_name} onChange={set("class_name")} maxLength={30}
              placeholder="e.g. 6th sem A" list={`${prefix}-classes`} />
          )}
          <Field id={`${prefix}-sphone`} label={isHub() ? "Student's mobile (for their login)" : "Student phone"} type="tel" inputMode="tel" value={value.student_phone} onChange={set("student_phone")} error={errs.student_phone} />
          <Field id={`${prefix}-semail`} wide label="Student email" type="email" value={value.student_email} onChange={set("student_email")} error={errs.student_email} placeholder="For event messages" />
        </div>
      </fieldset>

      <fieldset className="fs">
        <legend>Parent or guardian</legend>
        <div className="fields">
          <Field id={`${prefix}-pname`} label="Name" value={value.parent_name} onChange={set("parent_name")} maxLength={80} />
          <Field id={`${prefix}-prel`} label="Relation">
            <select id={`${prefix}-prel`} value={value.parent_relation} onChange={set("parent_relation")}>
              <option value="">Choose</option>
              {RELATIONS.map((r) => <option key={r}>{r}</option>)}
            </select>
          </Field>
          <Field id={`${prefix}-pphone`} wide label="WhatsApp number" type="tel" inputMode="tel" value={value.parent_phone} onChange={set("parent_phone")}
            placeholder="98765 43210" error={errs.parent_phone} hint={`Absence alerts, holidays and exam results go here. ${phoneHint}`} />
          <Field id={`${prefix}-pemail`} label="Email" type="email" value={value.parent_email} onChange={set("parent_email")} error={errs.parent_email}
            placeholder="parent@gmail.com" hint="Their emails will show in your Inbox." />
          <Field id={`${prefix}-alt`} label="Other phone (optional)" type="tel" inputMode="tel" value={value.alt_phone} onChange={set("alt_phone")} error={errs.alt_phone} />
          <Field id={`${prefix}-addr`} wide as="textarea" rows={2} label="Home address" value={value.address} onChange={set("address")} maxLength={400} />
        </div>
      </fieldset>

      <details className="fs" open={value.qualifications.length > 0 || undefined}>
        <summary>Qualifications <span className="muted">{value.qualifications.length ? `(${value.qualifications.length})` : "(optional)"}</span></summary>
        <div className="quick">
          {QUAL_PRESETS.slice(0, 3).map((c) => <button type="button" key={c} className="chip as-btn" onClick={() => quickAdd(c)}><Icon name="plus" size={14} />{c}</button>)}
        </div>
        <Rows prefix={`${prefix}-q`} items={value.qualifications} empty={EMPTY_QUAL} addLabel="Add qualification"
          onChange={(qualifications) => onChange({ ...value, qualifications })} cols="1.3fr 1.3fr 76px 1fr"
          fields={[
            { k: "course", label: "Course / exam", max: 80, list: `${prefix}-courses` },
            { k: "board", label: "Board / university", max: 80 },
            { k: "year", label: "Year", max: 10, inputMode: "numeric" },
            { k: "score", label: "Score", max: 20, ph: "88% or 8.6 CGPA" },
          ]} />
      </details>

      <details className="fs" open={value.achievements.length > 0 || undefined}>
        <summary>Achievements <span className="muted">{value.achievements.length ? `(${value.achievements.length})` : "(optional)"}</span></summary>
        <Rows prefix={`${prefix}-a`} items={value.achievements} empty={EMPTY_ACH} addLabel="Add achievement"
          onChange={(achievements) => onChange({ ...value, achievements })} cols="1.6fr 76px 1.6fr"
          fields={[
            { k: "title", label: "Achievement", max: 120, ph: "e.g. 1st prize, coding contest" },
            { k: "year", label: "Year", max: 10, inputMode: "numeric" },
            { k: "details", label: "Details", max: 300 },
          ]} />
      </details>
    </div>
  );
}


// IT Hub: a student can join several courses, each at its own batch timing.
function CoursePicker({ id, value, batchOf, options, batches, onChange }) {
  const all = [...new Set([...options, ...value])];
  const toggle = (c) => {
    if (value.includes(c)) {
      const rest = { ...batchOf }; delete rest[c];
      onChange(value.filter((x) => x !== c), rest);
    } else {
      onChange([...value, c], batches.length === 1 ? { ...batchOf, [c]: batches[0] } : batchOf);
    }
  };
  const missing = batches.length > 0 && value.some((c) => !batchOf[c]);
  return (
    <fieldset className="field wide course-picker" id={id}>
      <legend>Courses joined</legend>
      {all.length === 0 ? <p className="muted small">No courses yet. An admin adds them on the Courses page.</p> : (
        <div className="course-chips">
          {all.map((c) => (
            <label key={c} className={`chip-check${value.includes(c) ? " on" : ""}`}>
              <input type="checkbox" checked={value.includes(c)} onChange={() => toggle(c)} />{c}
            </label>
          ))}
        </div>
      )}
      {batches.length > 0 && value.length > 0 && (
        <div className="batch-picks">
          {value.map((c) => (
            <label key={c} className="batch-pick">
              <span>{c} batch</span>
              <select value={batchOf[c] || ""} onChange={(e) => onChange(value, { ...batchOf, [c]: e.target.value })}
                aria-label={`Batch timing for ${c}`} className={!batchOf[c] ? "need" : ""}>
                <option value="">Choose a batch…</option>
                {[...new Set([...batches, ...(batchOf[c] ? [batchOf[c]] : [])])].map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </label>
          ))}
        </div>
      )}
      {all.length > 0 && value.length === 0 && <small className="field-error">Tick at least one course.</small>}
      {missing && <small className="field-error">Choose the batch timing for each course.</small>}
    </fieldset>
  );
}

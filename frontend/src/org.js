// Two organisations share AttendAI: the college (login at /) and
// Aakansha IT Hub (login at /it-hub). Same screens; the IT Hub uses
// *courses* (a student can join several) where the college uses *branches*,
// and has no parent login.
export const HUB_PATH = "/it-hub";

export const onHubPage = () => {
  try { return window.location.pathname.toLowerCase().replace(/\/+$/, "").startsWith(HUB_PATH); } catch { return false; }
};

let current = onHubPage() ? "ithub" : "college";

export function setOrg(org) {
  current = org === "ithub" ? "ithub" : "college";
  try { document.documentElement.dataset.org = current; } catch { /* tests */ }
}
setOrg(current);

export const isHub = () => current === "ithub";
export const orgTitle = () => (isHub() ? "Aakansha IT Hub" : "AttendAI");
export const orgSub = () => (isHub() ? "Course register" : "Classroom register");
// "Branch" / "Course" words for labels
export const unit = () => (isHub() ? "Course" : "Branch");
export const units = () => (isHub() ? "Courses" : "Branches");
export const unitLower = () => unit().toLowerCase();
export const unitsLower = () => units().toLowerCase();

// IT Hub classes: "Course · Batch" (e.g. "Python · 4–6 PM"). Attendance and teacher
// access go by these; tests and fees go by the course.
export const SEP = " · ";
export const unitCourse = (u) => String(u || "").split(SEP)[0];
export const unitBatch = (u) => String(u || "").split(SEP)[1] || "";
// Course names this user can register students into, and the admin's batch timings
// (loaded once by the app; used by the registration form).
let hubLists = { courses: [], batches: [] };
export const setHubLists = (x) => { hubLists = { courses: x.courses || [], batches: x.batches || [] }; };
export const hubCourses = () => hubLists.courses;
export const hubBatches = () => hubLists.batches;
// "Java (4–6 PM), Python (6–8 PM)"
export const coursesText = (s) => (s?.courses || []).map((c) => (s.batches?.[c] ? `${c} (${s.batches[c]})` : c)).join(", ");

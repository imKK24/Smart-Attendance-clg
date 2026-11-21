export const pad = (n) => String(n).padStart(2, "0");
export const isoToday = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
export const parseISO = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
export const fmt = (s, o) => parseISO(s).toLocaleDateString("en-IN", o);
export const timeOf = (t) => (!t || t === "-" || t === "—" ? "–" : t);
export const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
export const fmtStamp = (s) => {
  if (!s) return "–";
  const d = new Date(s.replace(" ", "T"));
  return isNaN(d) ? s : d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
};
export const ago = (s) => {
  if (!s) return "";
  const d = new Date(s.replace(" ", "T"));
  const mins = Math.round((Date.now() - d) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};
export const dateRange = (a, b) => (a === b ? fmt(a, { day: "numeric", month: "short", year: "numeric" })
  : `${fmt(a, { day: "numeric", month: "short" })} – ${fmt(b, { day: "numeric", month: "short", year: "numeric" })}`);

// Same rules as the server: 10 digits get the country code.
export function phoneProblem(v) {
  const s = String(v || "").trim();
  if (!s) return "";
  const digits = s.replace(/\D/g, "");
  if (digits.length < 10 || digits.length > 15) {
    return "Use a 10-digit mobile number, or + and the country code.";
  }
  return "";
}
export const emailProblem = (v) => (v && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v) ? "This doesn't look like an email address." : "");

const nf = (d: number) => new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });

/** 25255.05 -> "25,255.05"; null -> "—" */
export function num(v: number | null | undefined, d = 2): string {
  return v == null || Number.isNaN(v) ? "—" : nf(d).format(v);
}

/** Rupees with optional sign: inr(-1234.5, true) -> "−₹1,234.50" */
export function inr(v: number | null | undefined, sign = false, d = 2): string {
  if (v == null || Number.isNaN(v)) return "—";
  const s = v < 0 ? "−" : sign && v > 0 ? "+" : "";
  return `${s}₹${nf(d).format(Math.abs(v))}`;
}

/** "2026-11-11T10:15:00" -> "10:15" */
export const hm = (iso?: string | null) => (iso ? iso.slice(11, 16) : "—");
/** "2026-11-11T10:15:00" -> "10:15:00" */
export const hms = (iso?: string | null) => (iso ? iso.slice(11, 19) : "—");
/** "2026-11-17" -> "17 Nov 2026" */
export function dmy(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso.slice(0, 10) + "T00:00:00Z");
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
}
/** IST wall-clock ISO string -> chart time (seconds), shown as-is on the axis. */
export const chartTime = (iso: string) => Math.floor(Date.parse(iso + "Z") / 1000);

export const pnlClass = (v: number | null | undefined) =>
  v == null ? "" : v > 0 ? "text-gain" : v < 0 ? "text-loss" : "";

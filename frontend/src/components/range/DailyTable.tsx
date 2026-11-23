import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { InfoTip, Pill } from "../common/Card";
import { Button, inputCls, selectInline } from "../common/Controls";
import { Empty } from "../common/States";
import { dmy, num, pnlClass, signed } from "../../utils/format";
import type { RangeDay } from "../../types/api";

type Key = "date" | "open" | "high" | "low" | "close" | "range" | "range_pct" | "change_pct";
type Kind = "all" | "up" | "down" | "partial";

const COLUMNS: { key: Key; label: string; tip?: string; right?: boolean }[] = [
  { key: "date", label: "Date" },
  { key: "open", label: "Open", right: true },
  { key: "high", label: "High", right: true },
  { key: "low", label: "Low", right: true },
  { key: "close", label: "Close", right: true },
  { key: "range", label: "Range (pts)", right: true, tip: "High minus low of the day, in index points." },
  { key: "range_pct", label: "Range (%)", right: true, tip: "The day's range as a percentage of its open." },
  { key: "change_pct", label: "Change (%)", right: true, tip: "Close against the previous complete session's close. Empty when there is none." },
];
const SIZES = [10, 25, 50, 100];
const WEEKDAY = (iso: string) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", { weekday: "long", timeZone: "UTC" });

/** Text a search can match: the date in several forms, the weekday and the prices. */
const haystack = (d: RangeDay) =>
  [d.date, dmy(d.date), WEEKDAY(d.date), d.status.replace("_", " "), d.open, d.high, d.low, d.close].join(" ").toLowerCase();

/** The daily history: the same rows as the chart, with sorting, search, a day-type filter and pagination. */
export function DailyTable({ days }: { days: RangeDay[] }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<Kind>("all");
  const [sort, setSort] = useState<{ key: Key; dir: 1 | -1 }>({ key: "date", dir: -1 });
  const [size, setSize] = useState(10);
  const [page, setPage] = useState(0);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = days.filter((d) => (kind === "all" || (kind === "up" ? d.close >= d.open : kind === "down" ? d.close < d.open : d.status !== "complete"))
      && (!needle || haystack(d).includes(needle)));
    const { key, dir } = sort;
    // empty values (the first day has no previous close) always go last, whichever way it is sorted
    return list.sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null || y == null) return x == null && y == null ? 0 : x == null ? 1 : -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
  }, [days, q, kind, sort]);

  const pages = Math.max(1, Math.ceil(rows.length / size));
  useEffect(() => { setPage(0); }, [q, kind, sort, size, days]);
  const at = Math.min(page, pages - 1);
  const shown = rows.slice(at * size, at * size + size);
  const toggle = (key: Key) => setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: -1 }));

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative min-w-48 flex-1 sm:max-w-xs">
          <span className="sr-only">Search days</span>
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input type="search" className={`${inputCls} pl-8`} placeholder="Search date, weekday or price" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-slate-500">Show</span>
          <select aria-label="Day type" className={selectInline} value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
            <option value="all">All days</option><option value="up">Green days (closed up)</option>
            <option value="down">Red days (closed down)</option><option value="partial">Incomplete days</option>
          </select>
        </label>
        <div className="ml-auto text-xs text-slate-500">{rows.length} of {days.length} days</div>
      </div>

      {!rows.length ? <Empty title="No days match">Clear the search or choose another day type.</Empty> : (
        <div className="overflow-x-auto rounded-xl border border-slate-200 dark:border-slate-800">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-800/60 dark:text-slate-400">
              <tr>
                {COLUMNS.map((c) => {
                  const on = sort.key === c.key;
                  return (
                    <th key={c.key} scope="col" className={`px-3 py-2 font-semibold ${c.right ? "text-right" : "text-left"}`}
                      aria-sort={on ? (sort.dir === 1 ? "ascending" : "descending") : "none"}>
                      <span className={`inline-flex items-center gap-1 ${c.right ? "flex-row-reverse" : ""}`}>
                        <button type="button" onClick={() => toggle(c.key)} className="inline-flex items-center gap-1 uppercase hover:text-slate-900 dark:hover:text-slate-100">
                          {c.label}{on && (sort.dir === 1 ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                        </button>
                        {c.tip && <InfoTip text={c.tip} />}
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {shown.map((d) => (
                <tr key={d.date} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                  <td className="whitespace-nowrap px-3 py-2">
                    <span className="font-medium">{dmy(d.date)}</span> <span className="text-xs text-slate-500">{WEEKDAY(d.date).slice(0, 3)}</span>
                    {d.status === "in_progress" && <Pill tone="info" className="ml-2" title={`Session still running; ${d.candles} minutes so far (to ${d.last})`}>live</Pill>}
                    {d.status === "partial" && <Pill tone="warn" className="ml-2" title={`Only ${d.candles} minutes stored (${d.first}-${d.last}); kept out of the range statistics`}>incomplete</Pill>}
                  </td>
                  {(["open", "high", "low", "close"] as const).map((k) => <td key={k} className="num px-3 py-2 text-right">{num(d[k])}</td>)}
                  <td className="num px-3 py-2 text-right font-semibold">{num(d.range)}</td>
                  <td className="num px-3 py-2 text-right">{num(d.range_pct, 2)}%</td>
                  <td className={`num px-3 py-2 text-right font-semibold ${pnlClass(d.change_pct)}`}>{d.change_pct == null ? "—" : `${signed(d.change_pct)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <label className="flex items-center gap-2 text-slate-500">Rows
          <select aria-label="Rows per page" className={selectInline} value={size} onChange={(e) => setSize(Number(e.target.value))}>
            {SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500" aria-live="polite">
            {rows.length ? `${at * size + 1}–${Math.min(rows.length, at * size + size)} of ${rows.length}` : "0 of 0"} · page {at + 1} of {pages}
          </span>
          <Button onClick={() => setPage(at - 1)} disabled={at === 0} title="Previous page"><ChevronLeft size={16} />Prev</Button>
          <Button onClick={() => setPage(at + 1)} disabled={at >= pages - 1} title="Next page">Next<ChevronRight size={16} /></Button>
        </div>
      </div>
    </div>
  );
}

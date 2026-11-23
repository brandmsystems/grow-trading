import { useEffect, useMemo, useState, type ReactNode } from "react";
import { BarChart3, CalendarRange, Gauge, RefreshCw } from "lucide-react";
import { useSettings } from "../context/SettingsContext";
import { useApi } from "../hooks/useApi";
import { getDailyRange } from "../services/api";
import { Card, InfoTip, Pill, type Accent } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, Segmented } from "../components/common/Controls";
import { Empty, ErrorNote, Limitation } from "../components/common/States";
import { AVG_LEGEND, RangeChart, type RangeView } from "../components/charts/RangeChart";
import { DailyTable } from "../components/range/DailyTable";
import { dmy, num, pct, pnlClass, signed, todayIST } from "../utils/format";
import type { DailyRange as DailyRangeData, RangeDay, RangePick } from "../types/api";

const PERIODS = [{ value: 1, label: "1M", name: "1-Month" }, { value: 3, label: "3M", name: "3-Month" },
  { value: 6, label: "6M", name: "6-Month" }, { value: 12, label: "1Y", name: "1-Year" }];

/** The day after the same date `months` earlier (so 1Y of 18 Mar 2026 starts on 19 Mar 2025, as the server's default does). */
export function periodStart(end: string, months: number): string {
  const [y, m, d] = end.split("-").map(Number);
  const t = m - 1 - months;
  const year = y + Math.floor(t / 12), month = ((t % 12) + 12) % 12;
  const day = Math.min(d, new Date(Date.UTC(year, month + 1, 0)).getUTCDate());
  return new Date(Date.UTC(year, month, day + 1)).toISOString().slice(0, 10);
}

const Skeleton = ({ className = "" }: { className?: string }) => <div className={`animate-pulse rounded-xl bg-slate-200 dark:bg-slate-800 ${className}`} />;

function Kpi({ label, tip, accent, value, sub }: { label: string; tip: string; accent: Accent; value: ReactNode; sub?: ReactNode }) {
  return (
    <Card accent={accent} bodyClass="p-4 pt-5">
      <div className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}<InfoTip text={tip} /></div>
      <div className="num mt-1 truncate text-xl font-bold tracking-tight sm:text-2xl">{value}</div>
      {sub && <div className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">{sub}</div>}
    </Card>
  );
}

function Legend({ day, label }: { day: RangeDay | null; label: string }) {
  if (!day) return <div className="h-6 text-xs text-slate-500">Move over the chart to see a day. Scroll to zoom, drag to pan.</div>;
  const wd = new Date(day.date + "T00:00:00Z").toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  return (
    <div data-testid="range-legend" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      <span className="font-semibold">{wd} {dmy(day.date)}</span>
      <span className="text-slate-500">{label}</span>
      {(["open", "high", "low", "close"] as const).map((k) => <span key={k}><span className="text-slate-500">{k[0].toUpperCase()} </span><span className="num font-semibold">{num(day[k])}</span></span>)}
      <span><span className="text-slate-500">Range </span><span className="num font-semibold">{num(day.range)} pts ({num(day.range_pct, 2)}%)</span></span>
      <span><span className="text-slate-500">Change </span><span className={`num font-semibold ${pnlClass(day.change_pct)}`}>{day.change_pct == null ? "—" : `${signed(day.change_pct)}%`}</span></span>
      {day.status === "partial" && <Pill tone="warn">incomplete: {day.candles} of 375 minutes</Pill>}
      {day.status === "in_progress" && <Pill tone="info">live: to {day.last}</Pill>}
    </div>
  );
}

function Analysis({ data, days }: { data: DailyRangeData; days: RangeDay[] }) {
  const { trend, current } = data.analysis;
  const s = data.summary;
  const lastDone = [...days].reverse().find((d) => d.status === "complete");
  const live = current && current.status === "in_progress" && current.date === todayIST();
  const adr10 = current?.adr["10"], u10 = current?.utilization["10"];
  const tone = trend?.label === "expanding" ? "warn" : trend?.label === "contracting" ? "info" : "neutral";
  return (
    <Card title="Range analysis" icon={<Gauge size={16} className="text-violet-600" />} right={lastDone ? `averages as of ${dmy(lastDone.date)}` : undefined}>
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <AvgStat label="ADR (period)" tip="Average daily range: the mean high-low of every complete session in the selected dates." value={s?.adr} sub={s?.adr_pct != null ? `${pct(s.adr_pct, 2)} of open` : undefined} />
            {([["10", lastDone?.avg10], ["20", lastDone?.avg20], ["50", lastDone?.avg50]] as const).map(([n, v]) => (
              <AvgStat key={n} label={`${n}-day avg`} tip={`Mean daily range (high - low) of the last ${n} complete sessions up to the end of the selected dates. Blank until ${n} sessions exist.`} value={v} />
            ))}
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">Range trend</span>
              <InfoTip text="Compares the 10-day average range with the 50-day one. 10% or more above = expanding (recent days are wider than usual), 10% or more below = contracting, otherwise steady. It describes the past, not the next day." />
              {trend?.label ? <Pill tone={tone}>{trend.label}</Pill> : <Pill>not enough sessions</Pill>}
            </div>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              {trend && trend.ratio != null
                ? `The 10-day average (${num(trend.avg10)} pts) is ${Math.abs((trend.ratio - 1) * 100).toFixed(1)}% ${trend.ratio >= 1 ? "above" : "below"} the 50-day average (${num(trend.avg50)} pts).`
                : "The 50-day average needs 50 complete sessions."}
            </p>
          </div>
          <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
            <PickStat label="Highest range" tip="The complete session with the widest high-low range in these dates." pick={s?.highest_range} />
            <PickStat label="Lowest range" tip="The complete session with the narrowest high-low range in these dates." pick={s?.lowest_range} />
            <div><dt className="text-xs text-slate-500">Median range</dt><dd className="num font-semibold">{s?.median_range != null ? `${num(s.median_range)} pts` : "—"}</dd>
              <dd className="text-xs text-slate-500">{s ? `${s.bullish_days} green / ${s.bearish_days} red days` : ""}</dd></div>
          </dl>
        </div>

        <div className="rounded-xl bg-slate-50 p-4 dark:bg-slate-800/50">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-1 text-sm font-medium">
              {live ? "Today's range vs average" : "Latest session vs average"}
              <InfoTip text="Range used = the session's high-low so far divided by the average range of the 10 (20, 50) complete sessions before it. Over 100% means the day has already moved more than a typical day. The session itself is never part of its own average." />
            </div>
            {current && <span className="text-xs text-slate-500">{dmy(current.date)}{current.status === "in_progress" ? ` · live to ${current.last}` : ""}</span>}
          </div>
          {!current ? <p className="mt-3 text-sm text-slate-500">No session stored yet.</p> : (
            <>
              <div className="mt-3 flex items-baseline gap-2">
                <span className="num text-2xl font-bold">{num(current.range)}</span><span className="text-sm text-slate-500">pts ({num(current.range_pct, 2)}% of open)</span>
              </div>
              <div className="mt-3" aria-label="Range used against the 10-day average">
                <div className="mb-1 flex justify-between text-xs"><span className="text-slate-500">Range used (10-day average)</span>
                  <span className="num font-semibold">{u10 != null ? `${u10.toFixed(1)}%` : "—"}</span></div>
                <div className="h-2.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700" role="progressbar" aria-valuemin={0} aria-valuemax={100}
                  aria-valuenow={u10 == null ? undefined : Math.min(100, Math.round(u10))}>
                  <div className={`h-full rounded-full ${u10 != null && u10 > 100 ? "bg-orange-500" : "bg-blue-500"}`} style={{ width: `${Math.min(100, u10 ?? 0)}%` }} />
                </div>
                <div className="mt-1 text-xs text-slate-500">{adr10 != null && u10 != null
                  ? (u10 > 100 ? `Already ${num(current.range - adr10)} pts wider than the average day.` : `${num(current.remaining["10"])} pts left before a typical day's range is used up.`)
                  : "The 10-day average needs 10 earlier complete sessions."}</div>
              </div>
              <table className="mt-3 w-full text-sm">
                <thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-1 font-medium">Average of</th><th className="py-1 text-right font-medium">Avg range</th><th className="py-1 text-right font-medium">Used</th><th className="py-1 text-right font-medium">Left</th></tr></thead>
                <tbody>
                  {["10", "20", "50"].map((n) => (
                    <tr key={n} className="border-t border-slate-200 dark:border-slate-700">
                      <td className="py-1">Last {n} sessions</td>
                      <td className="num py-1 text-right">{current.adr[n] != null ? num(current.adr[n]) : "—"}</td>
                      <td className="num py-1 text-right">{current.utilization[n] != null ? `${current.utilization[n]!.toFixed(1)}%` : "—"}</td>
                      <td className="num py-1 text-right">{current.remaining[n] != null ? num(current.remaining[n]) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {current.note && <p className="mt-2 text-xs text-orange-600 dark:text-orange-400">{current.note}</p>}
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

const AvgStat = ({ label, tip, value, sub }: { label: string; tip: string; value: number | null | undefined; sub?: string }) => (
  <div className="min-w-0">
    <div className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}<InfoTip text={tip} /></div>
    <div className="num text-base font-semibold">{value != null ? num(value) : "—"}</div>
    <div className="truncate text-xs text-slate-500">{sub ?? "points"}</div>
  </div>
);

const PickStat = ({ label, tip, pick }: { label: string; tip: string; pick: RangePick | null | undefined }) => (
  <div>
    <dt className="flex items-center gap-1 text-xs text-slate-500">{label}<InfoTip text={tip} /></dt>
    <dd className="num font-semibold">{pick ? `${num(pick.range)} pts` : "—"}</dd>
    <dd className="text-xs text-slate-500">{pick ? `${dmy(pick.date)} · ${num(pick.range_pct, 2)}%` : ""}</dd>
  </div>
);

export default function DailyRange() {
  const { settings } = useSettings();
  const [applied, setApplied] = useState<{ from: string; to: string } | null>(null);   // null = the server's default: previous 1 year
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [latest, setLatest] = useState("");
  const [view, setView] = useState<RangeView>("candles");
  const [hover, setHover] = useState<RangeDay | null>(null);
  const res = useApi(() => getDailyRange(applied?.from, applied?.to), [applied?.from, applied?.to]);
  const data = res.data;

  // The first answer is the default window; remember its end as "the latest stored session".
  useEffect(() => {
    if (data?.window && !latest) { setLatest(data.window.to); setFrom(data.window.from); setTo(data.window.to); }
  }, [data, latest]);

  const set = (f: string, t: string) => { setFrom(f); setTo(t); if (f && t && f <= t) setApplied({ from: f, to: t }); };
  const reversed = !!from && !!to && from > to;
  const active = PERIODS.find((p) => latest && from === periodStart(latest, p.value) && to === latest);
  const name = active?.name ?? "Period";
  const days = useMemo(() => data?.days ?? [], [data]);
  const last = days[days.length - 1] ?? null;
  const s = data?.summary;

  return (
    <div className="space-y-4">
      <PageHeader title="Daily Range" subtitle="NIFTY 50 daily high-low range for the previous year, built from the stored 1-minute candles. Nothing is fetched live here." />

      <Card>
        <div className="flex flex-wrap items-end gap-3">
          {/* not a <Field>: a <label> around the buttons would become the first button's accessible name */}
          <div role="group" aria-labelledby="range-period" className="block">
            <div id="range-period" className="mb-1 text-xs font-medium text-slate-600 dark:text-slate-400">Period</div>
            <Segmented value={active?.value ?? 0} options={PERIODS.map((p) => ({ value: p.value, label: p.label }))}
              onChange={(m) => latest && set(periodStart(latest, m), latest)} disabled={!latest} />
          </div>
          <Field label="From" className="w-40"><input type="date" className={inputCls} value={from} max={to || undefined} onChange={(e) => set(e.target.value, to)} aria-invalid={reversed} /></Field>
          <Field label="To" className="w-40"><input type="date" className={inputCls} value={to} min={from || undefined} onChange={(e) => set(from, e.target.value)} aria-invalid={reversed} /></Field>
          {!active && !!latest && <Pill tone="info">custom dates</Pill>}
          <div className="ml-auto flex items-center gap-2 text-xs text-slate-500">
            {data && <span>{data.counts.days} sessions · {data.counts.complete} complete{data.counts.partial ? ` · ${data.counts.partial} incomplete` : ""}{data.counts.in_progress ? " · 1 live" : ""}</span>}
            <Button onClick={() => void res.reload()} title="Reload"><RefreshCw size={14} className={res.loading ? "animate-spin" : ""} />Reload</Button>
          </div>
        </div>
        {reversed && <div role="alert" className="mt-2 text-sm text-red-600">The start date is after the end date.</div>}
      </Card>

      {res.error && <ErrorNote>{res.error} <button className="ml-2 underline" onClick={() => void res.reload()}>Try again</button></ErrorNote>}

      {res.loading && !data && !res.error && (
        <div aria-busy="true" aria-label="Loading daily range" className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="h-24" />)}</div>
          <Skeleton className="h-[420px]" /><Skeleton className="h-64" />
        </div>
      )}

      {data && !res.error && !days.length && (
        data.window === null
          ? <Empty title="No stored NIFTY data">Download history on the Market Data page first.</Empty>
          : <Empty title="No sessions in these dates">Weekends, market holidays and days that were never downloaded have no row. Choose other dates.</Empty>
      )}

      {data && s && days.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <Kpi accent="gain" label={`${name} high`} tip="The highest price traded on any stored session in the selected dates." value={num(s.high.price)} sub={dmy(s.high.date)} />
            <Kpi accent="loss" label={`${name} low`} tip="The lowest price traded on any stored session in the selected dates." value={num(s.low.price)} sub={dmy(s.low.date)} />
            <Kpi accent="spot" label="Current price" tip="The close of the newest stored 1-minute candle (not a live quote). While the market is open it moves with each stored candle."
              value={s.current ? num(s.current.price) : "—"} sub={s.current ? `${dmy(s.current.date)} ${s.current.time}${s.current.status === "in_progress" ? " · live session" : ""}` : undefined} />
            <Kpi accent="strat" label="Average daily range" tip="ADR: the mean of high minus low over the complete sessions in the selected dates. The percentage is the mean range as a share of each day's open."
              value={s.adr != null ? `${num(s.adr)} pts` : "—"} sub={s.adr_pct != null ? `${pct(s.adr_pct, 2)} of open` : undefined} />
            <Kpi accent="risk" label="Highest daily range" tip="The widest high-low range of any complete session in the selected dates."
              value={s.highest_range ? `${num(s.highest_range.range)} pts` : "—"} sub={s.highest_range ? `${dmy(s.highest_range.date)} · ${num(s.highest_range.range_pct, 2)}%` : undefined} />
            <Kpi accent="neutral" label="Lowest daily range" tip="The narrowest high-low range of any complete session in the selected dates."
              value={s.lowest_range ? `${num(s.lowest_range.range)} pts` : "—"} sub={s.lowest_range ? `${dmy(s.lowest_range.date)} · ${num(s.lowest_range.range_pct, 2)}%` : undefined} />
          </div>

          <Card title={`NIFTY 50 · daily · ${dmy(data.window?.from)} → ${dmy(data.window?.to)}`} icon={<CalendarRange size={16} className="text-blue-600" />}
            right={<Segmented value={view} onChange={setView} options={[{ value: "candles", label: "Candles" }, { value: "range", label: "Range bars" }]} />}>
            <div className="mb-2 min-h-6"><Legend day={hover ?? last} label={hover ? "" : "latest"} /></div>
            <RangeChart days={days} view={view} dark={settings.theme === "dark"} height={420} onHover={setHover} />
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
              <span className="inline-flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-green-600" />closed above its open</span>
              <span className="inline-flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-red-600" />closed below its open</span>
              <span className="inline-flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-slate-400/60" />lighter = incomplete or live day</span>
              {view === "range" && AVG_LEGEND.map((a) => <span key={a.key} className="inline-flex items-center gap-1"><i className="h-0.5 w-4" style={{ background: a.color }} />{a.label}</span>)}
            </div>
          </Card>

          <Analysis data={data} days={days} />

          <Card title="Daily history" icon={<BarChart3 size={16} className="text-blue-600" />} right="same dates as the chart">
            <DailyTable days={days} />
          </Card>

          <Limitation>
            Daily values are aggregated from the stored 1-minute NIFTY 50 spot candles by Asia/Kolkata date; no minute is ever filled in. Weekends and days without candles
            have no row. Sessions with missing minutes (and a session still running) are shown but left out of the range statistics, and are never used as a previous close.
            Range % is the range as a share of the day's open; change % is the close against the previous complete close. ADR describes the past and is not a forecast.
          </Limitation>
        </>
      )}
    </div>
  );
}

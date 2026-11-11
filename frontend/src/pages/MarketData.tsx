import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Database, Download, Square } from "lucide-react";
import { useApi, waitForJob } from "../hooks/useApi";
import { getDataOverview, startDownload, stopDownload } from "../services/api";
import { Card, Pill, Stat } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader } from "../components/common/Controls";
import { ErrorNote, Limitation, Loading, Progress } from "../components/common/States";
import { dmy, dmyhm, num } from "../utils/format";
import type { Job, Period } from "../types/api";

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const VERDICT = { none: ["No data", "bad"], partial: ["Partial", "warn"], full: ["Full coverage", "good"] } as const;
const period = (p: Period) => (p.from === p.to ? dmy(p.from) : `${dmy(p.from)} → ${dmy(p.to)}`);

export default function MarketData() {
  const ov = useApi(getDataOverview, []);
  const [job, setJob] = useState<Job | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const c = ov.data?.coverage;
  useEffect(() => { if (c && !from) { setFrom(c.target.from); setTo(c.target.to); } }, [c, from]);
  useEffect(() => {
    const j = ov.data?.job;
    if (j && !job) waitForJob(j.id, setJob).then(() => { setJob(null); void ov.reload(); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ov.data?.job]);

  async function download() {
    setErr(null);
    try {
      const r = await startDownload(from, to);
      const j = await waitForJob(String(r.job), setJob);
      setJob(null);
      if (j.state === "error") setErr(j.error);
      await ov.reload();
    } catch (e) { setJob(null); setErr((e as Error).message); }
  }

  if (ov.loading && !ov.data) return <Loading />;
  if (ov.error && !ov.data) return <ErrorNote>{ov.error}</ErrorNote>;
  const s = c!.summary;
  const months = new Map(c!.months.map((m) => [m.month, m]));
  const years = [...new Set(c!.months.map((m) => m.month.slice(0, 4)))].sort().reverse();
  const [vLabel, vTone] = VERDICT[c!.verdict];

  return (
    <div className="space-y-4">
      <PageHeader title="Market Data" subtitle={`Stored NIFTY 1-minute history · target window ${dmy(c!.target.from)} → ${dmy(c!.target.to)}`} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Card accent="spot"><Stat label="Sessions stored" value={num(s.sessions, 0)} sub={`${s.not_downloaded} not downloaded`} className="text-xl" /></Card>
        <Card accent="spot"><Stat label="Candles" value={num(s.candles, 0)} sub="1-minute" className="text-xl" /></Card>
        <Card accent="gain"><Stat label="Complete days" value={num(s.complete, 0)} sub={`${s.partial} with gaps`} className="text-xl" /></Card>
        <Card accent="risk"><Stat label="Missing minutes" value={num(s.missing_minutes, 0)} sub="inside stored days" className="text-xl" /></Card>
        <Card accent={s.rejected ? "loss" : "neutral"}><Stat label="Invalid candles" value={num(s.rejected, 0)} sub={`${num(s.outside_session ?? 0, 0)} out-of-hours, not stored`} className="text-xl" /></Card>
        <Card accent="strat"><Stat label="Coverage" value={`${s.coverage_pct}%`} sub={s.last ? `latest ${dmyhm(s.last)}` : "nothing stored"} className="text-xl" /></Card>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Download / update" icon={<Download size={16} className="text-blue-600" />}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="From"><input type="date" className={inputCls} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="To"><input type="date" className={inputCls} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={download} disabled={!!job}><Download size={15} /> Download or resume</Button>
            {job && <Button variant="danger" onClick={() => stopDownload()}><Square size={14} /> Stop</Button>}
          </div>
          {job && <div className="mt-3"><Progress value={job.progress} text={job.message} /></div>}
          {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
          <p className="mt-3 text-xs text-slate-500">Only missing days are requested, so it's safe to re-run. Candles are stored exactly as Groww returns them; gaps are listed, never filled.</p>
        </Card>
        <Card title="Availability" icon={<Database size={16} className="text-slate-500" />} right={<Pill tone={vTone}>{vLabel}</Pill>} className="lg:col-span-2">
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <div>
              <div className="font-semibold">Instruments</div>
              <ul className="mt-1 space-y-1 text-slate-600 dark:text-slate-300">
                <li><Pill tone="info">NSE-NIFTY</Pill> NIFTY 50 spot: coverage on this page</li>
                <li><Pill tone="strat">NIFTY FUT</Pill> near-month futures (volume and VWAP), downloaded with the spot</li>
                <li><Pill tone="neutral">NIFTY options</Pill> each contract's candles, downloaded when a backtest needs it</li>
              </ul>
            </div>
            <div className="text-slate-600 dark:text-slate-300">
              <div>Earliest candle: <b className="num">{dmyhm(s.first)}</b></div>
              <div>Latest candle: <b className="num">{dmyhm(s.last)}</b></div>
              <div>{s.no_data} weekdays with no candles (usually holidays){s.special_sessions ? `, ${s.special_sessions} special out-of-hours sessions` : ""}.</div>
              <div>{s.spikes} price spikes over 5% flagged.</div>
            </div>
          </div>
          <div className="mt-3"><Limitation>Coverage reports exist for NIFTY spot only. The backend doesn't report coverage for futures or option contracts.</Limitation></div>
        </Card>
      </div>

      <Card title="Coverage by month" right={<span className="flex gap-3"><span className="text-green-600">■ complete</span><span className="text-orange-500">■ gaps</span><span className="text-slate-400">■ not downloaded</span></span>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-xs">
            <thead><tr className="text-slate-500"><th className="py-1 text-left">Year</th>{MON.map((m) => <th key={m}>{m}</th>)}</tr></thead>
            <tbody>
              {years.map((y) => (
                <tr key={y}>
                  <td className="py-0.5 font-semibold">{y}</td>
                  {MON.map((_, i) => {
                    const k = `${y}-${String(i + 1).padStart(2, "0")}`, m = months.get(k);
                    if (!m) return <td key={k} className="text-center text-slate-300 dark:text-slate-700">·</td>;
                    const got = Number(m.complete ?? 0) + Number(m.partial ?? 0) + Number(m.in_progress ?? 0), miss = Number(m.not_downloaded ?? 0);
                    const cls = !got ? (miss ? "bg-slate-200 dark:bg-slate-800" : "border border-dashed border-slate-300 dark:border-slate-700") : (Number(m.partial ?? 0) || miss) ? "bg-orange-100 dark:bg-orange-950/50" : "bg-green-100 dark:bg-green-950/50";
                    const last = new Date(Date.UTC(Number(y), i + 1, 0)).toISOString().slice(0, 10);
                    return (
                      <td key={k} className="p-0.5">
                        <Link to={`/history?from=${k}-01&to=${last}`} title={`${got} sessions stored, ${m.partial ?? 0} with gaps, ${miss} not downloaded`}
                          className={`num block rounded-md py-1.5 text-center hover:ring-1 hover:ring-blue-400 ${cls}`}>{got || miss ? `${got}/${got + miss}` : "none"}</Link>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Missing periods">
          <div className="scroll-thin max-h-72 space-y-3 overflow-y-auto text-sm">
            {!c!.not_downloaded.length && !c!.no_data.length && <p className="text-slate-500">No missing periods.</p>}
            {c!.not_downloaded.length > 0 && <div><div className="text-xs font-semibold uppercase text-slate-500">Not downloaded</div>{c!.not_downloaded.map((p) => <div key={p.from} className="flex justify-between border-b border-slate-100 py-1 dark:border-slate-800"><span className="num">{period(p)}</span><span className="text-slate-500">{p.days} days</span></div>)}</div>}
            {c!.no_data.length > 0 && <div><div className="text-xs font-semibold uppercase text-slate-500">Groww returned no candles (usually holidays)</div>{c!.no_data.map((p) => <div key={p.from} className="flex justify-between border-b border-slate-100 py-1 dark:border-slate-800"><span className="num">{period(p)}</span><span className="text-slate-500">{p.days} day{p.days === 1 ? "" : "s"}</span></div>)}</div>}
          </div>
        </Card>
        <Card title="Days with missing candles">
          <div className="scroll-thin max-h-72 overflow-y-auto text-sm">
            {!c!.partial_days.length ? <p className="text-slate-500">None.</p> : c!.partial_days.slice().reverse().map((d) => (
              <div key={d.day} className="flex justify-between gap-3 border-b border-slate-100 py-1 dark:border-slate-800">
                <Link to={`/history?from=${d.day}&to=${d.day}&tf=1`} className="num text-blue-600 hover:underline">{dmy(d.day)}</Link>
                <span className="truncate text-xs text-slate-500">{d.missing} missing: {d.ranges.slice(0, 3).map((r) => (r[0] === r[1] ? r[0] : r.join("–"))).join(", ")}{d.ranges.length > 3 ? "…" : ""}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Download history">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead><tr className="text-left text-xs uppercase text-slate-500"><th className="py-2">Started</th><th>Range</th><th>Status</th><th className="text-right">Requests</th><th className="text-right">New</th><th className="text-right">Duplicates</th><th className="text-right">Invalid</th></tr></thead>
            <tbody>
              {ov.data!.downloads.map((r) => (
                <tr key={r.id} className="border-t border-slate-100 align-top dark:border-slate-800">
                  <td className="num py-1.5 text-xs">{dmyhm(r.started_at)}</td>
                  <td className="text-xs">{dmy(r.start_date)} → {dmy(r.end_date)}</td>
                  <td><Pill tone={r.status === "done" ? "good" : r.status === "failed" ? "bad" : "warn"}>{r.status}</Pill>{r.error && <div className="mt-0.5 max-w-xs text-xs text-red-600">{r.error}</div>}</td>
                  <td className="num text-right">{r.chunks_done}/{r.chunks_total}</td>
                  <td className="num text-right">{num(r.rows_new, 0)}</td>
                  <td className="num text-right">{num(r.rows_duplicate, 0)}</td>
                  <td className="num text-right">{num(r.rows_rejected, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Database, Download, Layers, Scale, Square } from "lucide-react";
import { useApi, waitForJob } from "../hooks/useApi";
import { getDataOverview, getLotSizes, getOptionsCoverage, startDownload, startOptionsDownload, stopDownload } from "../services/api";
import { Card, Pill, Stat } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader } from "../components/common/Controls";
import { ErrorNote, Loading, Progress } from "../components/common/States";
import { dmy, dmyhm, num } from "../utils/format";
import type { Job, Period } from "../types/api";

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const VERDICT = { none: ["No data", "bad"], partial: ["Partial", "warn"], full: ["Full coverage", "good"] } as const;
const period = (p: Period) => (p.from === p.to ? dmy(p.from) : `${dmy(p.from)} → ${dmy(p.to)}`);

export default function MarketData() {
  const ov = useApi(getDataOverview, []);
  const opt = useApi(getOptionsCoverage, []);
  const lots = useApi(getLotSizes, []);
  const [optJob, setOptJob] = useState<Job | null>(null);
  const [optErr, setOptErr] = useState<string | null>(null);
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

  useEffect(() => {
    const j = opt.data?.job;
    if (j && !optJob) waitForJob(j.id, setOptJob).then(() => { setOptJob(null); void opt.reload(); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opt.data?.job]);

  async function downloadOptions() {
    setOptErr(null);
    try {
      const r = await startOptionsDownload(from, to);
      const j = await waitForJob(String(r.job), setOptJob);
      setOptJob(null);
      if (j.state === "error") setOptErr(j.error);
      await Promise.all([opt.reload(), ov.reload()]);
    } catch (e) { setOptJob(null); setOptErr((e as Error).message); }
  }

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
  const ins = ov.data!.instruments;
  const o = opt.data;

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
            <Button variant="primary" onClick={download} disabled={!!job || !!optJob}><Download size={15} /> Download or resume</Button>
            {job && <Button variant="danger" onClick={() => stopDownload()}><Square size={14} /> Stop</Button>}
          </div>
          {job && <div className="mt-3"><Progress value={job.progress} text={job.message} /></div>}
          {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
          <p className="mt-3 text-xs text-slate-500">Only missing days are requested, so it's safe to re-run. Candles are stored exactly as Groww returns them; gaps are listed, never filled.</p>
        </Card>
        <Card title="Availability" icon={<Database size={16} className="text-slate-500" />} right={<Pill tone={vTone}>{vLabel}</Pill>} className="lg:col-span-2">
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-3">
            <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <Pill tone="info">NIFTY 50 spot</Pill>
              <div className="mt-2 space-y-0.5 text-slate-600 dark:text-slate-300">
                <div className="num">{num(ins.spot.sessions, 0)} sessions · {num(ins.spot.candles, 0)} candles</div>
                <div>{dmy(ins.spot.first)} → <b className="num">{dmyhm(ins.spot.last)}</b></div>
                <div className="text-xs text-slate-500">Last successful download {dmyhm(ins.spot.last_success)}</div>
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <Pill tone="strat">Near-month futures</Pill>
              <div className="mt-2 space-y-0.5 text-slate-600 dark:text-slate-300">
                <div className="num">{num(ins.futures.contracts, 0)} contracts · {num(ins.futures.candles, 0)} candles</div>
                <div>Latest <b className="num">{dmyhm(ins.futures.last)}</b></div>
                <div className="text-xs text-slate-500">{ins.futures.latest_contract ?? "—"} · volume and VWAP source, downloaded with the spot</div>
              </div>
            </div>
            <div className="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
              <Pill tone="neutral">NIFTY options</Pill>
              <div className="mt-2 space-y-0.5 text-slate-600 dark:text-slate-300">
                <div className="num">{num(ins.options.contracts, 0)} contracts · {num(ins.options.candles, 0)} candles</div>
                <div>{dmy(ins.options.first_day)} → <b className="num">{dmy(ins.options.last_day)}</b></div>
                <div className="text-xs text-slate-500">Last successful download {dmyhm(ins.options.last_success)}</div>
              </div>
            </div>
          </div>
          <div className="mt-3 space-y-1 text-sm text-slate-600 dark:text-slate-300">
            <div>Intervals: <b>{ins.intervals.map((i) => `${i}m`).join(", ")}</b>. 1-minute candles are stored; the others are built from them, aligned to the 09:15 open.</div>
            <div>{s.no_data} weekdays with no candles (usually holidays){s.special_sessions ? `, ${s.special_sessions} special out-of-hours sessions` : ""}; {s.spikes} price spikes over 5% flagged.</div>
          </div>
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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card title="Option history" icon={<Layers size={16} className="text-violet-600" />} className="lg:col-span-2"
          right={o && <Pill tone={o.summary.pct >= 99 ? "good" : o.summary.pct > 0 ? "warn" : "bad"}>{o.summary.pct}% downloaded</Pill>}>
          {opt.loading && !o ? <Loading className="h-24" /> : opt.error && !o ? <ErrorNote>{opt.error}</ErrorNote> : o && (
            <>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                CE and PE within {o.scope.strikes_each_side} strikes of each day's at-the-money strike, for every expiry a backtest can pick
                (nearest, next, monthly), {dmy(o.scope.from)} → {dmy(o.scope.to)}.
              </p>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Contracts in scope" value={num(o.summary.contracts, 0)} sub={`${o.summary.expiries} expiries`} />
                <Stat label="Contract-days downloaded" value={`${num(o.summary.downloaded_days, 0)} / ${num(o.summary.contract_days, 0)}`} />
                <Stat label="Candles" value={num(o.summary.candles, 0)} sub="1-minute, in scope" />
                <Stat label="Days with no trades" value={num(o.summary.empty_days, 0)} sub="Groww returned no candles" />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="primary" onClick={downloadOptions} disabled={!!optJob || !!job}><Download size={15} /> Download or resume options</Button>
                {optJob && <Button variant="danger" onClick={() => stopDownload()}><Square size={14} /> Stop</Button>}
              </div>
              {optJob && <div className="mt-3"><Progress value={optJob.progress} text={optJob.message} /></div>}
              {optErr && <div className="mt-3"><ErrorNote>{optErr}</ErrorNote></div>}
              {o.last_run && (
                <p className="mt-2 text-xs text-slate-500">
                  Last run {dmyhm(o.last_run.started_at)}: <b>{o.last_run.status}</b>, {num(o.last_run.chunks_done, 0)}/{num(o.last_run.chunks_total, 0)} requests
                  {o.last_run.rows_rejected ? `, ${o.last_run.rows_rejected} failed` : ""}. Last complete run {dmyhm(o.last_success)}.
                </p>
              )}
              <div className="scroll-thin mt-3 max-h-72 overflow-auto">
                <table className="w-full min-w-[520px] text-xs">
                  <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900"><tr><th className="py-1">Month</th><th className="text-right">Contracts</th><th className="text-right">Days downloaded</th><th className="text-right">Candles</th><th className="w-40 pl-3">Coverage</th></tr></thead>
                  <tbody>
                    {o.months.slice().reverse().map((m) => (
                      <tr key={m.month} className="border-t border-slate-100 dark:border-slate-800">
                        <td className="py-1">{MON[Number(m.month.slice(5)) - 1]} {m.month.slice(0, 4)}</td>
                        <td className="num text-right">{num(m.contracts, 0)}</td>
                        <td className="num text-right">{num(m.downloaded_days, 0)}/{num(m.contract_days, 0)}</td>
                        <td className="num text-right">{num(m.candles, 0)}</td>
                        <td className="pl-3"><div className="h-2 rounded bg-slate-100 dark:bg-slate-800"><div className={`h-2 rounded ${m.pct >= 99 ? "bg-green-500" : "bg-orange-400"}`} style={{ width: `${m.pct}%` }} /></div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
        <Card title="NIFTY lot sizes (NSE)" icon={<Scale size={16} className="text-orange-600" />}>
          {lots.loading ? <Loading className="h-24" /> : lots.error ? <ErrorNote>{lots.error}</ErrorNote> : (
            <>
              <table className="w-full text-sm">
                <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">From expiry</th><th>Cycle</th><th className="text-right">Lot</th></tr></thead>
                <tbody>
                  {(lots.data ?? []).slice().reverse().map((l) => (
                    <tr key={l.cycle + l.first_expiry} className="border-t border-slate-100 dark:border-slate-800" title={l.source}>
                      <td className="num py-1">{dmy(l.first_expiry)}</td><td className="capitalize">{l.cycle}</td><td className="num text-right font-semibold">{l.lot_size}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-slate-500">From NSE circulars 47854, 61415, 64625 and 70616 (hover a row for its source). A contract's lot size depends on its expiry date and cycle; the month's last expiry is the monthly one. Backtests use these unless you choose a fixed lot size.</p>
            </>
          )}
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

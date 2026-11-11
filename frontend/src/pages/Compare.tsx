import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BarChart3, RefreshCw } from "lucide-react";
import { useSettings } from "../context/SettingsContext";
import { useApi, waitForJob } from "../hooks/useApi";
import { getMeta, getResearch, runResearch } from "../services/api";
import { Card, Pill } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, Segmented } from "../components/common/Controls";
import { Empty, ErrorNote, Limitation, Loading, Progress } from "../components/common/States";
import { LineChart } from "../components/charts/SeriesChart";
import { dmy, inrShort, num, pct, pnlClass } from "../utils/format";
import type { Job, ModeKey, ResearchCell } from "../types/api";

const MODES: { value: ModeKey; label: string }[] = [{ value: "ITM5_BUY", label: "ITM 5 buy" }, { value: "ATM_BUY", label: "ATM buy" }, { value: "ATM_SELL", label: "ATM sell" }];
const SERIES = ["#2563eb", "#ea580c", "#7c3aed", "#16a34a"];
const key = (c: ResearchCell) => `${c.strategy}|${c.timeframe}`;

/** Green for profit, red for loss; stronger colour for bigger amounts. */
function cellBg(v: number, max: number) {
  const a = Math.min(1, Math.abs(v) / (max || 1));
  const alpha = (0.08 + a * 0.32).toFixed(2);
  return v >= 0 ? `rgba(22,163,74,${alpha})` : `rgba(220,38,38,${alpha})`;
}

export default function Compare() {
  const { settings } = useSettings();
  const nav = useNavigate();
  const [mode, setMode] = useState<ModeKey>("ATM_BUY");
  const [tf, setTf] = useState(15);
  const [start, setStart] = useState("09:30");
  const [cutoff, setCutoff] = useState("14:30");
  const [picked, setPicked] = useState<string[] | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const meta = useApi(getMeta, []);
  const res = useApi(() => getResearch(start, cutoff), [start, cutoff]);
  const data = res.data?.data;
  const m = (c: ResearchCell) => c.summary?.modes?.[mode];

  useEffect(() => {
    const j = res.data?.job;
    if (j && typeof j === "object" && !job) waitForJob(j.id, setJob, 3000).then(() => { setJob(null); void res.reload(); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [res.data?.job]);

  const cells = data?.cells ?? [];
  const done = cells.filter((c) => m(c));
  const tfs = [...new Set(cells.map((c) => c.timeframe))].sort((a, b) => a - b);
  const strats = [...new Map(cells.map((c) => [c.strategy, c.label])).entries()];
  const by = Object.fromEntries(cells.map((c) => [key(c), c]));
  const maxAbs = Math.max(1, ...done.map((c) => Math.abs(m(c)!.net_pnl)));
  const best = done.length ? key(done.reduce((a, b) => (m(b)!.net_pnl > m(a)!.net_pnl ? b : a))) : null;
  const sel = picked ?? (done.length ? [...done].sort((a, b) => m(b)!.net_pnl - m(a)!.net_pnl).slice(0, 3).map(key).concat(by["ema_9_21|15"] ? ["ema_9_21|15"] : []).filter((v, i, a) => a.indexOf(v) === i).slice(0, 4) : []);

  const equity = useMemo(() => sel.map((k, i) => {
    const c = by[k]; const s = c && m(c);
    let cum = 0;
    return { name: c ? `${c.label} ${c.timeframe}m` : k, color: SERIES[i], data: s ? s.daily.map(([d, v]) => ({ time: d, value: (cum += v) })) : [] };
  }), [sel.join(","), mode, data]); // eslint-disable-line react-hooks/exhaustive-deps

  const rows = cells.filter((c) => c.timeframe === tf && m(c));
  const years = [...new Set(rows.flatMap((c) => Object.keys(m(c)!.yearly)))].sort();
  const wf = data?.walk_forward?.[mode];

  async function runMissing() {
    try {
      const r = await runResearch(start, cutoff);
      const j = await waitForJob(String(r.job), setJob, 3000);
      setJob(null);
      if (j.state === "error") throw new Error(j.error ?? "Run failed");
      await res.reload();
    } catch (e) { setJob(null); alert((e as Error).message); }
  }
  const toggle = (k: string) => setPicked((p) => { const cur = p ?? sel; return cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k].slice(-4); });

  return (
    <div className="space-y-4">
      <PageHeader title="Strategy Comparison" subtitle={done[0] ? `${done.length} of ${cells.length} configurations · ${dmy(done[0].start_date)} → ${dmy(done[0].end_date)} · 1 lot, all charges` : "All strategies × timeframes over the stored history"}
        actions={<>
          <Segmented value={mode} onChange={setMode} options={MODES} />
          <Field label="" className="w-24"><select aria-label="Entry from" className={inputCls} value={start} onChange={(e) => { setStart(e.target.value); setPicked(null); }}>{(meta.data?.starts ?? ["09:30"]).map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="" className="w-24"><select aria-label="Time cut" className={inputCls} value={cutoff} onChange={(e) => { setCutoff(e.target.value); setPicked(null); }}>{(meta.data?.cutoffs ?? ["14:30"]).map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Button onClick={runMissing} disabled={!!job}><RefreshCw size={14} className={job ? "animate-spin" : ""} /> Run missing</Button>
        </>} />
      {job && <Card><Progress value={job.progress} text={job.message} /></Card>}
      {res.error && <ErrorNote>{res.error}</ErrorNote>}
      {res.loading && !data ? <Loading /> : !done.length ? (
        <Empty title="No comparison results yet">Run missing configurations. The first run downloads option candles and can take a long time.</Empty>
      ) : (
        <>
          <Card title="Net P&L by strategy and timeframe" icon={<BarChart3 size={16} className="text-violet-600" />} right="Tick up to 4 to chart · tap a cell to open it in Backtesting">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead><tr className="text-xs uppercase text-slate-500"><th className="py-2 text-left">Strategy</th>{tfs.map((t) => <th key={t} className="text-right">{t} min</th>)}</tr></thead>
                <tbody>
                  {strats.map(([s, label]) => (
                    <tr key={s} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="py-1.5 pr-2 font-semibold">{label}</td>
                      {tfs.map((t) => {
                        const c = by[`${s}|${t}`]; const x = c && m(c);
                        if (!x) return <td key={t} className="text-right text-xs text-slate-400">not run</td>;
                        const k = key(c);
                        return (
                          <td key={t} className="p-0.5">
                            <div role="button" tabIndex={0} onClick={() => nav(`/backtest?strategy=${s}&tf=${t}&start_date=${c.start_date}&end_date=${c.end_date}&entry_start=${start}&cutoff=${cutoff}&mode=${mode}`)}
                              onKeyDown={(e) => e.key === "Enter" && (e.currentTarget as HTMLElement).click()}
                              className={`cursor-pointer rounded-lg px-2 py-1.5 text-right ${k === best ? "ring-2 ring-blue-500" : ""}`} style={{ background: cellBg(x.net_pnl, maxAbs) }}>
                              <div className="flex items-center justify-between gap-2">
                                <input type="checkbox" aria-label={`Chart ${label} ${t}m`} checked={sel.includes(k)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(k)} />
                                <span className={`num font-bold ${pnlClass(x.net_pnl)}`}>{inrShort(x.net_pnl)}</span>
                              </div>
                              <div className="text-[11px] text-slate-600 dark:text-slate-400">{x.trades} trades · {pct(x.win_rate, 0)} won · PF {x.profit_factor == null ? "∞" : num(x.profit_factor)}</div>
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Equity curves" right={<span className="flex flex-wrap gap-3">{equity.map((s) => <span key={s.name} style={{ color: s.color }}>━ {s.name}</span>)}</span>}>
            <LineChart series={equity} dark={settings.theme === "dark"} height={300} />
          </Card>

          <div className="flex items-center gap-2"><span className="text-sm font-medium">Charts for</span><Segmented value={tf} onChange={setTf} options={tfs.map((t) => ({ value: t, label: `${t}m` }))} /></div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title={`Win rate · ${tf}m`}>
              {rows.map((c) => (
                <div key={c.strategy} className="grid grid-cols-[8rem_1fr_3.5rem] items-center gap-2 py-1 text-xs">
                  <span className="truncate">{c.label}</span>
                  <div className="relative h-3 rounded bg-slate-100 dark:bg-slate-800"><div className="h-full rounded bg-blue-500" style={{ width: `${m(c)!.win_rate}%` }} /><div className="absolute inset-y-[-2px] left-1/2 w-px bg-slate-500" /></div>
                  <span className="num text-right">{pct(m(c)!.win_rate)}</span>
                </div>
              ))}
            </Card>
            <Card title={`Maximum drawdown · ${tf}m`}>
              {rows.map((c) => {
                const mx = Math.max(1, ...rows.map((r) => m(r)!.max_drawdown));
                return (
                  <div key={c.strategy} className="grid grid-cols-[8rem_1fr_4.5rem] items-center gap-2 py-1 text-xs">
                    <span className="truncate">{c.label}</span>
                    <div className="h-3 rounded bg-slate-100 dark:bg-slate-800"><div className="h-full rounded bg-red-500" style={{ width: `${(m(c)!.max_drawdown / mx) * 100}%` }} /></div>
                    <span className="num text-right text-loss">{inrShort(-m(c)!.max_drawdown, false)}</span>
                  </div>
                );
              })}
            </Card>
          </div>

          <Card title={`Year by year · ${tf}m`}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-sm">
                <thead><tr className="text-xs uppercase text-slate-500"><th className="py-2 text-left">Strategy</th>{years.map((y) => <th key={y} className="text-right">{y}</th>)}<th className="text-right">Total</th></tr></thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.strategy} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="py-1.5 font-medium">{c.label}</td>
                      {years.map((y) => { const v = m(c)!.yearly[y]; return <td key={y} className={`num text-right ${v ? pnlClass(v.net) : ""}`}>{v ? inrShort(v.net) : "—"}</td>; })}
                      <td className={`num text-right font-bold ${pnlClass(m(c)!.net_pnl)}`}>{inrShort(m(c)!.net_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {wf && wf.rows.length > 0 && (
            <Card title="Walk-forward: picking the best setup using only earlier years">
              <p className="mb-2 text-sm text-slate-600 dark:text-slate-300">
                Out-of-sample total <b className={pnlClass(wf.total_oos)}>{inrShort(wf.total_oos)}</b> vs EMA 9/21 15m <b className={pnlClass(wf.baseline_total)}>{inrShort(wf.baseline_total)}</b>.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead><tr className="text-xs uppercase text-slate-500"><th className="py-2 text-left">Year</th><th className="text-left">Chosen</th><th className="text-right">Earlier years</th><th className="text-right">That year</th><th className="text-right">EMA 9/21 15m</th><th className="text-left pl-3">Best in hindsight</th></tr></thead>
                  <tbody>
                    {wf.rows.map((r) => (
                      <tr key={r.year} className="border-t border-slate-100 dark:border-slate-800">
                        <td className="py-1.5">{r.year}</td><td>{r.pick.label} {r.pick.timeframe}m</td>
                        <td className={`num text-right ${pnlClass(r.insample_net)}`}>{inrShort(r.insample_net)}</td>
                        <td className={`num text-right font-bold ${pnlClass(r.oos_net)}`}>{inrShort(r.oos_net)}</td>
                        <td className={`num text-right ${pnlClass(r.baseline_net)}`}>{inrShort(r.baseline_net)}</td>
                        <td className="pl-3 text-xs">{r.hindsight_best.label} {r.hindsight_best.timeframe}m <Pill tone={r.hindsight_best.net >= 0 ? "good" : "bad"}>{inrShort(r.hindsight_best.net)}</Pill></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
          <Limitation>Losses are shown as they happened. Picking the best of 28 configurations after the fact overstates what you'd have earned; the walk-forward table is the honest test. Past results don't predict future returns.</Limitation>
        </>
      )}
    </div>
  );
}

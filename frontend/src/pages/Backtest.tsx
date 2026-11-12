import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Play, Settings2 } from "lucide-react";
import { useSettings } from "../context/SettingsContext";
import { useApi, waitForJob } from "../hooks/useApi";
import { getBtChart, getBtResult, getMeta, runBacktest } from "../services/api";
import { Card, Pill, Stat } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, Segmented, selectInline } from "../components/common/Controls";
import { Empty, ErrorNote, Limitation, Loading, Progress } from "../components/common/States";
import { CandleChart, type ChartMarker } from "../components/charts/CandleChart";
import { BarsChart, LineChart } from "../components/charts/SeriesChart";
import { dmy, hm, inr, inrShort, num, pct, pnlClass } from "../utils/format";
import type { BtChart, BtParams, BtResult, BtTrade, Job, ModeKey } from "../types/api";

const MODES: { value: ModeKey; label: string }[] = [{ value: "ITM5_BUY", label: "ITM 5 buy" }, { value: "ATM_BUY", label: "ATM buy" }, { value: "ATM_SELL", label: "ATM sell" }];
const MODE_COLOR: Record<ModeKey, string> = { ITM5_BUY: "#7c3aed", ATM_BUY: "#2563eb", ATM_SELL: "#ea580c" };
const STORE = "gt-backtest";
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const COST_LABEL: Record<string, string> = { slippage_pct: "Slippage %", slippage_pts: "Slippage pts", brokerage_per_order: "Brokerage / order ₹",
  stt_sell_pct: "STT on sell %", exchange_pct: "Exchange %", sebi_per_crore: "SEBI ₹/crore", stamp_buy_pct: "Stamp on buy %", gst_pct: "GST %" };
const PCT_KEYS = new Set(["slippage_pct", "stt_sell_pct", "exchange_pct", "stamp_buy_pct", "gst_pct"]);

function metricsOf(trades: BtTrade[], capital: number) {
  const n = trades.length, wins = trades.filter((t) => t.net > 0).length;
  const net = trades.reduce((a, t) => a + t.net, 0), gross = trades.reduce((a, t) => a + t.gross, 0);
  const fric = trades.reduce((a, t) => a + t.friction, 0);
  const sw = trades.filter((t) => t.net > 0).reduce((a, t) => a + t.net, 0), sl = -trades.filter((t) => t.net <= 0).reduce((a, t) => a + t.net, 0);
  let eq = capital, peak = capital, dd = 0, ddp = 0;
  for (const t of trades) { eq += t.net; peak = Math.max(peak, eq); dd = Math.max(dd, peak - eq); if (peak > 0) ddp = Math.max(ddp, ((peak - eq) / peak) * 100); }
  return { n, wins, net, gross, fric, pf: sl > 0 ? sw / sl : null, exp: n ? net / n : 0, dd, ddp, rate: n ? (wins / n) * 100 : 0 };
}

export default function Backtest() {
  const { settings } = useSettings();
  const dark = settings.theme === "dark";
  const [search, setSearch] = useSearchParams();
  const meta = useApi(getMeta, []);
  const [params, setParams] = useState<BtParams | null>(null);
  const [result, setResult] = useState<BtResult | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mode, setMode] = useState<ModeKey>((search.get("mode") as ModeKey) || "ATM_BUY");
  const [year, setYear] = useState("all");
  const [outcome, setOutcome] = useState("all");
  const [selId, setSelId] = useState<string | null>(null);
  const [chart, setChart] = useState<BtChart | null>(null);
  const [chartErr, setChartErr] = useState<string | null>(null);

  // Defaults from the server, then saved settings, then a link from Strategy Comparison.
  useEffect(() => {
    if (!meta.data || params) return;
    let saved: Partial<BtParams> = {};
    try { saved = JSON.parse(localStorage.getItem(STORE) || "{}"); } catch { /* ignore */ }
    const p: BtParams = { ...meta.data.defaults, ...saved, costs: { ...meta.data.defaults.costs, ...(saved.costs ?? {}) }, end_date: meta.data.defaults.end_date };
    for (const k of ["strategy", "start_date", "end_date", "entry_start", "cutoff"] as const) { const v = search.get(k); if (v) (p as unknown as Record<string, unknown>)[k] = v; }
    if (search.get("tf")) p.timeframe = Number(search.get("tf"));
    if (search.toString()) setSearch({}, { replace: true });
    setParams(p);
    void run(p);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta.data]);

  async function run(p = params, force = false) {
    if (!p) return;
    setErr(null);
    try { localStorage.setItem(STORE, JSON.stringify(p)); } catch { /* ignore */ }
    try {
      const r = await runBacktest({ ...p, force });
      let hash = r.hash;
      if (!hash && r.job) {
        const j = await waitForJob(String(r.job), setJob);
        setJob(null);
        if (j.state === "error") throw new Error(j.error ?? "Backtest failed");
        hash = (j.result as { hash: string }).hash;
      }
      const res = await getBtResult(hash!);
      setResult(res); setSelId(null); setYear("all");
    } catch (e) { setJob(null); setErr((e as Error).message); }
  }
  const set = (patch: Partial<BtParams>) => setParams((p) => (p ? { ...p, ...patch } : p));

  const all = result?.trades[mode] ?? [];
  const years = useMemo(() => [...new Set(all.map((t) => t.day.slice(0, 4)))].sort(), [all]);
  const list = useMemo(() => all.filter((t) => (year === "all" || t.day.startsWith(year)) && (outcome === "all" || t.outcome === outcome)), [all, year, outcome]);
  const m = metricsOf(list, result?.params.capital ?? 100000);
  const sel = list.find((t) => t.id === selId) ?? list[0];

  const equity = useMemo(() => MODES.map(({ value, label }) => {
    const byDay = new Map<string, number>();
    for (const t of (result?.trades[value] ?? []).filter((t) => year === "all" || t.day.startsWith(year))) byDay.set(t.day, (byDay.get(t.day) ?? 0) + t.net);
    let cum = 0;
    return { name: label, color: MODE_COLOR[value], data: [...byDay.entries()].sort().map(([d, v]) => ({ time: d, value: (cum += v) })) };
  }), [result, year]);
  const monthly = useMemo(() => {
    const mm = new Map<string, number>();
    for (const t of list) mm.set(t.day.slice(0, 7), (mm.get(t.day.slice(0, 7)) ?? 0) + t.net);
    return [...mm.entries()].sort().map(([k, v]) => ({ time: `${k}-01`, value: Math.round(v) }));
  }, [list]);
  const yearly = useMemo(() => {
    const y = new Map<string, number[]>();
    for (const t of list) { const k = t.day.slice(0, 4); const a = y.get(k) ?? Array(12).fill(0); a[Number(t.day.slice(5, 7)) - 1] += t.net; y.set(k, a); }
    return [...y.entries()].sort().reverse();
  }, [list]);
  const days = useMemo(() => {
    const d = new Map<string, number>();
    for (const t of list) d.set(t.day, (d.get(t.day) ?? 0) + t.net);
    return [...d.entries()].sort((a, b) => b[1] - a[1]);
  }, [list]);

  useEffect(() => {
    if (!result || !sel) { setChart(null); return; }
    let live = true;
    setChart(null); setChartErr(null);
    getBtChart(result.hash, sel.id).then((c) => live && setChart(c)).catch((e) => live && setChartErr((e as Error).message));
    return () => { live = false; };
  }, [result, sel?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const markers = useMemo<ChartMarker[]>(() => sel ? [
    { ts: sel.entry_ts, position: sel.direction === "Bullish" ? "belowBar" : "aboveBar", color: "#7c3aed", shape: sel.direction === "Bullish" ? "arrowUp" : "arrowDown", text: `Entry ${hm(sel.fill_entry_ts)}` },
    { ts: sel.exit_ts, position: sel.direction === "Bullish" ? "aboveBar" : "belowBar", color: "#64748b", shape: "square", text: `Exit ${hm(sel.fill_exit_ts)}` },
  ] : [], [sel]);
  const optMarkers = useMemo<ChartMarker[]>(() => sel ? [
    { ts: sel.fill_entry_ts, position: "belowBar", color: "#7c3aed", shape: "arrowUp", text: `${sel.side} ${num(sel.opt_entry)}` },
    { ts: sel.fill_exit_ts, position: "aboveBar", color: "#64748b", shape: "square", text: `Exit ${num(sel.opt_exit)}` },
  ] : [], [sel]);

  if (meta.loading && !meta.data) return <Loading />;
  if (meta.error || !params) return <ErrorNote>{meta.error ?? "Couldn't load backtest settings."}</ErrorNote>;
  const md = meta.data!;

  return (
    <div className="space-y-4">
      <PageHeader title="Backtesting" subtitle={result ? `${result.strategy_label} · ${dmy(result.params.start_date)} → ${dmy(result.params.end_date)} · ${result.params.timeframe}-minute · ${result.signals} signals${result.partial_asof ? ` · today up to ${hm(result.partial_asof)}` : ""}` : "Real NIFTY option prices, every charge included."}
        actions={<Button variant="primary" onClick={() => run(params, false)} disabled={!!job}><Play size={15} /> Run backtest</Button>} />

      <Card title="Settings" icon={<Settings2 size={16} className="text-slate-500" />}>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="Strategy" className="col-span-2 sm:col-span-1">
            <select className={inputCls} value={params.strategy} onChange={(e) => set({ strategy: e.target.value })}>
              {Object.entries(md.strategies).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select></Field>
          <Field label="Timeframe"><select className={inputCls} value={params.timeframe} onChange={(e) => set({ timeframe: Number(e.target.value) })}>
            {md.timeframes.map((t) => <option key={t} value={t}>{t} min</option>)}</select></Field>
          <Field label="From"><input type="date" className={inputCls} value={params.start_date} onChange={(e) => set({ start_date: e.target.value })} /></Field>
          <Field label="To"><input type="date" className={inputCls} value={params.end_date} onChange={(e) => set({ end_date: e.target.value })} /></Field>
          <Field label="Entry from"><select className={inputCls} value={params.entry_start} onChange={(e) => set({ entry_start: e.target.value })}>
            {md.starts.map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Time cut"><select className={inputCls} value={params.cutoff} onChange={(e) => set({ cutoff: e.target.value })}>
            {md.cutoffs.map((s) => <option key={s}>{s}</option>)}</select></Field>
        </div>
        <details className="mt-3">
          <summary className="cursor-pointer text-sm font-medium text-blue-600">Expiry, lots and charges</summary>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            <Field label="Expiry"><select className={inputCls} value={params.expiry_rule} onChange={(e) => set({ expiry_rule: e.target.value })}>
              {Object.entries(md.expiry_rules).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <Field label="Lot size"><select className={inputCls} value={params.lot_size ? "fixed" : "nse"} onChange={(e) => set({ lot_size: e.target.value === "nse" ? 0 : 65 })}>
              <option value="nse">NSE history (per contract)</option><option value="fixed">Fixed</option></select></Field>
            {params.lot_size > 0 && <Field label="Fixed lot size"><input type="number" min={1} className={inputCls} value={params.lot_size} onChange={(e) => set({ lot_size: Math.max(1, Number(e.target.value)) })} /></Field>}
            <Field label="Lots"><input type="number" min={1} className={inputCls} value={params.lots} onChange={(e) => set({ lots: Number(e.target.value) })} /></Field>
            <Field label="Capital ₹"><input type="number" min={1} className={inputCls} value={params.capital} onChange={(e) => set({ capital: Number(e.target.value) })} /></Field>
            <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={params.roll_on_expiry_day} onChange={(e) => set({ roll_on_expiry_day: e.target.checked })} /> Roll to next expiry on expiry day</label>
            {Object.keys(md.defaults.costs).map((k) => (
              <Field key={k} label={COST_LABEL[k] ?? k}>
                <input type="number" step="any" className={inputCls} value={PCT_KEYS.has(k) ? +(params.costs[k] * 100).toPrecision(6) : params.costs[k]}
                  onChange={(e) => set({ costs: { ...params.costs, [k]: PCT_KEYS.has(k) ? Number(e.target.value) / 100 : Number(e.target.value) } })} />
              </Field>
            ))}
          </div>
        </details>
      </Card>

      {job && <Card><Progress value={job.progress} text={job.message} /></Card>}
      {err && <ErrorNote>{err}</ErrorNote>}
      {!result ? (!job && !err ? <Loading text="Running backtest…" /> : null) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Segmented value={mode} onChange={(v) => { setMode(v); setSelId(null); }} options={MODES} />
            <select aria-label="Year" className={selectInline} value={year} onChange={(e) => { setYear(e.target.value); setSelId(null); }}>
              <option value="all">All years</option>{years.map((y) => <option key={y}>{y}</option>)}
            </select>
            <select aria-label="Outcome" className={selectInline} value={outcome} onChange={(e) => { setOutcome(e.target.value); setSelId(null); }}>
              <option value="all">All trades</option><option value="win">Winners</option><option value="loss">Losers</option>
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Card accent={m.net >= 0 ? "gain" : "loss"}><Stat label="Net P&L" value={inr(m.net, true, 0)} className={`text-xl ${pnlClass(m.net)}`} sub={`gross ${inr(m.gross, true, 0)}`} /></Card>
            <Card accent="spot"><Stat label="Win rate" value={pct(m.rate)} className="text-xl" sub={`${m.wins} won · ${m.n - m.wins} lost`} /></Card>
            <Card accent="neutral"><Stat label="Total trades" value={m.n} className="text-xl" sub={`expectancy ${inr(m.exp, true, 0)}`} /></Card>
            <Card accent="loss"><Stat label="Max drawdown" value={inr(-m.dd, false, 0)} className="text-xl text-loss" sub={pct(m.ddp)} /></Card>
            <Card accent="risk"><Stat label="Brokerage & charges" value={inr(-m.fric, false, 0)} className="text-xl text-orange-600" sub="incl. slippage" tip="All friction: slippage, brokerage, STT, exchange, SEBI, stamp duty and GST." /></Card>
            <Card accent="strat"><Stat label="Profit factor" value={m.pf == null ? "∞" : num(m.pf)} className="text-xl" sub="won ÷ lost" /></Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <Card title="Equity curve (cumulative net P&L)" right={<span className="flex gap-3">{equity.map((s) => <span key={s.name} style={{ color: s.color }}>━ {s.name}</span>)}</span>}>
              {equity.some((s) => s.data.length) ? <LineChart series={equity} dark={dark} /> : <Empty title="No trades" />}
            </Card>
            <Card title={`Monthly P&L · ${MODES.find((x) => x.value === mode)!.label}`}>
              {monthly.length ? <BarsChart data={monthly} dark={dark} height={280} /> : <Empty title="No trades" />}
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card title="Yearly & monthly returns" className="xl:col-span-2">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[760px] text-xs">
                  <thead className="text-slate-500"><tr><th className="py-1 text-left">Year</th>{MON.map((x) => <th key={x} className="text-right">{x}</th>)}<th className="text-right">Year</th></tr></thead>
                  <tbody>
                    {yearly.map(([y, a]) => {
                      const tot = a.reduce((s, v) => s + v, 0);
                      return (
                        <tr key={y} className="border-t border-slate-100 dark:border-slate-800">
                          <td className="py-1.5 font-semibold">{y}</td>
                          {a.map((v, i) => <td key={i} className={`num text-right ${v ? pnlClass(v) : "text-slate-300 dark:text-slate-700"}`}>{v ? inrShort(v) : "·"}</td>)}
                          <td className={`num text-right font-bold ${pnlClass(tot)}`}>{inrShort(tot)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Best & worst days">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>{days.filter((d) => d[1] > 0).slice(0, 5).map(([d, v]) => <div key={d} className="flex justify-between py-0.5"><span className="num text-xs">{d}</span><span className="num text-gain">{inrShort(v)}</span></div>)}</div>
                <div>{days.filter((d) => d[1] < 0).slice(-5).reverse().map(([d, v]) => <div key={d} className="flex justify-between py-0.5"><span className="num text-xs">{d}</span><span className="num text-loss">{inrShort(v)}</span></div>)}</div>
              </div>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
            <Card title={`Trades (${list.length})`} className="xl:col-span-2" bodyClass="px-2 pb-2">
              <div className="scroll-thin max-h-[560px] overflow-y-auto">
                {list.length === 0 && <Empty title="No trades match" className="m-2" />}
                {list.map((t) => (
                  <button key={t.id} onClick={() => setSelId(t.id)}
                    className={`grid w-full grid-cols-[1fr_auto] gap-1 rounded-lg px-2 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800/60 ${sel?.id === t.id ? "bg-violet-50 dark:bg-violet-950/30" : ""}`}>
                    <span className="min-w-0">
                      <span className="num text-xs text-slate-500">{t.day} {hm(t.entry_ts)}→{hm(t.exit_ts)}</span>
                      <span className="flex items-center gap-1.5"><Pill tone={t.direction === "Bullish" ? "good" : "bad"}>{t.side} {t.opt_type}</Pill>
                        <span className="truncate text-xs text-slate-500">{num(t.strike, 0)} · #{t.ordinal} · {t.exit_reason === "square_off" ? "15:00" : t.exit_reason === "open" ? "open" : "cross"}{t.whipsaw ? " · whipsaw" : ""}</span></span>
                    </span>
                    <span className={`num self-center font-semibold ${pnlClass(t.net)}`}>{inr(t.net, true, 0)}</span>
                  </button>
                ))}
              </div>
            </Card>
            <div className="space-y-4 xl:col-span-3">
              {sel ? (
                <>
                  <Card title={`NIFTY spot · ${dmy(sel.day)}`} right={<span><span className="text-blue-500">━ {chart?.fast_label ?? "EMA 9"}</span> <span className="ml-1 text-orange-500">━ {chart?.slow_label ?? "EMA 21"}</span></span>}>
                    {chartErr ? <ErrorNote>{chartErr}</ErrorNote> : !chart ? <Loading className="h-[300px]" /> : <CandleChart bars={chart.spot} markers={markers} dark={dark} height={300} />}
                  </Card>
                  <Card title={`Option premium · ${sel.symbol}`} right="1-minute">
                    {chart ? <CandleChart bars={chart.option} markers={optMarkers} showEma={false} dark={dark} height={220} /> : <Loading className="h-[220px]" />}
                    <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-5">
                      <Stat label="Quantity" value={num(sel.qty, 0)} sub={sel.lot_size ? `lot ${sel.lot_size} · ${sel.lot_source === "fixed" ? "fixed" : sel.lot_source ?? ""}` : undefined} />
                      <Stat label="Premium in → out" value={`${num(sel.opt_entry)} → ${num(sel.opt_exit)}`} />
                      <Stat label="Fills (after slippage)" value={`${num(sel.entry_fill)} → ${num(sel.exit_fill)}`} />
                      <Stat label="Charges" value={inr(-sel.friction)} className="text-orange-600" />
                      <Stat label="Net" value={inr(sel.net, true)} className={pnlClass(sel.net)} />
                    </div>
                  </Card>
                </>
              ) : <Empty title="Select a trade" />}
            </div>
          </div>

          <details className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <summary className="cursor-pointer text-sm font-semibold">No-trade days ({result.no_trade_days.length}) & skipped trades ({result.skipped.length})</summary>
            <div className="mt-3 grid grid-cols-1 gap-4 text-xs md:grid-cols-2">
              <div className="max-h-64 overflow-y-auto">{result.no_trade_days.map((d) => <div key={d.day} className="flex gap-3 border-b border-slate-100 py-1 dark:border-slate-800"><span className="num">{d.day}</span><span className="text-slate-500">{d.reason}</span></div>)}</div>
              <div className="max-h-64 overflow-y-auto">{result.skipped.map((s, i) => <div key={i} className="flex gap-3 border-b border-slate-100 py-1 dark:border-slate-800"><span className="num">{s.day} {hm(s.entry_ts)}</span><span>{s.mode}</span><span className="text-slate-500">{s.reason}</span></div>)}</div>
            </div>
          </details>
          <Limitation>Past results don't predict future returns. Every number includes real option prices, slippage and Indian charges; nothing is hidden or smoothed.</Limitation>
        </>
      )}
    </div>
  );
}

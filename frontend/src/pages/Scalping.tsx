import { useEffect, useMemo, useState } from "react";
import { Award, Gauge, ListChecks, Play, RefreshCw, Square, Timer, X } from "lucide-react";
import { useSettings } from "../context/SettingsContext";
import { useLive } from "../context/LiveContext";
import { useApi, waitForJob } from "../hooks/useApi";
import { getScalpConfig, getScalping, getScalpPaperTrades, runScalping, startScalpPaper, stopEngine } from "../services/api";
import { Card, Pill, Stat } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, Segmented, selectInline } from "../components/common/Controls";
import { Empty, ErrorNote, Limitation, Loading, Progress, Warning } from "../components/common/States";
import { BarsChart, LineChart } from "../components/charts/SeriesChart";
import { dmy, dmyhm, hm, inr, inrShort, num, pct, pnlClass } from "../utils/format";
import type { Job, ScalpConfig, ScalpPaperTrade, ScalpStats, ScalpTrade } from "../types/api";

const REASON: Record<string, string> = {
  time_exit: "5-min time exit", stop_loss: "stop-loss", target: "target", square_off: "15:00 square-off",
  daily_loss_limit: "daily loss limit", manual_stop: "you stopped", manual_square_off: "you squared off",
};
const CHECK: Record<string, string> = {
  net_positive: "Net positive after costs", enough_trades: "Enough trades", profit_factor_1_1: "Profit factor ≥ 1.1",
  most_years_positive: "≥ 75% of years positive", out_of_sample_positive: "Positive out of sample",
};
const pf = (v: number | null | undefined) => (v == null ? "∞" : num(v));
const label = (c: ScalpConfig) => `${c.strategy_label} · ${c.contract_label} · ${c.exit_label}`;

function KPIs({ m }: { m: ScalpStats }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
      <Stat label="Net P&L" value={inr(m.net_pnl, true, 0)} className={pnlClass(m.net_pnl)} sub="after all costs" />
      <Stat label="Gross P&L" value={inr(m.gross_pnl, true, 0)} className={pnlClass(m.gross_pnl)} sub="before costs" />
      <Stat label="Brokerage" value={inr(m.brokerage ?? 0, false, 0)} className="text-orange-600" />
      <Stat label="Taxes & fees" value={inr(m.taxes ?? 0, false, 0)} className="text-orange-600" sub={`slippage ${inr(m.slippage ?? 0, false, 0)}`} tip="STT, exchange, SEBI, stamp duty and GST." />
      <Stat label="Trades" value={m.trades} sub={<><span className="text-gain">{m.wins ?? 0} won</span> · <span className="text-loss">{m.losses ?? 0} lost</span></>} />
      <Stat label="Win rate" value={pct(m.win_rate)} />
      <Stat label="Profit factor" value={pf(m.profit_factor)} />
      <Stat label="Max drawdown" value={inr(-m.max_drawdown, false, 0)} className="text-loss" />
      <Stat label="Avg holding" value={m.avg_hold_min != null ? `${num(m.avg_hold_min, 1)} min` : "—"} />
      <Stat label="Risk / reward" value={m.risk_reward ? `1 : ${num(m.risk_reward)}` : "—"} tip="Average win ÷ average loss (net)." />
      <Stat label="Avg win / loss" value={<span className="text-sm">{inr(m.avg_win ?? 0, false, 0)} / {inr(m.avg_loss ?? 0, false, 0)}</span>} />
      <Stat label="Exits" value={<span className="text-[11px] font-normal">{Object.entries(m.exits ?? {}).map(([k, v]) => `${REASON[k] ?? k} ${v}`).join(" · ") || "—"}</span>} />
    </div>
  );
}

function GroupTable({ title, rows }: { title: string; rows: Record<string, { net: number; gross: number; trades: number; win_rate: number }> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-xs">
        <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">{title}</th><th className="text-right">Trades</th><th className="text-right">Win rate</th><th className="text-right">Gross</th><th className="text-right">Net</th></tr></thead>
        <tbody>
          {Object.entries(rows).map(([k, v]) => (
            <tr key={k} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1">{k}</td><td className="num text-right">{v.trades}</td><td className="num text-right">{pct(v.win_rate)}</td>
              <td className={`num text-right ${pnlClass(v.gross)}`}>{inrShort(v.gross)}</td><td className={`num text-right font-semibold ${pnlClass(v.net)}`}>{inrShort(v.net)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TradeDetail({ t, onClose }: { t: ScalpTrade; onClose: () => void }) {
  return (
    <div className="mt-3 rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-800">
      <div className="flex items-center justify-between gap-2">
        <div className="font-semibold">{t.symbol} · {t.direction} · {dmy(t.day)}</div>
        <Button onClick={onClose}><X size={14} /></Button>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Signal (bar close)" value={hm(t.signal_ts)} sub={`NIFTY ${num(t.spot)} · ${t.regime}`} />
        <Stat label="BUY" value={`₹${num(t.entry)} → fill ₹${num(t.entry_fill)}`} sub={hm(t.entry_ts)} />
        <Stat label="SELL" value={`₹${num(t.exit)} → fill ₹${num(t.exit_fill)}`} sub={`${hm(t.exit_ts)} · ${REASON[t.reason] ?? t.reason}`} />
        <Stat label="Held" value={`${num(t.hold_min, 1)} min`} />
        <Stat label="Contract" value={`${num(t.strike, 0)} ${t.opt_type}`} sub={`expiry ${dmy(t.expiry)}`} />
        <Stat label="Quantity" value={`${t.qty}`} sub={`lot size ${t.lot_size}`} />
        <Stat label="Gross" value={inr(t.gross, true)} className={pnlClass(t.gross)} />
        <Stat label="Slippage" value={inr(t.slippage)} className="text-orange-600" />
        <Stat label="Brokerage" value={inr(t.brokerage)} className="text-orange-600" />
        <Stat label="Taxes & fees" value={inr(t.taxes)} className="text-orange-600" />
        <Stat label="Net" value={inr(t.net, true)} className={pnlClass(t.net)} />
      </div>
    </div>
  );
}

function BacktestTrades({ trades }: { trades: ScalpTrade[] }) {
  const [filter, setFilter] = useState<"all" | "win" | "loss">("all");
  const [page, setPage] = useState(0);
  const [sel, setSel] = useState<ScalpTrade | null>(null);
  const rows = trades.filter((t) => filter === "all" || (filter === "win" ? t.net > 0 : t.net <= 0)).slice().reverse();
  const per = 50, pages = Math.max(1, Math.ceil(rows.length / per));
  useEffect(() => { setPage(0); setSel(null); }, [filter, trades]);
  return (
    <>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: `All ${trades.length}` }, { value: "win", label: `Winning ${trades.filter((t) => t.net > 0).length}` }, { value: "loss", label: `Losing ${trades.filter((t) => t.net <= 0).length}` }]} />
        <span className="text-xs text-slate-500">newest first · click a trade for every detail</span>
      </div>
      <div className="scroll-thin max-h-[28rem] overflow-auto">
        <table className="w-full min-w-[900px] text-xs">
          <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900">
            <tr><th className="py-1.5">Day</th><th>Signal</th><th>Contract</th><th className="text-right">Qty</th><th className="text-right">BUY</th><th className="text-right">SELL</th><th>Exit</th><th className="text-right">Held</th><th className="text-right">Gross</th><th className="text-right">Costs</th><th className="text-right">Net</th></tr>
          </thead>
          <tbody>
            {rows.slice(page * per, page * per + per).map((t) => (
              <tr key={t.entry_ts + t.symbol} onClick={() => setSel(t)} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60 ${sel === t ? "bg-blue-50 dark:bg-blue-950/40" : ""}`}>
                <td className="py-1">{dmy(t.day)}</td><td>{hm(t.signal_ts)} <Pill tone={t.opt_type === "CE" ? "good" : "bad"}>{t.opt_type}</Pill></td>
                <td>{num(t.strike, 0)} · {dmy(t.expiry).slice(0, 6)}</td><td className="num text-right">{t.qty}</td>
                <td className="num text-right">{hm(t.entry_ts)} ₹{num(t.entry_fill)}</td><td className="num text-right">{hm(t.exit_ts)} ₹{num(t.exit_fill)}</td>
                <td>{REASON[t.reason] ?? t.reason}</td><td className="num text-right">{num(t.hold_min, 0)}m</td>
                <td className={`num text-right ${pnlClass(t.gross)}`}>{inr(t.gross, true, 0)}</td><td className="num text-right text-orange-600">{inr(t.friction, false, 0)}</td>
                <td className={`num text-right font-semibold ${pnlClass(t.net)}`}>{inr(t.net, true, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center gap-2 text-xs">
          <Button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>Newer</Button>
          <span>Page {page + 1} / {pages}</span>
          <Button onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}>Older</Button>
        </div>
      )}
      {sel && <TradeDetail t={sel} onClose={() => setSel(null)} />}
    </>
  );
}

function ConfigDetail({ k, dark }: { k: string; dark: boolean }) {
  const d = useApi(() => getScalpConfig(k), [k]);
  const c = d.data;
  if (d.error) return <ErrorNote>{d.error}</ErrorNote>;
  if (!c) return <Loading />;
  const monthly = Object.entries(c.monthly ?? {}).map(([m, v]) => ({ time: `${m}-01`, value: v.net }));
  return (
    <div className="space-y-4">
      <Card title={label(c)} icon={<Gauge size={16} className="text-violet-600" />} accent="strat"
        right={<Pill tone={c.verdict.consistent ? "good" : "bad"}>{c.verdict.consistent ? "Consistently profitable" : "Not consistently profitable"}</Pill>}>
        <KPIs m={c} />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.entries(c.verdict.checks).map(([n, ok]) => <Pill key={n} tone={ok ? "good" : "bad"}>{ok ? "✓" : "✗"} {CHECK[n] ?? n}</Pill>)}
          <Pill tone="neutral">years positive {c.verdict.years_positive}</Pill>
        </div>
        {Object.keys(c.skipped).length > 0 && (
          <p className="mt-2 text-xs text-slate-500">Signals not traded: {Object.entries(c.skipped).map(([r, n]) => `${r} ${n}`).join(" · ")}</p>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="CE versus PE">
          <div className="grid grid-cols-2 gap-4">
            {(["ce", "pe"] as const).map((s) => (
              <div key={s} className="space-y-2">
                <Pill tone={s === "ce" ? "good" : "bad"}>{s.toUpperCase()} · {s === "ce" ? "bullish" : "bearish"} signals</Pill>
                <Stat label="Net" value={inr(c[s].net_pnl, true, 0)} className={pnlClass(c[s].net_pnl)} sub={`gross ${inr(c[s].gross_pnl, true, 0)}`} />
                <Stat label="Trades · win rate" value={`${c[s].trades} · ${pct(c[s].win_rate)}`} />
                <Stat label="Profit factor · max DD" value={`${pf(c[s].profit_factor)} · ${inrShort(-c[s].max_drawdown, false)}`} />
              </div>
            ))}
          </div>
        </Card>
        <Card title="In-sample vs out-of-sample" right="split by trading days, 60 / 40">
          <div className="grid grid-cols-2 gap-4">
            {([["In-sample (first 60%)", c.in_sample], ["Out-of-sample (last 40%)", c.out_of_sample]] as const).map(([t, v]) => (
              <div key={t} className="space-y-2">
                <div className="text-xs font-semibold">{t}</div>
                {v ? <>
                  <Stat label="Net" value={inr(v.net_pnl, true, 0)} className={pnlClass(v.net_pnl)} />
                  <Stat label="Trades · PF" value={`${v.trades} · ${pf(v.profit_factor)}`} />
                  <Stat label="Max drawdown" value={inr(-v.max_drawdown, false, 0)} className="text-loss" />
                </> : <span className="text-xs text-slate-500">no trades</span>}
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card title="Equity (net, 1 lot per trade)">
        <LineChart series={[{ name: "Net", color: "#7c3aed", data: (c.equity ?? []).map(([t, v]) => ({ time: t, value: v })) }]} dark={dark} height={260} />
      </Card>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Yearly performance"><GroupTable title="Year" rows={c.yearly} /></Card>
        <Card title="By market condition" right="daily regime of NIFTY"><GroupTable title="Regime" rows={c.regimes ?? {}} /></Card>
      </div>
      <Card title="Monthly net P&L"><BarsChart data={monthly} dark={dark} height={220} /></Card>

      {c.risk && (
        <Card title="Sized by risk % of ₹1,00,000" right="lots so the loss at the stop fits the risk">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs">
              <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">Risk / trade</th><th className="text-right">Trades</th><th className="text-right">Avg lots</th><th className="text-right">Gross</th><th className="text-right">Brokerage</th><th className="text-right">Taxes</th><th className="text-right">Net</th><th className="text-right">Max DD</th><th className="text-right">PF</th><th className="text-right">Too small</th></tr></thead>
              <tbody>
                {Object.entries(c.risk).map(([r, v]) => (
                  <tr key={r} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="py-1">{r}%</td><td className="num text-right">{v.trades}</td><td className="num text-right">{num(v.avg_lots)}</td>
                    <td className={`num text-right ${pnlClass(v.gross_pnl)}`}>{inrShort(v.gross_pnl)}</td><td className="num text-right">{inrShort(v.brokerage, false)}</td><td className="num text-right">{inrShort(v.taxes, false)}</td>
                    <td className={`num text-right font-semibold ${pnlClass(v.net_pnl)}`}>{inrShort(v.net_pnl)}</td><td className="num text-right text-loss">{inrShort(-v.max_drawdown, false)} ({pct(v.max_drawdown_pct)})</td>
                    <td className="num text-right">{pf(v.profit_factor)}</td><td className="num text-right">{v.too_small}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      <Card title="Backtest trades (BUY and SELL)" icon={<ListChecks size={16} className="text-blue-600" />}><BacktestTrades trades={c.trade_list} /></Card>
    </div>
  );
}

function PaperPanel({ configs, selected, consistent }: { configs: ScalpConfig[]; selected: string; consistent: string[] }) {
  const { data, refresh } = useLive();
  const [key, setKey] = useState(selected);
  const [mode, setMode] = useState<"paper" | "replay">("paper");
  const [risk, setRisk] = useState({ risk_pct: 1, daily_risk_pct: 3, max_trades_per_day: 20, max_lots: 10 });
  const [day, setDay] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState<ScalpPaperTrade | null>(null);
  useEffect(() => setKey(selected), [selected]);
  const running = data && data.state !== "stopped";
  const scalpRunning = running && data?.config?.signal_mode === "scalp";
  const trades = useApi(() => getScalpPaperTrades(), [data?.trades_today, data?.position?.entry_ts, data?.state]);
  const c = configs.find((x) => x.key === key);

  async function start() {
    if (!c) return;
    if (!consistent.includes(key) && !window.confirm("This configuration did NOT pass the consistency checks after costs. Paper-trade it anyway? (No real orders are sent.)")) return;
    setBusy(true); setErr(null);
    try { await startScalpPaper(key, mode, risk, mode === "replay" ? day : undefined); refresh(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function stop() {
    if (!window.confirm("Stop the engine? Any open paper position is squared off first.")) return;
    setBusy(true);
    try { await stopEngine(); refresh(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const p = data?.position;
  return (
    <Card title="Automatic paper trading" icon={<Timer size={16} className="text-orange-600" />} accent="risk"
      right={<Pill tone={scalpRunning ? "good" : running ? "warn" : "neutral"}>{scalpRunning ? `Scalping · ${data?.config?.trade_mode}` : running ? "Engine busy (other mode)" : "Stopped"}</Pill>}>
      <div className="space-y-3 text-sm">
        <Limitation>Paper mode uses live Groww prices with simulated fills, slippage and charges; no order is ever sent. Real-money scalping is not enabled. A configuration is never picked for you by win rate — choose one from the table above.</Limitation>
        {scalpRunning && data?.config?.scalp_config && (
          <p className="text-xs">Running <b>{data.config.scalp_config}</b>{p ? <> · open {num(p.strike, 0)} {p.opt_type} @ ₹{num(p.entry_price)} since {hm(p.entry_ts)}, LTP ₹{num(p.ltp)} (<span className={pnlClass(p.mtm)}>{inr(p.mtm, true)}</span>)</> : " · no open position"} · {data.trades_today} trade(s) today, realised <span className={pnlClass(data.realised_today)}>{inr(data.realised_today, true)}</span></p>
        )}
        <fieldset disabled={!!running || busy} className="grid grid-cols-2 gap-3 disabled:opacity-60 sm:grid-cols-4">
          <Field label="Tested configuration" className="col-span-2 sm:col-span-4">
            <select className={inputCls} value={key} onChange={(e) => setKey(e.target.value)}>
              {configs.map((x) => <option key={x.key} value={x.key}>{consistent.includes(x.key) ? "✓ " : ""}{label(x)} · net {inrShort(x.net_pnl)}</option>)}
            </select>
          </Field>
          <Field label="Mode"><Segmented value={mode} onChange={setMode} options={[{ value: "paper", label: "Paper (live)" }, { value: "replay", label: "Replay" }]} /></Field>
          {mode === "replay" ? <Field label="Replay day"><input type="date" className={inputCls} value={day} onChange={(e) => setDay(e.target.value)} /></Field> : <div />}
          <Field label="Risk / trade %"><input type="number" min={0.05} max={100} step={0.05} className={inputCls} value={risk.risk_pct} onChange={(e) => setRisk({ ...risk, risk_pct: Number(e.target.value) })} /></Field>
          <Field label="Daily risk %"><input type="number" min={0} max={100} step={0.5} className={inputCls} value={risk.daily_risk_pct} onChange={(e) => setRisk({ ...risk, daily_risk_pct: Number(e.target.value) })} /></Field>
          <Field label="Max trades / day"><input type="number" min={1} className={inputCls} value={risk.max_trades_per_day} onChange={(e) => setRisk({ ...risk, max_trades_per_day: Math.max(1, Number(e.target.value)) })} /></Field>
          <Field label="Max lots / trade"><input type="number" min={1} className={inputCls} value={risk.max_lots} onChange={(e) => setRisk({ ...risk, max_lots: Math.max(1, Number(e.target.value)) })} /></Field>
        </fieldset>
        {c && !consistent.includes(key) && <Warning>{label(c)} lost {inrShort(c.net_pnl)} after costs over the backtest ({c.verdict.years_positive} years positive). Paper-trading it is for observation only.</Warning>}
        {c?.exit_kind === "time" && <p className="text-xs text-slate-500">Fixed 5-minute exit. The paper risk rules need a stop-loss, so a protective 30% premium stop also applies (the backtest has none).</p>}
        {err && <p className="text-red-600">{err}</p>}
        <div className="flex gap-2">
          {!running ? <Button variant="primary" onClick={start} disabled={busy || !c || (mode === "replay" && !day)} className="min-h-11 flex-1"><Play size={16} /> Start {mode === "replay" ? "replay" : "paper scalping"}</Button>
            : <Button variant="danger" onClick={stop} disabled={busy} className="min-h-11 flex-1"><Square size={16} /> Stop engine</Button>}
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between font-semibold"><span>Scalping transactions (paper and replay)</span><span className="text-xs font-normal text-slate-500">click a row for details</span></div>
          {trades.error && <ErrorNote>{trades.error}</ErrorNote>}
          {trades.data && !trades.data.length && <Empty title="No scalping paper trades yet" />}
          {trades.data && trades.data.length > 0 && (
            <div className="scroll-thin max-h-96 overflow-auto">
              <table className="w-full min-w-[900px] text-xs">
                <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900">
                  <tr><th className="py-1.5">Day</th><th>Mode</th><th>Configuration</th><th>Contract</th><th className="text-right">Qty</th><th className="text-right">BUY</th><th className="text-right">SELL</th><th>Exit</th><th className="text-right">Gross</th><th className="text-right">Costs</th><th className="text-right">Net</th></tr>
                </thead>
                <tbody>
                  {trades.data.map((t) => (
                    <tr key={t.id} onClick={() => setSel(t)} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60 ${sel?.id === t.id ? "bg-blue-50 dark:bg-blue-950/40" : ""}`}>
                      <td className="py-1">{dmy(t.day)}</td><td>{t.trade_mode}</td><td className="max-w-48 truncate">{t.scalp_config ?? t.strategy}</td>
                      <td>{num(t.strike, 0)} <Pill tone={t.opt_type === "CE" ? "good" : "bad"}>{t.opt_type}</Pill></td><td className="num text-right">{t.qty}</td>
                      <td className="num text-right">{hm(t.entry_ts)} ₹{num(t.entry_price)}</td>
                      <td className="num text-right">{t.exit_ts ? `${hm(t.exit_ts)} ₹${num(t.exit_price)}` : "open"}</td>
                      <td>{t.exit_reason ? REASON[t.exit_reason] ?? t.exit_reason : "—"}</td>
                      <td className={`num text-right ${pnlClass(t.gross)}`}>{t.gross != null ? inr(t.gross, true, 0) : "—"}</td>
                      <td className="num text-right text-orange-600">{t.charges?.total != null ? inr(t.charges.total + (t.slippage ?? 0), false, 0) : "—"}</td>
                      <td className={`num text-right font-semibold ${pnlClass(t.net)}`}>{t.net != null ? inr(t.net, true, 0) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {sel && (
            <div className="mt-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
              <div className="flex items-center justify-between gap-2"><div className="font-semibold">{sel.trading_symbol} · {sel.direction} · {dmy(sel.day)} · {sel.trade_mode}</div><Button onClick={() => setSel(null)}><X size={14} /></Button></div>
              <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Configuration" value={<span className="text-xs font-normal">{sel.scalp_config ?? "—"}</span>} />
                <Stat label="Signal bar close" value={dmyhm(sel.signal_ts)} />
                <Stat label="BUY" value={`₹${num(sel.entry_price)}`} sub={dmyhm(sel.entry_ts)} />
                <Stat label="SELL" value={sel.exit_price != null ? `₹${num(sel.exit_price)}` : "open"} sub={dmyhm(sel.exit_ts)} />
                <Stat label="Exit reason" value={sel.exit_reason ? REASON[sel.exit_reason] ?? sel.exit_reason : "open"} />
                <Stat label="Quantity" value={sel.qty} sub={sel.risk ? `${sel.risk.lots} lot(s) × ${sel.risk.lot_size}` : undefined} />
                <Stat label="Stop / target premium" value={`${num(sel.stop_premium)} / ${num(sel.target_premium)}`} />
                <Stat label="Gross" value={sel.gross != null ? inr(sel.gross, true) : "—"} className={pnlClass(sel.gross)} />
                <Stat label="Slippage" value={sel.slippage != null ? inr(sel.slippage) : "—"} className="text-orange-600" />
                <Stat label="Brokerage" value={sel.charges?.brokerage != null ? inr(sel.charges.brokerage) : "—"} className="text-orange-600" />
                <Stat label="Taxes & fees" value={sel.charges?.total != null ? inr(sel.charges.total - (sel.charges.brokerage ?? 0)) : "—"} className="text-orange-600" />
                <Stat label="Net" value={sel.net != null ? inr(sel.net, true) : "—"} className={pnlClass(sel.net)} />
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

type SortKey = "rank" | "net_pnl" | "oos_net" | "profit_factor" | "max_drawdown" | "win_rate" | "trades";

export default function Scalping() {
  const { settings } = useSettings();
  const dark = settings.theme === "dark";
  const res = useApi(getScalping, []);
  const [job, setJob] = useState<Job | null>(null);
  const [contract, setContract] = useState<"all" | "ATM_BUY" | "ITM5_BUY">("all");
  const [exitKind, setExitKind] = useState<"all" | "time" | "sl_target">("all");
  const [sort, setSort] = useState<SortKey>("rank");
  const [picked, setPicked] = useState<string | null>(null);
  const run = res.data?.data;

  useEffect(() => {
    const j = res.data?.job;
    if (j && typeof j === "object" && !job) waitForJob(j.id, setJob, 3000).then(() => { setJob(null); void res.reload(); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [res.data?.job]);

  async function start() {
    if (!window.confirm("Re-run the full five-year scalping analysis? It reads every stored option candle and takes several minutes.")) return;
    try {
      const r = await runScalping();
      const j = await waitForJob(String(r.job), setJob, 3000);
      setJob(null);
      if (j.state === "error") throw new Error(j.error ?? "Run failed");
      await res.reload();
    } catch (e) { setJob(null); alert((e as Error).message); }
  }

  const configs = run?.configs ?? [];
  const rank = useMemo(() => Object.fromEntries((run?.ranking ?? []).map((k, i) => [k, i + 1])), [run]);
  const rows = useMemo(() => configs
    .filter((c) => (contract === "all" || c.contract === contract) && (exitKind === "all" || c.exit_kind === exitKind))
    .sort((a, b) => {
      if (sort === "rank") return (rank[a.key] ?? 9999) - (rank[b.key] ?? 9999);
      if (sort === "max_drawdown") return a.max_drawdown - b.max_drawdown;
      return ((b[sort] as number) ?? -Infinity) - ((a[sort] as number) ?? -Infinity);
    }), [configs, contract, exitKind, sort, rank]);
  const featured = run?.best ?? run?.top_in_sample ?? configs[0]?.key ?? null;
  const selected = picked ?? featured;
  const best = configs.find((c) => c.key === run?.best);
  const top = configs.find((c) => c.key === run?.top_in_sample);
  const netPositive = configs.filter((c) => c.net_pnl > 0).length;
  const grossPositive = configs.filter((c) => c.gross_pnl > 0).length;
  const bestExisting = [...(run?.existing ?? [])].sort((a, b) => b.net_pnl - a.net_pnl).slice(0, 8);
  const strategies = [...new Map(configs.map((c) => [c.strategy, c.strategy_label])).entries()];
  const sumBy = (f: (c: ScalpConfig) => boolean, side: "ce" | "pe") => configs.filter(f).reduce((s, c) => s + c[side].net_pnl, 0);

  return (
    <div className="space-y-4">
      <PageHeader title="5-Minute Scalping" subtitle={run ? `${configs.length} configurations · ${dmy(run.start_date)} → ${dmy(run.end_date)} · completed 5-min NIFTY bars, real option premiums, all costs` : "EMA strategies on completed 5-minute bars, 5-minute holds, ATM and ITM 5 options"}
        actions={<Button onClick={start} disabled={!!job}><RefreshCw size={14} className={job ? "animate-spin" : ""} /> Run analysis</Button>} />
      {job && <Card><Progress value={job.progress} text={job.message} /></Card>}
      {res.error && <ErrorNote>{res.error}</ErrorNote>}
      {res.loading && !run ? <Loading /> : !run ? (
        <Empty title="No scalping analysis yet">Run the analysis. It uses the stored NIFTY and option 1-minute history (Data page).</Empty>
      ) : (
        <>
          <Card title="Verdict" icon={<Award size={16} className="text-blue-600" />} accent={run.consistent.length ? "gain" : "loss"}>
            <div className="space-y-2 text-sm">
              {run.consistent.length ? (
                <p><b className="text-gain">{run.consistent.length}</b> configuration(s) passed every consistency check after costs.</p>
              ) : (
                <p className="font-semibold text-loss">No configuration has shown consistent profitability after all costs. {netPositive} of {configs.length} are net positive; {grossPositive} were positive before costs.</p>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <Stat label="Best-performing (selection rule)" value={best ? label(best) : "None qualifies"} className={best ? "text-gain" : "text-loss"}
                  sub={best ? `net ${inrShort(best.net_pnl)} · out-of-sample ${inrShort(best.oos_net)}` : "no in-sample leader stayed positive out of sample"} />
                <Stat label="Top in-sample (before the test)" value={top ? <span className="text-sm">{label(top)}</span> : "—"}
                  sub={top ? `in-sample ${inrShort(top.in_sample?.net_pnl)} → out-of-sample ${inrShort(top.oos_net)}` : undefined} />
                <Stat label="Walk-forward total (year by year)" value={inrShort(run.walk_forward.total_oos)} className={pnlClass(run.walk_forward.total_oos)}
                  sub={`${run.walk_forward.rows.filter((r) => r.pick).length} of ${run.walk_forward.rows.length} years had a qualifying pick`} />
              </div>
              <p className="text-xs text-slate-500">{run.selection_rule}</p>
            </div>
          </Card>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card title="CE versus PE (net, all configurations)">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[360px] text-xs">
                  <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">Strategy</th><th className="text-right">CE net</th><th className="text-right">PE net</th></tr></thead>
                  <tbody>
                    {strategies.map(([s, l]) => {
                      const ce = sumBy((c) => c.strategy === s, "ce"), pe = sumBy((c) => c.strategy === s, "pe");
                      return <tr key={s} className="border-t border-slate-100 dark:border-slate-800"><td className="py-1">{l}</td><td className={`num text-right ${pnlClass(ce)}`}>{inrShort(ce)}</td><td className={`num text-right ${pnlClass(pe)}`}>{inrShort(pe)}</td></tr>;
                    })}
                  </tbody>
                </table>
              </div>
              <p className="mt-1 text-[11px] text-slate-500">Summed over every contract and exit rule of the strategy, 1 lot per trade.</p>
            </Card>
            <Card title="Walk-forward (choose on earlier years, test on the next)">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-xs">
                  <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">Year</th><th>Trained on</th><th>Pick</th><th className="text-right">That year</th></tr></thead>
                  <tbody>
                    {run.walk_forward.rows.map((r) => (
                      <tr key={r.year} className="border-t border-slate-100 dark:border-slate-800">
                        <td className="py-1">{r.year}</td><td>{r.trained_on}</td><td className="max-w-56 truncate">{r.pick_label ?? <span className="text-slate-500">none qualified: no trading</span>}</td>
                        <td className={`num text-right ${pnlClass(r.oos_net)}`}>{r.pick ? inrShort(r.oos_net) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          <Card title="All configurations" right="click a row for its full report">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Segmented value={contract} onChange={setContract} options={[{ value: "all", label: "All" }, { value: "ATM_BUY", label: "ATM" }, { value: "ITM5_BUY", label: "ITM 5" }]} />
              <Segmented value={exitKind} onChange={setExitKind} options={[{ value: "all", label: "All exits" }, { value: "time", label: "Fixed 5-min" }, { value: "sl_target", label: "SL / target" }]} />
              <select aria-label="Sort" className={selectInline} value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
                <option value="rank">Sort: in-sample rank</option><option value="net_pnl">Net P&L</option><option value="oos_net">Out-of-sample net</option>
                <option value="profit_factor">Profit factor</option><option value="max_drawdown">Smallest drawdown</option><option value="win_rate">Win rate</option><option value="trades">Trades</option>
              </select>
            </div>
            <div className="scroll-thin max-h-[30rem] overflow-auto">
              <table className="w-full min-w-[980px] text-xs">
                <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900">
                  <tr><th className="py-1.5">#</th><th>Strategy</th><th>Contract</th><th>Exit</th><th className="text-right">Trades</th><th className="text-right">Win</th><th className="text-right">Gross</th><th className="text-right">Brokerage</th><th className="text-right">Taxes</th><th className="text-right">Net</th><th className="text-right">PF</th><th className="text-right">Max DD</th><th className="text-right">Out-of-sample</th><th className="text-right">Years +</th></tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.key} onClick={() => setPicked(c.key)} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60 ${selected === c.key ? "bg-blue-50 dark:bg-blue-950/40" : ""}`}>
                      <td className="py-1">{rank[c.key] ?? "—"}</td><td>{c.strategy_label}</td><td>{c.contract === "ATM_BUY" ? "ATM" : "ITM 5"}</td><td>{c.exit_kind === "time" ? "5-min" : `SL ${c.stop}% / TP ${c.target}%`}</td>
                      <td className="num text-right">{c.trades}</td><td className="num text-right">{pct(c.win_rate, 0)}</td>
                      <td className={`num text-right ${pnlClass(c.gross_pnl)}`}>{inrShort(c.gross_pnl)}</td><td className="num text-right">{inrShort(c.brokerage ?? 0, false)}</td><td className="num text-right">{inrShort(c.taxes ?? 0, false)}</td>
                      <td className={`num text-right font-semibold ${pnlClass(c.net_pnl)}`}>{inrShort(c.net_pnl)}</td><td className="num text-right">{pf(c.profit_factor)}</td>
                      <td className="num text-right text-loss">{inrShort(-c.max_drawdown, false)}</td><td className={`num text-right ${pnlClass(c.oos_net)}`}>{inrShort(c.oos_net)}</td><td className="num text-right">{c.verdict.years_positive}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {selected && <ConfigDetail k={selected} dark={dark} />}

          <Card title="Against the existing strategies" right="Compare page results, 1 lot, same costs, held until the opposite cross">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-xs">
                <thead><tr className="text-left uppercase text-slate-500"><th className="py-1.5">Strategy</th><th>TF</th><th>Contract</th><th className="text-right">Trades</th><th className="text-right">Win</th><th className="text-right">Net</th><th className="text-right">PF</th><th className="text-right">Max DD</th><th className="text-right">Years +</th></tr></thead>
                <tbody>
                  {top && <tr className="bg-violet-50 dark:bg-violet-950/30"><td className="py-1 font-semibold">Scalp: {top.strategy_label} ({top.exit_label})</td><td>5m</td><td>{top.contract === "ATM_BUY" ? "ATM" : "ITM 5"}</td><td className="num text-right">{top.trades}</td><td className="num text-right">{pct(top.win_rate, 0)}</td><td className={`num text-right font-semibold ${pnlClass(top.net_pnl)}`}>{inrShort(top.net_pnl)}</td><td className="num text-right">{pf(top.profit_factor)}</td><td className="num text-right text-loss">{inrShort(-top.max_drawdown, false)}</td><td className="num text-right">{top.verdict.years_positive}</td></tr>}
                  {bestExisting.map((e) => (
                    <tr key={`${e.strategy}${e.timeframe}${e.contract}`} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="py-1">{e.label}</td><td>{e.timeframe}m</td><td>{e.contract === "ATM_BUY" ? "ATM" : "ITM 5"}</td><td className="num text-right">{e.trades}</td><td className="num text-right">{pct(e.win_rate, 0)}</td>
                      <td className={`num text-right font-semibold ${pnlClass(e.net_pnl)}`}>{inrShort(e.net_pnl)}</td><td className="num text-right">{pf(e.profit_factor)}</td><td className="num text-right text-loss">{inrShort(-e.max_drawdown, false)}</td><td className="num text-right">{e.years_positive}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-1 text-[11px] text-slate-500">The 8 best existing strategy × timeframe × contract results by net P&L ({run.existing.length} in total).</p>
          </Card>

          {selected && <PaperPanel configs={configs} selected={selected} consistent={run.consistent} />}
          <Limitation>Results are historical simulations with real option premiums, NSE lot sizes, slippage, brokerage and taxes. They do not promise future profits. Picking the best of {configs.length} configurations after the fact overstates what you would have earned; the out-of-sample and walk-forward figures are the honest tests.</Limitation>
        </>
      )}
    </div>
  );
}

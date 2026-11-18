// Start a tested configuration in paper or replay mode and review its trades. Paper and replay only.
import { useEffect, useState } from "react";
import { Play, Square, Timer, X } from "lucide-react";
import { useLive } from "../../context/LiveContext";
import { useApi } from "../../hooks/useApi";
import { getScalpPaperTrades, startScalpPaper, stopEngine } from "../../services/api";
import { Card, Pill, Stat } from "../../components/common/Card";
import { Button, Field, inputCls, Segmented } from "../../components/common/Controls";
import { Empty, ErrorNote, Limitation, Warning } from "../../components/common/States";
import { dmy, dmyhm, hm, inr, inrShort, num, pnlClass } from "../../utils/format";
import type { ScalpConfig, ScalpPaperTrade } from "../../types/api";
import { REASON, label } from "./shared";

export function PaperPanel({ configs, selected, consistent }: { configs: ScalpConfig[]; selected: string; consistent: string[] }) {
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

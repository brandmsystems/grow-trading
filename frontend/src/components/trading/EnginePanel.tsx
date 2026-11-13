import { useEffect, useState } from "react";
import { Play, Power, ShieldCheck, Square, XCircle } from "lucide-react";
import type { EngineConfig, Position } from "../../types/api";
import { confirmOrder, getMeta, rejectOrder, setPaperStop, squareOff, startEngine, stopEngine } from "../../services/api";
import { useSettings } from "../../context/SettingsContext";
import { useLive } from "../../context/LiveContext";
import { dmy, hm, inr, num, pnlClass, todayIST } from "../../utils/format";
import { Card, Pill, Stat } from "../common/Card";
import { Button, Field, inputCls, Segmented } from "../common/Controls";
import { PendingOrder } from "./PendingOrder";
import { PRESETS } from "./RiskManagement";

/** Paper position stop-loss: entry, stop, target, risk, and an editor (the backend refuses changes beyond the risk limits). */
function PaperStop({ p, busy, onSaved }: { p: Position; busy: boolean; onSaved: () => void }) {
  const [val, setVal] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function save() {
    const v = Number(val);
    if (!v) { setMsg({ ok: false, text: "Enter a stop-loss premium." }); return; }
    try {
      const r = await setPaperStop(v);
      setMsg({ ok: true, text: `Stop ${num(r.old_stop)} → ${num(r.new_stop)}; max loss ₹${num(r.old_max_loss, 0)} → ₹${num(r.new_max_loss, 0)}` });
      setVal(""); onSaved();
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
  }
  return (
    <div className="col-span-2 space-y-2 rounded-lg bg-orange-50 p-2 text-xs dark:bg-orange-950/30">
      <div className="grid grid-cols-3 gap-2">
        <Stat label="Entry premium" value={`₹${num(p.entry_price)}`} />
        <Stat label="Stop-loss" value={`₹${num(p.stop_premium)}`} className="text-loss" sub={p.nifty_stop != null ? `NIFTY ≈ ${num(p.nifty_stop, 0)}` : undefined} />
        <Stat label="Target" value={p.target_premium != null ? `₹${num(p.target_premium)}` : "—"} className="text-gain" sub={p.risk_reward ? `R:R 1 : ${num(p.risk_reward, 2)}` : undefined} />
        <Stat label="Max risk" value={p.max_loss != null ? `₹${num(p.max_loss, 0)}` : "—"} className="text-loss" sub={p.max_loss_pct != null ? `${num(p.max_loss_pct)}% of capital` : undefined} />
        <Stat label="Risk budget" value={p.risk_amount != null ? `₹${num(p.risk_amount, 0)}` : "—"} />
        <Stat label="Method" value={<span className="text-[11px] font-normal">{p.stop_method ?? "—"}</span>} />
      </div>
      <div className="flex gap-2">
        <input type="number" min={0.05} step={0.05} placeholder="New stop ₹" className={`${inputCls} max-w-32`} value={val} onChange={(e) => setVal(e.target.value)} />
        <Button onClick={save} disabled={busy}>Change stop</Button>
      </div>
      {msg && <p className={msg.ok ? "text-gain" : "text-red-600"}>{msg.text}</p>}
      <p className="text-slate-500">Exits automatically when the option premium reaches the stop (fresh prices only). Changes that would exceed the trade's risk amount or today's loss limit are refused.</p>
    </div>
  );
}

const STATE = { stopped: ["Stopped", "neutral"], waiting: ["Waiting for market", "info"], running: ["Running", "good"], halted: ["Halted", "warn"], error: ["ERROR: check positions", "bad"] } as const;

/** Engine settings and controls. Live mode keeps every safeguard; each live entry needs your confirmation by default. */
export function EnginePanel() {
  const { data, refresh } = useLive();
  const { settings, update } = useSettings();
  const [confirmText, setConfirmText] = useState("");
  const [replayDay, setReplayDay] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [strategies, setStrategies] = useState<Record<string, string>>({ ema_9_21: "EMA 9/21" });
  useEffect(() => { getMeta().then((m) => setStrategies(m.strategies)).catch(() => {}); }, []);
  if (!data) return null;

  const running = data.state !== "stopped";
  const cfg: EngineConfig = running && data.config ? data.config : settings.engine;
  const set = (p: Partial<EngineConfig>) => update({ engine: { ...settings.engine, ...p } });
  const [label, tone] = STATE[data.state] ?? STATE.stopped;
  const p = data.position;

  async function act(fn: () => Promise<unknown>, ask?: string) {
    if (ask && !window.confirm(ask)) return;
    setBusy(true); setErr(null);
    try { await fn(); refresh(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const start = () => act(
    () => startEngine({ ...settings.engine, timeframe: settings.timeframe }, confirmText, replayDay || undefined),
    cfg.trade_mode === "live" ? `Start LIVE trading with ${cfg.lots} lot(s)? ${cfg.order_confirmation === "manual" ? "You will confirm each order." : "Orders will be placed AUTOMATICALLY."}` : undefined,
  );

  return (
    <Card title="Trading Controls" icon={<Power size={16} className="text-blue-600" />} right={<Pill tone={tone}>{label}{running ? ` · ${cfg.trade_mode}` : ""}</Pill>}>
      <div className="space-y-3 text-sm">
        {data.pending_order && (
          <PendingOrder order={data.pending_order} now={data.feed?.now ?? new Date().toISOString()} busy={busy}
            onConfirm={() => act(() => confirmOrder(data.pending_order!.id))}
            onReject={() => act(() => rejectOrder(data.pending_order!.id))} />
        )}
        {p && (
          <div className="grid grid-cols-2 gap-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
            <Stat label="Open position" value={`${num(p.strike, 0)} ${p.opt_type}`} sub={`${p.side} · ${p.qty} qty`} />
            <Stat label="Entry → LTP" value={`₹${num(p.entry_price)} → ₹${num(p.ltp)}`} sub={`since ${hm(p.entry_ts)}`} />
            <Stat label="Open P&L" value={inr(p.mtm, true)} className={pnlClass(p.mtm)} />
            {p.stop_ref != null && <Stat label="NIFTY stop / target" value={`${num(p.stop_ref, 0)} / ${num(p.target_ref, 0)}`} />}
            {p.stop_premium != null && <PaperStop p={p} busy={busy} onSaved={refresh} />}
          </div>
        )}
        {data.halt_reason && <p className="rounded-lg bg-red-50 p-2 text-red-700 dark:bg-red-950/50 dark:text-red-400">{data.halt_reason}</p>}

        <fieldset disabled={running || busy} className="space-y-3 disabled:opacity-60">
          <Segmented value={cfg.trade_mode} onChange={(v) => set({ trade_mode: v })} size="md"
            options={[{ value: "paper", label: "Paper" }, { value: "live", label: "Live", tone: "danger" }, { value: "replay", label: "Replay" }]} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Option">
              <select className={inputCls} value={cfg.exec_mode} onChange={(e) => set({ exec_mode: e.target.value as EngineConfig["exec_mode"] })}>
                <option value="ATM_BUY">ATM buy</option><option value="ITM5_BUY">ITM 5 buy</option><option value="ATM_SELL">ATM sell</option>
              </select></Field>
            <Field label="Timeframe">
              <select className={inputCls} value={running ? cfg.timeframe : settings.timeframe} onChange={(e) => update({ timeframe: Number(e.target.value) })}>
                {[5, 15, 30].map((t) => <option key={t} value={t}>{t} min</option>)}
              </select></Field>
            <Field label="Signals">
              <select className={inputCls} value={cfg.signal_mode} onChange={(e) => set({ signal_mode: e.target.value as EngineConfig["signal_mode"] })}>
                <option value="cross">Every crossover</option><option value="trend">Whenever the trend agrees</option><option value="prediction">Prediction score</option>
              </select></Field>
            {cfg.signal_mode === "prediction" ? (
              <Field label="Min score">
                <input type="number" min={0} max={100} step={5} className={inputCls} value={cfg.min_score} onChange={(e) => set({ min_score: Number(e.target.value) })} />
              </Field>
            ) : cfg.trade_mode !== "paper" ? (
              <Field label="Lots">
                <input type="number" min={1} className={inputCls} value={cfg.lots} onChange={(e) => set({ lots: Math.max(1, Number(e.target.value)) })} />
              </Field>
            ) : <div />}
            {cfg.trade_mode === "paper" && (
              <div className="col-span-2 space-y-2 rounded-xl border border-orange-300 p-3 dark:border-orange-900">
                <div className="text-xs font-semibold uppercase text-orange-600">Risk per trade (lots are calculated)</div>
                <Segmented value={PRESETS.find((x) => x.pct === cfg.risk_pct)?.key ?? "custom"}
                  onChange={(v) => { const pr = PRESETS.find((x) => x.key === v); if (pr) set({ risk_pct: pr.pct }); }}
                  options={[...PRESETS.map((x) => ({ value: x.key, label: `${x.pct}%` })), { value: "custom", label: "Custom" }]} />
                <div className="grid grid-cols-2 gap-2">
                  <Field label="Risk per trade %"><input type="number" min={0.05} max={100} step={0.05} className={inputCls} value={cfg.risk_pct} onChange={(e) => set({ risk_pct: Number(e.target.value) })} /></Field>
                  <Field label="Daily risk %"><input type="number" min={0} max={100} step={0.5} className={inputCls} value={cfg.daily_risk_pct} onChange={(e) => set({ daily_risk_pct: Number(e.target.value) })} /></Field>
                  <Field label="Max lots / trade"><input type="number" min={1} className={inputCls} value={cfg.max_lots} onChange={(e) => set({ max_lots: Math.max(1, Number(e.target.value)) })} /></Field>
                  <Field label="Max open positions"><input type="number" min={1} max={1} className={inputCls} value={cfg.max_open_positions} onChange={(e) => set({ max_open_positions: Math.max(1, Number(e.target.value)) })} /></Field>
                  <Field label="Keep at least ₹"><input type="number" min={0} step={5000} className={inputCls} value={cfg.min_balance} onChange={(e) => set({ min_balance: Math.max(0, Number(e.target.value)) })} /></Field>
                  <Field label="Stop-loss">
                    <select className={inputCls} value={cfg.stop_mode} onChange={(e) => set({ stop_mode: e.target.value as EngineConfig["stop_mode"] })}>
                      <option value="atr">ATR × delta</option><option value="pct">% of premium</option><option value="points">Fixed premium points</option></select></Field>
                  {cfg.stop_mode === "atr"
                    ? <Field label="ATR multiple"><input type="number" min={0.25} step={0.25} className={inputCls} value={cfg.stop_atr} onChange={(e) => set({ stop_atr: Number(e.target.value) })} /></Field>
                    : cfg.stop_mode === "pct"
                    ? <Field label="Stop % below premium"><input type="number" min={1} max={99} className={inputCls} value={cfg.stop_pct} onChange={(e) => set({ stop_pct: Number(e.target.value) })} /></Field>
                    : <Field label="Stop ₹ below premium"><input type="number" min={0.5} step={0.5} className={inputCls} value={cfg.stop_points ?? 20} onChange={(e) => set({ stop_points: Number(e.target.value) })} /></Field>}
                </div>
                <p className="text-[11px] text-slate-500">Paper trades exit when the option premium reaches the stop-loss. The engine holds one position at a time.</p>
              </div>
            )}
            {cfg.signal_mode === "prediction" && (
              <Field label="Strategy" className="col-span-2">
                <select className={inputCls} value={cfg.strategy} onChange={(e) => set({ strategy: e.target.value })}>
                  {Object.entries(strategies).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select></Field>
            )}
            <Field label="Max daily loss ₹">
              <input type="number" min={0} step={500} className={inputCls} value={cfg.max_daily_loss} onChange={(e) => set({ max_daily_loss: Number(e.target.value) })} /></Field>
            <Field label="Max trades / day">
              <input type="number" min={1} className={inputCls} value={cfg.max_trades_per_day} onChange={(e) => set({ max_trades_per_day: Number(e.target.value) })} /></Field>
            {cfg.trade_mode === "replay" && (
              <Field label="Replay day" className="col-span-2">
                <input type="date" className={inputCls} value={replayDay} onChange={(e) => setReplayDay(e.target.value)} /></Field>
            )}
          </div>
          {cfg.trade_mode === "live" && (
            <div className="space-y-2 rounded-xl border border-red-400 bg-red-50 p-3 text-xs dark:bg-red-950/40">
              <p><b>Real money.</b> MIS market orders on your Groww account, capped at {data.live_max_lots} lot(s). Keep the app running until 15:00.</p>
              <p className="flex items-center gap-1.5 font-semibold text-green-700 dark:text-green-400">
                <ShieldCheck size={14} />{cfg.order_confirmation === "manual" ? "Manual confirmation ON: you approve every entry order." : "Automatic entries ON"}
              </p>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={cfg.order_confirmation === "auto"} onChange={(e) => set({ order_confirmation: e.target.checked ? "auto" : "manual" })} />
                Place entry orders automatically (not recommended)
              </label>
              <Field label={<>Type <b>{data.confirm_phrase}</b> to start</>}>
                <input className={inputCls} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} autoComplete="off" /></Field>
            </div>
          )}
        </fieldset>

        {err && <p className="text-sm text-red-600">{err}</p>}
        <div className="flex flex-wrap gap-2">
          {!running ? (
            <Button variant={cfg.trade_mode === "live" ? "danger" : "primary"} onClick={start} disabled={busy} className="min-h-11 flex-1">
              <Play size={16} /> Start {cfg.trade_mode === "live" ? "LIVE trading" : cfg.trade_mode === "replay" ? "replay" : "paper trading"}
            </Button>
          ) : (
            <>
              <Button onClick={() => act(squareOff, "Square off the open position now? The engine keeps running.")} disabled={busy || !p} className="min-h-11 flex-1">
                <XCircle size={16} /> Square off
              </Button>
              <Button variant="danger" onClick={() => act(stopEngine, "Stop the engine? Any open position is squared off first.")} disabled={busy} className="min-h-11 flex-1">
                <Square size={16} /> Stop
              </Button>
            </>
          )}
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {cfg.trade_mode === "paper" ? "Paper: live Groww prices, simulated fills with slippage and charges. No orders are sent."
            : cfg.trade_mode === "replay" ? "Replay: a stored trading day on a fast clock with simulated fills."
            : cfg.order_confirmation === "manual" ? "Each entry waits for your confirmation; protective exits (stop, square-off, 15:00) are automatic."
            : "Automatic: entries are placed without asking."}
          {" "}{data.day && data.day !== todayIST() ? `Session ${dmy(data.day)}` : "Today"}: {data.trades_today} trade(s), realised <span className={pnlClass(data.realised_today)}>{inr(data.realised_today, true)}</span>.
        </p>
      </div>
    </Card>
  );
}

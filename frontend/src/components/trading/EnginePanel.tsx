import { useEffect, useState } from "react";
import { Play, Power, ShieldCheck, Square, XCircle } from "lucide-react";
import type { EngineConfig } from "../../types/api";
import { confirmOrder, getMeta, rejectOrder, squareOff, startEngine, stopEngine } from "../../services/api";
import { useSettings } from "../../context/SettingsContext";
import { useLive } from "../../context/LiveContext";
import { dmy, hm, inr, num, pnlClass, todayIST } from "../../utils/format";
import { Card, Pill, Stat } from "../common/Card";
import { Button, Field, inputCls, Segmented } from "../common/Controls";
import { PendingOrder } from "./PendingOrder";

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
                <option value="cross">Every crossover</option><option value="prediction">Prediction score</option>
              </select></Field>
            {cfg.signal_mode === "prediction" ? (
              <Field label="Min score">
                <input type="number" min={0} max={100} step={5} className={inputCls} value={cfg.min_score} onChange={(e) => set({ min_score: Number(e.target.value) })} />
              </Field>
            ) : (
              <Field label="Lots">
                <input type="number" min={1} className={inputCls} value={cfg.lots} onChange={(e) => set({ lots: Math.max(1, Number(e.target.value)) })} />
              </Field>
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

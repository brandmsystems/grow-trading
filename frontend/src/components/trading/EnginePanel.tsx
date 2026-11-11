import { useEffect, useState } from "react";
import { Play, Square, XCircle } from "lucide-react";
import type { Dashboard, EngineConfig } from "../../types/api";
import { confirmOrder, getMeta, rejectOrder, squareOff, startEngine, stopEngine } from "../../services/api";
import { useSettings } from "../../context/SettingsContext";
import { hm, inr, num, pnlClass } from "../../utils/format";
import { Card, Stat } from "../common/Card";
import { PendingOrder } from "./PendingOrder";

const field = "w-full rounded-md border border-slate-300 bg-transparent px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900";

/** Engine settings and controls. Live mode keeps every existing safeguard and adds per-order confirmation. */
export function EnginePanel({ data, onChange }: { data: Dashboard; onChange: () => void }) {
  const { settings, update } = useSettings();
  const running = data.state !== "stopped";
  const cfg: EngineConfig = running && data.config ? data.config : settings.engine;
  const set = (p: Partial<EngineConfig>) => update({ engine: { ...settings.engine, ...p } });
  const [confirmText, setConfirmText] = useState("");
  const [replayDay, setReplayDay] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [strategies, setStrategies] = useState<Record<string, string>>({ ema_9_21: "EMA 9/21" });
  useEffect(() => { getMeta().then((m) => setStrategies(m.strategies)).catch(() => {}); }, []);

  async function act(fn: () => Promise<unknown>, ask?: string) {
    if (ask && !window.confirm(ask)) return;
    setBusy(true); setErr(null);
    try { await fn(); onChange(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  const start = () => act(
    () => startEngine({ ...settings.engine, timeframe: settings.timeframe }, confirmText, replayDay || undefined),
    cfg.trade_mode === "live" ? `Start LIVE trading with ${cfg.lots} lot(s)? ${cfg.order_confirmation === "manual" ? "You will confirm each order." : "Orders will be placed AUTOMATICALLY."}` : undefined,
  );
  const p = data.position;

  return (
    <Card title="Trading engine" right={running ? `${cfg.trade_mode} · ${cfg.timeframe}-minute` : "stopped"}>
      <div className="space-y-3 p-4 text-sm">
        {data.pending_order && (
          <PendingOrder order={data.pending_order} now={data.feed?.now ?? new Date().toISOString()} busy={busy}
            onConfirm={() => act(() => confirmOrder(data.pending_order!.id))}
            onReject={() => act(() => rejectOrder(data.pending_order!.id))} />
        )}
        {p && (
          <div className="grid grid-cols-2 gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-800">
            <Stat label="Position" value={`${num(p.strike, 0)} ${p.opt_type}`} sub={`${p.side} · ${p.qty} qty`} />
            <Stat label="Entry" value={`₹${num(p.entry_price)}`} sub={hm(p.entry_ts)} />
            <Stat label="LTP" value={`₹${num(p.ltp)}`} />
            <Stat label="Open P&L" value={inr(p.mtm, true)} className={pnlClass(p.mtm)} />
          </div>
        )}
        {data.halt_reason && <p className="rounded-md bg-red-50 p-2 text-red-700 dark:bg-red-950/50 dark:text-red-400">{data.halt_reason}</p>}

        <fieldset disabled={running || busy} className="grid grid-cols-2 gap-3 disabled:opacity-60">
          <label className="col-span-2 flex flex-col gap-1">Mode
            <div className="grid grid-cols-3 overflow-hidden rounded-md border border-slate-300 dark:border-slate-700">
              {(["paper", "live", "replay"] as const).map((m) => (
                <button key={m} type="button" onClick={() => set({ trade_mode: m })}
                  className={`py-1.5 capitalize ${cfg.trade_mode === m ? (m === "live" ? "bg-red-600 text-white" : "bg-blue-600 text-white") : ""}`}>{m}</button>
              ))}
            </div>
          </label>
          <label className="flex flex-col gap-1">Option
            <select className={field} value={cfg.exec_mode} onChange={(e) => set({ exec_mode: e.target.value as EngineConfig["exec_mode"] })}>
              <option value="ATM_BUY">ATM buy</option><option value="ITM5_BUY">ITM 5 buy</option><option value="ATM_SELL">ATM sell</option>
            </select></label>
          <label className="flex flex-col gap-1">Timeframe
            <select className={field} value={running ? cfg.timeframe : settings.timeframe} onChange={(e) => update({ timeframe: Number(e.target.value) })}>
              {[5, 15, 30].map((t) => <option key={t} value={t}>{t} min</option>)}
            </select></label>
          <label className="flex flex-col gap-1">Signals
            <select className={field} value={cfg.signal_mode} onChange={(e) => set({ signal_mode: e.target.value as EngineConfig["signal_mode"] })}>
              <option value="cross">Every crossover</option><option value="prediction">Prediction score</option>
            </select></label>
          {cfg.signal_mode === "prediction" ? (
            <label className="flex flex-col gap-1">Min score
              <input type="number" min={0} max={100} step={5} className={field} value={cfg.min_score} onChange={(e) => set({ min_score: Number(e.target.value) })} />
            </label>
          ) : (
            <label className="flex flex-col gap-1">Lots
              <input type="number" min={1} className={field} value={cfg.lots} onChange={(e) => set({ lots: Math.max(1, Number(e.target.value)) })} />
            </label>
          )}
          {cfg.signal_mode === "prediction" && (
            <label className="col-span-2 flex flex-col gap-1">Strategy
              <select className={field} value={cfg.strategy} onChange={(e) => set({ strategy: e.target.value })}>
                {Object.entries(strategies).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
          )}
          <label className="flex flex-col gap-1">Max daily loss ₹
            <input type="number" min={0} step={500} className={field} value={cfg.max_daily_loss} onChange={(e) => set({ max_daily_loss: Number(e.target.value) })} /></label>
          <label className="flex flex-col gap-1">Max trades / day
            <input type="number" min={1} className={field} value={cfg.max_trades_per_day} onChange={(e) => set({ max_trades_per_day: Number(e.target.value) })} /></label>

          {cfg.trade_mode === "replay" && (
            <label className="col-span-2 flex flex-col gap-1">Replay day
              <input type="date" className={field} value={replayDay} onChange={(e) => setReplayDay(e.target.value)} /></label>
          )}
          {cfg.trade_mode === "live" && (
            <div className="col-span-2 space-y-2 rounded-lg border border-red-500 bg-red-50 p-3 text-xs dark:bg-red-950/40">
              <p><b>Real money.</b> MIS market orders on your Groww account, capped at {data.live_max_lots} lot(s). Keep this app running until 15:00.</p>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={cfg.order_confirmation === "auto"}
                  onChange={(e) => set({ order_confirmation: e.target.checked ? "auto" : "manual" })} />
                Place entry orders automatically (off = I confirm each order)
              </label>
              <label className="flex flex-col gap-1">Type <b>{data.confirm_phrase}</b> to start
                <input className={field} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} autoComplete="off" /></label>
            </div>
          )}
        </fieldset>

        {err && <p className="text-sm text-red-600">{err}</p>}
        <div className="flex flex-wrap gap-2">
          {!running ? (
            <button onClick={start} disabled={busy}
              className={`flex items-center gap-1.5 rounded-lg px-4 py-2 font-semibold text-white disabled:opacity-50 ${cfg.trade_mode === "live" ? "bg-red-600 hover:bg-red-700" : "bg-blue-600 hover:bg-blue-700"}`}>
              <Play size={16} /> Start {cfg.trade_mode === "live" ? "LIVE" : cfg.trade_mode}
            </button>
          ) : (
            <>
              <button onClick={() => act(squareOff, "Square off the open position now? The engine keeps running.")} disabled={busy || !p}
                className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-4 py-2 hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800">
                <XCircle size={16} /> Square off
              </button>
              <button onClick={() => act(stopEngine, "Stop the engine? Any open position is squared off first.")} disabled={busy}
                className="flex items-center gap-1.5 rounded-lg border border-red-500 px-4 py-2 text-red-600 hover:bg-red-50 disabled:opacity-50 dark:hover:bg-red-950/40">
                <Square size={16} /> Stop
              </button>
            </>
          )}
        </div>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {cfg.trade_mode === "paper" ? "Paper: live Groww prices, simulated fills with slippage and charges. No orders are sent."
            : cfg.trade_mode === "replay" ? "Replay: a stored trading day on a fast clock with simulated fills."
            : cfg.order_confirmation === "manual" ? "Each entry waits for your confirmation; protective exits (stop, square-off, 15:00) are automatic." : "Automatic: entries are placed without asking."}
          {" "}Today: {data.trades_today} trade(s), realised <span className={pnlClass(data.realised_today)}>{inr(data.realised_today, true)}</span>.
          {data.feed?.ema && <> EMA gap {num(data.feed.ema.gap)}.</>}
        </p>
      </div>
    </Card>
  );
}

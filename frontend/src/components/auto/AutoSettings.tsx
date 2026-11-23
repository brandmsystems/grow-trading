import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import type { BiasSettings } from "../../types/api";
import { Card } from "../common/Card";
import { Button, Field, inputCls } from "../common/Controls";
import { Warning } from "../common/States";

type NumKey = { [K in keyof BiasSettings]-?: BiasSettings[K] extends number ? K : never }[keyof BiasSettings];

/** A number box that can be typed into key by key; a valid number is passed up as soon as it parses. */
export function Num({ label, k, s, set, step = 1, min = 0, max, unit }: {
  label: string; k: NumKey; s: BiasSettings; set: (p: Partial<BiasSettings>) => void; step?: number; min?: number; max?: number; unit?: string;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <Field label={unit ? `${label} (${unit})` : label}>
      <input type="number" className={inputCls} step={step} min={min} max={max} value={draft ?? s[k]} aria-label={label}
        onChange={(e) => { setDraft(e.target.value); const v = e.target.valueAsNumber; if (Number.isFinite(v)) set({ [k]: v } as Partial<BiasSettings>); }}
        onBlur={() => setDraft(null)} />
    </Field>
  );
}

export function Check({ label, on, onChange, hint }: { label: string; on: boolean; onChange: (v: boolean) => void; hint?: string }) {
  return (
    <label className="flex items-start gap-2 text-sm" title={hint}>
      <input type="checkbox" className="mt-1" checked={on} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

export const toggle = (list: string[], k: string, on: boolean) => (on ? [...new Set([...list, k])] : list.filter((x) => x !== k));
const H = ({ children }: { children: string }) => <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500 first:mt-0">{children}</h3>;

/** Every setting of the automated engine. While it runs, Apply changes the live engine at once (no restart). */
export function AutoSettings({ s, set, indicators, running, onApply, busy, msg }: {
  s: BiasSettings; set: (p: Partial<BiasSettings>) => void; indicators: { key: string; label: string }[];
  running: boolean; onApply: () => void; busy: boolean; msg: { ok: boolean; text: string } | null;
}) {
  const sells = s.bias_allow.some((k) => k.startsWith("SELL"));
  return (
    <Card title="Settings" icon={<SlidersHorizontal size={16} className="text-slate-600" />}
      right={running ? "applied to the running engine without a restart" : "used when you start the engine"}>
      <H>Analysis</H>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Analysis interval">
          <select className={inputCls} value={s.timeframe} disabled={running} aria-label="Analysis interval" title={running ? "Applies from the next start" : undefined}
            onChange={(e) => { const tf = Number(e.target.value); set({ timeframe: tf, bias_confirm_tf: s.bias_confirm_tf <= tf ? tf * 2 : s.bias_confirm_tf }); }}>
            <option value={5}>5 minutes</option><option value={15}>15 minutes</option></select></Field>
        <Field label="Confirmation timeframe">
          <select className={inputCls} value={s.bias_confirm_tf} aria-label="Confirmation timeframe" onChange={(e) => set({ bias_confirm_tf: Number(e.target.value) })}>
            {[15, 30, 60].filter((m) => m > s.timeframe).map((m) => <option key={m} value={m}>{m} minutes</option>)}</select></Field>
        <Num label="Minimum confidence" unit="%" k="bias_min_confidence" s={s} set={set} step={1} max={100} />
        <Num label="15m trend needs" unit="± score" k="bias_trend_thr" s={s} set={set} step={0.05} max={1} />
        <Num label="5m confirmation needs" unit="± score" k="bias_confirm_thr" s={s} set={set} step={0.05} max={1} />
        <Num label="Minimum 5m ATR" unit="% of price" k="bias_min_atr_pct" s={s} set={set} step={0.01} max={5} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3 lg:grid-cols-4">
        {indicators.map((i) => <Check key={i.key} label={i.label} on={s.bias_indicators.includes(i.key)}
          onChange={(v) => set({ bias_indicators: toggle(s.bias_indicators, i.key, v) })} />)}
      </div>

      <H>Instruments</H>
      <div className="flex flex-wrap gap-x-5 gap-y-1.5">
        {([["BUY_CE", "Buy CE"], ["BUY_PE", "Buy PE"], ["SELL_CE", "Sell (write) CE"], ["SELL_PE", "Sell (write) PE"]] as const).map(([k, l]) => (
          <Check key={k} label={l} on={s.bias_allow.includes(k)} onChange={(v) => set({ bias_allow: toggle(s.bias_allow, k, v) })} />))}
      </div>
      {sells && <div className="mt-2"><Warning>Writing options can lose many times what buying risks. In paper trading it uses the separate, smaller risk % below and a stop above the premium.</Warning></div>}
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Contract when buying">
          <select className={inputCls} value={s.exec_mode === "ITM5_BUY" ? "ITM5_BUY" : "ATM_BUY"} onChange={(e) => set({ exec_mode: e.target.value as BiasSettings["exec_mode"] })} aria-label="Contract when buying">
            <option value="ATM_BUY">ATM</option><option value="ITM5_BUY">Deep ITM (5 strikes)</option></select></Field>
        <Field label="Entry window from"><input type="time" className={inputCls} value={s.entry_start} onChange={(e) => set({ entry_start: e.target.value })} aria-label="Entry window start" /></Field>
        <Field label="Entry window until"><input type="time" className={inputCls} value={s.cutoff} onChange={(e) => set({ cutoff: e.target.value })} aria-label="Entry window end" /></Field>
        <Num label="Maximum trades a day" k="max_trades_per_day" s={s} set={set} min={1} max={200} />
      </div>

      <H>Risk</H>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Num label="Risk per trade (buying)" unit="% of capital" k="risk_pct" s={s} set={set} step={0.1} min={0.1} max={100} />
        <Num label="Risk per trade (writing)" unit="% of capital" k="sell_risk_pct" s={s} set={set} step={0.1} min={0.1} max={100} />
        <Num label="Daily loss limit" unit="% of capital" k="daily_risk_pct" s={s} set={set} step={0.5} max={100} />
        <Num label="Maximum lots" k="max_lots" s={s} set={set} min={1} />
      </div>

      <H>Stop-loss, target and exits</H>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Field label="Stop-loss method">
          <select className={inputCls} value={s.stop_mode} onChange={(e) => set({ stop_mode: e.target.value as BiasSettings["stop_mode"] })} aria-label="Stop-loss method">
            <option value="atr">NIFTY ATR × delta</option><option value="pct">% of premium</option><option value="points">Premium points</option></select></Field>
        {s.stop_mode === "atr" && <Num label="Stop ATR multiple" k="stop_atr" s={s} set={set} step={0.1} min={0.1} />}
        {s.stop_mode === "pct" && <Num label="Stop-loss" unit="% of premium" k="stop_pct" s={s} set={set} step={1} min={1} max={99} />}
        {s.stop_mode === "points" && <Num label="Stop-loss" unit="premium points" k="stop_points" s={s} set={set} step={1} min={1} />}
        <Num label="Target" unit="× stop distance" k="target_rr" s={s} set={set} step={0.1} min={0.1} />
        <Num label="Trailing stop" unit="% from best, 0 = off" k="trail_pct" s={s} set={set} step={1} max={99} />
        <Num label="Trail starts after" unit="% in profit" k="trail_activate_pct" s={s} set={set} step={1} />
        <Num label="Time exit after" unit="minutes, 0 = off" k="bias_max_hold_min" s={s} set={set} step={5} max={375} />
        <Num label="Cool-down after an exit" unit="candles" k="bias_cooldown_bars" s={s} set={set} max={20} />
      </div>
      <div className="mt-2"><Check label="Exit when the analysis turns into an opposite entry signal (never reverses on the same candle)" on={s.bias_exit_opposite} onChange={(v) => set({ bias_exit_opposite: v })} /></div>

      <H>Contract checks (a value that is not available is skipped, not guessed)</H>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Num label="Minimum premium" unit="₹" k="min_premium" s={s} set={set} step={0.5} />
        <Num label="Minimum open interest" unit="0 = off" k="min_oi" s={s} set={set} step={1000} />
        <Num label="Maximum bid-ask spread" unit="%, 0 = off" k="max_spread_pct" s={s} set={set} step={0.5} max={100} />
        <Num label="Minimum |delta| when buying" unit="0 = off" k="min_delta" s={s} set={set} step={0.05} max={1} />
        <Field label="Pre-market bias">
          <select className={inputCls} value={s.premarket_mode ?? "log"} aria-label="Pre-market bias" onChange={(e) => set({ premarket_mode: e.target.value as NonNullable<BiasSettings["premarket_mode"]> })}>
            <option value="log">Log whether it agreed</option><option value="block_opposed">Skip trades against it</option><option value="off">Ignore</option></select></Field>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={onApply} disabled={busy}>{running ? "Apply to running engine" : "Save for next start"}</Button>
        {msg && <span role="status" className={`text-xs ${msg.ok ? "text-gain" : "text-red-600"}`}>{msg.text}</span>}
      </div>
    </Card>
  );
}

import { ChevronDown, ClipboardList, Shapes } from "lucide-react";
import type { CandlePattern, TradingPlan as Plan } from "../../types/api";
import { hm, num } from "../../utils/format";
import { Card, Pill, Stat } from "../common/Card";

const BIAS = { bullish: ["Bullish bias", "good"], bearish: ["Bearish bias", "bad"], none: ["No preferred direction", "neutral"] } as const;

/** Today's trading plan from the backend (insight.trading_plan): calculated levels and the three scenarios. */
export function TradingPlanCard({ plan }: { plan: Plan | null | undefined }) {
  if (!plan) return null;
  const [label, tone] = BIAS[plan.preferred] ?? BIAS.none;
  const last = plan.changes[plan.changes.length - 1];
  return (
    <Card title="Today's Trading Plan" icon={<ClipboardList size={16} className="text-violet-600" />}
      right={<Pill tone={tone}>{label}</Pill>}>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        <Stat label="Prev close" value={num(plan.prev_close)} className="text-sm" />
        <Stat label="Open" value={num(plan.open)} className="text-sm" />
        <Stat label="High" value={num(plan.high)} className="text-sm text-gain" />
        <Stat label="Low" value={num(plan.low)} className="text-sm text-loss" />
        <Stat label="Bullish level" value={num(plan.bullish_level)} className="text-sm text-gain" sub={plan.opening_range ? "opening range high" : "previous day high"} />
        <Stat label="Bearish level" value={num(plan.bearish_level)} className="text-sm text-loss" sub={plan.opening_range ? "opening range low" : "previous day low"} />
      </div>
      <div className="mt-2 grid grid-cols-1 gap-x-4 gap-y-0.5 text-xs text-slate-600 sm:grid-cols-2 dark:text-slate-300">
        <span><b>Trend:</b> {plan.trend} (daily regime)</span>
        <span><b>EMA 9/21:</b> {plan.ema_direction ?? "—"}</span>
        <span><b>VWAP:</b> {plan.vwap_position ?? "futures VWAP unavailable"}</span>
        <span><b>RSI:</b> {plan.rsi ?? "—"}</span>
        <span className="sm:col-span-2"><b>Volatility:</b> {plan.volatility ?? "—"}</span>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-3">
        {plan.scenarios.map((s) => (
          <details key={s.key} open={s.active} className={`rounded-xl border p-2 text-xs ${s.active ? (s.key === "bullish" ? "border-green-400 bg-green-50 dark:bg-green-950/30" : s.key === "bearish" ? "border-red-400 bg-red-50 dark:bg-red-950/30" : "border-slate-400 bg-slate-50 dark:bg-slate-800/50") : "border-slate-200 dark:border-slate-800"}`}>
            <summary className="cursor-pointer font-semibold">{s.title}{s.active ? " · current" : ""}</summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-slate-600 dark:text-slate-300">{s.conditions.map((c) => <li key={c}>{c}</li>)}</ul>
          </details>
        ))}
      </div>
      <details className="group mt-2 text-xs">
        <summary className="flex cursor-pointer list-none items-center gap-1 font-semibold text-blue-600">Support & resistance and plan history <ChevronDown size={14} className="transition group-open:rotate-180" /></summary>
        <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-2">
          <table className="w-full">
            <tbody>
              {plan.levels.map((l) => (
                <tr key={l.name} className="border-t border-slate-100 dark:border-slate-800" title={l.source}>
                  <td className="py-1">{l.name}</td>
                  <td className={l.kind === "resistance" ? "text-loss" : l.kind === "support" ? "text-gain" : "text-violet-600"}>{l.kind}</td>
                  <td className="num text-right font-semibold">{num(l.price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="space-y-1">
            {plan.changes.slice().reverse().map((c) => <li key={c.ts + c.reason}><span className="num font-semibold">{hm(c.ts)}</span> · {c.reason}</li>)}
          </ul>
        </div>
        <p className="mt-2 text-slate-500">{plan.entry_rule} {plan.note}</p>
      </details>
      <p className="mt-2 text-[11px] text-slate-500">Plan from the bar closing {hm(plan.bar_close)} · created {hm(plan.created_at)}{last ? ` · last change ${hm(last.ts)}: ${last.reason}` : ""}</p>
    </Card>
  );
}

const PB = { bullish: "good", bearish: "bad", neutral: "neutral" } as const;

/** Candle patterns on closed bars (patterns.detect), with confirmation and effect on the current signal. */
export function PatternsCard({ items }: { items: CandlePattern[] | undefined }) {
  if (!items) return null;
  const shown = items.filter((p) => p.bias !== "neutral").slice(-6).reverse();
  const doji = items.filter((p) => p.bias === "neutral").length;
  return (
    <Card title="Candle Patterns" icon={<Shapes size={16} className="text-orange-600" />} right={<span className="text-xs text-slate-500">closed candles only</span>}>
      {!items.length ? <p className="text-sm text-slate-500">No patterns on today's closed candles yet.</p> : (
        <div className="space-y-1.5">
          {shown.map((p) => (
            <details key={p.name + p.ts} className="rounded-lg border border-slate-200 px-2 py-1.5 text-xs dark:border-slate-800">
              <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
                <Pill tone={PB[p.bias]}>{p.bias}</Pill><b>{p.name}</b><span className="num text-slate-500">{hm(p.ts)}</span>
                <span className={p.status === "confirmed" ? "text-gain" : p.status === "not confirmed" ? "text-loss" : "text-orange-600"}>{p.status}</span>
              </summary>
              <div className="mt-1 space-y-0.5 text-slate-600 dark:text-slate-300">
                <div className="num">O {num(p.o)} · H {num(p.h)} · L {num(p.l)} · C {num(p.c)}</div>
                <div>{p.why}</div>
                <div>Confirmation: {Object.entries(p.confirmation).map(([k, v]) => `${k.toUpperCase()} ${v}`).join(" · ") || "—"}</div>
                <div className="font-semibold">{p.effect}</div>
              </div>
            </details>
          ))}
          {doji > 0 && <p className="text-[11px] text-slate-500">{doji} doji (indecision) today, not listed.</p>}
        </div>
      )}
      <p className="mt-2 text-[11px] text-slate-500">Patterns are context, not trading signals; they never change the strategy's BUY CE / BUY PE / HOLD.</p>
    </Card>
  );
}

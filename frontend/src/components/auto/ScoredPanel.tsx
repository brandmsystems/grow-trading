import { ListChecks } from "lucide-react";
import type { BiasAnalysis, BiasSettings, RejectedSignal } from "../../types/api";
import { hm, num } from "../../utils/format";
import { Card, Pill } from "../common/Card";
import { Button, Field, inputCls } from "../common/Controls";
import { Num } from "./AutoSettings";

/** The scored strategy (market structure + EMA + VWAP + FVG + ADR, points out of 100): its settings, what each component earned and
 *  why, every gate, the near-miss signals that were refused, and the risk preset. Paper and replay only. */
export function ScoredPanel({ a, s, set, running, onApply, busy, msg, periods = [5, 10, 20], preset, rejected = [] }: {
  a: BiasAnalysis | null; s: BiasSettings; set: (p: Partial<BiasSettings>) => void; running: boolean; onApply: () => void; busy: boolean;
  msg: { ok: boolean; text: string } | null; periods?: number[]; preset?: Partial<BiasSettings>; rejected?: RejectedSignal[];
}) {
  const c = a?.scored ?? null;
  const decided = a?.strategy === "scored";
  return (
    <Card title="Scored strategy: market structure + EMA + VWAP + FVG + ADR" icon={<ListChecks size={16} className="text-violet-600" />} accent="strat"
      right={decided ? "active entry strategy · paper only" : "preview · applies when the engine uses it"}>
      <div className="space-y-3" data-testid="scored">
        <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-4">
          <Num label="Minimum score" unit="of 100" k="sc_min_score" s={s} set={set} step={5} max={100} />
          <Field label="ADR period">
            <select className={inputCls} value={s.sc_adr_period} aria-label="Scored ADR period" onChange={(e) => set({ sc_adr_period: Number(e.target.value) })}>
              {periods.map((p) => <option key={p} value={p}>{p} sessions</option>)}</select></Field>
          <Num label="No entry once ADR used" unit="%" k="sc_adr_max_used" s={s} set={set} step={5} min={10} max={1000} />
          <Num label="Smallest gap" unit="× ATR" k="sc_fvg_min_atr" s={s} set={set} step={0.05} max={5} />
          <Num label="Gap tradable for" unit="candles" k="sc_fvg_max_age" s={s} set={set} step={1} min={1} max={200} />
          <Field label="Higher-timeframe context">
            <select className={inputCls} value={s.sc_ctx_tf} aria-label="Context timeframe" onChange={(e) => set({ sc_ctx_tf: Number(e.target.value) })}>
              <option value={0}>Off</option><option value={30}>30-minute trend must not be against</option><option value={60}>60-minute trend must not be against</option></select></Field>
          <Num label="Stop at least" unit="% of premium" k="sc_stop_min_pct" s={s} set={set} step={1} max={99} />
          <Num label="Stop at most" unit="% of premium" k="sc_stop_max_pct" s={s} set={set} step={1} min={1} max={100} />
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600 dark:text-slate-300">
          <Button disabled={!preset} onClick={() => preset && set(preset)}>Use the specified risk preset</Button>
          <span>0.5% of capital per trade · ATR stop · 2R target · 1.5% daily loss limit · at most 5 trades · one position · {s.timeframe}m entries confirmed by the {s.bias_confirm_tf}m trend (change them under Settings). Currently: risk {s.risk_pct}%, target {s.target_rr}R, daily loss {s.daily_risk_pct}%, {s.max_trades_per_day} trades.</span>
        </div>

        {!c ? (
          <p className="text-sm text-slate-500" data-testid="scored-empty">Waiting for a closed candle with enough history. Each component's points, the gates and the reasons a signal is refused appear here.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Score ({c.entry_tf}m entries, {c.confirm_tf}m trend)</div>
                <div className="num text-2xl font-bold" data-testid="sc-score">{num(c.score, 0)} <span className="text-sm font-normal text-slate-500">/ 100 · minimum {num(s.sc_min_score, 0)}</span></div>
              </div>
              <div className="text-right text-sm" data-testid="sc-decision">
                <Pill tone={c.passed ? (c.candidate === "BUY CE" ? "good" : "bad") : "neutral"}>{c.passed ? `${c.candidate} candidate` : "No entry"}</Pill>
                <div className="mt-1 text-xs text-slate-500">long {c.score_long != null ? num(c.score_long, 0) : "—"} · short {c.score_short != null ? num(c.score_short, 0) : "—"}</div>
              </div>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" role="progressbar" aria-valuenow={c.score} aria-valuemin={0} aria-valuemax={100} aria-label="Strategy score">
              <div className={`h-full ${c.passed ? "bg-green-500" : "bg-slate-400"}`} style={{ width: `${Math.min(100, Math.max(0, c.score))}%` }} />
            </div>

            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[520px] text-xs" data-testid="sc-components">
                <thead className="text-left text-slate-500"><tr><th className="py-1.5">Component</th><th className="text-right">Points</th><th className="pl-2">What the candle shows</th></tr></thead>
                <tbody>
                  {c.components.map((x) => (
                    <tr key={x.key} className="border-t border-slate-100 align-top dark:border-slate-800" data-testid={`sc-row-${x.key}`}>
                      <td className="py-1.5 font-medium">{x.label}</td>
                      <td className="num text-right"><span className={x.earned ? "text-gain" : x.points > 0 ? "" : "text-slate-400"}>{num(x.points, 0)}</span> / {x.max}</td>
                      <td className="pl-2 text-slate-600 dark:text-slate-300">{x.condition}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>

            <div data-testid="sc-gates">
              <div className="mb-1 text-xs font-semibold">Entry gates (all must pass, as well as the score)</div>
              <ul className="grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2">
                {c.gates.map((g) => (
                  <li key={g.key} className="flex items-start gap-1.5"><span aria-hidden className={g.ok ? "text-gain" : "text-loss"}>{g.ok ? "✓" : "✗"}</span>
                    <span><b>{g.label}</b>{g.ok ? "" : `: ${g.text}`}</span></li>))}
              </ul>
            </div>
            <p className={`rounded-lg px-3 py-2 text-xs ${c.passed ? "bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-200" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`} data-testid="sc-reasons">
              {c.passed ? <><b>All conditions met:</b> {c.candidate}.</> : <><b>Why no entry:</b> {c.rejections.join("; ")}.</>}
            </p>
          </>
        )}

        <div data-testid="sc-rejected">
          <div className="mb-1 text-xs font-semibold">Rejected signals (a candidate that scored at least 80% of the minimum and was refused)</div>
          {rejected.length === 0 ? <p className="text-xs text-slate-500">None yet.</p> : (
            <div className="scroll-thin max-h-48 overflow-auto">
              <table className="w-full min-w-[420px] text-xs">
                <thead className="text-left text-slate-500"><tr><th className="py-1">Candle</th><th>Side</th><th className="text-right">Score</th><th className="pl-2">Why it was refused</th></tr></thead>
                <tbody>
                  {rejected.map((r) => (
                    <tr key={r.bar_close + r.side} className="border-t border-slate-100 align-top dark:border-slate-800">
                      <td className="num py-1">{hm(r.bar_close)}</td><td>{r.side}</td><td className="num text-right">{num(r.score, 0)}</td>
                      <td className="pl-2 text-slate-600 dark:text-slate-300">{r.reasons.join("; ") || "—"}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={onApply} disabled={busy}>{running ? "Apply scored-strategy settings" : "Save scored-strategy settings"}</Button>
          {msg && <span role="status" data-testid="sc-msg" className={`text-xs ${msg.ok ? "text-gain" : "text-red-600"}`}>{msg.text}</span>}
        </div>
        <p className="text-xs text-slate-500">{c?.note ?? "Fixed starting rules, not fitted to any result. The score is how many conditions are met, not a probability of winning."} Closed candles only. No trade is forced: if no candle qualifies the engine stays flat. A 1-minute entry refinement is not implemented.</p>
      </div>
    </Card>
  );
}

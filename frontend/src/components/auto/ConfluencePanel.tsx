import { Link } from "react-router-dom";
import { Layers } from "lucide-react";
import type { BiasAnalysis, BiasSettings, CfFactor, FvgZone } from "../../types/api";
import { num } from "../../utils/format";
import { Card, Pill, type Tone } from "../common/Card";
import { Button, Field, inputCls } from "../common/Controls";
import { Check, Num, toggle } from "./AutoSettings";
import { voteTone } from "./BiasPanel";

const WORD = { bullish: "Bullish", bearish: "Bearish", neutral: "Neutral", unavailable: "n/a" } as const;
const FACTORS = [["ema", "EMA trend"], ["vwap", "VWAP"], ["fvg", "Fair value gap"], ["structure", "Market structure"]] as const;

function Zone({ name, z }: { name: string; z: FvgZone | null | undefined }) {
  if (!z) return <li>{name}: no active gap</li>;
  const tone: Tone = z.state === "filled" ? "neutral" : z.state === "mitigated" ? "warn" : "info";
  return (
    <li>{name}: {num(z.lo)}–{num(z.hi)} <Pill tone={tone}>{z.state}</Pill>{" "}
      {z.retest ? <Pill tone="good">retest confirmed</Pill> : <span className="text-slate-500">{z.age_bars} candle{z.age_bars === 1 ? "" : "s"} old</span>}
      {z.active > 1 && <span className="text-slate-500"> · {z.active} active</span>}</li>
  );
}

/** The confluence strategy (FVG + VWAP + ADR + EMA + market structure): which entry strategy runs, every factor's
 *  value and condition, the confirmation score, the ADR filter, and why an entry was refused. Paper and replay only. */
export function ConfluencePanel({ a, s, set, running, onApply, busy, msg, periods = [5, 10, 20] }: {
  a: BiasAnalysis | null; s: BiasSettings; set: (p: Partial<BiasSettings>) => void; running: boolean;
  onApply: () => void; busy: boolean; msg: { ok: boolean; text: string } | null; periods?: number[];
}) {
  const c = a?.confluence ?? null;
  const active = s.entry_strategy === "confluence";
  const byKey = new Map<string, CfFactor>((c?.factors ?? []).map((f) => [f.key, f]));
  const fvg = byKey.get("fvg")?.values as { bullish?: FvgZone | null; bearish?: FvgZone | null } | undefined;
  const decided = a?.strategy === "confluence";
  const strategySelect = (
    <Field label="Entry strategy">
      <select className={inputCls} value={s.entry_strategy} aria-label="Entry strategy" onChange={(e) => set({ entry_strategy: e.target.value as BiasSettings["entry_strategy"] })}>
        <option value="bias">Bias votes (12 indicators)</option><option value="confluence">Confluence: FVG + VWAP + ADR + EMA + structure</option>
        <option value="scored">Scored: structure + EMA + VWAP + FVG + ADR (points)</option>
        <option value="configured">Configured: the strategies that are ON in Trading Settings</option></select></Field>
  );
  if (s.entry_strategy === "configured") {
    return (
      <Card title="Entry strategy" icon={<Layers size={16} className="text-violet-600" />} accent="strat" right="managed in Trading Settings">
        <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-4">{strategySelect}</div>
        <p className="mt-3 text-xs text-slate-600 dark:text-slate-300" data-testid="configured-note">
          Signals come from every strategy that is ON in <Link to="/trading-settings" className="text-blue-700 underline dark:text-blue-400">Trading Settings</Link>; the timeframes, indicators,
          risk, stop, target, trading window and daily limits are read from there on every tick, so a change applies to the next candle without a restart. The per-strategy fields on this page
          do not apply in this mode.</p>
      </Card>
    );
  }
  if (s.entry_strategy === "scored") {
    return (
      <Card title="Entry strategy" icon={<Layers size={16} className="text-violet-600" />} accent="strat" right="the scored strategy is selected: its panel is below">
        <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-4">{strategySelect}</div>
      </Card>
    );
  }
  return (
    <Card title="Confluence strategy" icon={<Layers size={16} className="text-violet-600" />} accent="strat"
      right={active ? "active entry strategy · paper only" : "preview of the factors · not the active strategy"}>
      <div className="space-y-3" data-testid="confluence">
        <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-4">
          {strategySelect}
          <Num label="Confirmation score needed" unit="%" k="cf_min_score" s={s} set={set} step={5} max={100} />
          <Field label="ADR period">
            <select className={inputCls} value={s.cf_adr_period} aria-label="ADR period" onChange={(e) => set({ cf_adr_period: Number(e.target.value) })}>
              {periods.map((p) => <option key={p} value={p}>{p} sessions</option>)}</select></Field>
          <Num label="Stop entries once ADR used" unit="%" k="cf_adr_max_used" s={s} set={set} step={5} min={10} max={1000} />
          <Num label="Smallest fair value gap" unit="× ATR" k="cf_fvg_min_atr" s={s} set={set} step={0.05} max={5} />
          <Num label="Gap stays tradable for" unit="candles" k="cf_fvg_max_age" s={s} set={set} step={1} min={1} max={200} />
          <div className="col-span-2 flex flex-col gap-1.5">
            <Check label="ADR filter: no entry once the day's range is used up" on={s.cf_adr_filter} onChange={(v) => set({ cf_adr_filter: v })} />
            <Check label="15-minute trend must not be against the trade" on={s.cf_htf} onChange={(v) => set({ cf_htf: v })} />
          </div>
        </div>

        <div className="scroll-thin overflow-x-auto">
          <table className="w-full min-w-[560px] text-xs" data-testid="cf-factors">
            <thead className="text-left text-slate-500">
              <tr><th className="py-1.5">Factor</th><th>On</th><th title="Must be fully confirmed (vote ±1) for an entry">Required</th><th className="text-right">Vote</th><th className="pl-2">Status</th><th className="pl-2">Condition now</th></tr>
            </thead>
            <tbody>
              {FACTORS.map(([key, label]) => {
                const f = byKey.get(key);
                const on = s.cf_factors.includes(key);
                return (
                  <tr key={key} className={`border-t border-slate-100 align-top dark:border-slate-800 ${on ? "" : "opacity-50"}`} data-testid={`cf-row-${key}`}>
                    <td className="py-1.5 font-medium">{label}</td>
                    <td><input type="checkbox" aria-label={`Use ${label}`} checked={on}
                      onChange={(e) => set({ cf_factors: toggle(s.cf_factors, key, e.target.checked), ...(e.target.checked ? {} : { cf_require: toggle(s.cf_require, key, false) }) })} /></td>
                    <td><input type="checkbox" aria-label={`Require ${label}`} checked={s.cf_require.includes(key)} disabled={!on}
                      onChange={(e) => set({ cf_require: toggle(s.cf_require, key, e.target.checked) })} /></td>
                    <td className="num text-right">{f?.vote != null ? num(f.vote, 1) : "—"}</td>
                    <td className="pl-2">{f ? <Pill tone={voteTone(f.status)}>{WORD[f.status]}</Pill> : null}</td>
                    <td className="pl-2 text-slate-600 dark:text-slate-300">{f?.condition ?? "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!c ? (
          <p className="text-sm text-slate-500" data-testid="confluence-empty">
            Waiting for a closed candle with enough history. Each factor's value, condition and vote, the confirmation score and the reasons an entry is refused appear here.</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Confirmation score</div>
                <div className="num text-2xl font-bold" data-testid="cf-score">{num(c.score, 0)}% <span className="text-sm font-normal text-slate-500">of the {num(s.cf_min_score, 0)}% needed</span></div>
              </div>
              <div className="text-right text-sm" data-testid="cf-decision">
                <Pill tone={c.passed ? (c.candidate === "BUY CE" ? "good" : "bad") : "neutral"}>{c.passed ? `${c.candidate} candidate` : "No entry"}</Pill>
                {decided && <div className="mt-1 text-xs text-slate-500">decided by the confluence strategy</div>}
              </div>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" role="progressbar" aria-valuenow={c.score} aria-valuemin={0} aria-valuemax={100} aria-label="Confirmation score">
              <div className={`h-full ${c.passed ? "bg-green-500" : "bg-slate-400"}`} style={{ width: `${Math.min(100, Math.max(0, c.score))}%` }} />
            </div>

            <div className="grid gap-3 text-xs sm:grid-cols-2">
              <div data-testid="cf-fvg">
                <div className="mb-1 font-semibold">Fair value gaps</div>
                <ul className="space-y-1"><Zone name="Bullish" z={fvg?.bullish} /><Zone name="Bearish" z={fvg?.bearish} /></ul>
                <p className="mt-1 text-slate-500">Unfilled = price has not come back; mitigated = price entered the gap but not through it; a retest is a candle that enters the gap, holds it and closes back out in its direction.</p>
              </div>
              <div data-testid="cf-adr">
                <div className="mb-1 flex items-center gap-2 font-semibold">Average Daily Range
                  {c.adr.filter ? <Pill tone={c.adr.ok == null ? "neutral" : c.adr.ok ? "good" : "warn"}>{c.adr.ok == null ? "not checked" : c.adr.ok ? "room left" : "exhausted"}</Pill> : <Pill tone="neutral">filter off</Pill>}</div>
                <table className="w-full">
                  <thead className="text-left text-slate-500"><tr><th>Period</th><th className="text-right">ADR</th><th className="text-right">Used today</th></tr></thead>
                  <tbody>
                    {c.adr.rows.map((r) => (
                      <tr key={r.period} className={`border-t border-slate-100 dark:border-slate-800 ${r.period === c.adr.period ? "font-semibold" : ""}`}>
                        <td className="py-1">{r.period}-day{r.period === c.adr.period ? " (filter)" : ""}</td>
                        <td className="num text-right">{r.adr != null ? num(r.adr) : "—"}</td>
                        <td className="num text-right">{r.used != null ? `${num(r.used, 0)}%` : "—"}</td>
                      </tr>))}
                  </tbody>
                </table>
                <p className="mt-1 text-slate-500">{c.adr.text}</p>
              </div>
            </div>

            <p className={`rounded-lg px-3 py-2 text-xs ${c.passed ? "bg-green-50 text-green-800 dark:bg-green-950 dark:text-green-200" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"}`} data-testid="cf-reasons">
              {c.passed ? <><b>All conditions met:</b> {c.candidate}.</> : <><b>Why no entry:</b> {c.rejections.length ? c.rejections.join("; ") : "no factor points one way"}.</>}
            </p>
          </>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={onApply} disabled={busy}>{running ? "Apply strategy settings" : "Save strategy settings"}</Button>
          {msg && <span role="status" data-testid="cf-msg" className={`text-xs ${msg.ok ? "text-gain" : "text-red-600"}`}>{msg.text}</span>}
        </div>
        <p className="text-xs text-slate-500">{c?.note ?? "Fixed starting rules, not fitted to any result. The score is how many enabled factors agree, not a probability of winning."} Closed candles only; a factor with missing data (no futures candles, too few sessions for the ADR) is left out and shown as n/a.</p>
      </div>
    </Card>
  );
}

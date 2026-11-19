import { Compass } from "lucide-react";
import type { BiasAnalysis, BiasLabel, CandleDir, Outcome, VoteStatus } from "../../types/api";
import { hm, num } from "../../utils/format";
import { Card, Pill, Stat, type Tone } from "../common/Card";

export const biasTone = (b: BiasLabel | string | undefined): Tone =>
  b === "STRONG BULLISH" || b === "BULLISH" ? "good" : b === "STRONG BEARISH" || b === "BEARISH" ? "bad" : "neutral";
export const trendTone = (t: string | undefined): Tone => (t === "Bullish" ? "good" : t === "Bearish" ? "bad" : "neutral");
export const dirTone = (d: CandleDir | string | null | undefined): Tone => (d === "UP" ? "good" : d === "DOWN" ? "bad" : "neutral");
export const outcomeTone = (o: Outcome | null | undefined): Tone => (o === "CORRECT" ? "good" : o === "INCORRECT" ? "bad" : "neutral");
export const voteTone = (s: VoteStatus): Tone => (s === "bullish" ? "good" : s === "bearish" ? "bad" : "neutral");
export const arrow = (d: string | null | undefined) => (d === "UP" ? "▲ UP" : d === "DOWN" ? "▼ DOWN" : "◆ NEUTRAL");

/** The directional bias of the latest closed 5-minute candle, with the reasons. */
export function BiasPanel({ a, asOf, live }: { a: BiasAnalysis | null; asOf?: string; live?: boolean }) {
  if (!a) {
    return <Card title="Market bias" icon={<Compass size={16} className="text-blue-600" />}>
      <p className="text-sm text-slate-500">Waiting for the first closed 5-minute candle.</p></Card>;
  }
  const tone = biasTone(a.bias);
  const t1 = a.tf_primary ?? 5, t2 = a.tf_confirm ?? 15;
  const big = tone === "good" ? "text-gain" : tone === "bad" ? "text-loss" : "text-slate-600 dark:text-slate-300";
  return (
    <Card title="Market bias" icon={<Compass size={16} className="text-blue-600" />} accent={tone === "good" ? "gain" : tone === "bad" ? "loss" : "neutral"}
      right={<span>{live === false ? `last session ${asOf ?? ""} · ` : ""}candle closed {hm(a.bar_close)}</span>}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className={`text-2xl font-bold tracking-tight sm:text-3xl ${big}`} data-testid="bias-label">{a.bias}</div>
          <div className="mt-1 text-xs text-slate-500">NIFTY {num(a.close)} · ATR {a.atr != null ? num(a.atr) : "—"} ({a.atr_pct != null ? `${num(a.atr_pct, 3)}%` : "—"}) · RSI {t1}m {a.rsi_5m ?? "—"} / {t2}m {a.rsi_15m ?? "—"}</div>
        </div>
        <div className="text-right">
          <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">Indicator agreement</div>
          <div className="num text-2xl font-bold" data-testid="bias-confidence">{num(a.confidence, 0)}%</div>
        </div>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" role="progressbar" aria-valuenow={a.confidence} aria-valuemin={0} aria-valuemax={100} aria-label="Indicator agreement">
        <div className={`h-full ${tone === "good" ? "bg-green-500" : tone === "bad" ? "bg-red-500" : "bg-slate-400"}`} style={{ width: `${Math.min(100, Math.max(0, a.confidence))}%` }} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label={`${t2}m trend (primary)`} value={<Pill tone={trendTone(a.trend_15m)}>{a.trend_15m}</Pill>} sub={`score ${a.score_15m != null ? num(a.score_15m, 2) : "—"}`}
          tip="The 15-minute indicators' weighted vote, from -1 (all bearish) to +1 (all bullish). Entries need it to point the same way as the 5-minute vote." />
        <Stat label={`${t1}m trend (entry)`} value={<Pill tone={trendTone(a.trend_5m)}>{a.trend_5m}</Pill>} sub={`score ${a.score_5m != null ? num(a.score_5m, 2) : "—"}`} />
        <Stat label={`Next ${t1}m candle`} value={<Pill tone={dirTone(a.prediction)}>{arrow(a.prediction)}</Pill>} sub="a forecast, not a promise"
          tip="The direction the combined bias leans for the next candle. It is scored against what actually happens (see Predictions vs actual)." />
        <Stat label="Entry signal" value={<Pill tone={a.signal === "BUY CE" ? "good" : a.signal === "BUY PE" ? "bad" : "neutral"}>{a.signal}</Pill>}
          sub={a.conflict ? `${t1}m and ${t2}m disagree` : a.signal === "HOLD" ? "waiting" : "candidate"} />
      </div>
      {a.signal === "HOLD" && a.hold_reasons.length > 0 && (
        <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          <b>Why HOLD:</b> {a.hold_reasons.join("; ")}.</p>
      )}
      <div className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
        <div><div className="mb-1 font-semibold text-gain">Supporting ({a.supports.length})</div>
          <div className="flex flex-wrap gap-1">{a.supports.length ? a.supports.map((s) => <Pill key={s} tone="good">{s}</Pill>) : <span className="text-slate-500">none</span>}</div></div>
        <div><div className="mb-1 font-semibold text-loss">Against ({a.against.length})</div>
          <div className="flex flex-wrap gap-1">{a.against.length ? a.against.map((s) => <Pill key={s} tone="bad">{s}</Pill>) : <span className="text-slate-500">none</span>}</div></div>
      </div>
      <p className="mt-3 text-[11px] text-slate-500">{a.note} Weights and thresholds are fixed starting values; validation results are on the Accuracy panel below.</p>
    </Card>
  );
}

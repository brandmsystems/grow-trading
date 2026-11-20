import { Repeat } from "lucide-react";
import type { AutomationPhase, BiasAnalysis, BiasAutomation, BiasSettings, BiasSummary, BiasTrade } from "../../types/api";
import { hm, inr, pnlClass } from "../../utils/format";
import { Card, Pill, Stat, type Tone } from "../common/Card";
import { Button } from "../common/Controls";
import { Num } from "./AutoSettings";

const TONE: Record<AutomationPhase, Tone> = { ready: "good", holding: "info", exiting: "warn", waiting: "neutral", paused: "warn", limit: "warn", halted: "bad" };
const EXIT: Record<string, string> = {
  profit_target: "net profit target", stop_loss: "stop-loss", target: "risk-reward target", opposite_signal: "analysis turned the other way",
  time_exit: "holding-time limit", square_off: "15:00 square-off", daily_loss_limit: "daily loss limit", manual_stop: "engine stopped", manual_square_off: "closed manually",
};

/** Continuous automation: what the engine is doing now, the two numbers that drive it (bias threshold, net profit target),
 *  this session's results, and the Pause / Resume and Stop buttons sit above. Paper and replay only. */
export function AutomationPanel({ a, bias, s, set, running, onApply, busy, summary, trades, msg }: {
  a: BiasAutomation | undefined; bias: BiasAnalysis | null; s: BiasSettings; set: (p: Partial<BiasSettings>) => void; running: boolean;
  onApply: () => void; busy: boolean; summary: BiasSummary | null; trades: BiasTrade[]; msg: { ok: boolean; text: string } | null;
}) {
  const last = trades.find((t) => t.status === "CLOSED");
  const eligible = bias ? bias.confidence >= s.bias_min_confidence && bias.direction !== 0 : null;
  return (
    <Card title="Continuous automation" icon={<Repeat size={16} className="text-green-600" />} accent="strat"
      right="paper only · one position at a time">
      <div className="space-y-3" data-testid="automation">
        <div className="flex flex-wrap items-center gap-2" data-testid="automation-phase">
          {running && a ? <Pill tone={TONE[a.phase]}>{a.label}</Pill> : <Pill tone="neutral">Not running</Pill>}
          <span className="min-w-0 flex-1 text-sm text-slate-600 dark:text-slate-300">
            {running && a ? a.detail : "Start paper trading to begin: every completed 5-minute candle is analysed, and a trade opens only when the bias confidence is at or above your threshold and the 15-minute trend confirms it."}
          </span>
        </div>

        {bias && (
          <p className="text-sm" data-testid="automation-bias">
            Current bias <b>{bias.bias}</b> · agreement <b>{bias.confidence.toFixed(0)}%</b> vs your minimum <b>{s.bias_min_confidence}%</b>
            {eligible != null && <> · <span className={eligible ? "text-gain" : "text-slate-500"}>{eligible ? `eligible for ${bias.signal}` : "below the threshold or no confirmed signal: no entry"}</span></>}
          </p>
        )}

        <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-4">
          <Num label="Market Bias threshold" unit="%" k="bias_min_confidence" s={s} set={set} step={1} max={100} />
          <Num label="Net profit target per trade" unit="₹, 0 = off" k="profit_target_net" s={s} set={set} step={100} />
          <Button variant="primary" onClick={onApply} disabled={busy}>{running ? "Apply threshold & target" : "Save threshold & target"}</Button>
          {msg && <span role="status" data-testid="automation-msg" className={`text-xs ${msg.ok ? "text-gain" : "text-red-600"}`}>{msg.text}</span>}
        </div>
        <p className="text-xs text-slate-500">
          The ₹{s.profit_target_net.toLocaleString("en-IN")} target is per trade, after brokerage, taxes and slippage; it is not a daily target. The stop-loss, the daily loss limit, position sizing and the 15:00 square-off stay in force.
          After any exit the next entry waits for a candle that opened after it. Agreement between indicators is not a probability of winning.
        </p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="automation-stats">
          <Stat label="Completed trades" value={String(summary?.trades ?? 0)} sub={summary && summary.open ? `${summary.open} open` : undefined} />
          <Stat label="Profit target hits" value={String(a?.target_hits ?? summary?.target_hits ?? 0)} />
          <Stat label="Total trades today" value={String(a?.trades_today ?? summary?.trades ?? 0)} />
          <Stat label="Net paper P&L" value={summary ? inr(summary.net, true) : "—"} className={pnlClass(summary?.net)} />
        </div>
        {last && (
          <p className="text-xs text-slate-600 dark:text-slate-400" data-testid="last-exit">
            Last exit {hm(last.exit_ts)}: {last.exit_reason ? EXIT[last.exit_reason] ?? last.exit_reason : "—"} · net <span className={pnlClass(last.net)}>{inr(last.net, true)}</span>
          </p>
        )}
      </div>
    </Card>
  );
}

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { Dashboard } from "../../types/api";
import { hms, inr, num, pnlClass } from "../../utils/format";
import { Card, Pill } from "../common/Card";

/** NIFTY price, EMA 9/21 trend and today's P&L: the three numbers you check first. */
export function MarketSummary({ data }: { data: Dashboard }) {
  const q = data.feed?.quote;
  const ema = data.feed?.ema;
  const trend = ema ? (ema.fast > ema.slow ? 1 : ema.fast < ema.slow ? -1 : 0) : null;
  const mtm = data.position?.mtm ?? 0;
  const dayNet = (data.realised_today ?? 0) + (data.position ? mtm : 0);
  const up = (q?.change ?? 0) >= 0;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Card>
        <div className="p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">NIFTY 50</span>
            {q && <Pill tone={q.state === "live" ? "good" : q.state === "delayed" ? "warn" : "neutral"}>{q.state}</Pill>}
          </div>
          <div className="num mt-1 text-3xl font-semibold">{num(q?.price)}</div>
          <div className={`num text-sm ${up ? "text-gain" : "text-loss"}`}>
            {q?.change != null ? `${up ? "+" : "−"}${num(Math.abs(q.change))} (${num(q.change_pct)}%)` : "—"}
          </div>
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            O {num(q?.open)} · H {num(q?.high)} · L {num(q?.low)} · as of {hms(q?.as_of)}
          </div>
          {q?.error && <div className="mt-1 text-xs text-amber-600">{q.error}</div>}
        </div>
      </Card>
      <Card>
        <div className="p-4">
          <span className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Trend · {data.feed?.timeframe ?? 5}-minute</span>
          <div className={`mt-1 flex items-center gap-2 text-2xl font-semibold ${trend === 1 ? "text-gain" : trend === -1 ? "text-loss" : ""}`}>
            {trend === 1 ? <ArrowUpRight /> : trend === -1 ? <ArrowDownRight /> : <Minus />}
            {trend === 1 ? "Uptrend" : trend === -1 ? "Downtrend" : trend === 0 ? "Flat" : "—"}
          </div>
          <div className="num mt-2 text-sm">
            <span className="text-ema-fast">EMA 9 {num(ema?.fast)}</span>
            <span className="mx-2 text-slate-400">/</span>
            <span className="text-ema-slow">EMA 21 {num(ema?.slow)}</span>
          </div>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {ema ? `Gap ${num(ema.gap)} · last closed bar ${ema.bar_close.slice(11, 16)}` : data.feed?.bars_error ?? "No bars yet"}
          </div>
        </div>
      </Card>
      <Card>
        <div className="p-4">
          <span className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">Today's P&amp;L (after costs)</span>
          <div className={`num mt-1 text-3xl font-semibold ${pnlClass(dayNet)}`}>{inr(dayNet, true)}</div>
          <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {data.position ? `Open ${inr(mtm, true)} · realised ${inr(data.realised_today, true)}` : `${data.trades_today} trade(s) today`}
            {data.config ? ` · ${data.config.trade_mode}` : ""}
          </div>
        </div>
      </Card>
    </div>
  );
}

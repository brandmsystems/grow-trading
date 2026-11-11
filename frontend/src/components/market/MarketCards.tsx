import { ArrowDownRight, ArrowUpRight, BarChart3, Gauge, Layers, LineChart as LineIcon, Minus } from "lucide-react";
import type { Dashboard, LiveTrade } from "../../types/api";
import { dmy, hm, hms, inr, num, pct, pnlClass, signed, todayIST } from "../../utils/format";
import { BigValue, Card, Dot, Pill, Stat } from "../common/Card";
import { Limitation } from "../common/States";

/** NIFTY 50 spot: the underlying index value (never an option price). */
export function SpotCard({ data, compact = false }: { data: Dashboard; compact?: boolean }) {
  const q = data.feed?.quote;
  const up = (q?.change ?? 0) > 0, down = (q?.change ?? 0) < 0;
  const live = q?.state === "live";
  return (
    <Card accent="spot" title="NIFTY 50 Spot" icon={<LineIcon size={16} className="text-blue-600" />}
      right={<Pill tone={live ? "good" : q?.state === "delayed" ? "warn" : "neutral"}><Dot tone={live ? "good" : q?.state === "delayed" ? "warn" : "neutral"} pulse={live} />{live ? "LIVE" : q?.state === "closed" ? "MARKET CLOSED" : (q?.state ?? "—").toUpperCase()}</Pill>}>
      <BigValue value={num(q?.price)}
        sub={<span className={`num flex items-center gap-1 font-semibold ${up ? "text-gain" : down ? "text-loss" : "text-slate-500"}`}>
          {up ? <ArrowUpRight size={16} /> : down ? <ArrowDownRight size={16} /> : <Minus size={16} />}
          {signed(q?.change)} ({signed(q?.change_pct)}%)
        </span>} />
      {!compact && (
        <div className="mt-3 grid grid-cols-3 gap-2">
          <Stat label="Day high" value={num(q?.high)} className="text-sm" />
          <Stat label="Day low" value={num(q?.low)} className="text-sm" />
          <Stat label="Prev close" value={num(q?.prev_close)} className="text-sm" />
        </div>
      )}
      <div className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        Index value · {up ? "rising" : down ? "falling" : "flat"} vs previous close · as of {hms(q?.as_of)}
      </div>
      {q?.error && <p className="mt-1 text-xs text-orange-600">{q.error}</p>}
    </Card>
  );
}

/** Option premium: the actual price of the selected CE or PE contract (never the index). */
export function PremiumCard({ data }: { data: Dashboard }) {
  const sig = data.feed?.signal;
  const rec = sig?.rec;
  const has = rec?.verified && rec.premium != null;
  const side = (t: "CE" | "PE") => {
    const sel = has && rec!.opt_type === t;
    const tone = t === "CE" ? "border-green-300 bg-green-50 dark:border-green-900 dark:bg-green-950/30" : "border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950/30";
    return (
      <div className={`rounded-xl border p-3 ${sel ? tone : "border-slate-200 dark:border-slate-800"}`}>
        <div className="flex items-center justify-between">
          <Pill tone={t === "CE" ? "good" : "bad"}>{t === "CE" ? "CALL (CE)" : "PUT (PE)"}</Pill>
          {sel && <span className="text-[11px] font-semibold text-slate-500">SELECTED</span>}
        </div>
        {sel ? (
          <>
            <div className="num mt-2 text-xl font-bold">₹{num(rec!.premium)}</div>
            <div className="text-xs text-slate-500">Strike {num(rec!.strike, 0)} · {dmy(rec!.expiry)}</div>
            <div className="mt-1 grid grid-cols-3 gap-1 text-[11px] text-slate-500">
              <span>OI {rec!.oi != null ? num(rec!.oi, 0) : "—"}</span>
              <span>IV {rec!.iv != null ? num(rec!.iv, 1) : "—"}</span>
              <span>Δ {rec!.delta != null ? num(rec!.delta, 2) : "—"}</span>
            </div>
          </>
        ) : (
          <p className="mt-2 text-xs text-slate-500">{has ? "Not the recommended side." : sig?.action === "HOLD" ? "No contract selected while the signal is HOLD." : rec?.error ?? "No verified contract."}</p>
        )}
      </div>
    );
  };
  return (
    <Card accent="neutral" title="NIFTY Options Premium" icon={<Layers size={16} className="text-slate-500" />}
      right={has ? `as of ${hms(rec!.quote_as_of)}` : undefined}>
      <div className="grid grid-cols-2 gap-2">{side("CE")}{side("PE")}</div>
      <div className="mt-2">
        <Limitation>Premium = price of one option contract, not the NIFTY index. The backend returns only the recommended contract, with no premium change or volume.</Limitation>
      </div>
    </Card>
  );
}

/** EMA 9/21, trend, latest crossover and the strategy's current call. */
export function StrategyCard({ data }: { data: Dashboard }) {
  const ema = data.feed?.ema;
  const sig = data.feed?.signal;
  const trend = ema ? Math.sign(ema.fast - ema.slow) : null;
  const last = data.feed?.crosses?.length ? data.feed.crosses[data.feed.crosses.length - 1] : null;
  return (
    <Card accent="strat" title="9/21 EMA Strategy" icon={<Gauge size={16} className="text-violet-600" />} right={`${data.feed?.timeframe ?? 5}-minute`}>
      <div className="flex items-center gap-2">
        <Pill tone={sig?.action === "BUY CE" ? "good" : sig?.action === "BUY PE" ? "bad" : "neutral"} className="px-3 py-1 text-sm">{sig?.action ?? "HOLD"}</Pill>
        <span className={`flex items-center gap-1 text-sm font-semibold ${trend === 1 ? "text-gain" : trend === -1 ? "text-loss" : "text-slate-500"}`}>
          {trend === 1 ? <ArrowUpRight size={16} /> : trend === -1 ? <ArrowDownRight size={16} /> : <Minus size={16} />}
          {trend === 1 ? "Uptrend" : trend === -1 ? "Downtrend" : trend === 0 ? "Flat" : "—"}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Stat label="EMA 9" value={num(ema?.fast)} className="text-blue-600 dark:text-blue-400" />
        <Stat label="EMA 21" value={num(ema?.slow)} className="text-orange-600 dark:text-orange-400" />
        <Stat label="Gap (9 − 21)" value={signed(ema?.gap)} tip="Positive: EMA 9 above EMA 21 (bullish). Negative: below (bearish)." />
        <Stat label="Latest cross" value={last ? `${last.direction > 0 ? "Bullish" : "Bearish"} ${hm(last.ts)}` : "None today"}
          className={last ? (last.direction > 0 ? "text-gain" : "text-loss") : ""} />
      </div>
      <p className="mt-2 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">{sig?.reason}</p>
    </Card>
  );
}

/** Today's engine results from /api/live/trades. */
export function PerformanceCard({ data, trades }: { data: Dashboard; trades: LiveTrade[] }) {
  const closed = trades.filter((t) => t.status === "CLOSED" && t.net != null);
  const wins = closed.filter((t) => (t.net ?? 0) > 0).length;
  const mtm = data.position?.mtm ?? 0;
  const net = (data.realised_today ?? 0) + (data.position ? mtm : 0);
  const mode = data.config?.trade_mode;
  const day = data.day ?? null;
  const other = day && day !== todayIST();
  return (
    <Card accent={net > 0 ? "gain" : net < 0 ? "loss" : "neutral"} title={other ? "Last Engine Session" : "Today's Performance"} icon={<BarChart3 size={16} className="text-slate-500" />}
      right={mode ? `${mode.toUpperCase()}${other ? ` · ${dmy(day)}` : ""}` : "engine off"}>
      <BigValue value={inr(net, true)} className={pnlClass(net)} sub={<span className="text-xs text-slate-500">P&amp;L after charges{data.position ? ` · open ${inr(mtm, true)}` : ""}</span>} />
      <div className="mt-3 grid grid-cols-4 gap-2">
        <Stat label="Trades" value={trades.length} />
        <Stat label="Won" value={wins} className="text-gain" />
        <Stat label="Lost" value={closed.length - wins} className="text-loss" />
        <Stat label="Win rate" value={closed.length ? pct((wins / closed.length) * 100, 0) : "—"} />
      </div>
      {!trades.length && <p className="mt-2 text-xs text-slate-500">No engine trades today{data.state === "stopped" ? ". Start Paper trading on the Live page." : "."}</p>}
    </Card>
  );
}

import { AlertTriangle, CheckCircle2, MinusCircle, Target } from "lucide-react";
import type { Dashboard } from "../../types/api";
import { dmy, hm, num, signed } from "../../utils/format";
import { Card, Stat } from "../common/Card";

/** The one prominent call: BUY CE / BUY PE / HOLD with the verified contract and its levels. */
export function RecommendationCard({ data, flash }: { data: Dashboard; flash?: boolean }) {
  const sig = data.feed?.signal;
  const rec = sig?.rec;
  const ema = data.feed?.ema;
  const action = sig?.action ?? "HOLD";
  const look = action === "BUY CE"
    ? { box: "from-green-600 to-emerald-500", text: "Bullish: buy a call option" }
    : action === "BUY PE" ? { box: "from-red-600 to-rose-500", text: "Bearish: buy a put option" }
    : { box: "from-slate-600 to-slate-500", text: "No position: wait for the next crossover" };
  const emaOk = ema ? (action === "BUY CE" ? ema.fast > ema.slow : action === "BUY PE" ? ema.fast < ema.slow : null) : null;
  return (
    <Card title="Recommended Option" icon={<Target size={16} className="text-violet-600" />} right={sig?.since ? `signal ${hm(sig.since)}` : undefined}
      className={flash ? "flash" : ""}>
      <div className={`rounded-xl bg-gradient-to-r ${look.box} px-4 py-3 text-white`}>
        <div className="text-2xl font-extrabold tracking-tight sm:text-3xl">{action}</div>
        <div className="text-sm opacity-90">{look.text}</div>
      </div>
      <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{sig?.reason ?? data.feed?.error ?? "Waiting for data…"}</p>

      {action !== "HOLD" && rec && (rec.verified ? (
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Stat label="Option" value={`NIFTY ${num(rec.strike, 0)} ${rec.opt_type}`} sub={rec.strike_rule} />
          <Stat label="Expiry" value={dmy(rec.expiry)} sub={rec.symbol} />
          <Stat label="Current premium" value={`₹${num(rec.premium)}`} sub={`as of ${(rec.quote_as_of ?? "").slice(11, 19)}`} />
          <Stat label="Entry reference" value={`₹${num(rec.entry)}`} sub={rec.entry_basis} tip="The price you'd likely pay now: the best offer, or LTP plus the backtest slippage." />
          <Stat label="Stop loss" value={`₹${num(rec.stop)}`} className="text-loss" sub={`NIFTY ${num(rec.nifty_stop)}`} tip="Estimate: NIFTY moving 1 × ATR against the trade, converted to premium with the option's delta." />
          <Stat label="Target" value={`₹${num(rec.target)}`} className="text-gain" sub={`NIFTY ${num(rec.nifty_target)}`} tip="Estimate: NIFTY moving 2 × ATR in favour, converted with delta." />
        </div>
      ) : (
        <p className="mt-3 flex items-start gap-2 text-sm text-orange-600"><AlertTriangle size={16} className="mt-0.5 shrink-0" />{rec.error ?? "The option couldn't be verified, so nothing is recommended."}</p>
      ))}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-xl bg-violet-50 px-3 py-2 text-xs dark:bg-violet-950/30">
        <span className="font-semibold text-violet-700 dark:text-violet-300">EMA check</span>
        <span className="num">EMA 9 {num(ema?.fast)} · EMA 21 {num(ema?.slow)} · gap {signed(ema?.gap)}</span>
        {emaOk === true && <span className="flex items-center gap-1 text-gain"><CheckCircle2 size={14} />confirms {action}</span>}
        {emaOk === false && <span className="flex items-center gap-1 text-loss"><AlertTriangle size={14} />EMAs no longer agree</span>}
        {emaOk === null && <span className="flex items-center gap-1 text-slate-500"><MinusCircle size={14} />no open signal</span>}
      </div>
      <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
        Strategy-generated signal, not a guaranteed result. The strategy exits on the opposite crossover or at 15:00; the stop and target are estimates.
      </p>
    </Card>
  );
}

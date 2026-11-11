import { useEffect, useState } from "react";
import { ShieldCheck, X } from "lucide-react";
import type { PendingOrder as P } from "../../types/api";
import { dmy, num } from "../../utils/format";

/** A live entry order the engine is holding until you confirm it. It lapses with the signal. */
export function PendingOrder({ order, now, busy, onConfirm, onReject }: {
  order: P; now: string; busy: boolean; onConfirm: () => void; onReject: () => void;
}) {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    // The server clock is IST wall time; count down against it, adjusted by local elapsed time.
    const serverNow = Date.parse(now + "Z"), started = Date.now(), expires = Date.parse(order.expires + "Z");
    const tick = () => setLeft(Math.max(0, Math.round((expires - (serverNow + Date.now() - started)) / 1000)));
    tick();
    const t = window.setInterval(tick, 1000);
    return () => window.clearInterval(t);
  }, [order.expires, now]);
  return (
    <div className="rounded-xl border-2 border-amber-500 bg-amber-50 p-4 dark:bg-amber-950/40" role="alertdialog" aria-label="Order awaiting confirmation">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold">Confirm live order</span>
        <span className="num text-sm text-amber-700 dark:text-amber-400">{left}s left</span>
      </div>
      <p className="text-sm">
        <b>{order.side} {num(order.strike, 0)} {order.opt_type}</b> · {dmy(order.expiry)} · qty {order.qty}
        {order.ltp != null && <> · LTP ₹{num(order.ltp)}</>}
      </p>
      <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
        {order.trading_symbol} · signal at {order.signal_ts.slice(11, 16)} with NIFTY {num(order.nifty)}. A real MIS market order will be placed on Groww.
      </p>
      <div className="mt-3 flex gap-2">
        <button disabled={busy || left === 0} onClick={onConfirm}
          className="flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50">
          <ShieldCheck size={16} /> Place order
        </button>
        <button disabled={busy} onClick={onReject}
          className="flex items-center gap-1.5 rounded-lg border border-slate-300 px-4 py-2 text-sm hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">
          <X size={16} /> Skip
        </button>
      </div>
    </div>
  );
}

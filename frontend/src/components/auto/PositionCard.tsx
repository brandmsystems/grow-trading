import { useState } from "react";
import { Crosshair } from "lucide-react";
import { setPaperStop, setPaperTarget, squareOff } from "../../services/api";
import type { Position } from "../../types/api";
import { hm, inr, num, pnlClass } from "../../utils/format";
import { Card, Pill, Stat } from "../common/Card";
import { Button, inputCls } from "../common/Controls";

/** The open paper position: entry, stop, target, P&L, with manual close and stop/target adjustment. */
export function PositionCard({ p, editable, onChanged, profitTarget = 0 }: { p: Position | null; editable: boolean; onChanged: () => void; profitTarget?: number }) {
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<string>) {
    setBusy(true);
    try { setMsg({ ok: true, text: await fn() }); onChanged(); } catch (e) { setMsg({ ok: false, text: (e as Error).message }); } finally { setBusy(false); }
  }
  return (
    <Card title="Active position" icon={<Crosshair size={16} className="text-green-600" />} accent={p ? (p.direction === "Bullish" ? "gain" : "loss") : undefined}>
      {!p ? <p className="text-sm text-slate-500">No open position. A trade opens only when every condition is met on a closed 5-minute candle.</p> : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={p.direction === "Bullish" ? "good" : "bad"}>{p.side} {p.opt_type}</Pill>
            <span className="font-semibold">{p.trading_symbol}</span><span className="text-xs text-slate-500">since {hm(p.entry_ts)}</span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Quantity" value={String(p.qty)} />
            <Stat label="Entry premium" value={`₹${num(p.entry_price)}`} />
            <Stat label="Current premium" value={p.ltp != null ? `₹${num(p.ltp)}` : "—"} />
            <Stat label="Open P&L (net)" value={p.mtm != null ? inr(p.mtm, true) : "—"} className={pnlClass(p.mtm)} />
            <Stat label="Stop-loss" value={p.stop_premium != null ? `₹${num(p.stop_premium)}` : "—"} className="text-loss" />
            <Stat label="Target" value={p.target_premium != null ? `₹${num(p.target_premium)}` : "—"} className="text-gain" />
            <Stat label="Max loss at entry" value={p.max_loss != null ? inr(-p.max_loss, false, 0) : "—"} />
            <Stat label="Risk : reward" value={p.risk_reward ? `1 : ${num(p.risk_reward, 1)}` : "—"} />
            {profitTarget > 0 && <Stat label="Net profit target" value={inr(profitTarget, false, 0)} sub={p.mtm != null ? `${Math.max(0, Math.round((p.mtm / profitTarget) * 100))}% reached` : undefined} />}
          </div>
          {p.entry_reason && <p className="text-xs text-slate-600 dark:text-slate-400" data-testid="entry-reason"><b>Why it was entered:</b> {p.entry_reason}{p.entry_confidence != null ? ` (agreement ${Math.round(p.entry_confidence)}%)` : ""}</p>}
          {editable && (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">New stop ₹
                <input type="number" step={0.05} min={0.05} className={`${inputCls} w-28`} value={stop} onChange={(e) => setStop(e.target.value)} aria-label="New stop-loss premium" /></label>
              <Button disabled={busy || !Number(stop)} onClick={() => run(async () => { const r = await setPaperStop(Number(stop)); setStop(""); return `Stop ${num(r.old_stop)} → ${num(r.new_stop)}`; })}>Set stop</Button>
              <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">New target ₹
                <input type="number" step={0.05} min={0.05} className={`${inputCls} w-28`} value={target} onChange={(e) => setTarget(e.target.value)} aria-label="New target premium" /></label>
              <Button disabled={busy || !Number(target)} onClick={() => run(async () => { const r = await setPaperTarget(Number(target)); setTarget(""); return `Target ${r.old_target != null ? num(r.old_target) : "none"} → ${num(r.new_target)}`; })}>Set target</Button>
              <Button variant="danger" disabled={busy} onClick={() => { if (window.confirm("Close this paper position now?")) void run(async () => { await squareOff(); return "Position closed."; }); }}>Close now</Button>
            </div>
          )}
          {msg && <p className={`text-xs ${msg.ok ? "text-gain" : "text-red-600"}`} role="status">{msg.text}</p>}
        </div>
      )}
    </Card>
  );
}

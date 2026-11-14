import { useEffect, useState } from "react";
import { ListChecks, X } from "lucide-react";
import type { LiveTrade, StopChange } from "../../types/api";
import { getPaperTrades, getStopChanges } from "../../services/api";
import { dmy, hm, inr, num, pnlClass } from "../../utils/format";
import { Card, Pill, Stat } from "../common/Card";
import { Button } from "../common/Controls";
import { Empty, ErrorNote } from "../common/States";
import { Decision, RiskRows } from "./RiskManagement";

const REASON: Record<string, string> = {
  opposite_cross: "opposite crossover", square_off: "15:00 square-off", stop_loss: "stop-loss", stop: "NIFTY stop",
  target: "target", time_exit: "5-min time exit", daily_loss_limit: "daily loss limit", manual_stop: "you stopped", manual_square_off: "you squared off",
};

function StopHistory({ tradeId }: { tradeId: number }) {
  const [rows, setRows] = useState<StopChange[] | null>(null);
  useEffect(() => { getStopChanges(tradeId).then(setRows).catch(() => setRows([])); }, [tradeId]);
  if (!rows?.length) return null;
  return (
    <div className="mt-3 text-xs">
      <div className="mb-1 font-semibold">Stop-loss history</div>
      {rows.map((r) => (
        <div key={r.ts} className="flex flex-wrap justify-between gap-2 border-t border-slate-100 py-1 dark:border-slate-800">
          <span className="num">{hm(r.ts)} · {r.source === "entry" ? "set at entry" : "changed by you"}</span>
          <span className="num">{r.old_stop != null ? `₹${num(r.old_stop)} → ` : ""}₹{num(r.new_stop)} · max loss {r.old_max_loss != null ? `₹${num(r.old_max_loss, 0)} → ` : ""}₹{num(r.new_max_loss, 0)}</span>
        </div>
      ))}
    </div>
  );
}

/** Paper trade history with the risk calculation saved at entry. Click a row for the full detail. */
export function PaperTrades({ refreshKey }: { refreshKey: unknown }) {
  const [rows, setRows] = useState<LiveTrade[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<LiveTrade | null>(null);
  useEffect(() => { getPaperTrades().then((t) => { setRows(t); setErr(null); }).catch((e) => setErr((e as Error).message)); }, [refreshKey]);

  return (
    <Card title="Paper Trades & Risk" icon={<ListChecks size={16} className="text-blue-600" />} right={<span className="text-xs text-slate-500">click a trade for its risk calculation</span>}>
      {err && <ErrorNote>{err}</ErrorNote>}
      {rows && !rows.length && <Empty title="No paper trades yet" />}
      {rows && rows.length > 0 && (
        <div className="scroll-thin max-h-96 overflow-auto">
          <table className="w-full min-w-[860px] text-xs">
            <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900">
              <tr><th className="py-1.5">Date</th><th>Contract</th><th>Side</th><th className="text-right">Risk %</th><th className="text-right">Capital</th>
                <th className="text-right">Risk ₹</th><th className="text-right">Stop dist.</th><th className="text-right">Lots × qty</th>
                <th className="text-right">Max loss</th><th className="text-right">Gross</th><th className="text-right">Charges</th><th className="text-right">Net</th><th className="text-right">R:R</th></tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const r = t.risk;
                const ch = t.charges?.total ?? null;
                return (
                  <tr key={t.id} onClick={() => setSel(t)} className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60 ${sel?.id === t.id ? "bg-blue-50 dark:bg-blue-950/40" : ""}`}>
                    <td className="py-1.5">{dmy(t.day)} {hm(t.entry_ts)}</td>
                    <td>{num(t.strike, 0)} {t.opt_type}</td>
                    <td><Pill tone={t.direction === "Bullish" ? "good" : "bad"}>{t.side}</Pill></td>
                    <td className="num text-right">{r ? `${num(r.risk_pct, 2)}%` : "—"}</td>
                    <td className="num text-right">{r ? inr(r.capital, false, 0) : "—"}</td>
                    <td className="num text-right">{r?.risk_amount != null ? inr(r.risk_amount, false, 0) : "—"}</td>
                    <td className="num text-right">{r?.stop_distance != null ? num(r.stop_distance) : "—"}</td>
                    <td className="num text-right">{r ? `${r.lots} × ${r.lot_size}` : `${t.qty}`}</td>
                    <td className="num text-right text-loss">{r?.max_loss != null ? inr(-r.max_loss, false, 0) : "—"}</td>
                    <td className={`num text-right ${pnlClass(t.gross)}`}>{t.gross != null ? inr(t.gross, true) : "open"}</td>
                    <td className="num text-right text-orange-600">{ch != null ? inr(ch + (t.slippage ?? 0)) : "—"}</td>
                    <td className={`num text-right font-semibold ${pnlClass(t.net)}`}>{t.net != null ? inr(t.net, true) : "—"}</td>
                    <td className="num text-right">{r?.risk_reward ? `1:${num(r.risk_reward, 1)}` : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {sel && (
        <div className="mt-4 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
          <div className="flex items-center justify-between gap-2">
            <div className="font-semibold">{sel.trading_symbol} · {sel.side} · {dmy(sel.day)}</div>
            <Button onClick={() => setSel(null)}><X size={14} /></Button>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Entry → exit" value={`₹${num(sel.entry_price)} → ${sel.exit_price != null ? `₹${num(sel.exit_price)}` : "open"}`} sub={`${hm(sel.entry_ts)} → ${hm(sel.exit_ts)}`} />
            <Stat label="Exit reason" value={sel.exit_reason ? REASON[sel.exit_reason] ?? sel.exit_reason : "open"} />
            <Stat label="Realised gross" value={sel.gross != null ? inr(sel.gross, true) : "—"} className={pnlClass(sel.gross)} />
            <Stat label="Charges + slippage" value={sel.charges?.total != null ? inr(sel.charges.total + (sel.slippage ?? 0)) : "—"} className="text-orange-600" />
            <Stat label="Net P&L" value={sel.net != null ? inr(sel.net, true) : "—"} className={pnlClass(sel.net)} />
            <Stat label="Stop / target premium" value={`${num(sel.stop_premium)} / ${num(sel.target_premium)}`} />
            <Stat label="Net vs max loss" value={sel.net != null && sel.risk?.max_loss ? `${num((sel.net / sel.risk.max_loss) * 100, 0)}%` : "—"} tip="Net P&L as a share of the maximum loss planned at entry (−100% = full stop-loss)." />
          </div>
          <StopHistory tradeId={sel.id} />
          {sel.risk ? (
            <div className="mt-3">
              <div className="mb-1 flex items-center gap-2 text-sm font-semibold">Risk calculation at entry <Decision r={sel.risk} />
                <span className="text-xs font-normal text-slate-500">{sel.risk.calculated_at ? `calculated ${hm(sel.risk.calculated_at)}` : ""}</span></div>
              <RiskRows r={sel.risk} />
              {sel.risk.checks && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {Object.entries(sel.risk.checks).map(([k, ok]) => <Pill key={k} tone={ok ? "good" : "bad"}>{ok ? "✓" : "✗"} {k.replace(/_/g, " ")}</Pill>)}
                </div>
              )}
            </div>
          ) : <p className="mt-2 text-sm text-slate-500">This trade was taken before risk sizing existed (fixed lots), so it has no stored calculation.</p>}
        </div>
      )}
    </Card>
  );
}

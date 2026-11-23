import { useEffect, useState } from "react";
import { ListChecks, X } from "lucide-react";
import { getBiasTrade } from "../../services/api";
import type { BiasTrade, BiasTradeDetail } from "../../types/api";
import { dmy, hm, inr, num, pnlClass } from "../../utils/format";
import { Card, Pill, Stat } from "../common/Card";
import { Button } from "../common/Controls";
import { Empty, ErrorNote, Loading } from "../common/States";
import { Decision, RiskRows } from "../trading/RiskManagement";
import { IndicatorTable } from "./IndicatorTable";

const REASON: Record<string, string> = {
  opposite_signal: "analysis turned the other way", stop_loss: "stop-loss", target: "target", profit_target: "net profit target", time_exit: "holding-time limit",
  square_off: "15:00 square-off", daily_loss_limit: "daily loss limit", manual_stop: "engine stopped", manual_square_off: "closed manually",
};

/** Everything behind one trade: why it was entered, the checks, the risk, every stop change and why it ended. */
function TradeDetail({ id, onClose }: { id: number; onClose: () => void }) {
  const [d, setD] = useState<BiasTradeDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { getBiasTrade(id).then(setD).catch((e) => setErr((e as Error).message)); }, [id]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const t = d?.trade;
  const a = t?.analysis;
  return (
    <div role="dialog" aria-modal="true" aria-label="Trade reasoning" className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/50 p-0 sm:items-center sm:p-4" onClick={onClose}>
      <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-t-2xl bg-white p-4 shadow-xl dark:bg-slate-900 sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between gap-2">
          <h2 className="text-base font-semibold">{t ? `${t.action ?? t.side} · ${t.trading_symbol} · ${dmy(t.day)}` : "Trade reasoning"}</h2>
          <Button onClick={onClose} variant="ghost" title="Close"><X size={16} /></Button>
        </div>
        {!d && !err && <Loading />}
        {err && <ErrorNote>{err}</ErrorNote>}
        {t && (
          <div className="space-y-4 text-sm">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Entry → exit" value={`₹${num(t.entry_price)} → ${t.exit_price != null ? `₹${num(t.exit_price)}` : "open"}`} sub={`${hm(t.entry_ts)} → ${hm(t.exit_ts)}`} />
              <Stat label="Quantity" value={String(t.qty)} sub={t.risk ? `${t.risk.lots} lot(s) × ${t.risk.lot_size}` : undefined} />
              <Stat label="Stop / target" value={`${t.stop_premium != null ? num(t.stop_premium) : "—"} / ${t.target_premium != null ? num(t.target_premium) : "—"}`} />
              <Stat label="Confidence" value={t.confidence != null ? `${num(t.confidence, 0)}%` : "—"} sub={a?.strategy === "confluence" ? "confirmation score" : a?.strategy === "scored" ? "strategy score of 100" : "indicator agreement"} />
              <Stat label="Gross" value={t.gross != null ? inr(t.gross, true) : "—"} className={pnlClass(t.gross)} />
              <Stat label="Charges + slippage" value={t.charges?.total != null ? inr(t.charges.total + (t.slippage ?? 0)) : "—"} className="text-orange-600" />
              <Stat label="Net P&L" value={t.net != null ? inr(t.net, true) : "open"} className={pnlClass(t.net)} />
              <Stat label="Ended by" value={t.exit_reason ? REASON[t.exit_reason] ?? t.exit_reason : "open"} />
            </div>
            {a ? (
              <>
                <div>
                  <div className="mb-1 font-semibold">Why it was entered</div>
                  <p className="text-slate-600 dark:text-slate-300">{a.summary}.</p>
                  <div className="mt-2 flex flex-wrap gap-1">{a.supports.map((s) => <Pill key={s} tone="good">{s}</Pill>)}{a.against.map((s) => <Pill key={s} tone="bad">against: {s}</Pill>)}</div>
                </div>
                {a.confluence && (
                  <div data-testid="trade-confluence">
                    <div className="mb-1 font-semibold">Confluence at entry · score {num(a.confluence.score, 0)}% (minimum {num(a.confluence.min_score, 0)}%)</div>
                    <ul className="space-y-0.5 text-xs">
                      {a.confluence.factors.filter((f) => f.enabled).map((f) => (
                        <li key={f.key}><b>{f.label}</b> ({f.vote != null ? num(f.vote, 1) : "n/a"}{f.required ? ", required" : ""}): {f.condition}</li>))}
                      <li><b>ADR</b>: {a.confluence.adr.text}</li>
                    </ul>
                  </div>
                )}
                {a.scored && (
                  <div data-testid="trade-scored">
                    <div className="mb-1 font-semibold">Scored strategy at entry · {num(a.scored.score, 0)} / 100 (minimum {num(a.scored.min_score, 0)}) · {a.scored.entry_tf}m entry, {a.scored.confirm_tf}m trend</div>
                    <ul className="space-y-0.5 text-xs">
                      {a.scored.components.map((c) => <li key={c.key}><b>{c.label}</b> ({num(c.points, 0)} / {c.max}): {c.condition}</li>)}
                    </ul>
                  </div>
                )}
                {a.contract_checks && a.contract_checks.length > 0 && (
                  <div>
                    <div className="mb-1 font-semibold">Contract checks</div>
                    <ul className="space-y-0.5 text-xs">{a.contract_checks.map((c) => (
                      <li key={c.check} className="flex items-start gap-1.5"><span aria-hidden>{c.ok === true ? "✓" : c.ok === false ? "✗" : "–"}</span><span>{c.text}</span></li>))}</ul>
                  </div>
                )}
                <IndicatorTable rows={a.indicators} title="Every strategy at entry" tf={[a.tf_primary ?? 5, a.tf_confirm ?? 15]} />
              </>
            ) : <p className="text-slate-500">No stored analysis for this trade.</p>}
            {t.risk && (
              <div>
                <div className="mb-1 flex items-center gap-2 font-semibold">Risk calculation <Decision r={t.risk} /></div>
                <RiskRows r={t.risk} />
              </div>
            )}
            {d.stop_changes.length > 0 && (
              <div>
                <div className="mb-1 font-semibold">Stop-loss history</div>
                {d.stop_changes.map((s) => (
                  <div key={s.ts + s.new_stop} className="flex flex-wrap justify-between gap-2 border-t border-slate-100 py-1 text-xs dark:border-slate-800">
                    <span>{hm(s.ts)} · {s.source === "entry" ? "set at entry" : s.source === "trail" ? "trailing stop" : "changed by you"}{s.note ? ` (${s.note})` : ""}</span>
                    <span className="num">{s.old_stop != null ? `₹${num(s.old_stop)} → ` : ""}₹{num(s.new_stop)}</span>
                  </div>
                ))}
              </div>
            )}
            {t.exit_detail && (
              <div>
                <div className="mb-1 font-semibold">How it ended</div>
                <p className="text-xs text-slate-600 dark:text-slate-300">
                  {REASON[t.exit_detail.reason] ?? t.exit_detail.reason} at ₹{num(t.exit_detail.exit_premium)}; best premium seen {t.exit_detail.best_premium != null ? `₹${num(t.exit_detail.best_premium)}` : "—"};
                  stop at exit {t.exit_detail.stop_at_exit != null ? `₹${num(t.exit_detail.stop_at_exit)}` : "—"}. Analysis then: {t.exit_detail.bias_at_exit?.bias ?? "—"}, 15m {t.exit_detail.bias_at_exit?.trend_15m ?? "—"}, 5m {t.exit_detail.bias_at_exit?.trend_5m ?? "—"}.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** The day's automated trades. Click one for its complete reasoning. */
export function TradeTable({ rows, day }: { rows: BiasTrade[]; day: string }) {
  const [sel, setSel] = useState<number | null>(null);
  return (
    <Card title="Orders and positions" icon={<ListChecks size={16} className="text-blue-600" />} right={<span>{day} · click a trade for its reasoning</span>}>
      {rows.length === 0 ? <Empty title="No automated trades yet">The engine only trades when the 15-minute trend, the 5-minute confirmation and the confidence all agree. It never forces trades.</Empty> : (
        <div className="scroll-thin max-h-96 overflow-auto">
          <table className="w-full min-w-[820px] text-xs">
            <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900">
              <tr><th className="py-1.5">Entry</th><th>Order</th><th>Contract</th><th className="text-right">Qty</th><th className="text-right">Entry ₹</th><th className="text-right">Exit ₹</th>
                <th className="text-right">Stop</th><th className="text-right">Target</th><th className="text-right">Conf.</th><th>Ended by</th><th className="text-right">Net</th></tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id} onClick={() => setSel(t.id)} tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") setSel(t.id); }}
                  className="cursor-pointer border-t border-slate-100 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/60">
                  <td className="py-1.5">{hm(t.entry_ts)}</td>
                  <td><Pill tone={t.direction === "Bullish" ? "good" : "bad"}>{t.action ?? `${t.side} ${t.opt_type}`}</Pill></td>
                  <td>{num(t.strike, 0)} {t.opt_type}</td>
                  <td className="num text-right">{t.qty}</td>
                  <td className="num text-right">{num(t.entry_price)}</td>
                  <td className="num text-right">{t.exit_price != null ? num(t.exit_price) : <Pill tone="info">open</Pill>}</td>
                  <td className="num text-right">{t.stop_premium != null ? num(t.stop_premium) : "—"}</td>
                  <td className="num text-right">{t.target_premium != null ? num(t.target_premium) : "—"}</td>
                  <td className="num text-right">{t.confidence != null ? `${num(t.confidence, 0)}%` : "—"}</td>
                  <td>{t.exit_reason ? REASON[t.exit_reason] ?? t.exit_reason : "—"}</td>
                  <td className={`num text-right font-semibold ${pnlClass(t.net)}`}>{t.net != null ? inr(t.net, true) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sel != null && <TradeDetail id={sel} onClose={() => setSel(null)} />}
    </Card>
  );
}

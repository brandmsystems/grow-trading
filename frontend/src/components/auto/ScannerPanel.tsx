import { useMemo, useState } from "react";
import { Radar } from "lucide-react";
import type { BiasConfig, BiasSettings, Position, ScanBlock, ScanOpp } from "../../types/api";
import { hm, inr, num, pnlClass } from "../../utils/format";
import { Card, Pill, type Tone } from "../common/Card";
import { Button, Field, inputCls } from "../common/Controls";
import { Check, Num } from "./AutoSettings";

const EVIDENCE_TONE: Record<string, Tone> = { positive: "good", insufficient: "warn", negative: "bad" };
const DECISION_TONE: Record<string, Tone> = { ENTER: "good", REJECTED: "warn", HOLD: "neutral", CANDIDATE: "info", OFF: "neutral" };

/** Buying and writing are different risks: say which one an action is. */
export const actionKind = (a: string | null | undefined) => (!a ? null : a.startsWith("SELL") ? "option writing (unlimited-loss side: margin and a stop apply)" : a.startsWith("BUY") ? "option buying (loss limited to the premium)" : null);

function Quality({ o }: { o: ScanOpp }) {
  const [open, setOpen] = useState(false);
  if (o.quality == null) return <span className="text-slate-400">—</span>;
  return (
    <div>
      <button type="button" className="num font-medium underline decoration-dotted" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={`Score of ${o.label}`}>{num(o.quality, 1)} / 100</button>
      {open && (
        <ul className="mt-1 space-y-0.5 text-[11px] text-slate-600 dark:text-slate-300" data-testid={`scan-components-${o.strategy}`}>
          {o.components.map((c) => (
            <li key={c.key}><b>{c.label}</b> <span className="num">{num(c.points, 1)}/{c.max}</span> · {c.note}</li>))}
          <li className="text-slate-500">The candle part only; liquidity, Greeks and reward/risk are added when the contract is checked (see the trade's reasoning).</li>
        </ul>)}
    </div>
  );
}

/** The continuous opportunity scanner: strategy evidence, live opportunities with their decisions and scores, every open position,
 *  the refused signals with exact reasons, and the portfolio risk limits. Paper and replay only. */
export function ScannerPanel({ scan, positions = [], s, set, cfg, running, onApply, busy, msg, tradesToday, cap, preset }: {
  scan: ScanBlock | null | undefined; positions?: Position[]; s: BiasSettings; set: (p: Partial<BiasSettings>) => void; cfg?: BiasConfig["scanner"]; running: boolean;
  onApply: () => void; busy: boolean; msg: { ok: boolean; text: string } | null; tradesToday: number; cap: number | null; preset?: Partial<BiasSettings>;
}) {
  const [fStrategy, setFStrategy] = useState("all");
  const [fType, setFType] = useState("all");
  const [fSide, setFSide] = useState("all");
  const opps = scan?.state?.opportunities ?? [];
  const shown = useMemo(() => opps.filter((o) => o.state !== "off" && o.state !== "blocked" && (fStrategy === "all" || o.strategy === fStrategy)
    && (fType === "all" || (o.action ?? (o.direction > 0 ? "BUY CE" : "BUY PE")).endsWith(fType)) && (fSide === "all" || (o.action ?? "BUY").startsWith(fSide))), [opps, fStrategy, fType, fSide]);
  const rejected = (scan?.rejected ?? []).filter((r) => fStrategy === "all" || r.strategy === fStrategy);
  const openPositions = positions.filter((p) => (fStrategy === "all" || p.strategy === fStrategy) && (fType === "all" || p.opt_type === fType) && (fSide === "all" || p.side === fSide));
  const risk = scan?.open_risk ?? 0;
  const active = s.entry_strategy === "scanner";
  return (
    <Card title="Continuous opportunity scanner" icon={<Radar size={16} className="text-violet-600" />} accent="strat"
      right={active ? "active entry strategy · paper only" : "select the Scanner entry strategy to use it"}>
      <div className="space-y-4" data-testid="scanner">
        <p className="text-xs text-slate-600 dark:text-slate-300">Every closed {s.timeframe}-minute candle, each strategy that is ON in Trading Settings is evaluated on its own; the {s.bias_confirm_tf}-minute trend confirms the direction.
          Qualified opportunities are ranked by quality score and taken when every limit allows. Nothing is forced and there is <b>no fixed daily trade count</b>: the risk limits below bound the day.
          The score counts sound conditions met; <b>it is not a probability of winning</b>, and no strategy has shown an edge after costs.</p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="scan-stats">
          <div><div className="text-[11px] uppercase tracking-wide text-slate-500">Candles scanned</div><div className="num text-lg font-semibold">{scan?.candles_scanned ?? 0}</div></div>
          <div><div className="text-[11px] uppercase tracking-wide text-slate-500">Open positions</div><div className="num text-lg font-semibold">{scan?.open_positions ?? positions.length} of {s.max_open_positions}</div></div>
          <div><div className="text-[11px] uppercase tracking-wide text-slate-500">Open risk</div><div className="num text-lg font-semibold">{inr(risk, false, 0)}</div></div>
          <div><div className="text-[11px] uppercase tracking-wide text-slate-500">Trades today</div><div className="num text-lg font-semibold" data-testid="scan-trades">{tradesToday}{cap ? ` of ${cap}` : ""}</div>
            <div className="text-[11px] text-slate-500">{cap ? "capped by your setting" : "no count cap"}</div></div>
        </div>

        <div className="flex flex-wrap items-end gap-3" data-testid="scan-filters">
          <Field label="Strategy"><select className={inputCls} value={fStrategy} aria-label="Filter by strategy" onChange={(e) => setFStrategy(e.target.value)}>
            <option value="all">All strategies</option>{(cfg?.strategies ?? []).map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}</select></Field>
          <Field label="Option"><select className={inputCls} value={fType} aria-label="Filter by CE or PE" onChange={(e) => setFType(e.target.value)}>
            <option value="all">CE and PE</option><option value="CE">CE</option><option value="PE">PE</option></select></Field>
          <Field label="Side"><select className={inputCls} value={fSide} aria-label="Filter by buy or sell" onChange={(e) => setFSide(e.target.value)}>
            <option value="all">Buy and sell</option><option value="BUY">BUY (option buying)</option><option value="SELL">SELL (option writing)</option></select></Field>
          <Field label="Timeframe"><select className={inputCls} value={s.timeframe} aria-label="Scanner timeframe" disabled={running} onChange={(e) => set({ timeframe: Number(e.target.value) })}>
            <option value={5}>5 minutes</option><option value={15}>15 minutes</option></select></Field>
        </div>

        <div data-testid="scan-opps">
          <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-semibold">Opportunities on the latest candle
            {scan?.state && <><span className="font-normal text-slate-500">{hm(scan.state.bar_close)}</span><Pill tone={scan.state.decision === "BUY" ? "good" : "neutral"}>{scan.state.decision}</Pill></>}</div>
          {!scan?.state ? <p className="text-sm text-slate-500" data-testid="scan-empty">Start paper trading with the Scanner strategy: each closed candle appears here with every strategy's decision, score and reasons.</p> : shown.length === 0 ? (
            <p className="text-sm text-slate-500">No strategy matches the filters on this candle.</p>) : (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[640px] text-xs">
                <thead className="text-left text-slate-500"><tr><th className="py-1.5">Strategy</th><th>Decision</th><th>Action</th><th>Score</th><th>Validated result</th><th className="pl-2">Reason</th></tr></thead>
                <tbody>
                  {shown.map((o) => (
                    <tr key={o.strategy} className="border-t border-slate-100 align-top dark:border-slate-800" data-testid={`scan-row-${o.strategy}`}>
                      <td className="py-1.5 font-medium">{o.label}</td>
                      <td><Pill tone={DECISION_TONE[o.decision] ?? "neutral"}>{o.decision === "ENTER" ? "BUY" : o.decision === "REJECTED" ? "REJECTED" : o.state === "signal" ? "CANDIDATE" : "HOLD"}</Pill></td>
                      <td title={actionKind(o.action) ?? undefined}>{o.action ?? "—"}</td>
                      <td><Quality o={o} /></td>
                      <td><Pill tone={EVIDENCE_TONE[o.evidence.status]}>{o.evidence.label}</Pill></td>
                      <td className="pl-2 text-slate-600 dark:text-slate-300">{o.reasons.join("; ") || "—"}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
        </div>

        <div data-testid="scan-positions">
          <div className="mb-1 text-xs font-semibold">Open positions across strategies</div>
          {openPositions.length === 0 ? <p className="text-xs text-slate-500">None open.</p> : (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full min-w-[640px] text-xs">
                <thead className="text-left text-slate-500"><tr><th className="py-1">Strategy</th><th>Contract</th><th>Kind</th><th className="text-right">Qty</th><th className="text-right">Entry</th><th className="text-right">Stop</th><th className="text-right">Target</th><th className="text-right">Risk</th><th className="text-right">Open P&L</th></tr></thead>
                <tbody>
                  {openPositions.map((p) => (
                    <tr key={p.id ?? p.trading_symbol} className="border-t border-slate-100 dark:border-slate-800">
                      <td className="py-1">{p.strategy ?? "—"}{p.quality != null && <span className="text-slate-500"> · {num(p.quality, 0)}</span>}</td>
                      <td>{p.side} {p.opt_type} {p.strike}</td>
                      <td title={actionKind(`${p.side} ${p.opt_type}`) ?? undefined}>{p.side === "SELL" ? "writing" : "buying"}</td>
                      <td className="num text-right">{p.qty}</td><td className="num text-right">{num(p.entry_price)}</td>
                      <td className="num text-right">{p.stop_premium != null ? num(p.stop_premium) : "—"}</td><td className="num text-right">{p.target_premium != null ? num(p.target_premium) : "—"}</td>
                      <td className="num text-right">{p.risk_amount != null ? inr(p.risk_amount, false, 0) : "—"}</td>
                      <td className={`num text-right font-medium ${pnlClass(p.mtm)}`}>{p.mtm != null ? inr(p.mtm, true, 0) : "—"}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
        </div>

        <div data-testid="scan-rejected">
          <div className="mb-1 text-xs font-semibold">Rejected signals, with the exact reason</div>
          {rejected.length === 0 ? <p className="text-xs text-slate-500">None yet.</p> : (
            <div className="scroll-thin max-h-56 overflow-auto">
              <table className="w-full min-w-[520px] text-xs">
                <thead className="text-left text-slate-500"><tr><th className="py-1">Candle</th><th>Strategy</th><th>Direction</th><th className="pl-2">Why it was refused</th></tr></thead>
                <tbody>
                  {rejected.map((r, i) => (
                    <tr key={`${r.bar_close}${r.strategy}${i}`} className="border-t border-slate-100 align-top dark:border-slate-800">
                      <td className="num py-1">{hm(r.bar_close)}</td><td>{r.strategy ?? "—"}</td><td>{r.direction}</td><td className="pl-2 text-slate-600 dark:text-slate-300">{r.reason}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
        </div>

        <div>
          <div className="mb-2 text-xs font-semibold">Risk limits (virtual capital and risk per trade are under Settings; every limit applies to the next entry)</div>
          <div className="grid grid-cols-2 items-end gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Num label="Maximum open positions" k="max_open_positions" s={s} set={set} min={1} max={20} />
            <Num label="Positions per strategy" k="max_strategy_positions" s={s} set={set} min={1} max={20} />
            <Num label="Maximum total open risk" unit="% of capital, 0 = off" k="max_open_risk_pct" s={s} set={set} step={0.5} max={100} />
            <Num label="Maximum open risk per strategy" unit="% of capital, 0 = off" k="max_strategy_risk_pct" s={s} set={set} step={0.25} max={100} />
            <Num label="Minimum quality score" unit="of 100" k="scan_min_quality" s={s} set={set} step={5} max={100} />
            <Num label="Daily trade cap" unit="0 = no cap" k="max_trades_per_day" s={s} set={set} min={0} max={1000} />
          </div>
          <div className="mt-2"><Check label="Also trade strategies without a validated positive result (research use)" on={s.scan_allow_unvalidated} onChange={(v) => set({ scan_allow_unvalidated: v })}
            hint="Every strategy tested so far has a negative result after costs. Off: the scanner trades only validated-positive strategies, which today means none." /></div>
          <p className="mt-1 text-xs text-slate-500" data-testid="scan-evidence-note">{cfg?.note ?? "Strategies with a negative or missing validated result trade only if you allow them."} Every strategy tested so far is labelled negative.</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={!preset} onClick={() => preset && set(preset)}>Use the scanner preset</Button>
          <Button variant="primary" onClick={onApply} disabled={busy}>{running ? "Apply scanner settings" : "Save scanner settings"}</Button>
          {msg && <span role="status" data-testid="scan-msg" className={`text-xs ${msg.ok ? "text-gain" : "text-red-600"}`}>{msg.text}</span>}
        </div>
      </div>
    </Card>
  );
}

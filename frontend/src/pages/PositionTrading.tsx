import { useMemo, useState } from "react";
import { CalendarClock, RefreshCw } from "lucide-react";
import { useApi } from "../hooks/useApi";
import {
  getPositionAccount, getPositionAnalysis, getPositionBacktest, getPositionChart, getPositionConfig, getPositionDecisions, getPositions, managePositions, openPosition,
  recordPositionDecision, resetPositionAccount, savePositionSettings,
} from "../services/api";
import type { PosOpportunity, PosSettings, PositionDecision } from "../types/api";
import { dmy, inr, num, pct, pnlClass } from "../utils/format";
import { useSettings } from "../context/SettingsContext";
import { Card, Pill, Stat, type Tone } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, Segmented } from "../components/common/Controls";
import { ErrorNote, Limitation, Loading, Warning } from "../components/common/States";
import { BarsChart, LineChart } from "../components/charts/SeriesChart";

const TONE: Record<PositionDecision, Tone> = { "STRONG BUY CE": "good", "BUY CE": "good", "STRONG BUY PE": "bad", "BUY PE": "bad", HOLD: "neutral", "NO TRADE": "warn" };
const TREND_TONE = (w: string): Tone => (w.includes("up") ? "good" : w.includes("down") ? "bad" : "neutral");
const EVID: Record<string, Tone> = { positive: "good", insufficient: "warn", negative: "bad", none: "neutral" };
const dayOf = (iso: string) => iso.slice(0, 10);

function Score({ o }: { o: PosOpportunity }) {
  return (
    <table className="w-full text-xs" data-testid={`pos-components-${o.type}`}>
      <tbody>
        {o.components.map((c) => (
          <tr key={c.key} className="border-t border-slate-100 align-top dark:border-slate-800">
            <td className="py-1 font-medium">{c.label}</td><td className="num text-right">{num(c.points, 1)} / {c.max}</td><td className="pl-2 text-slate-600 dark:text-slate-300">{c.note}</td>
          </tr>))}
      </tbody>
    </table>
  );
}

/** Position Trading: multi-day / multi-week NIFTY option ideas, scored and explained, with a separate virtual account. Paper only. */
export default function PositionTrading() {
  const { settings: ui } = useSettings();
  const dark = ui.theme === "dark";
  const analysis = useApi(() => getPositionAnalysis(), []);
  const cfg = useApi(getPositionConfig, []);
  const account = useApi(getPositionAccount, []);
  const positions = useApi(getPositions, []);
  const decisions = useApi(getPositionDecisions, []);
  const bt = useApi(getPositionBacktest, []);
  const [tf, setTf] = useState<"D" | "W">("D");
  const chart = useApi(() => getPositionChart(tf), [tf]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<PosSettings | null>(null);
  const [capital, setCapital] = useState("");
  const [calc, setCalc] = useState({ capital: "500000", risk: "1", premium: "150", lot: "65", stop: "35" });
  const a = analysis.data;
  const s = draft ?? cfg.data?.settings.config ?? null;

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); await Promise.all([analysis.reload(), account.reload(), positions.reload(), decisions.reload()]); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  };

  const closes = useMemo(() => (chart.data?.bars ?? []).map((b) => ({ t: dayOf(b.t), b })), [chart.data]);
  const series = useMemo(() => [
    { name: "Close", color: dark ? "#e2e8f0" : "#0f172a", data: closes.map((x) => ({ time: x.t, value: x.b.c })) },
    ...([["e20", "EMA 20", "#3b82f6"], ["e50", "EMA 50", "#f97316"], ["e100", "EMA 100", "#8b5cf6"], ["e200", "EMA 200", "#ef4444"]] as const).map(([k, name, color]) => ({
      name, color, data: closes.filter((x) => x.b[k] != null).map((x) => ({ time: x.t, value: x.b[k] as number })) })),
  ], [closes, dark]);

  const monthly = useMemo(() => {
    const m: Record<string, number> = {};
    for (const c of bt.data?.cells ?? []) for (const [k, v] of Object.entries(c.by_month)) m[k] = (m[k] ?? 0) + v;
    return Object.entries(m).sort().map(([k, v]) => ({ time: `${k}-01`, value: v }));
  }, [bt.data]);

  const open = positions.data?.filter((p) => p.status === "OPEN") ?? [];
  const closed = positions.data?.filter((p) => p.status === "CLOSED") ?? [];
  const calcLots = (() => {
    const c = Number(calc.capital), r = Number(calc.risk), p = Number(calc.premium), l = Number(calc.lot), st = Number(calc.stop);
    if (![c, r, p, l, st].every((x) => x > 0)) return null;
    const perLot = p * (st / 100) * l;
    return { perLot, lots: Math.floor((c * r / 100) / perLot), cost: p * l };
  })();

  return (
    <div className="space-y-4">
      <PageHeader title="Position Trading" subtitle="Multi-day and multi-week NIFTY option ideas from completed weekly, daily and 4-hour candles. Paper trading only."
        actions={<Button disabled={busy} onClick={() => void analysis.reload()}><RefreshCw size={14} />Refresh analysis</Button>} />

      <Card accent="strat" bodyClass="p-4">
        <p className="text-sm" data-testid="pos-paper-note">Paper trading only: this page cannot place a real order. The score counts sound conditions met, <b>it is not a probability of winning</b>, and no strategy here has a validated edge: see the backtest below.</p>
        {msg && <p role="status" className={`mt-2 text-xs ${msg.ok ? "text-gain" : "text-red-600"}`} data-testid="pos-msg">{msg.text}</p>}
      </Card>

      {analysis.loading && !a && <Card><Loading text="Analysing weekly, daily and 4-hour candles…" /></Card>}
      {analysis.error && <ErrorNote>{analysis.error}</ErrorNote>}
      {a?.settings_error && <Warning>The saved position settings could not be used ({a.settings_error}); defaults are shown and automatic entries are blocked.</Warning>}

      {a && (
        <Card title="Decision" right={a.day ? `completed daily bar of ${dmy(a.day)}` : ""} accent={a.decision.includes("CE") ? "gain" : a.decision.includes("PE") ? "loss" : "neutral"}>
          <div className="flex flex-wrap items-center gap-4">
            <span data-testid="pos-decision"><Pill tone={TONE[a.decision]}>{a.decision}</Pill></span>
            <div className="num text-2xl font-bold" data-testid="pos-score">{a.score != null ? num(a.score, 1) : "—"}<span className="text-sm font-normal text-slate-500"> / 100</span></div>
          </div>
          <ul className="mt-2 list-disc pl-5 text-sm text-slate-700 dark:text-slate-200" data-testid="pos-reasons">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </Card>
      )}

      {a?.market && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Market trend and regime" className="lg:col-span-1">
            <div className="text-lg font-semibold" data-testid="pos-regime">{a.market.regime.label}</div>
            <p className="text-xs text-slate-500">{a.market.regime.why}</p>
            <div className="mt-3 flex flex-wrap gap-2" data-testid="pos-timeframes">
              {([["Weekly", a.market.timeframes.weekly], ["Daily", a.market.timeframes.daily], ["4-hour", a.market.timeframes.h4], ["1-hour", a.market.timeframes.h1]] as const).map(([k, v]) => (
                <div key={k} className="text-xs"><div className="text-slate-500">{k}</div><Pill tone={TREND_TONE(v)}>{v}</Pill></div>))}
            </div>
            <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
              {(["rsi", "adx", "atr_pct"] as const).map((k) => <Stat key={k} label={k === "atr_pct" ? "ATR %" : k.toUpperCase()} value={a.market!.values[k] != null ? num(a.market!.values[k] as number, 1) : "—"} />)}
            </div>
            <div className="mt-3 text-xs" data-testid="pos-context">
              {a.context?.available ? (<><div className="font-semibold">Pre-market context ({a.context.bias})</div><ul className="mt-1 space-y-0.5">{a.context.factors?.map((f) => <li key={f.key}>{f.label}: {f.available ? f.summary : "not available"}</li>)}</ul><p className="mt-1 text-slate-500">{a.context.note}</p></>)
                : <p className="text-slate-500">VIX, global markets, crude and FII/DII: {a.context?.why}</p>}
            </div>
          </Card>
          <Card title="Trend chart" className="lg:col-span-2" right={<Segmented value={tf} options={[{ value: "D", label: "Daily" }, { value: "W", label: "Weekly" }]} onChange={setTf} />}>
            {chart.loading && !chart.data ? <Loading /> : chart.error ? <ErrorNote>{chart.error}</ErrorNote> : <LineChart series={series} dark={dark} height={300} />}
          </Card>
        </div>
      )}

      {a?.comparison && (
        <Card title="BUY CE or BUY PE: contract comparison" right="premiums: the decision day's stored prices, or a live Groww quote when those are not stored yet; theta is a model value, IV and delta come from Groww when live">
          <div className="grid gap-4 md:grid-cols-2" data-testid="pos-comparison">
            {(["CE", "PE"] as const).map((k) => {
              const c = a.comparison![k];
              return (
                <div key={k} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
                  <div className="flex items-center justify-between"><b>BUY {k}</b><span className="num text-xs">candle score {num(c.candle_score, 1)} + contract {c.contract_quality != null ? num(c.contract_quality, 1) : "—"}</span></div>
                  {c.best ? <p className="mt-1 text-sm">{dmy(c.best.expiry)} {c.best.strike} {k} @ ₹{num(c.best.premium)} · {c.best.dte} days</p> : <p className="mt-1 text-sm text-slate-500">No usable contract.</p>}
                  <ul className="mt-1 space-y-0.5 text-xs text-slate-600 dark:text-slate-300">{c.explanation.map((e) => <li key={e}>{e}</li>)}</ul>
                  {c.best?.estimate.available && <p className="mt-1 text-xs text-slate-500">IV ≈ {num((c.best.estimate.iv ?? 0) * 100, 1)}%, delta ≈ {c.best.estimate.delta}, theta ≈ {c.best.estimate.theta_pct_day}% a day. {c.best.estimate.note}</p>}
                  <p className="mt-1 text-xs text-slate-500">Bid-ask spread: not stored historically (checked live when Groww is connected).</p>
                </div>);
            })}
          </div>
        </Card>
      )}

      {a && (
        <Card title="Best available opportunities" right={`${a.opportunities.length} with a strategy signal`}>
          {a.opportunities.length === 0 && <p className="text-sm text-slate-500" data-testid="pos-no-opps">No valid setup: no enabled strategy has a signal on the last completed daily bars. Nothing is forced.</p>}
          <div className="space-y-4">
            {a.opportunities.map((o) => (
              <div key={o.type} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800" data-testid={`pos-opp-${o.type}`}>
                <div className="flex flex-wrap items-center gap-3"><Pill tone={TONE[o.decision]}>{o.decision}</Pill><span className="num font-semibold">{num(o.score, 1)} / 100</span>
                  <span className="text-xs text-slate-500">{o.strategy_labels.join(" + ")}</span>
                  {o.evidence.map((e, i) => <Pill key={i} tone={EVID[e.status]}>{e.label}</Pill>)}</div>
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">{o.why}{o.gates.length ? `; ${o.gates.join("; ")}` : ""}</p>
                <div className="mt-2 grid gap-4 lg:grid-cols-2"><Score o={o} />
                  {o.plan && (
                    <div className="text-xs" data-testid={`pos-plan-${o.type}`}>
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                        <Stat label="Entry range" value={`₹${num(o.plan.entry.low)}–${num(o.plan.entry.high)}`} sub={`last ₹${num(o.plan.entry.premium)}`} />
                        <Stat label="Premium stop" value={`₹${num(o.plan.stop_premium)}`} /><Stat label="Target 1 / 2" value={`₹${num(o.plan.target1)} / ${num(o.plan.target2)}`} />
                        <Stat label="NIFTY invalidation" value={o.plan.invalidation != null ? num(o.plan.invalidation, 0) : "—"} />
                        <Stat label="Holding" value={`${o.plan.hold_days} days`} sub={`exit by ${dmy(o.plan.planned_exit)}`} />
                        <Stat label="Risk / reward" value={o.plan.risk_reward.ratio != null ? `${o.plan.risk_reward.ratio}R` : "—"} sub="after costs" />
                        <Stat label="Lots / qty" value={`${o.plan.lots} / ${o.plan.qty}`} /><Stat label="Max loss" value={o.plan.max_loss != null ? inr(o.plan.max_loss, false, 0) : "—"} />
                        <Stat label="Capital required" value={o.plan.capital_required != null ? inr(o.plan.capital_required, false, 0) : "—"} />
                      </div>
                      <p className="mt-2 text-slate-500">{o.plan.trailing}. {o.plan.invalidation_note}.</p>
                      <ul className="mt-1 list-disc pl-4 text-orange-700 dark:text-orange-300">{o.plan.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
                      <p className="mt-1 text-slate-500">Backtested rules: {o.plan.backtested_rules}. Target 2, trailing and the invalidation level are management aids that were not backtested.</p>
                      <div className="mt-2"><Button variant="primary" disabled={busy || !o.decision.includes("BUY")} onClick={() => void act(() => openPosition(o.direction), `Paper position opened for ${o.type}.`)}>Open paper position ({o.type})</Button></div>
                    </div>)}
                </div>
              </div>))}
          </div>
        </Card>
      )}

      {a && cfg.data && s && (
        <Card title="Strategies and settings" right={`settings version ${cfg.data.settings.version}`}>
          <div className="scroll-thin overflow-x-auto"><table className="w-full min-w-[560px] text-xs" data-testid="pos-strategies">
            <thead className="text-left text-slate-500"><tr><th className="py-1">On</th><th>Strategy</th><th>Signal</th><th>Validated result</th></tr></thead>
            <tbody>{a.strategies.map((r) => (
              <tr key={r.key} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1"><input type="checkbox" aria-label={`Enable ${r.label}`} checked={s.strategies[r.key]?.enabled ?? true}
                  onChange={(e) => setDraft({ ...s, strategies: { ...s.strategies, [r.key]: { ...s.strategies[r.key], enabled: e.target.checked } } })} /></td>
                <td className="font-medium">{r.label}</td>
                <td>{r.signal > 0 ? <Pill tone="good">BUY CE</Pill> : r.signal < 0 ? <Pill tone="bad">BUY PE</Pill> : <span className="text-slate-400">none</span>}</td>
                <td><Pill tone={EVID[r.evidence.status]}>{r.evidence.label}</Pill> <span className="text-slate-500">{r.evidence.note}</span></td>
              </tr>))}</tbody></table></div>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" data-testid="pos-risk-settings">
            {(Object.entries(cfg.data.risk_schema)).map(([k, m]) => (
              <Field key={k} label={m.label}><input type="number" className={inputCls} aria-label={m.label} min={m.min} max={m.max} step={m.type === "int" ? 1 : 0.25} value={(s.risk as unknown as Record<string, number>)[k]}
                onChange={(e) => setDraft({ ...s, risk: { ...s.risk, [k]: Number(e.target.value) } })} /></Field>))}
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={s.auto_enter} onChange={(e) => setDraft({ ...s, auto_enter: e.target.checked })} />Enter automatically after the close (needs a validated positive strategy; none has one today)</label>
          <div className="mt-3"><Button variant="primary" disabled={busy || !draft} onClick={() => void act(async () => { await savePositionSettings(draft as PosSettings); setDraft(null); await cfg.reload(); }, "Settings saved.")}>Save settings</Button></div>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Risk and capital calculator" right="approximate: excludes brokerage and slippage; the paper entry uses the exact sizing">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5" data-testid="pos-calc">
            {([["capital", "Capital ₹"], ["risk", "Risk %"], ["premium", "Premium ₹"], ["lot", "Lot size"], ["stop", "Stop %"]] as const).map(([k, l]) => (
              <Field key={k} label={l}><input className={inputCls} aria-label={l} inputMode="decimal" value={calc[k]} onChange={(e) => setCalc({ ...calc, [k]: e.target.value })} /></Field>))}
          </div>
          <p className="mt-2 text-sm" data-testid="pos-calc-out">{calcLots ? `Risk per lot ₹${num(calcLots.perLot, 0)} · ${calcLots.lots} lot(s) · cost of one lot ₹${num(calcLots.cost, 0)}` : "Enter positive numbers."}</p>
        </Card>
        <Card title="Virtual position account" right="separate from the intraday paper account">
          {account.data && (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3" data-testid="pos-account">
              <Stat label="Balance" value={inr(account.data.state.balance, false, 0)} sub={`start ${inr(account.data.state.starting_capital, false, 0)}`} />
              <Stat label="Equity" value={inr(account.data.state.equity, false, 0)} sub={`open P&L ${inr(account.data.state.open_pnl, true, 0)}`} />
              <Stat label="Realised" value={inr(account.data.state.realised, true, 0)} className={pnlClass(account.data.state.realised)} />
              <Stat label="Exposure" value={pct(account.data.state.exposure_pct)} sub={`${account.data.state.open_positions} open`} />
              <Stat label="Open risk" value={inr(account.data.state.open_risk, false, 0)} sub={pct(account.data.state.open_risk_pct)} />
              <Stat label="Max drawdown" value={inr(account.data.state.max_drawdown, false, 0)} />
            </div>)}
          <div className="mt-3 flex flex-wrap items-end gap-2"><Field label="New virtual capital ₹"><input className={`${inputCls} w-40`} aria-label="New virtual capital" inputMode="decimal" value={capital} onChange={(e) => setCapital(e.target.value)} /></Field>
            <Button disabled={busy || !Number(capital)} onClick={() => void act(() => resetPositionAccount(Number(capital)), "New account started; earlier trades are kept.")}>Start a new account</Button>
            <Button disabled={busy} onClick={() => void act(() => managePositions(), "Positions checked against live prices.")}>Check positions now</Button></div>
        </Card>
      </div>

      <Card title="Open and completed paper positions" right={`${open.length} open · ${closed.length} completed`}>
        {(positions.data ?? []).length === 0 ? <p className="text-sm text-slate-500" data-testid="pos-no-positions">No position yet. Nothing is forced: a position opens only from a BUY idea you accept.</p> : (
          <div className="scroll-thin overflow-x-auto"><table className="w-full min-w-[760px] text-xs" data-testid="pos-positions">
            <thead className="text-left text-slate-500"><tr><th className="py-1">Strategy</th><th>Contract</th><th className="text-right">Qty</th><th className="text-right">Entry</th><th className="text-right">Last / exit</th><th className="text-right">Stop</th><th>Exit plan</th><th className="text-right">P&L</th><th>Status</th></tr></thead>
            <tbody>{(positions.data ?? []).map((p) => (
              <tr key={p.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1">{p.strategy}</td><td>{p.opt_type} {p.strike} · {dmy(p.expiry)}</td><td className="num text-right">{p.qty}</td><td className="num text-right">{num(p.entry_price)}</td>
                <td className="num text-right">{p.exit_price != null ? num(p.exit_price) : p.last_price != null ? num(p.last_price) : "—"}</td><td className="num text-right">{num(p.stop_premium)}</td>
                <td>{p.planned_exit ? dmy(p.planned_exit) : "—"}{p.t1_hit ? " · T1 hit" : ""}</td>
                <td className={`num text-right font-medium ${pnlClass(p.net ?? p.mtm)}`}>{p.net != null ? inr(p.net, true, 0) : p.mtm != null ? inr(p.mtm, true, 0) : "—"}</td>
                <td>{p.status === "OPEN" ? "OPEN" : p.exit_reason}</td></tr>))}</tbody></table></div>)}
        {account.data && account.data.summary.overall.trades > 0 && <p className="mt-2 text-xs text-slate-500">Completed: {account.data.summary.overall.trades} trades, net {inr(account.data.summary.overall.net, true, 0)}, win rate {pct(account.data.summary.overall.win_rate, 0)}, profit factor {account.data.summary.overall.profit_factor ?? "—"}. A small sample says little.</p>}
      </Card>

      <Card title="Historical backtest: nine strategies x holds of 3, 5, 10 and 20 days" right={bt.data ? `${dmy(bt.data.meta.data_from)} to ${dmy(bt.data.meta.data_to)}` : ""}>
        {bt.error && <p className="text-sm text-slate-500" data-testid="pos-bt-missing">The backtest has not been run yet: python scripts/research_position.py run</p>}
        {bt.data && (
          <div className="space-y-3" data-testid="pos-backtest">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{Object.entries(bt.data.pooled_by_hold).map(([h, st]) => <Stat key={h} label={`${h}-day holds, all strategies`} value={inr(st.net, true, 0)} className={pnlClass(st.net)} sub={`${st.trades} trades · win ${pct(st.win_rate, 0)}`} />)}</div>
            <div className="scroll-thin max-h-96 overflow-auto"><table className="w-full min-w-[820px] text-xs">
              <thead className="sticky top-0 bg-white text-left text-slate-500 dark:bg-slate-900"><tr><th className="py-1">Strategy</th><th className="text-right">Hold</th><th className="text-right">Trades</th><th className="text-right">Win</th><th className="text-right">Net</th><th className="text-right">PF</th><th className="text-right">Expectancy</th><th className="text-right">Max DD</th><th className="text-right">Train / valid. / out-of-sample</th><th className="text-right">Not simulated</th></tr></thead>
              <tbody>{[...bt.data.cells].sort((x, y) => y.periods.out_of_sample.net - x.periods.out_of_sample.net).map((c) => (
                <tr key={`${c.strategy}${c.hold}`} className="border-t border-slate-100 dark:border-slate-800"><td className="py-1">{c.strategy}{c.robust && <Pill tone="good">robust</Pill>}</td><td className="num text-right">{c.hold}d</td><td className="num text-right">{c.trades}</td>
                  <td className="num text-right">{c.win_rate != null ? pct(c.win_rate, 0) : "—"}</td><td className={`num text-right ${pnlClass(c.net)}`}>{inr(c.net, true, 0)}</td><td className="num text-right">{c.profit_factor ?? "—"}</td>
                  <td className="num text-right">{c.expectancy != null ? inr(c.expectancy, true, 0) : "—"}</td><td className="num text-right">{inr(c.max_drawdown, false, 0)}</td>
                  <td className="num text-right">{(["train", "validation", "out_of_sample"] as const).map((k) => `${num(c.periods[k].net / 1000, 0)}k (${c.periods[k].trades})`).join(" / ")}</td><td className="num text-right">{c.unsimulatable_n}</td></tr>))}</tbody></table></div>
            {monthly.length > 0 && <div><div className="mb-1 text-xs font-semibold">Monthly net P&L, all strategies and holds (overlapping streams, not a portfolio)</div><BarsChart data={monthly} dark={dark} height={180} /></div>}
            <Limitation>Robust means net positive in train (2022-23), validation (2024) and out-of-sample (2025 onward) with at least 20 trades each. Nothing was tuned, so these are chronological hold-outs, not re-fitted walk-forward results. {bt.data.cells.filter((c) => c.robust).length === 0 ? "No strategy and hold combination is robust. " : ""}
              Trades whose option has no stored candle at entry or exit are not simulated and are counted, never filled with a made-up price: longer holds lose most of their trades this way, so the 10- and 20-day results rest on a few biased cases. IV and Greeks are not stored historically and were not used. Weekly trend uses EMA 10/20/50 because EMA 100/200 on weekly bars need more history than is stored.</Limitation>
          </div>)}
      </Card>

      <Card title="Daily decision history" icon={<CalendarClock size={16} />} right={<Button disabled={busy} onClick={() => void act(() => recordPositionDecision(), "Decision recorded.")}>Record today's decision</Button>}>
        {(decisions.data ?? []).length === 0 ? <p className="text-sm text-slate-500" data-testid="pos-no-decisions">No decision recorded yet. One is stored after each close (15:45) while the server runs, or when you press the button.</p> : (
          <div className="scroll-thin max-h-72 overflow-auto"><table className="w-full min-w-[560px] text-xs" data-testid="pos-decisions">
            <thead className="text-left text-slate-500"><tr><th className="py-1">Day</th><th>Decision</th><th className="text-right">Score</th><th>Strategies</th><th>Reasons</th></tr></thead>
            <tbody>{(decisions.data ?? []).map((d) => (
              <tr key={d.day} className="border-t border-slate-100 align-top dark:border-slate-800"><td className="py-1">{dmy(d.day)}</td><td><Pill tone={TONE[d.decision]}>{d.decision}</Pill></td><td className="num text-right">{d.score != null ? num(d.score, 1) : "—"}</td>
                <td>{(d.strategies ?? []).join(", ") || "—"}</td><td className="text-slate-600 dark:text-slate-300">{(d.reasons ?? []).join("; ")}</td></tr>))}</tbody></table></div>)}
      </Card>
    </div>
  );
}

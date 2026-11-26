import { useEffect, useMemo, useState } from "react";
import { Bot, Play, Square, ShieldCheck } from "lucide-react";
import { usePoll } from "../hooks/usePoll";
import { useApi } from "../hooks/useApi";
import {
  getBiasAnalysis, getBiasConfig, getBiasPredictions, getBiasStatus, getBiasSummary, getBiasTrades, pauseBias, resumeBias, startBias, stopEngine, updateBiasSettings,
} from "../services/api";
import type { BiasGroup, BiasSettings, StrategyStats } from "../types/api";
import { hms, inr, pct, pnlClass, todayIST } from "../utils/format";
import { Card, Pill, Stat } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader } from "../components/common/Controls";
import { ErrorNote, Limitation, Loading, Warning } from "../components/common/States";
import { BiasPanel } from "../components/auto/BiasPanel";
import { IndicatorTable } from "../components/auto/IndicatorTable";
import { PredictionTable } from "../components/auto/PredictionTable";
import { AccuracyPanel } from "../components/auto/AccuracyPanel";
import { TradeTable } from "../components/auto/TradeTable";
import { PositionCard } from "../components/auto/PositionCard";
import { AutoSettings } from "../components/auto/AutoSettings";
import { AutomationPanel } from "../components/auto/AutomationPanel";
import { ConfluencePanel } from "../components/auto/ConfluencePanel";
import { ScoredPanel } from "../components/auto/ScoredPanel";
import { ScannerPanel } from "../components/auto/ScannerPanel";

const STORE = "gt.auto.settings";
/** The confluence settings an older server does not send yet: the page still works (bias strategy) instead of failing on a missing list. */
const CF_FALLBACK: Partial<BiasSettings> = {
  entry_strategy: "bias", cf_factors: ["ema", "vwap", "fvg", "structure"], cf_require: [], cf_min_score: 75, cf_adr_filter: true, cf_adr_period: 10,
  cf_adr_max_used: 100, cf_fvg_min_atr: 0.1, cf_fvg_max_age: 24, cf_htf: true,
  sc_min_score: 80, sc_adr_period: 10, sc_adr_max_used: 100, sc_fvg_min_atr: 0.1, sc_fvg_max_age: 24, sc_ctx_tf: 0, sc_stop_min_pct: 5, sc_stop_max_pct: 50,
  max_open_positions: 1, max_open_risk_pct: 0, max_strategy_positions: 1, max_strategy_risk_pct: 0, scan_min_quality: 55, scan_allow_unvalidated: false,
};
/** What the analysis preview depends on (the scored settings and timeframes only count while that strategy is selected). */
const cfOf = (x: Partial<BiasSettings>) => JSON.stringify([x.cf_factors, x.cf_require, x.cf_min_score, x.cf_adr_filter, x.cf_adr_period, x.cf_adr_max_used, x.cf_fvg_min_atr, x.cf_fvg_max_age, x.cf_htf,
  x.entry_strategy === "scored" ? [x.timeframe, x.bias_confirm_tf, x.sc_min_score, x.sc_adr_period, x.sc_adr_max_used, x.sc_fvg_min_atr, x.sc_fvg_max_age, x.sc_ctx_tf, x.sc_stop_min_pct, x.sc_stop_max_pct] : null]);
const CF_DEFAULT_KEY = cfOf(CF_FALLBACK);
const STATE = { stopped: ["Stopped", "neutral"], waiting: ["Waiting for market", "info"], running: ["Running", "good"], halted: ["Halted", "warn"], error: ["ERROR", "bad"] } as const;

function saved(): Partial<BiasSettings> {
  try {
    const v = JSON.parse(localStorage.getItem(STORE) ?? "{}") as Partial<BiasSettings>;
    // settings saved before the continuous automation existed: take the new 70% default instead of the old 55%
    if (!("profit_target_net" in v)) delete v.bias_min_confidence;
    v.profit_target_net = 0;           // the fixed net profit target is no longer offered: exits follow the strategy
    return v;
  } catch { return {}; }
}

function GroupTable({ title, rows }: { title: string; rows: Record<string, BiasGroup> }) {
  const e = Object.entries(rows);
  if (!e.length) return null;
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-slate-600 dark:text-slate-300">{title}</div>
      <table className="w-full text-xs">
        <tbody>
          {e.map(([k, g]) => (
            <tr key={k} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1">{k}</td><td className="num text-right">{g.trades}</td>
              <td className="num text-right">{g.win_rate != null ? pct(g.win_rate, 0) : "—"}</td>
              <td className={`num text-right font-medium ${pnlClass(g.net)}`}>{inr(g.net, true, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const STRATEGY_LABEL: Record<string, string> = { bias: "Bias votes", confluence: "Confluence", scored: "Scored (structure + EMA + VWAP + FVG + ADR)" };
const strategyName = (k: string, labels?: Record<string, string>) => labels?.[k] ?? STRATEGY_LABEL[k] ?? k;

/** Performance of each entry strategy on its own trades: sample size, win rate, net expectancy per trade, profit factor, drawdown. */
function StrategyTable({ rows, labels }: { rows: Record<string, StrategyStats>; labels?: Record<string, string> }) {
  const e = Object.entries(rows);
  if (!e.length) return null;
  return (
    <div className="sm:col-span-2" data-testid="by-strategy">
      <div className="mb-1 text-xs font-semibold text-slate-600 dark:text-slate-300">By entry strategy · trades, win rate, net expectancy per trade, profit factor, max drawdown, net</div>
      <div className="scroll-thin overflow-x-auto">
        <table className="w-full min-w-[480px] text-xs">
          <tbody>
            {e.map(([k, g]) => (
              <tr key={k} className="border-t border-slate-100 dark:border-slate-800" data-testid={`strategy-${k}`}>
                <td className="py-1">{strategyName(k, labels)}</td><td className="num text-right">{g.trades}</td>
                <td className="num text-right">{g.win_rate != null ? pct(g.win_rate, 0) : "—"}</td>
                <td className={`num text-right ${pnlClass(g.expectancy)}`}>{g.expectancy != null ? inr(g.expectancy, true, 0) : "—"}</td>
                <td className="num text-right">{g.profit_factor != null ? g.profit_factor.toFixed(2) : "—"}</td>
                <td className="num text-right">{inr(g.max_drawdown, false, 0)}</td>
                <td className={`num text-right font-medium ${pnlClass(g.net)}`}>{inr(g.net, true, 0)}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
      <p className="mt-1 text-[11px] text-slate-500">A small sample says little: these numbers describe paper trades, they do not show an edge.</p>
    </div>
  );
}

/** Automated multi-timeframe paper trading: 5m entries confirmed by the 15m trend. Paper and replay only. */
export default function AutoTrading() {
  const cfg = useApi(getBiasConfig, []);
  const status = usePoll(getBiasStatus, 3000);
  const st = status.data;
  const running = !!st?.running;
  const mode = st?.trade_mode ?? "paper";
  const day = st?.day ?? todayIST();
  const session = mode === "replay" ? st?.session_id ?? null : null;

  const trades = usePoll(() => getBiasTrades(day, mode, session), 8000, [day, mode, session]);
  const summary = usePoll(() => getBiasSummary(day, mode, session), 8000, [day, mode, session]);
  const preds = usePoll(() => getBiasPredictions(day, mode, 80, session), 8000, [day, mode, session]);

  const [s, setS] = useState<BiasSettings | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [msgFrom, setMsgFrom] = useState<"panel" | "settings" | "confluence" | "scored" | "scanner">("settings");   // the message shows beside the Apply button that was pressed
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [replayDay, setReplayDay] = useState("");

  const base = cfg.data;
  useEffect(() => {
    if (base && !s) setS({ ...CF_FALLBACK, ...base.defaults, ...saved(), ...(base.settings ?? {}) });
  }, [base, s]);
  const set = (p: Partial<BiasSettings>) => setS((x) => (x ? { ...x, ...p } : x));

  // The latest candle's analysis (idle: the bias; always: a preview of the confluence factors). It is first read at once with the
  // default confluence settings (in parallel with the config); later edits reach the server once they stop changing, and a
  // running engine answers with its own settings.
  const cfNow = cfOf(s ?? CF_FALLBACK);
  const [cfKey, setCfKey] = useState(CF_DEFAULT_KEY);
  useEffect(() => {
    if (cfNow === cfKey) return;
    const t = setTimeout(() => setCfKey(cfNow), 500);
    return () => clearTimeout(t);
  }, [cfNow, cfKey]);
  const engineStrategy = running ? (st?.config as Record<string, unknown> | undefined)?.entry_strategy : undefined;
  const engineCf = engineStrategy === "confluence" || engineStrategy === "scored";
  const idle = usePoll(() => (engineCf ? Promise.resolve(null) : getBiasAnalysis(s ?? CF_FALLBACK)), 30000, [engineCf, cfKey]);

  const latest = running ? st?.bias?.latest ?? null : idle.data?.analysis ?? null;
  const counters = useMemo(() => {
    const b = st?.bias;
    const max = b ? b.max_trades : s?.max_trades_per_day || null;          // null / 0 = no count cap
    const used = b?.trades_today ?? summary.data?.trades ?? 0;
    return { used, max, left: max ? b?.remaining_trades ?? Math.max(0, max - used) : null };
  }, [st, s, summary.data]);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null);
    try { await fn(); await Promise.all([status.reload(), trades.reload(), summary.reload(), preds.reload()]); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  async function apply(from: "panel" | "settings" | "confluence" | "scored" | "scanner" = "settings") {
    if (!s) return;
    setMsgFrom(from);
    try { localStorage.setItem(STORE, JSON.stringify(s)); } catch { /* private window */ }
    if (!running) { setMsg({ ok: true, text: "Saved. These settings are used when you start the engine." }); return; }
    const live = (st?.config ?? {}) as unknown as Record<string, unknown>;
    const diff = Object.fromEntries(Object.entries(s).filter(([k, v]) => JSON.stringify(live[k]) !== JSON.stringify(v)));
    if (!Object.keys(diff).length) { setMsg({ ok: true, text: "Nothing changed." }); return; }
    setBusy(true);
    try { const r = await updateBiasSettings(diff as Partial<BiasSettings>); setMsg({ ok: true, text: r.changed.length ? `Applied: ${r.changed.join("; ")}` : "No change." }); await status.reload(); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); } finally { setBusy(false); }
  }

  const auto = st?.bias?.automation;
  const [stLabel, stTone] = STATE[st?.state ?? "stopped"];
  const sm = summary.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Automated Paper Trading"
        subtitle="Every closed 5-minute candle is analysed, the 15-minute trend confirms the direction, and qualified trades are taken in a virtual account."
        actions={<Pill tone={stTone}>{stLabel}{running ? ` · ${mode}` : ""}</Pill>} />

      <Card accent="strat" bodyClass="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <ShieldCheck size={18} className="shrink-0 text-green-600" />
          <p className="min-w-0 flex-1 text-sm">Paper trading only: this page cannot place a real order. The agreement % below measures how many indicators point the same way; it is not a probability of winning, and the accuracy panel shows how often the next candle actually went that way.</p>
        </div>
        <p className="mt-2 text-xs text-slate-600 dark:text-slate-400" data-testid="validation-note">
          <b>Validated on stored real candles (19 Nov):</b> the next candle went the predicted way 50.9% of the time over 65,270 calls (2022-2026), a coin flip. Replayed on real option premiums with all costs it made +₹2,789 net over 28 sessions (Oct-Nov 2026) and lost ₹36,004 over 65 sessions (Jul-Sep 2026). No edge was found: treat it as a way to watch the analysis, not as something that makes money. Details: docs/AUTO_TRADING.md.</p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          {!running ? (
            <>
              <Button variant="success" disabled={busy || !s} onClick={() => act(() => startBias(s as BiasSettings, "paper"))}><Play size={14} />Start paper trading</Button>
              <Field label="Replay a finished day"><input type="date" className={`${inputCls} w-40`} max={todayIST()} value={replayDay} onChange={(e) => setReplayDay(e.target.value)} aria-label="Replay day" /></Field>
              <Button disabled={busy || !s || !replayDay} onClick={() => act(() => startBias(s as BiasSettings, "replay", replayDay))}><Bot size={14} />Replay day</Button>
            </>
          ) : (
            <>
              <Button disabled={busy} onClick={() => act(() => (auto?.paused ? resumeBias() : pauseBias()))}>{auto?.paused ? "Resume" : "Pause"}</Button>
              <Button variant="danger" disabled={busy} onClick={() => act(() => stopEngine())}><Square size={14} />Stop engine</Button>
            </>
          )}
          {st?.nifty && <span className="text-xs text-slate-500">NIFTY {st.nifty.price.toLocaleString("en-IN")} · {hms(st.nifty.ts)}</span>}
        </div>
        {st?.halt_reason && <div className="mt-3"><Warning>{st.halt_reason}</Warning></div>}
        {st?.conn_error && <div className="mt-3"><ErrorNote offline>{st.conn_error}</ErrorNote></div>}
        {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
        {status.error && <div className="mt-3"><ErrorNote offline>{status.error}</ErrorNote></div>}
      </Card>

      {s && (
        <AutomationPanel a={auto} bias={latest} s={s} set={set} running={running} onApply={() => void apply("panel")} busy={busy} summary={sm ?? null}
          trades={trades.data ?? []} msg={msgFrom === "panel" ? msg : null} />
      )}

      {s && (
        <ConfluencePanel a={engineCf ? latest : idle.data?.analysis ?? null} s={s} set={set} running={running} onApply={() => void apply("confluence")} busy={busy}
          msg={msgFrom === "confluence" ? msg : null} periods={base?.adr_periods} />
      )}
      {s && s.entry_strategy === "scored" && (
        <ScoredPanel a={engineCf ? latest : idle.data?.analysis ?? null} s={s} set={set} running={running} onApply={() => void apply("scored")} busy={busy}
          msg={msgFrom === "scored" ? msg : null} periods={base?.adr_periods} preset={base?.presets?.scored} rejected={st?.bias?.rejected} />
      )}

      {s && (s.entry_strategy === "scanner" || engineStrategy === "scanner") && (
        <ScannerPanel scan={st?.bias?.scan} positions={st?.positions ?? []} s={s} set={set} cfg={base?.scanner} running={running} onApply={() => void apply("scanner")} busy={busy}
          msg={msgFrom === "scanner" ? msg : null} tradesToday={counters.used} cap={counters.max} preset={base?.presets?.scanner} />
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {!running && idle.loading && !latest && <Card><Loading text="Reading candles…" /></Card>}
          {!running && idle.error && <ErrorNote>{idle.error}</ErrorNote>}
          {(running || latest) && <BiasPanel a={latest} asOf={idle.data?.as_of_day} live={running ? true : idle.data?.live} />}
        </div>
        <div className="space-y-4">
          <Card title="Today" bodyClass="px-4 pb-4">
            <div className="grid grid-cols-2 gap-3">
              <Stat label="Trades today" value={counters.max ? `${counters.used} of ${counters.max}` : `${counters.used}`} sub={counters.max ? `${counters.left} remaining · never forced` : "no count cap · risk limits apply · never forced"} />
              <Stat label="Net P&L" value={sm ? inr(sm.net, true) : "—"} className={pnlClass(sm?.net)} sub={sm ? `gross ${inr(sm.gross, true, 0)}` : undefined} />
              <Stat label="Wins / losses" value={sm ? `${sm.wins} / ${sm.losses}` : "—"} />
              <Stat label="Win rate" value={sm?.win_rate != null ? pct(sm.win_rate, 0) : "—"} sub={sm && sm.open ? `${sm.open} open` : undefined} />
            </div>
          </Card>
          <PositionCard p={st?.position ?? null} profitTarget={running ? Number((st?.config as Record<string, unknown> | undefined)?.profit_target_net ?? 0) : 0} editable={running && mode === "paper"} onChanged={() => { void status.reload(); void trades.reload(); void summary.reload(); }} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {latest && <IndicatorTable rows={latest.indicators} tf={[latest.tf_primary ?? 5, latest.tf_confirm ?? 15]} />}
        <PredictionTable rows={preds.data ?? []} day={day} />
      </div>

      <TradeTable rows={trades.data ?? []} day={day} />

      <div className="grid gap-4 lg:grid-cols-2">
        <AccuracyPanel mode={mode} tf={s?.timeframe ?? 5} confirm={s?.bias_confirm_tf ?? 15} />
        <Card title="Performance breakdown">
          {!sm || sm.trades === 0 ? <p className="text-sm text-slate-500">Closed trades appear here, split by instrument, exit reason, confidence and the indicators that supported them.</p> : (
            <div className="grid gap-4 sm:grid-cols-2">
              <GroupTable title="By instrument · trades, win rate, net" rows={sm.by_instrument} />
              <GroupTable title="By exit reason" rows={sm.by_exit} />
              <GroupTable title="By confidence at entry" rows={sm.by_confidence} />
              <GroupTable title="By supporting strategy" rows={sm.by_indicator} />
              {sm.by_strategy && <StrategyTable rows={sm.by_strategy} labels={Object.fromEntries((base?.scanner?.strategies ?? []).map((x) => [x.key, x.label]))} />}
            </div>
          )}
          {sm && <div className="mt-3"><Limitation>{sm.note}</Limitation></div>}
        </Card>
      </div>

      {s && base && (
        <AutoSettings s={s} set={set} indicators={base.indicators} running={running} onApply={() => void apply("settings")} busy={busy} msg={msgFrom === "settings" ? msg : null} />
      )}

      {running && st?.events && (
        <Card title="Engine log">
          <ul className="scroll-thin max-h-56 space-y-1 overflow-auto text-xs">
            {st.events.slice(0, 40).map((e) => (
              <li key={e.ts + e.message} className={e.level === "error" ? "text-red-600" : e.level === "warn" ? "text-orange-600" : ""}>
                <span className="num text-slate-400">{hms(e.ts)}</span> {e.message}</li>))}
          </ul>
        </Card>
      )}
    </div>
  );
}

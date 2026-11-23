import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { CandlestickChart, Gauge, ListChecks, ShieldCheck, SlidersHorizontal, Timer } from "lucide-react";
import { useApi } from "../hooks/useApi";
import { ApiError, getTradingSettings, resetTradingSettings, saveTradingSettings, validateTradingSettings } from "../services/api";
import type { TsCheck, TsConfig, TsIssue, TsState, TsStrategyMeta, TsValue } from "../types/api";
import { dmy, hms } from "../utils/format";
import { Card, Pill } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader } from "../components/common/Controls";
import { ErrorNote, Loading, Warning } from "../components/common/States";
import { cfgEqual, issueAt, ItemCard, ParamField, setIn, Toggle } from "../components/settings/SettingsControls";

const GROUPS: { kinds: TsStrategyMeta["kind"][]; title: string; note: string }[] = [
  { kinds: ["crossover"], title: "EMA crossover strategies", note: "Fast and slow EMA of the entry timeframe; a fresh cross, optionally confirmed by VWAP, RSI or MACD." },
  { kinds: ["bias", "confluence", "scored"], title: "Multi-indicator strategies", note: "The bias votes, the equal-weight confluence rule and the scored (points out of 100) rule." },
  { kinds: ["method"], title: "Research entry methods", note: "Fixed rules from the entry research. The five-year test found no profitable method; they are OFF by default." },
];
const EXIT_LABEL = { entry: "The entry timeframe's opposite signal", trend: "The trend timeframe turning against the trade" } as const;
const TF_LABEL: Record<number, string> = { 1: "1 minute", 5: "5 minutes", 15: "15 minutes", 30: "30 minutes" };
const when = (iso: string | null) => (iso ? `${dmy(iso)} ${hms(iso)}` : "never (the defaults are in use)");

/** Trading Settings: one saved configuration (strategies, timeframes, indicators, rules) the paper-trading engine reads. Paper and replay only. */
export default function TradingSettings() {
  const api = useApi(getTradingSettings, []);
  const state = api.data;
  const meta = state?.meta;
  const [draft, setDraft] = useState<TsConfig | null>(null);
  const [check, setCheck] = useState<TsCheck | null>(null);
  const [serverErrors, setServerErrors] = useState<TsIssue[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => { if (state && !draft) setDraft(state.config); }, [state, draft]);
  const dirty = !!draft && !!state && !cfgEqual(draft, state.config);

  // check the draft with the server (debounced): every error and warning, and the summary it would give
  useEffect(() => {
    if (!draft || !dirty) { setCheck(null); return; }
    let live = true;
    const t = setTimeout(() => { validateTradingSettings(draft).then((c) => { if (live) setCheck(c); }).catch(() => { if (live) setCheck(null); }); }, 350);
    return () => { live = false; clearTimeout(t); };
  }, [draft, dirty]);

  // unsaved changes: the browser warns on refresh or close, and a click on an in-app link asks first
  useEffect(() => {
    if (!dirty) return;
    const before = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    const click = (e: MouseEvent) => {
      const a = (e.target as HTMLElement | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      const href = a?.getAttribute("href") ?? "";
      if (!a || a.target === "_blank" || !href.startsWith("/") || href === window.location.pathname) return;
      if (!window.confirm("You have unsaved changes in Trading Settings. Leave this page and lose them?")) { e.preventDefault(); e.stopPropagation(); }
    };
    window.addEventListener("beforeunload", before);
    document.addEventListener("click", click, true);
    return () => { window.removeEventListener("beforeunload", before); document.removeEventListener("click", click, true); };
  }, [dirty]);

  const issues = useMemo(() => [...serverErrors, ...(check?.errors ?? [])], [serverErrors, check]);
  const warnings = dirty ? check?.warnings ?? [] : state?.warnings ?? [];
  const summary = (dirty ? check?.summary : null) ?? state?.summary;
  const edit = (path: string[], value: unknown) => { setDraft((d) => (d ? setIn(d, path, value) : d)); setServerErrors([]); setMsg(null); };
  const bulk = (scope: "strategies" | "indicators" | "timeframes", on: boolean) => {
    setDraft((d) => {
      if (!d) return d;
      if (scope === "timeframes") return { ...d, timeframes: { ...d.timeframes, enabled: Object.fromEntries(Object.keys(d.timeframes.enabled).map((k) => [k, on])) } };
      return { ...d, [scope]: Object.fromEntries(Object.entries(d[scope]).map(([k, v]) => [k, { ...v, enabled: on }])) };
    });
    setServerErrors([]); setMsg(null);
  };

  async function save() {
    if (!draft || !state) return;
    setBusy(true); setMsg(null);
    try {
      const res = await saveTradingSettings(draft, state.version);
      api.setData({ ...res, meta: state.meta, defaults: state.defaults } as TsState);
      setDraft(res.config); setServerErrors([]); setCheck(null);
      setMsg({ ok: true, text: `Saved as version ${res.version}. A running engine applies it on its next tick.` });
    } catch (e) {
      const err = e as ApiError;
      setServerErrors(err.errors ?? []);
      setMsg({ ok: false, text: err.message });
    } finally { setBusy(false); }
  }
  async function reset() {
    setBusy(true); setMsg(null); setConfirmReset(false);
    try {
      const res = await resetTradingSettings();
      api.setData({ ...res, meta: state?.meta, defaults: state?.defaults } as TsState);
      setDraft(res.config); setServerErrors([]); setCheck(null);
      setMsg({ ok: true, text: `Reset to the defaults and saved as version ${res.version}.` });
    } catch (e) { setMsg({ ok: false, text: (e as Error).message }); } finally { setBusy(false); }
  }

  if (api.loading && !state) return <Loading />;
  if (api.error && !state) return <ErrorNote offline>{api.error}</ErrorNote>;
  if (!state || !draft || !meta) return <Loading />;

  const blocked = summary?.strategies_blocked ?? {};
  const stratByKind = (kinds: TsStrategyMeta["kind"][]) => meta.strategies.filter((s) => kinds.includes(s.kind));
  const onCount = Object.values(draft.strategies).filter((s) => s.enabled).length;
  const canSave = dirty && !busy && issues.length === 0 && check !== null;

  return (
    <div className="space-y-4">
      <PageHeader title="Trading Settings"
        subtitle="One saved configuration for the paper-trading engine: which strategies may signal, which timeframes and indicators take part, and the risk rules."
        actions={<Pill tone={dirty ? "warn" : "good"}>{dirty ? "Unsaved changes" : `Version ${state.version}`}</Pill>} />

      <Card accent="strat" bodyClass="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <ShieldCheck size={18} className="shrink-0 text-green-600" />
          <p className="min-w-0 flex-1 text-sm">Paper and replay only: nothing on this page can place a real order. A strategy that is OFF can never create a paper order, a strategy that needs an indicator that is OFF is blocked
            (never silently run without it), and only enabled timeframes are used. The <b>Configured</b> entry strategy on the <Link to="/auto" className="text-blue-700 underline dark:text-blue-400">Automated Paper Trading</Link> page
            applies these settings live; every other entry strategy is gated by the ON / OFF switches, the timeframes and the indicators below.</p>
        </div>
      </Card>

      {summary && (
        <Card title="Active configuration" icon={<ListChecks size={16} className="text-violet-600" />}
          right={<span data-testid="saved-at">{state.version ? `version ${state.version} · saved ${when(state.saved_at)}` : "defaults · nothing saved yet"}</span>}>
          <div className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4" data-testid="summary">
            <div><div className="text-xs text-slate-500">Strategies</div><div className="font-semibold">{summary.strategies_active.length} active of {summary.strategies_on.length} ON</div>
              <div className="text-xs text-slate-500">{summary.strategies_active.slice(0, 4).map((k) => meta.strategies.find((s) => s.key === k)?.label ?? k).join(", ")}{summary.strategies_active.length > 4 ? ` +${summary.strategies_active.length - 4} more` : ""}</div>
              {Object.keys(summary.strategies_blocked).length > 0 && <div className="text-xs text-orange-700 dark:text-orange-400">{Object.keys(summary.strategies_blocked).length} blocked</div>}</div>
            <div><div className="text-xs text-slate-500">Timeframes</div><div className="font-semibold">{summary.timeframes_enabled.map((t) => `${t}m`).join(" · ") || "none"} enabled</div>
              <div className="text-xs text-slate-500">trend {summary.trend_tf}m · entry {summary.entry_tf}m · exit {summary.exit === "entry" ? "on the entry candle" : "on the trend timeframe"}</div></div>
            <div><div className="text-xs text-slate-500">Indicators</div><div className="font-semibold">{summary.indicators_on.length} ON · {summary.indicators_off.length} OFF</div>
              <div className="text-xs text-slate-500">{summary.indicators_off.length ? `off: ${summary.indicators_off.join(", ")}` : "all participate"}</div></div>
            <div><div className="text-xs text-slate-500">Rules</div><div className="font-semibold">{summary.rules.window} · {summary.rules.max_trades_per_day} trades a day</div>
              <div className="text-xs text-slate-500">risk {summary.rules.risk_pct}% · {summary.rules.stop} stop · {summary.rules.target_rr}R target · daily loss {summary.rules.daily_loss_pct}%</div></div>
          </div>
        </Card>
      )}

      {state.error && <ErrorNote>The saved configuration is invalid ({state.error}). The engine places no orders until you save a valid one.</ErrorNote>}
      {issues.length > 0 && (
        <div role="alert" data-testid="issues" className="rounded-xl border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
          <b>{issues.length} problem{issues.length === 1 ? "" : "s"} to fix before saving:</b>
          <ul className="mt-1 list-disc pl-5 text-xs">{issues.map((i) => <li key={i.path + i.message}><code>{i.path}</code>: {i.message}</li>)}</ul>
        </div>
      )}
      {warnings.length > 0 && <div data-testid="warnings"><Warning>{warnings.map((w) => w.message).join(" ")}</Warning></div>}

      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white/95 p-3 shadow-sm backdrop-blur dark:border-slate-800 dark:bg-slate-900/95" data-testid="actions">
        <Button variant="primary" disabled={!canSave} onClick={() => void save()}>Save settings</Button>
        <Button disabled={!dirty || busy} onClick={() => { setDraft(state.config); setServerErrors([]); setMsg(null); }}>Discard changes</Button>
        {!confirmReset ? <Button variant="danger" disabled={busy} onClick={() => setConfirmReset(true)}>Reset to defaults</Button> : (
          <span className="flex items-center gap-2 text-xs"><span>Reset every setting to the defaults and save?</span>
            <Button variant="danger" onClick={() => void reset()}>Yes, reset</Button><Button onClick={() => setConfirmReset(false)}>Cancel</Button></span>)}
        {dirty && <span className="text-xs font-medium text-orange-700 dark:text-orange-400" data-testid="unsaved">You have unsaved changes: they are not used until you save.</span>}
        {msg && <span role="status" data-testid="msg" className={`text-xs ${msg.ok ? "text-gain" : "text-red-600"}`}>{msg.text}{!msg.ok && msg.text.includes("changed elsewhere") && <> <button type="button" className="underline" onClick={() => { setDraft(null); setServerErrors([]); void api.reload(); }}>Reload</button></>}</span>}
        <span className="ml-auto text-xs text-slate-500">Last saved: {when(state.saved_at)}</span>
      </div>

      <Card title="Strategies" icon={<CandlestickChart size={16} className="text-blue-600" />} right={`${onCount} of ${meta.strategies.length} ON`}>
        <div className="mb-3 flex flex-wrap gap-2">
          <Button onClick={() => bulk("strategies", true)}>Enable all strategies</Button><Button onClick={() => bulk("strategies", false)}>Disable all strategies</Button>
        </div>
        {GROUPS.map((g) => (
          <section key={g.title} className="mb-4 last:mb-0" aria-label={g.title}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{g.title}</h3>
            <p className="mb-2 text-xs text-slate-500">{g.note}</p>
            <div className="grid gap-3 lg:grid-cols-2">
              {stratByKind(g.kinds).map((s) => {
                const d = draft.strategies[s.key];
                return <ItemCard key={s.key} id={s.key} title={s.label} note={s.note} on={d.enabled} blocked={blocked[s.key]} params={s.params} values={d.params} issues={issues}
                  basePath={`strategies.${s.key}`} onToggle={(v) => edit(["strategies", s.key, "enabled"], v)} onParam={(k, v) => edit(["strategies", s.key, "params", k], v)} />;
              })}
            </div>
          </section>
        ))}
      </Card>

      <Card title="Timeframes" icon={<Timer size={16} className="text-blue-600" />} right="only enabled timeframes are used by the engine">
        <div className="mb-3 flex flex-wrap gap-2">
          <Button onClick={() => bulk("timeframes", true)}>Enable all timeframes</Button><Button onClick={() => bulk("timeframes", false)}>Disable all timeframes</Button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {meta.timeframes.all.map((tf) => (
            <div key={tf} data-testid={`tf-${tf}`} className="flex items-start gap-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
              <Toggle on={draft.timeframes.enabled[String(tf)]} label={`${TF_LABEL[tf]} ${draft.timeframes.enabled[String(tf)] ? "ON" : "OFF"}`} onChange={(v) => edit(["timeframes", "enabled", String(tf)], v)} />
              <div><div className="text-sm font-semibold">{TF_LABEL[tf]}</div><p className="text-xs text-slate-500">{meta.timeframes.notes[String(tf)]}</p></div>
            </div>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Field label="Trend confirmation timeframe"><select className={inputCls} aria-label="Trend confirmation timeframe" value={draft.timeframes.trend} onChange={(e) => edit(["timeframes", "trend"], Number(e.target.value))}>
            {meta.timeframes.trend.map((t) => <option key={t} value={t}>{TF_LABEL[t]}</option>)}</select>{issueAt(issues, "timeframes.trend") && <span role="alert" className="text-[11px] font-normal text-red-600">{issueAt(issues, "timeframes.trend")}</span>}</Field>
          <Field label="Entry signal timeframe"><select className={inputCls} aria-label="Entry signal timeframe" value={draft.timeframes.entry} onChange={(e) => edit(["timeframes", "entry"], Number(e.target.value))}>
            {meta.timeframes.entry.map((t) => <option key={t} value={t}>{TF_LABEL[t]}</option>)}</select>{issueAt(issues, "timeframes.entry") && <span role="alert" className="text-[11px] font-normal text-red-600">{issueAt(issues, "timeframes.entry")}</span>}</Field>
          <Field label="Exit confirmation"><select className={inputCls} aria-label="Exit confirmation" value={draft.timeframes.exit} onChange={(e) => edit(["timeframes", "exit"], e.target.value)}>
            {meta.timeframes.exit.map((t) => <option key={t} value={t}>{EXIT_LABEL[t as "entry" | "trend"]}</option>)}</select></Field>
        </div>
        <label className="mt-3 flex items-center gap-2 text-sm"><input type="checkbox" checked={draft.timeframes.trend_filter} onChange={(e) => edit(["timeframes", "trend_filter"], e.target.checked)} />
          Crossover and research strategies must agree with the trend timeframe (EMA 20/50 of its closed candles)</label>
        {issueAt(issues, "timeframes.enabled") && <p role="alert" className="mt-2 text-xs text-red-600">{issueAt(issues, "timeframes.enabled")}</p>}
      </Card>

      <Card title="Indicators" icon={<Gauge size={16} className="text-blue-600" />} right={`${Object.values(draft.indicators).filter((i) => i.enabled).length} of ${meta.indicators.length} ON`}>
        <div className="mb-3 flex flex-wrap gap-2">
          <Button onClick={() => bulk("indicators", true)}>Enable all indicators</Button><Button onClick={() => bulk("indicators", false)}>Disable all indicators</Button>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {meta.indicators.map((i) => {
            const d = draft.indicators[i.key];
            return <ItemCard key={i.key} id={`ind-${i.key}`} title={i.label} note={i.note} on={d.enabled} params={i.params} values={d.params} issues={issues} basePath={`indicators.${i.key}`}
              onToggle={(v) => edit(["indicators", i.key, "enabled"], v)} onParam={(k, v) => edit(["indicators", i.key, "params", k], v)} />;
          })}
        </div>
        {issues.filter((i) => /^indicators\.[a-z_]+\.enabled$/.test(i.path)).map((i) => <p key={i.path} role="alert" className="mt-2 text-xs text-red-600">{i.message}</p>)}
      </Card>

      <Card title="Paper trading rules" icon={<SlidersHorizontal size={16} className="text-blue-600" />} right="applied to every new paper order">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" data-testid="rules">
          {meta.rules.map((p) => <ParamField key={p.key} p={p} id={`rule-${p.key}`} value={draft.rules[p.key] as TsValue} onChange={(v) => edit(["rules", p.key], v)} error={issueAt(issues, `rules.${p.key}`)} />)}
        </div>
        <p className="mt-3 text-xs text-slate-500">An order is placed only when: a strategy is ON, its timeframe is enabled, every indicator it needs is ON, its entry conditions are met on a closed candle, and these limits allow a new trade.
          The engine holds one position at a time.</p>
      </Card>
    </div>
  );
}

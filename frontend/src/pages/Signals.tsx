import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, History, MinusCircle, RefreshCw, XCircle, Zap } from "lucide-react";
import { useLive } from "../context/LiveContext";
import { useApi, waitForJob } from "../hooks/useApi";
import { buildSignalAnalysis, getMeta, getSignalAnalysis } from "../services/api";
import { Card, Pill, Stat } from "../components/common/Card";
import { Button, Field, inputCls, PageHeader, Segmented } from "../components/common/Controls";
import { Empty, ErrorNote, Limitation, Loading, Progress } from "../components/common/States";
import { AlertList } from "../components/layout/NotificationPanel";
import { isExit } from "../hooks/useAlerts";
import { dmy, dmyhm, hm, num, pct } from "../utils/format";
import type { HistSignal, Job } from "../types/api";

/** Signal strength in three plain levels (instead of the four score bands). */
export function strength(score: number | null | undefined) {
  if (score == null) return { label: "Not scored", tone: "neutral" as const, w: 0 };
  if (score >= 70) return { label: "Strong", tone: "good" as const, w: score };
  if (score >= 50) return { label: "Moderate", tone: "warn" as const, w: score };
  return { label: "Weak", tone: "neutral" as const, w: score };
}

function StrengthBar({ score }: { score: number | null }) {
  const s = strength(score);
  const color = s.tone === "good" ? "bg-green-500" : s.tone === "warn" ? "bg-orange-500" : "bg-slate-400";
  return (
    <div className="flex min-w-24 items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800"><div className={`h-full ${color}`} style={{ width: `${s.w}%` }} /></div>
      <span className="w-16 text-xs text-slate-500">{s.label}</span>
    </div>
  );
}

const callTone = (c: string) => (c === "Bullish" ? "good" : c === "Bearish" ? "bad" : "neutral");

export default function Signals() {
  const { data } = useLive();
  const [strategy, setStrategy] = useState("ema_9_21");
  const [tf, setTf] = useState(15);
  const [job, setJob] = useState<Job | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const meta = useApi(getMeta, []);
  const an = useApi(() => getSignalAnalysis(strategy, tf), [strategy, tf]);
  const analysis = an.data?.data ?? null;

  async function rebuild() {
    try {
      const r = await buildSignalAnalysis(strategy, tf);
      const j = await waitForJob(String(r.job), setJob);
      setJob(null);
      if (j.state === "error") throw new Error(j.error ?? "Build failed");
      await an.reload();
    } catch (e) { setJob(null); an.setData(null); alert((e as Error).message); }
  }
  // An analysis that's being built elsewhere: follow it.
  useEffect(() => {
    const j = an.data?.job;
    if (j && typeof j === "object" && !job) waitForJob(j.id, setJob).then(() => { setJob(null); void an.reload(); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [an.data?.job]);

  const selected: HistSignal | undefined = useMemo(() => analysis?.signals.find((s) => s.id === sel) ?? analysis?.signals[0], [analysis, sel]);
  const groups = useMemo(() => {
    const c = analysis?.calibration ?? [];
    const agg = (lo: number, hi: number) => {
      const rows = c.filter((b) => b.from >= lo && b.from < hi && b.n > 0);
      const n = rows.reduce((a, b) => a + b.n, 0);
      const hits = rows.reduce((a, b) => a + (b.hit_rate ?? 0) * b.n / 100, 0);
      return { n, rate: n ? (hits / n) * 100 : null };
    };
    return [{ label: "Weak (<50)", ...agg(0, 50) }, { label: "Moderate (50–69)", ...agg(50, 70) }, { label: "Strong (70+)", ...agg(70, 101) }];
  }, [analysis]);

  const live = data?.feed?.signal;
  const rec = live?.rec;
  const ema = data?.feed?.ema;
  const exits = (data?.alerts ?? []).filter(isExit);

  return (
    <div className="space-y-4">
      <PageHeader title="Trading Signals" subtitle="Live signals from the 9/21 EMA strategy, plus how past signals actually turned out." />

      {/* ------------------------------------------------ live */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card accent="strat" title="Latest live signal" icon={<Zap size={16} className="text-violet-600" />} className="lg:col-span-2"
          right={live?.since ? `since ${hm(live.since)}` : undefined}>
          {!data ? <Loading className="h-24" /> : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <Pill tone={live?.action === "BUY CE" ? "good" : live?.action === "BUY PE" ? "bad" : "neutral"} className="px-4 py-1.5 text-lg">{live?.action ?? "HOLD"}</Pill>
                <span className="text-sm text-slate-600 dark:text-slate-300">{live?.reason}</span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Entry reference" value={rec?.verified ? `₹${num(rec.entry)}` : live?.nifty != null ? `NIFTY ${num(live.nifty)}` : "—"} />
                <Stat label="Stop loss" value={rec?.verified ? `₹${num(rec.stop)}` : "—"} className="text-loss" sub={rec?.nifty_stop ? `NIFTY ${num(rec.nifty_stop)}` : undefined} />
                <Stat label="Target" value={rec?.verified ? `₹${num(rec.target)}` : "—"} className="text-gain" sub={rec?.nifty_target ? `NIFTY ${num(rec.nifty_target)}` : undefined} />
                <Stat label="Signal time" value={hm(live?.since)} sub={`${data.feed?.timeframe ?? "—"}-minute bars`} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-xs">
                <Pill tone="strat">EMA 9 {num(ema?.fast)}</Pill>
                <Pill tone="strat">EMA 21 {num(ema?.slow)}</Pill>
                {ema && <Pill tone={ema.fast > ema.slow ? "good" : "bad"}>{ema.fast > ema.slow ? "EMA 9 above 21: bullish" : "EMA 9 below 21: bearish"}</Pill>}
              </div>
              <p className="mt-2 text-xs text-slate-500">Live crossover signals have no strength score. The score below comes from the historical model on the Signals analysis.</p>
            </>
          )}
        </Card>
        <Card title="Exit signals" right={`${exits.length}`}>
          {exits.length ? <AlertList alerts={exits} limit={6} /> : <p className="py-4 text-center text-sm text-slate-500">No engine exits recorded yet.</p>}
        </Card>
      </div>

      {/* ------------------------------------------------ history */}
      <Card title="Past signals: how they performed" icon={<History size={16} className="text-slate-500" />}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Field label="" className="w-40">
              <select aria-label="Strategy" className={inputCls} value={strategy} onChange={(e) => { setStrategy(e.target.value); setSel(null); }}>
                {Object.entries(meta.data?.strategies ?? { ema_9_21: "EMA 9/21" }).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </Field>
            <Segmented value={tf} onChange={(v) => { setTf(v); setSel(null); }} options={[1, 5, 15, 30].map((t) => ({ value: t, label: `${t}m` }))} />
            <Button onClick={rebuild} disabled={!!job}><RefreshCw size={14} className={job ? "animate-spin" : ""} /> {analysis ? "Rebuild" : "Build"}</Button>
          </div>
        }>
        {job && <div className="mb-3"><Progress value={job.progress} text={job.message} /></div>}
        {an.error && <ErrorNote>{an.error}</ErrorNote>}
        {an.loading && !analysis ? <Loading /> : !analysis ? (
          <Empty title="No analysis for this strategy and timeframe">Build it to score every past crossover. It takes a few seconds.</Empty>
        ) : (
          <div className="space-y-4">
            <Limitation>History, not a forecast: each signal's outcome is what NIFTY did next. A hit means the target (2 × ATR) was reached before the stop (1 × ATR) by 15:00. Scores were checked only on years the model hadn't seen.</Limitation>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              <Stat label="Signals" value={analysis.counts.signals.toLocaleString("en-IN")} sub={`${analysis.strategy_label} · ${analysis.timeframe}m`} />
              <Stat label="Hit rate (all)" value={pct(analysis.model.base_rate)} />
              {groups.map((g) => <Stat key={g.label} label={g.label} value={pct(g.rate)} sub={`${g.n} signals`} />)}
            </div>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
              <div className="overflow-x-auto xl:col-span-3">
                <table className="w-full min-w-[640px] text-sm">
                  <thead className="text-left text-xs uppercase text-slate-500">
                    <tr><th className="py-2">Time</th><th>Signal</th><th>Strength</th><th className="text-right">Entry</th><th className="text-right">Stop</th><th className="text-right">Target</th><th className="pr-1 text-right">Result</th></tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {analysis.signals.slice(0, 150).map((s) => (
                      <tr key={s.id} onClick={() => setSel(s.id)}
                        className={`cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/60 ${selected?.id === s.id ? "bg-violet-50 dark:bg-violet-950/30" : ""}`}>
                        <td className="num py-2 text-xs">{dmyhm(s.ts)}</td>
                        <td><Pill tone={callTone(s.direction)}>{s.direction === "Bullish" ? "BUY CE" : "BUY PE"}</Pill></td>
                        <td><StrengthBar score={s.score} /></td>
                        <td className="num text-right">{num(s.entry)}</td>
                        <td className="num text-right text-loss">{num(s.stop)}</td>
                        <td className="num text-right text-gain">{num(s.target)}</td>
                        <td className={`pr-1 text-right text-xs font-semibold ${s.outcome === "hit" ? "text-gain" : s.outcome === "miss" ? "text-loss" : "text-slate-500"}`}>{s.outcome}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {selected && (
                <div className="space-y-3 rounded-xl border border-slate-200 p-3 xl:col-span-2 dark:border-slate-800">
                  <div className="flex items-center justify-between">
                    <Pill tone={callTone(selected.direction)} className="text-sm">{selected.direction === "Bullish" ? "BUY CE" : "BUY PE"}</Pill>
                    <span className="text-xs text-slate-500">{dmy(selected.ts)} {hm(selected.ts)}</span>
                  </div>
                  <StrengthBar score={selected.score} />
                  <p className="text-sm text-slate-600 dark:text-slate-300">{selected.reason}</p>
                  <ul className="space-y-1">
                    {selected.indicators.map((i) => (
                      <li key={i.name} className="flex items-center gap-2 text-sm">
                        {i.supports === true ? <CheckCircle2 size={15} className="text-gain" /> : i.supports === false ? <XCircle size={15} className="text-loss" /> : <MinusCircle size={15} className="text-slate-400" />}
                        <span className="w-32 shrink-0">{i.name}</span><span className="truncate text-xs text-slate-500">{i.value}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="text-xs text-slate-500">
                    Result: <b className={selected.outcome === "hit" ? "text-gain" : selected.outcome === "miss" ? "text-loss" : ""}>{selected.outcome}</b>
                    {selected.decided_at && ` at ${hm(selected.decided_at)}`}
                    {selected.comparable?.hit_rate != null && ` · similar past signals hit ${pct(selected.comparable.hit_rate)} of ${selected.comparable.n}`}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

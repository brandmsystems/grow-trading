import { AlertTriangle, CheckCircle2, Scale } from "lucide-react";
import type { CalibBin, SignalAnalysis } from "../../types/api";
import { num, pct } from "../../utils/format";
import { Card, Stat } from "../common/Card";

/** One row's range bar on a 0–100% scale: 95% range (band), actual hit rate (dot), average score (tick). */
function RangeBar({ b }: { b: CalibBin }) {
  if (b.hit_rate == null) return <span className="text-xs text-slate-400">no signals</span>;
  const [lo, hi] = b.ci ?? [b.hit_rate, b.hit_rate];
  return (
    <div className="relative h-4 min-w-32" role="img" aria-label={`hit rate ${b.hit_rate}%, 95% range ${lo} to ${hi}%, average score ${b.mean_score}`}>
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-slate-200 dark:bg-slate-700" />
      <div className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-violet-200 dark:bg-violet-900" style={{ left: `${lo}%`, width: `${Math.max(hi - lo, 0.5)}%` }} />
      {b.mean_score != null && <div className="absolute top-0 h-4 w-0.5 bg-slate-500" style={{ left: `${b.mean_score}%` }} title={`average score ${num(b.mean_score, 1)}`} />}
      <div className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-violet-600 ring-2 ring-white dark:ring-slate-900" style={{ left: `${b.hit_rate}%` }} />
    </div>
  );
}

function BinTable({ rows, first }: { rows: (CalibBin & { band?: string })[]; first: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-xs">
        <thead className="text-left text-slate-500">
          <tr><th className="py-1.5">{first}</th><th className="text-right">Signals</th><th className="text-right">Avg score</th><th className="text-right">Actual hit rate</th><th className="text-right">95% range</th><th className="w-2/5 pl-3">0% ─ 100%</th></tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={`${b.from}-${b.to}`} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1.5">{b.band ?? `${num(b.from, 1)}–${num(b.to, 1)}`}</td>
              <td className="num text-right">{b.n}</td>
              <td className="num text-right">{b.mean_score != null ? num(b.mean_score, 1) : "—"}</td>
              <td className="num text-right font-semibold">{pct(b.hit_rate)}</td>
              <td className="num text-right text-slate-500">{b.ci ? `${b.ci[0]}–${b.ci[1]}%` : "—"}</td>
              <td className="pl-3"><RangeBar b={b} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** How well the signal score matches what actually happened, judged only on years the model hadn't seen. */
export function CalibrationCard({ a }: { a: SignalAnalysis }) {
  const m = a.model;
  const wf = m.calibration_wf;
  const v = m.verdict;
  if (!v) return null;   // built before calibration existed: the Rebuild button refreshes it
  return (
    <Card title="Calibration check" icon={<Scale size={16} className="text-violet-600" />} right={<span className="text-xs text-slate-500">out-of-sample only</span>}>
      <p className={`flex items-start gap-2 rounded-xl px-3 py-2 text-sm ${v.edge ? "bg-green-50 text-green-800 dark:bg-green-950/30 dark:text-green-300" : "bg-orange-50 text-orange-800 dark:bg-orange-950/30 dark:text-orange-300"}`}>
        {v.edge ? <CheckCircle2 size={16} className="mt-0.5 shrink-0" /> : <AlertTriangle size={16} className="mt-0.5 shrink-0" />}{v.text}
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Out-of-sample signals" value={a.counts.oos.toLocaleString("en-IN")} sub={`of ${a.counts.labelled.toLocaleString("en-IN")} with a result`} />
        <Stat label="AUC (0.5 = coin flip)" value={num(m.auc, 3)} sub={m.auc_ci ? `95% range ${m.auc_ci[0]}–${m.auc_ci[1]}` : undefined}
          tip="How often a hit scored higher than a miss. 0.5 is no better than chance; the range is a bootstrap 95% interval." />
        <Stat label="Average hit rate" value={pct(m.base_rate)} sub="the forecast to beat" />
        <Stat label="Calibrated vs average" value={wf?.skill != null ? `${wf.skill > 0 ? "+" : ""}${num(wf.skill, 1)}%` : "—"}
          className={wf?.skill != null ? (wf.skill > 0 ? "text-gain" : "text-loss") : ""}
          sub={wf?.n ? `Brier ${num(wf.brier, 4)} vs ${num(wf.brier_base, 4)} · ${wf.n} signals` : "needs 2+ out-of-sample years"}
          tip="Brier skill: how much the calibrated hit rates beat simply using the earlier years' average, on years neither had seen. Above 0 is better." />
      </div>
      <div className="mt-4 space-y-4">
        <div>
          <div className="mb-1 text-sm font-semibold">Score bands</div>
          <BinTable rows={a.calibration} first="Band" />
        </div>
        {a.reliability && a.reliability.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-violet-700 dark:text-violet-300">Ten equal-sized score groups</summary>
            <div className="mt-2"><BinTable rows={a.reliability} first="Score range" /></div>
          </details>
        )}
        {wf && wf.folds.length > 0 && (
          <details>
            <summary className="cursor-pointer text-sm font-semibold text-violet-700 dark:text-violet-300">Walk-forward by year</summary>
            <table className="mt-2 w-full text-xs">
              <thead className="text-left text-slate-500"><tr><th className="py-1">Year</th><th className="text-right">Signals</th><th className="text-right">Calibrated on</th><th className="text-right">Brier (calibrated)</th><th className="text-right">Brier (average)</th></tr></thead>
              <tbody>{wf.folds.map((f) => (
                <tr key={f.year} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-1">{f.year}</td><td className="num text-right">{f.n}</td><td className="num text-right">{f.trained_on} earlier</td>
                  <td className={`num text-right ${f.brier != null && f.brier_base != null ? (f.brier < f.brier_base ? "text-gain" : "text-loss") : ""}`}>{num(f.brier, 4)}</td>
                  <td className="num text-right">{num(f.brier_base, 4)}</td>
                </tr>))}</tbody>
            </table>
          </details>
        )}
      </div>
      <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-full bg-violet-600" />actual hit rate</span>
        <span className="flex items-center gap-1"><span className="inline-block h-1.5 w-5 rounded-full bg-violet-200 dark:bg-violet-900" />95% range</span>
        <span className="flex items-center gap-1"><span className="inline-block h-3 w-0.5 bg-slate-500" />average score</span>
        <span>A well-calibrated score has its tick on the dot. Lower is better for Brier.</span>
      </p>
    </Card>
  );
}

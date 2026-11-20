import { useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { usePoll } from "../hooks/usePoll";
import { getPremarket, getPremarketHistory, refreshPremarket } from "../services/api";
import type { PmReport } from "../types/api";
import { dmy, hm } from "../utils/format";
import { Card, Pill } from "../components/common/Card";
import { Button, PageHeader } from "../components/common/Controls";
import { ErrorNote, Loading, Warning } from "../components/common/States";
import { ScoreMeter, totalTone } from "../components/premarket/ScoreMeter";
import { FactorCard } from "../components/premarket/FactorCard";
import { NewsFeed } from "../components/premarket/NewsFeed";
import { Recommendation } from "../components/premarket/Recommendation";
import { ManualInputs } from "../components/premarket/ManualInputs";
import { HistoryPanel } from "../components/premarket/HistoryPanel";

/** Pre-market analysis: previous day's news, five factors worth one point each, the total, the conclusion and its track record.
 *  Information only. The trading engine may read the stored result as an extra, optional confirmation. */
export default function PreMarket() {
  const rep = usePoll(() => getPremarket(), 60000);
  const hist = usePoll(getPremarketHistory, 120000);
  const [fresh, setFresh] = useState<PmReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const report = fresh && fresh.day === rep.data?.day ? fresh : rep.data?.report ?? null;
  const refresh = async () => {
    setBusy(true); setErr(null);
    try { setFresh((await refreshPremarket()).report); void hist.reload(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  const saved = (r: PmReport) => { setFresh(r); void hist.reload(); };
  const tone = report ? totalTone(report) : "neutral";

  return (
    <div className="space-y-4">
      <PageHeader title="Pre-Market Analysis" subtitle={`${rep.data ? dmy(rep.data.day) : "Today"} · five factors, one point each, before NIFTY opens`}
        actions={<Button onClick={() => void refresh()} disabled={busy} variant="primary"><RefreshCw size={14} className={busy ? "animate-spin" : ""} /> {report ? "Refresh data" : "Generate report"}</Button>} />
      <div className="flex items-start gap-2 rounded-xl border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200">
        <ShieldCheck size={16} className="mt-0.5 shrink-0" />
        <span>This is context, not a trade signal, and this page cannot place an order. Paper entries still need a completed 5-minute candle signal confirmed by the 15-minute direction. The engine can log whether this bias agreed with each paper trade, and optionally skip trades against it (Automated Paper Trading settings).</span>
      </div>
      {err && <ErrorNote>{err}</ErrorNote>}
      {rep.error && !rep.data && <ErrorNote offline>{rep.error}</ErrorNote>}
      {rep.loading && !rep.data && <Loading />}
      {rep.data && !report && (
        <Card title="No report for today yet">
          <p className="text-sm text-slate-600 dark:text-slate-300">A report is created automatically from 08:30 IST on trading days while the server runs. You can generate one now; it reads the outside sources from this machine and the stored NIFTY candles.</p>
        </Card>
      )}
      {report && (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <Pill tone="info">updated {hm(report.generated_at)}</Pill>
            {report.snapshots && report.snapshots.length > 1 && <span>{report.snapshots.length} recalculations changed the result today</span>}
            {report.actual && <Pill tone={report.outcome === "CORRECT" ? "good" : report.outcome === "INCORRECT" ? "bad" : "neutral"}>
              NIFTY {report.actual.change_pct > 0 ? "+" : ""}{report.actual.change_pct}% · {report.outcome}</Pill>}
          </div>
          {report.warnings.length > 0 && (
            <Warning><ul className="list-disc pl-4" data-testid="pm-warnings">{[...new Set(report.warnings)].map((w) => <li key={w}>{w}</li>)}</ul></Warning>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Total score" accent={tone === "good" ? "gain" : tone === "bad" ? "loss" : "neutral"} right={<span>{report.total.bias}</span>}>
              <div className="mb-3 flex items-baseline gap-3">
                <span className={`num text-5xl font-bold ${tone === "good" ? "text-gain" : tone === "bad" ? "text-loss" : ""}`} data-testid="pm-total">{report.total.total > 0 ? `+${report.total.total}` : report.total.total}</span>
                <span className="text-sm text-slate-500">of ±5</span>
              </div>
              <ScoreMeter total={report.total.total} available={report.total.available_factors} />
            </Card>
            <Recommendation r={report} />
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {report.factors.map((f, i) => <FactorCard key={f.key} f={f} index={i + 1} />)}
          </div>
        </>
      )}
      <NewsFeed />
      <ManualInputs onSaved={saved} />
      {hist.data && <HistoryPanel h={hist.data} />}
      <Card title="What validation found" bodyClass="px-4 pb-4">
        <p className="text-sm" data-testid="pm-validation">
          Rebuilt for 1,032 sessions (Sep 2022 to Nov 2026) from data known before the open, the four factors that have history called NIFTY's close against the
          previous close right 56.9% of the time when the score was +2 or beyond −2 (269 calls, 95% range 50.9–62.7%), and 51.1% in 2025–26. The US half of the global
          factor did best (61.0%) because US moves carry into NIFTY's opening gap; crude (48.3%), VIX (48.1%) and structure (54.1%) did not help on their own.
          Open to close, the part a trade placed after 09:15 can capture, showed no relation to the score. Treat the score as a reading of the opening, not a prediction of the day.
          Gift Nifty and FII/DII have no history, so they are not part of this test (docs/PREMARKET.md).
        </p>
      </Card>
      <p className="text-xs text-slate-500">Sources: Yahoo Finance (indices, crude, India VIX; may be delayed up to 15 minutes), publisher RSS feeds and Google News (articles from a list of trusted outlets; summaries are the publishers' own), your stored NIFTY candles, and figures you enter. Gift Nifty and automatic FII/DII data are not available. Weights and thresholds are fixed starting values, never fitted to a result; the history above shows how the bias has done.</p>
    </div>
  );
}

import { useState } from "react";
import { ExternalLink, Layers, Zap } from "lucide-react";
import type { PmArticle, PmDirection, PmFactor } from "../../types/api";
import { Pill, type Tone } from "../common/Card";

const FACTOR_NAME: Record<PmFactor["key"], string> = {
  global: "Global markets", fii_dii: "FII / DII", crude: "Crude oil", vix: "India VIX", structure: "NIFTY structure",
};
const sentTone = (s: PmArticle["sentiment"]): Tone => (s === "positive" ? "good" : s === "negative" ? "bad" : "neutral");
const dirTone = (d: PmDirection): Tone => (d === "bullish" ? "good" : d === "bearish" ? "bad" : "neutral");
const levelTone = (l: PmArticle["impact_level"]): Tone => (l === "High" ? "bad" : l === "Medium" ? "warn" : "neutral");
const when = (iso: string) => iso.replace("T", " ");

/** The publisher's thumbnail, or a tile with the source's initial when there is none or it cannot be loaded. */
function Thumb({ a }: { a: PmArticle }) {
  const [bad, setBad] = useState(false);
  if (a.image && !bad) {
    return <img src={a.image} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setBad(true)}
      className="h-40 w-full shrink-0 rounded-lg bg-slate-100 object-cover sm:h-24 sm:w-40 dark:bg-slate-800" data-testid="thumb" />;
  }
  return <div aria-hidden className="grid h-16 w-full shrink-0 place-items-center rounded-lg bg-slate-100 text-2xl font-bold text-slate-400 sm:h-24 sm:w-40 dark:bg-slate-800" data-testid="thumb-fallback">
    {a.source.charAt(0).toUpperCase()}
  </div>;
}

/** One news article: headline, the publisher's own summary, source and time, sentiment, expected NIFTY effect, why it matters,
 *  the sectors and indices it touches, related coverage and a link to the original. Analysis comes from fixed keyword rules. */
export function ArticleCard({ a }: { a: PmArticle }) {
  return (
    <article className={`flex flex-col gap-3 rounded-xl border p-3 sm:flex-row ${a.is_breaking ? "border-red-300 bg-red-50/40 dark:border-red-900 dark:bg-red-950/20" : "border-slate-200 dark:border-slate-800"}`} data-testid="article">
      <Thumb a={a} />
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {a.is_breaking && <Pill tone="bad"><Zap size={11} className="mr-0.5 inline" />Breaking</Pill>}
          {a.is_new && <Pill tone="info">New</Pill>}
          <Pill tone={levelTone(a.impact_level)}>{a.impact_level} impact</Pill>
          <Pill tone={sentTone(a.sentiment)}>{a.sentiment}</Pill>
          <Pill tone={dirTone(a.nifty_impact)}>NIFTY: {a.nifty_impact}</Pill>
          <span className="text-[11px] text-slate-500">{a.topic}</span>
        </div>
        <h3 className="text-sm font-semibold leading-snug">
          {a.link ? <a href={a.link} target="_blank" rel="noreferrer noopener" className="hover:underline">{a.headline}</a> : a.headline}
        </h3>
        {a.summary
          ? <p className="text-sm text-slate-600 dark:text-slate-300" data-testid="summary">{a.summary}</p>
          : <p className="text-xs italic text-slate-500" data-testid="no-summary">This publisher's feed gives no summary. Open the original article to read it.</p>}
        <p className="text-xs text-slate-500">
          <span className="font-medium text-slate-700 dark:text-slate-300">{a.source}</span> · {when(a.published)} IST · {a.via}
        </p>
        <p className="rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-600 dark:bg-slate-800/60 dark:text-slate-300" data-testid="why">
          <span className="font-medium">Why it matters: </span>{a.why}
        </p>
        {(a.sectors.length > 0 || a.indices.length > 0 || a.factor) && (
          <div className="flex flex-wrap gap-1 text-[11px]">
            {a.indices.map((i) => <span key={i} className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700 dark:bg-blue-950 dark:text-blue-300">{i}</span>)}
            {a.sectors.map((s) => <span key={s} className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600 dark:bg-slate-800 dark:text-slate-300">{s}</span>)}
            {a.factor && <span className="rounded bg-violet-50 px-1.5 py-0.5 text-violet-700 dark:bg-violet-950 dark:text-violet-300">Evidence for: {FACTOR_NAME[a.factor]}</span>}
          </div>
        )}
        {a.related.length > 0 && (
          <details className="text-xs" data-testid="related">
            <summary className="flex cursor-pointer items-center gap-1 text-slate-500"><Layers size={12} /> Also covered by {a.related.length} other {a.related.length === 1 ? "outlet" : "outlets"}</summary>
            <ul className="mt-1 space-y-1 pl-4">
              {a.related.map((r) => (
                <li key={r.link || r.headline}>
                  {r.link ? <a href={r.link} target="_blank" rel="noreferrer noopener" className="hover:underline">{r.headline}</a> : r.headline}
                  <span className="text-slate-500"> · {r.source} · {when(r.published)}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
        {a.link && (
          <a href={a.link} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:underline dark:text-blue-400">
            Read full news <ExternalLink size={12} />
          </a>
        )}
      </div>
    </article>
  );
}

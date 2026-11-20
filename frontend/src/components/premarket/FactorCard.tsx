import { Clock } from "lucide-react";
import type { PmFactor } from "../../types/api";
import { Card, Pill, type Tone } from "../common/Card";

const tone = (s: PmFactor["status"]): Tone => (s === "BULLISH" ? "good" : s === "BEARISH" ? "bad" : s === "UNAVAILABLE" ? "warn" : "neutral");

/** One of the five factors: result, score, the data behind it, where and when it came from. */
export function FactorCard({ f, index }: { f: PmFactor; index: number }) {
  const sc = f.available ? (f.score > 0 ? `+${f.score}` : String(f.score)) : "0";
  return (
    <Card title={`${index}. ${f.title}`} accent={f.status === "BULLISH" ? "gain" : f.status === "BEARISH" ? "loss" : "neutral"}
      right={<span className="flex items-center gap-2"><Pill tone={tone(f.status)}>{f.status}</Pill><span className="num text-base font-bold" data-testid={`score-${f.key}`}>{sc}</span></span>}>
      <p className="text-sm">{f.summary}</p>
      <dl className="mt-3 space-y-1 text-xs">
        {f.data.map((r, i) => (
          <div key={i} className="flex flex-wrap justify-between gap-x-3 border-t border-slate-100 py-1 dark:border-slate-800">
            <dt className="text-slate-500">{r.label}</dt>
            <dd className="num text-right font-medium">{r.value}{r.note && <span className="ml-1 font-normal text-slate-500">· {r.note}</span>}</dd>
          </div>
        ))}
      </dl>
      {f.warnings.map((w) => <p key={w} className="mt-2 rounded-md bg-orange-50 px-2 py-1 text-xs text-orange-800 dark:bg-orange-950 dark:text-orange-300">{w}</p>)}
      {f.news && f.news.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-2 dark:border-slate-800" data-testid={`evidence-${f.key}`}>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">News evidence</div>
          <ul className="space-y-1.5 text-xs">
            {f.news.map((n) => (
              <li key={n.id} className="flex items-start gap-2">
                <Pill tone={n.relation === "supports" ? "good" : n.relation === "conflicts" ? "bad" : "neutral"} className="mt-0.5 !px-1.5 !text-[10px]">{n.relation}</Pill>
                <span className="min-w-0">
                  {n.link ? <a href={n.link} target="_blank" rel="noreferrer noopener" className="hover:underline">{n.headline}</a> : n.headline}
                  <span className="text-slate-500"> · {n.source} · {n.published.slice(5, 16).replace("T", " ")} · {n.impact_level}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-[11px] text-slate-500">Evidence only: the score above comes from market data. An article backs one factor, so no event is counted twice.</p>
        </div>
      )}
      <p className="mt-2 text-xs text-slate-500">{f.explanation}</p>
      <div className="mt-2 flex items-center gap-1 text-[11px] text-slate-500">
        <Clock size={11} /> {f.asof ? `data ${f.asof.replace("T", " ")}` : "no data time"} · {f.source ?? "no source"}{f.delayed ? ` · ${f.delayed}` : ""}
      </div>
    </Card>
  );
}

import { useMemo, useRef, useState } from "react";
import { ExternalLink, Newspaper, RefreshCw } from "lucide-react";
import { useApi } from "../../hooks/useApi";
import { getPremarketNews } from "../../services/api";
import type { PmArticle } from "../../types/api";
import { dmy } from "../../utils/format";
import { Card, Pill } from "../common/Card";
import { Button } from "../common/Controls";
import { Empty, ErrorNote, Limitation, Loading, Warning } from "../common/States";
import type { Lang } from "./lessons";
import { UI, tt } from "./ui";

const PAGE = 12;
/** Topic chips: a keyword rule over the headline and the publisher's summary, or a category the news service already assigned. */
const TOPICS: { key: string; test: (a: PmArticle, text: string) => boolean }[] = [
  { key: "all", test: () => true },
  { key: "nifty", test: (_a, t) => /nifty|sensex/.test(t) },
  { key: "options", test: (_a, t) => /\boptions?\b|derivatives?|f&o|\bexpiry\b|put-call|open interest/.test(t) },
  { key: "nse", test: (_a, t) => /\bnse\b|national stock exchange/.test(t) },
  { key: "sebi", test: (_a, t) => /\bsebi\b/.test(t) },
  { key: "vix", test: (_a, t) => /\bvix\b|volatil/.test(t) },
  { key: "fii", test: (a, t) => a.categories.includes("fii_dii") || /\bfiis?\b|\bdiis?\b|foreign (portfolio|institutional)/.test(t) },
  { key: "global", test: (a, t) => a.categories.some((c) => ["global", "us", "asia"].includes(c)) || /wall street|global markets?/.test(t) },
];
const text = (a: PmArticle) => `${a.headline} ${a.summary ?? ""} ${a.topic}`.toLowerCase();

const TOPIC_ML: Record<string, string> = {
  "Indian Stock Market": "ഇന്ത്യൻ ഓഹരി വിപണി", "Global Markets": "ആഗോള വിപണികൾ", "US Market": "യുഎസ് വിപണി", "Asian Markets": "ഏഷ്യൻ വിപണികൾ",
  "FII / DII": "FII / DII", "RBI / Federal Reserve": "RBI / ഫെഡറൽ റിസർവ്", "Crude Oil": "ക്രൂഡ് ഓയിൽ", "Economic News": "സാമ്പത്തിക വാർത്തകൾ",
  "NIFTY / Bank NIFTY": "NIFTY / Bank NIFTY", "Important Breaking News": "പ്രധാന ബ്രേക്കിംഗ് വാർത്ത",
};
const SENT_ML = { positive: "പോസിറ്റീവ്", negative: "നെഗറ്റീവ്", neutral: "നിഷ്പക്ഷം" } as const;
const DIR_ML = { bullish: "ഉയർച്ചയ്ക്ക് അനുകൂലം", bearish: "താഴ്ചയ്ക്ക് അനുകൂലം", neutral: "നിഷ്പക്ഷം" } as const;
const LEVEL_ML = { High: "ഉയർന്നത്", Medium: "ഇടത്തരം", Low: "കുറവ്" } as const;

/** Malayalam summary built from the article's own tags (topic, sentiment, expected NIFTY effect, impact), not a machine translation. */
export function mlSummary(a: PmArticle): string {
  return `വിഷയം: ${TOPIC_ML[a.topic] ?? a.topic}. വാർത്തയുടെ സ്വഭാവം: ${SENT_ML[a.sentiment] ?? a.sentiment}. NIFTY-യിൽ സാധ്യതയുള്ള സ്വാധീനം: ${DIR_ML[a.nifty_impact] ?? a.nifty_impact}. സ്വാധീന തോത്: ${LEVEL_ML[a.impact_level] ?? a.impact_level}.`;
}
export const stamp = (iso: string) => `${dmy(iso.slice(0, 10))}, ${iso.slice(11, 16)} IST`;

function Article({ a, lang }: { a: PmArticle; lang: Lang }) {
  return (
    <article className="space-y-1.5 rounded-xl border border-slate-200 p-3 dark:border-slate-800" data-testid="learn-article">
      <div className="flex flex-wrap items-center gap-1.5">
        {a.is_breaking && <Pill tone="bad">{lang === "ml" ? "ബ്രേക്കിംഗ്" : "Breaking"}</Pill>}
        <Pill tone="info">{lang === "ml" ? TOPIC_ML[a.topic] ?? a.topic : a.topic}</Pill>
      </div>
      <h3 className="text-sm font-semibold leading-snug">
        {a.link ? <a href={a.link} target="_blank" rel="noreferrer noopener" className="hover:underline">{a.headline}</a> : a.headline}
      </h3>
      {lang === "ml" && <p className="rounded-md bg-blue-50 px-2 py-1 text-sm text-slate-700 dark:bg-blue-950/30 dark:text-slate-200" data-testid="learn-ml-summary">{mlSummary(a)}</p>}
      {a.summary
        ? <p className="text-sm text-slate-600 dark:text-slate-300" data-testid="learn-summary">{lang === "ml" && <span className="mr-1 text-xs font-semibold text-slate-500">{tt(UI.publisherSummary, lang)}:</span>}{a.summary}</p>
        : <p className="text-xs italic text-slate-500">{tt(UI.noSummary, lang)}</p>}
      <p className="text-xs text-slate-500">
        <span className="font-medium text-slate-700 dark:text-slate-300">{tt(UI.source, lang)}: {a.source}</span> · {tt(UI.published, lang)}: <time dateTime={a.published}>{stamp(a.published)}</time>
      </p>
      {a.link && <a href={a.link} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 hover:underline dark:text-blue-400">
        {tt(UI.readMore, lang)} <ExternalLink size={12} /></a>}
    </article>
  );
}

/** Latest options and market news. Reads the existing news service (publisher RSS feeds and Google News through the backend), so it shows
 *  real articles only. If no source answers it says so. Malayalam mode adds a summary built from the article's tags. */
export function LearnNews({ lang }: { lang: Lang }) {
  const force = useRef(false);
  const feed = useApi(() => getPremarketNews(force.current), []);
  const [topic, setTopic] = useState("all");
  const [shown, setShown] = useState(PAGE);
  const [busy, setBusy] = useState(false);

  const refresh = async () => { force.current = true; setBusy(true); try { await feed.reload(); } finally { force.current = false; setBusy(false); } };
  const data = feed.data;
  const counts = useMemo(() => Object.fromEntries(TOPICS.map((t) => [t.key, (data?.articles ?? []).filter((a) => t.test(a, text(a))).length])), [data]);
  const list = useMemo(() => {
    const t = TOPICS.find((x) => x.key === topic) ?? TOPICS[0];
    return (data?.articles ?? []).filter((a) => t.test(a, text(a))).sort((a, b) => (a.published < b.published ? 1 : -1));
  }, [data, topic]);

  return (
    <Card title={<span>{tt(UI.news, lang)}</span>} icon={<Newspaper size={16} className="text-blue-600" />}
      right={data?.fetched_at ? <span data-testid="learn-news-updated">{tt(UI.updated, lang)}: {stamp(data.fetched_at)}</span> : undefined}>
      <div className="space-y-3" data-testid="learn-news">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="max-w-xl text-xs text-slate-500">{tt(UI.newsIntro, lang)}</p>
          <Button onClick={() => void refresh()} disabled={busy || feed.loading}><RefreshCw size={14} className={busy || feed.loading ? "animate-spin" : ""} />{tt(UI.refresh, lang)}</Button>
        </div>
        {lang === "ml" && <Limitation>{tt(UI.mlNote, lang)}</Limitation>}

        {feed.loading && !data && <Loading text={tt(UI.loadingNews, lang)} className="h-32" />}
        {feed.error && !data && (
          <ErrorNote offline><div>{tt(UI.newsError, lang)} {feed.error}</div>
            <div className="mt-2"><Button onClick={() => void feed.reload()}>{tt(UI.retry, lang)}</Button></div></ErrorNote>
        )}
        {feed.error && data && <ErrorNote>{tt(UI.newsError, lang)} {feed.error}</ErrorNote>}

        {data && data.status === "unavailable" && <Empty title={tt(UI.news, lang)}>{tt(UI.notConnected, lang)}</Empty>}
        {data && data.status === "stale" && <Warning>{tt(UI.stale, lang)} {data.fetched_at ? stamp(data.fetched_at) : "—"}.</Warning>}

        {data && data.status !== "unavailable" && (
          <>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label={tt(UI.news, lang)}>
              {TOPICS.map((t) => (
                <button key={t.key} type="button" aria-pressed={topic === t.key} onClick={() => { setTopic(t.key); setShown(PAGE); }}
                  className={`rounded-full border px-3 py-1 text-xs font-medium ${topic === t.key ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 bg-white text-slate-600 hover:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"}`}>
                  {tt(UI.topics[t.key], lang)} ({counts[t.key]})
                </button>
              ))}
            </div>
            {list.length === 0
              ? <Empty title={tt(UI.emptyNews, lang)} />
              : <div className="space-y-2">{list.slice(0, shown).map((a) => <Article key={a.id} a={a} lang={lang} />)}</div>}
            {list.length > shown && <div className="text-center"><Button onClick={() => setShown(shown + PAGE)}>{tt(UI.showMore, lang)} ({list.length - shown})</Button></div>}
          </>
        )}
      </div>
    </Card>
  );
}

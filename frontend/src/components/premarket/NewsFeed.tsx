import { useMemo, useState } from "react";
import { CalendarClock, Newspaper, RefreshCw, Search, Zap } from "lucide-react";
import { usePoll } from "../../hooks/usePoll";
import { getPremarketNews } from "../../services/api";
import type { PmNewsFeed } from "../../types/api";
import { breakingNow, filterArticles, groupByPeriod } from "../../utils/news";
import { Card, Pill } from "../common/Card";
import { Button, inputCls, selectInline } from "../common/Controls";
import { Empty, ErrorNote, Loading, Warning } from "../common/States";
import { ArticleCard } from "./ArticleCard";

const PAGE = 30;

/** The live news section of the Pre-Market page: real articles from publisher RSS feeds and Google News, readable here, with the
 *  category tabs, search, date filter, breaking highlight, today's events and the state of every source. Nothing is invented:
 *  when no source answers the feed says so, and when a refresh fails the last good fetch is labelled with its own time. */
export function NewsFeed() {
  const poll = usePoll(() => getPremarketNews(), 120000);
  const [forced, setForced] = useState<PmNewsFeed | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshErr, setRefreshErr] = useState<string | null>(null);
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [date, setDate] = useState("all");
  const [shown, setShown] = useState(PAGE);

  const feed = forced && (!poll.data || forced.now >= poll.data.now) ? forced : poll.data;
  const refresh = async () => {
    setBusy(true); setRefreshErr(null);
    try { setForced(await getPremarketNews(true)); } catch (e) { setRefreshErr((e as Error).message); } finally { setBusy(false); }
  };
  const list = useMemo(() => (feed ? filterArticles(feed, { tab, query, date }) : []), [feed, tab, query, date]);
  const groups = useMemo(() => (feed ? groupByPeriod(list.slice(0, shown), feed.periods) : []), [feed, list, shown]);
  const breaking = useMemo(() => (feed ? breakingNow(feed.articles) : []), [feed]);
  const customDay = /^\d{4}-\d{2}-\d{2}$/.test(date);
  const reset = (f: () => void) => () => { f(); setShown(PAGE); };

  return (
    <Card title="Market news" icon={<Newspaper size={16} className="text-blue-600" />} bodyClass="px-4 pb-4"
      right={feed?.fetched_at ? <span data-testid="news-updated">last updated {feed.fetched_at.slice(11, 19)} IST</span> : undefined}>
      <div className="space-y-3" data-testid="news-section">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input type="search" aria-label="Search news" placeholder="Search headlines, summaries, sectors, sources" value={query}
              onChange={(e) => { setQuery(e.target.value); setShown(PAGE); }} className={`${inputCls} pl-8`} />
          </div>
          <select aria-label="Date filter" value={customDay ? "custom" : date} onChange={(e) => { setDate(e.target.value === "custom" ? (feed?.now.slice(0, 10) ?? "") : e.target.value); setShown(PAGE); }} className={selectInline}>
            <option value="all">All dates</option>
            <option value="today">Today</option>
            <option value="previous">Previous trading day{feed ? ` (${feed.previous_trading_day.slice(5)})` : ""}</option>
            <option value="24h">Last 24 hours</option>
            <option value="custom">Pick a date</option>
          </select>
          {customDay && <input type="date" aria-label="News date" value={date} onChange={(e) => { setDate(e.target.value); setShown(PAGE); }} className={`${selectInline}`} />}
          <Button onClick={() => void refresh()} disabled={busy} variant="secondary"><RefreshCw size={14} className={busy ? "animate-spin" : ""} /> Refresh news</Button>
        </div>

        {refreshErr && <ErrorNote>{refreshErr}</ErrorNote>}
        {poll.loading && !feed && <Loading text="Fetching the latest news…" className="h-32" />}
        {poll.error && !feed && <ErrorNote offline>Could not load news: {poll.error}. Nothing is shown rather than made-up headlines. <button type="button" className="underline" onClick={() => void poll.reload()}>Try again</button></ErrorNote>}

        {feed && (
          <>
            {feed.status === "unavailable" && (
              <ErrorNote offline><span data-testid="news-unavailable">No news source could be reached right now, so there is no news to show. Nothing is made up or filled in; try Refresh news in a moment.</span></ErrorNote>
            )}
            {feed.status === "stale" && (
              <Warning><span data-testid="news-stale">Could not refresh. These articles are from the last successful fetch at {feed.fetched_at?.slice(11, 16)} IST and are <b>not live</b>.</span></Warning>
            )}
            {poll.error && <Warning>Refresh failed ({poll.error}); showing what was loaded at {feed.fetched_at?.slice(11, 16)} IST.</Warning>}
            {feed.status !== "unavailable" && (
              <p className="text-xs text-slate-500" data-testid="news-sources">
                <Pill tone={feed.status === "live" ? "good" : "warn"}>{feed.status}</Pill>{" "}
                {feed.summary.total} articles from {feed.sources.publishers.filter((p) => p.feeds_ok > 0).map((p) => p.name).join(", ") || "no publisher"}
                {feed.sources.searches_ok > 0 ? ` and Google News (${feed.sources.searches_ok} of ${feed.sources.searches} searches)` : ""}.
                {feed.sources.publishers.some((p) => p.feeds_ok < p.feeds) && " Some feeds did not answer."}
              </p>
            )}
            {feed.warnings.length > 0 && feed.status === "live" && <p className="text-xs text-orange-700 dark:text-orange-400" data-testid="news-warnings">{[...new Set(feed.warnings)].join(" · ")}</p>}

            {breaking.length > 0 && (
              <div className="rounded-xl border border-red-300 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950/30" data-testid="breaking">
                <div className="mb-1 flex items-center gap-1.5 text-sm font-semibold text-red-700 dark:text-red-400"><Zap size={14} /> Breaking</div>
                <ul className="space-y-1 text-sm">
                  {breaking.map((a) => (
                    <li key={a.id}>
                      <a href={a.link} target="_blank" rel="noreferrer noopener" className="font-medium hover:underline">{a.headline}</a>
                      <span className="text-xs text-slate-500"> · {a.source} · {a.published.slice(11, 16)} · NIFTY: {a.nifty_impact}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="rounded-xl bg-blue-50 p-3 text-sm dark:bg-blue-950/40" data-testid="events">
              <div className="mb-1 flex items-center gap-1.5 font-semibold text-blue-800 dark:text-blue-300"><CalendarClock size={14} /> Today's events</div>
              {feed.events.length > 0
                ? <ul className="space-y-1 text-xs">{feed.events.map((e, i) => <li key={i}>{e.title} <span className="text-slate-500">({e.basis})</span></li>)}</ul>
                : <p className="text-xs text-slate-600 dark:text-slate-300">No events on record for today. There is no verified economic calendar feed: only the weekly expiry, events you enter below and headlines that mention something today (marked unverified) can appear here.</p>}
            </div>

            <div role="tablist" aria-label="News categories" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
              {feed.categories.map((c) => (
                <button key={c.key} type="button" role="tab" aria-selected={tab === c.key} onClick={reset(() => setTab(c.key))}
                  className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium ${tab === c.key ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"}`}>
                  {c.label} <span className="opacity-70">{c.count}</span>
                </button>
              ))}
            </div>

            {feed.status !== "unavailable" && list.length === 0 && (
              <Empty title={feed.articles.length === 0 ? "No articles" : "No articles match"}>
                {feed.articles.length === 0 ? "The sources answered but had no relevant articles." : "Try another tab, a wider date range or different search words."}
              </Empty>
            )}
            <div className="space-y-4" data-testid="news">
              {groups.map((g) => (
                <section key={g.key} aria-label={g.label} data-testid={`period-${g.key}`}>
                  <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {g.label} <span className="rounded-full bg-slate-100 px-2 py-0.5 normal-case dark:bg-slate-800">{g.items.length}</span>
                    {g.key === "earlier" && <span className="normal-case text-slate-400">older news, not today's</span>}
                  </h3>
                  <div className="space-y-3">{g.items.map((a) => <ArticleCard key={a.id} a={a} />)}</div>
                </section>
              ))}
            </div>
            {list.length > shown && (
              <div className="text-center">
                <Button onClick={() => setShown((n) => n + PAGE)} variant="secondary">Show more ({list.length - shown} left)</Button>
              </div>
            )}
            <p className="text-[11px] text-slate-500" data-testid="news-method">{feed.method} Summaries and links are the publishers'; open "Read full news" for the original article.</p>
          </>
        )}
      </div>
    </Card>
  );
}

import type { PmArticle, PmNewsFeed, PmPeriod } from "../types/api";

export type DateFilter = "all" | "today" | "previous" | "24h" | string;      // or a YYYY-MM-DD day

export interface NewsFilter { tab: string; query: string; date: DateFilter }

/** Articles of one tab (a category key, "all" or "breaking") that match the search words and the date filter. Newest first. */
export function filterArticles(feed: Pick<PmNewsFeed, "articles" | "now" | "previous_trading_day">, f: NewsFilter): PmArticle[] {
  const words = f.query.toLowerCase().split(/\s+/).filter(Boolean);
  const today = feed.now.slice(0, 10);
  const cutoff = Date.parse(feed.now) - 24 * 3600 * 1000;
  return feed.articles.filter((a) => {
    if (f.tab !== "all" && !a.categories.includes(f.tab)) return false;
    const day = a.published.slice(0, 10);
    if (f.date === "today" && day !== today) return false;
    if (f.date === "previous" && day !== feed.previous_trading_day) return false;
    if (f.date === "24h" && Date.parse(a.published) < cutoff) return false;
    if (/^\d{4}-\d{2}-\d{2}$/.test(f.date) && day !== f.date) return false;
    if (!words.length) return true;
    const hay = [a.headline, a.summary ?? "", a.source, a.topic, ...a.sectors, ...a.indices].join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** Keeps the order of `periods` and drops empty groups. */
export function groupByPeriod(articles: PmArticle[], periods: { key: PmPeriod; label: string }[]) {
  return periods.map((p) => ({ ...p, items: articles.filter((a) => a.period === p.key) })).filter((g) => g.items.length > 0);
}

/** Articles worth a breaking-news highlight: flagged breaking and not from an earlier period. */
export const breakingNow = (articles: PmArticle[], n = 3) => articles.filter((a) => a.is_breaking && a.period !== "earlier").slice(0, n);

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PreMarket from "../../pages/PreMarket";
import { fail, mockApi, type MockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { makePmArticle, makePmFeed } from "../../test/fixtures";
import { breakingNow, filterArticles, groupByPeriod } from "../../utils/news";
import type { PmNewsFeed } from "../../types/api";

afterEach(() => { vi.restoreAllMocks(); });

const withFeed = (api: MockApi, feed: unknown) => api.on("GET", "/api/premarket/news", () => feed);
const page = (api = mockApi()) => renderWithProviders(<PreMarket />, { api });
const section = async () => within(await screen.findByTestId("news-section"));

describe("news feed on the Pre-Market page", () => {
  it("shows real articles with summary, source, time, sentiment, NIFTY impact, impact level and an original link", async () => {
    page();
    const cards = within(await screen.findByTestId("news")).getAllByTestId("article");
    const first = within(cards.find((c) => c.textContent?.includes("Wall Street rallies"))!);
    expect(first.getByText(/US stocks closed higher as the Federal Reserve hinted at easing/)).toBeInTheDocument();
    expect(first.getByText("Reuters")).toBeInTheDocument();
    expect(first.getByText(/2026-11-18 22:10 IST/)).toBeInTheDocument();
    expect(first.getByText("positive")).toBeInTheDocument();
    expect(first.getByText("NIFTY: bullish")).toBeInTheDocument();
    expect(first.getByText("High impact")).toBeInTheDocument();
    expect(first.getByTestId("why")).toHaveTextContent(/Why it matters: .*NIFTY's opening/);
    expect(first.getByText("NIFTY IT")).toBeInTheDocument();
    expect(first.getByText("IT & technology")).toBeInTheDocument();
    expect(first.getByRole("link", { name: /Read full news/ })).toHaveAttribute("href", "https://example.com/a");
    expect(first.getByRole("link", { name: /Read full news/ })).toHaveAttribute("target", "_blank");
    expect(first.getByTestId("thumb")).toHaveAttribute("src", "https://example.com/a.jpg");
  });

  it("never invents a summary or a picture: it says the feed gave none and shows the source initial", async () => {
    page();
    const card = within((await screen.findAllByTestId("article")).find((c) => c.textContent?.includes("Crude oil slumps"))!);
    expect(card.getByTestId("no-summary")).toHaveTextContent(/gives no summary/);
    expect(card.queryByTestId("summary")).not.toBeInTheDocument();
    expect(card.getByTestId("thumb-fallback")).toHaveTextContent("B");
  });

  it("combines related coverage under one article and lists the other outlets with links", async () => {
    page();
    const card = within((await screen.findAllByTestId("article")).find((c) => c.textContent?.includes("Crude oil slumps"))!);
    expect(card.getByText(/Also covered by 1 other outlet/)).toBeInTheDocument();
    expect(card.getByRole("link", { name: "Oil falls as demand worries grow" })).toHaveAttribute("href", "https://example.com/b2");
  });

  it("has the eleven category tabs with counts and filters by tab", async () => {
    page();
    const tabs = within(await screen.findByRole("tablist", { name: /news categories/i })).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent?.replace(/\d+$/, "").trim())).toEqual([
      "All News", "Indian Stock Market", "Global Markets", "US Market", "Asian Markets", "FII / DII", "RBI / Federal Reserve", "Crude Oil",
      "Economic News", "NIFTY / Bank NIFTY", "Important Breaking News"]);
    fireEvent.click(screen.getByRole("tab", { name: /Crude Oil/ }));
    const list = within(screen.getByTestId("news"));
    expect(list.getAllByTestId("article")).toHaveLength(1);
    expect(list.getByText("Crude oil slumps on demand fears")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Asian Markets/ }));
    expect(await screen.findByText("No articles match")).toBeInTheDocument();
  });

  it("highlights breaking news and separates new from older periods", async () => {
    page();
    const b = await screen.findByTestId("breaking");
    expect(within(b).getByRole("link", { name: /RBI holds repo rate steady/ })).toBeInTheDocument();
    expect(within(b).queryByText(/FIIs sell/)).not.toBeInTheDocument();
    const pre = screen.getByTestId("period-today_pre_market");
    expect(within(pre).getByText("New")).toBeInTheDocument();
    expect(within(pre).getByText("Breaking")).toBeInTheDocument();
    expect(screen.getByTestId("period-overnight")).toBeInTheDocument();
    expect(within(screen.getByTestId("period-earlier")).getByText(/older news, not today's/)).toBeInTheDocument();
  });

  it("searches headlines, summaries and sectors", async () => {
    page();
    await screen.findByTestId("news");
    fireEvent.change(screen.getByLabelText("Search news"), { target: { value: "oil gas" } });
    const list = within(screen.getByTestId("news"));
    expect(list.getAllByTestId("article")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Search news"), { target: { value: "federal reserve hinted" } });
    expect(within(screen.getByTestId("news")).getByText(/Wall Street rallies/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search news"), { target: { value: "zzzz" } });
    expect(screen.getByText("No articles match")).toBeInTheDocument();
  });

  it("filters by date: today, the previous trading day and a picked day", async () => {
    page();
    await screen.findByTestId("news");
    fireEvent.change(screen.getByLabelText("Date filter"), { target: { value: "today" } });
    expect(within(screen.getByTestId("news")).getAllByTestId("article")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Date filter"), { target: { value: "previous" } });
    expect(within(screen.getByTestId("news")).getAllByTestId("article")).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Date filter"), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText("News date"), { target: { value: "2026-11-17" } });
    const list = within(screen.getByTestId("news"));
    expect(list.getAllByTestId("article")).toHaveLength(1);
    expect(list.getByText(/FIIs sell/)).toBeInTheDocument();
  });

  it("refresh news asks the server to skip its cache and shows the new time", async () => {
    const api = mockApi();
    page(api);
    await screen.findByTestId("news");
    api.on("GET", "/api/premarket/news", (req) => makePmFeed({ fetched_at: req.query.get("refresh") ? "2026-11-19T09:01:02" : "2026-11-19T08:44:30", now: "2026-11-19T09:01:05" }));
    fireEvent.click(screen.getByRole("button", { name: /refresh news/i }));
    await waitFor(() => expect(screen.getByTestId("news-updated")).toHaveTextContent("09:01:02"));
    expect(api.callsTo("GET", "/api/premarket/news").some((c) => c.query.get("refresh") === "1")).toBe(true);
  });

  it("says plainly when no source answered, with no articles and no made-up news", async () => {
    const api = mockApi();
    withFeed(api, makePmFeed({ status: "unavailable", articles: [], fetched_at: null, events: [], summary: { total: 0, with_summary: 0, with_image: 0, breaking: 0, periods: {}, sentiment: {} },
      sources: { publishers: [], searches_ok: 0, searches: 9 }, warnings: ["Mint feed failed"] }));
    page(api);
    expect(await screen.findByTestId("news-unavailable")).toHaveTextContent(/No news source could be reached/);
    expect(screen.queryByTestId("article")).not.toBeInTheDocument();
    expect(screen.queryByTestId("breaking")).not.toBeInTheDocument();
  });

  it("labels a failed refresh as not live and shows when the articles were fetched", async () => {
    const api = mockApi();
    withFeed(api, makePmFeed({ status: "stale", fetched_at: "2026-11-19T07:10:00", warnings: ["Could not refresh: showing the last successful fetch"] }));
    page(api);
    expect(await screen.findByTestId("news-stale")).toHaveTextContent(/07:10 IST.*not live/);
    expect(screen.getByTestId("news-updated")).toHaveTextContent("07:10:00");
  });

  it("shows an error, not an empty feed, when the news request fails, and the rest of the page still works", async () => {
    const api = mockApi();
    api.on("GET", "/api/premarket/news", () => fail("boom", 500));
    page(api);
    expect(await screen.findByText(/Could not load news/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
    expect(await screen.findByTestId("pm-total")).toHaveTextContent("+3");
  });

  it("shows a loading state while the first fetch runs", async () => {
    page();
    expect(screen.getByText(/Fetching the latest news/)).toBeInTheDocument();
    await screen.findByTestId("news");
  });

  it("shows where the news came from and the plain method note", async () => {
    page();
    const s = await section();
    expect(s.getByTestId("news-sources")).toHaveTextContent(/4 articles from Mint, The Economic Times and Google News \(9 of 9 searches\)/);
    expect(s.getByTestId("news-method")).toHaveTextContent(/fixed keyword rules/);
    expect(screen.getByTestId("news-updated")).toHaveTextContent("08:44:30");
  });

  it("explains an empty events list instead of inventing a calendar", async () => {
    const api = mockApi();
    withFeed(api, makePmFeed({ events: [] }));
    page(api);
    expect(await screen.findByTestId("events")).toHaveTextContent(/no verified economic calendar/i);
  });

  it("shows news evidence on a factor card and says it does not change the score", async () => {
    page();
    const ev = await screen.findByTestId("evidence-global");
    expect(within(ev).getByRole("link", { name: /Wall Street rallies/ })).toHaveAttribute("href", "https://example.com/a");
    expect(ev).toHaveTextContent(/Evidence only: the score above comes from market data/);
    expect(screen.queryByTestId("evidence-vix")).not.toBeInTheDocument();
  });

  it("shows more articles in steps", async () => {
    const many = Array.from({ length: 45 }, (_, i) => makePmArticle({ id: `m${i}`, headline: `Headline number ${i}`, link: `https://example.com/m${i}`, period: "overnight" }));
    const api = mockApi();
    withFeed(api, makePmFeed({ articles: many }));
    page(api);
    expect(await screen.findAllByTestId("article")).toHaveLength(30);
    fireEvent.click(screen.getByRole("button", { name: /Show more \(15 left\)/ }));
    expect(screen.getAllByTestId("article")).toHaveLength(45);
  });
});

describe("news helpers", () => {
  const feed: PmNewsFeed = makePmFeed();
  it("filters by tab, words and date together", () => {
    expect(filterArticles(feed, { tab: "all", query: "", date: "all" })).toHaveLength(4);
    expect(filterArticles(feed, { tab: "central_banks", query: "", date: "all" }).map((a) => a.id)).toEqual(["a1", "a3"]);
    expect(filterArticles(feed, { tab: "all", query: "bloomberg crude", date: "all" }).map((a) => a.id)).toEqual(["a2"]);
    expect(filterArticles(feed, { tab: "all", query: "", date: "24h" }).map((a) => a.id)).toEqual(["a1", "a2", "a3"]);
  });
  it("groups by period in the given order and drops empty ones", () => {
    const g = groupByPeriod(feed.articles, feed.periods);
    expect(g.map((x) => x.key)).toEqual(["today_pre_market", "overnight", "earlier"]);
  });
  it("picks recent breaking news only", () => {
    expect(breakingNow(feed.articles).map((a) => a.id)).toEqual(["a3"]);
    expect(breakingNow([makePmArticle({ is_breaking: true, period: "earlier" })])).toEqual([]);
  });
});

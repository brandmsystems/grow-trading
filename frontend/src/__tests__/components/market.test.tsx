import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OptionChainTable } from "../../components/market/OptionChainTable";
import { PerformanceCard, PremiumCard, SpotCard, StrategyCard } from "../../components/market/MarketCards";
import { PatternsCard, TradingPlanCard } from "../../components/market/TradingPlan";
import { RecommendationCard } from "../../components/trading/RecommendationCard";
import { CalibrationCard } from "../../components/trading/Calibration";
import { renderWithProviders } from "../../test/render";
import { fail, mockApi } from "../../test/mockApi";
import {
  at, buyCeDashboard, makeConfig, makeDashboard, makeFeed, makeOptionChain, makePlan, makePosition, makeQuote, makeRecommendation, makeSignalAnalysis, makeTrade,
} from "../../test/fixtures";
import { todayIST } from "../../utils/format";
import type { CandlePattern, Explanation } from "../../types/api";

const ui = (el: React.ReactElement, api = mockApi()) => renderWithProviders(el, { bare: true, api });

describe("SpotCard", () => {
  it("shows the index value, change, day range and previous close", () => {
    ui(<SpotCard data={makeDashboard()} />);
    expect(screen.getByText("25,000.50")).toBeInTheDocument();
    expect(screen.getByText(/\+120\.25 \(\+0\.48%\)/)).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.getByText("250.00 pts")).toBeInTheDocument();                     // 25,100 - 24,850
    expect(screen.getByText("24,880.25")).toBeInTheDocument();
    expect(screen.getByText(/60% of today's range/)).toBeInTheDocument();
  });

  it.each([
    ["closed", "MARKET CLOSED", null],
    ["delayed", "DELAYED", /Delayed: Groww hasn't answered/],
    ["unavailable", "UNAVAILABLE", /Disconnected: no NIFTY price/],
  ])("labels a %s quote honestly", (state, label, note) => {
    ui(<SpotCard data={makeDashboard({ feed: { quote: makeQuote({ state, age_sec: 42 }) } })} />);
    expect(screen.getByText(label)).toBeInTheDocument();
    if (note) expect(screen.getByText(note)).toBeInTheDocument();
  });

  it("rising and falling are worded from the sign of the change", () => {
    const { unmount } = ui(<SpotCard data={makeDashboard()} />);
    expect(screen.getByText(/rising vs previous close/)).toBeInTheDocument();
    unmount();
    ui(<SpotCard data={makeDashboard({ feed: { quote: makeQuote({ change: -50, change_pct: -0.2 }) } })} />);
    expect(screen.getByText(/falling vs previous close/)).toBeInTheDocument();
    expect(screen.getByText(/−50\.00 \(−0\.20%\)/)).toBeInTheDocument();
  });

  it("shows dashes instead of inventing numbers when there is no price", () => {
    ui(<SpotCard data={makeDashboard({ feed: { quote: makeQuote({ price: null, change: null, change_pct: null, high: null, low: null, prev_close: null, range_pct: null }) } })} />);
    expect(screen.getAllByText("—").length).toBeGreaterThan(2);
  });
});

describe("PremiumCard", () => {
  it("shows CE and PE premiums with change, OI, IV and delta", () => {
    ui(<PremiumCard data={makeDashboard()} />);
    expect(screen.getByText("CALL (CE)")).toBeInTheDocument();
    expect(screen.getByText("PUT (PE)")).toBeInTheDocument();
    expect(screen.getByText("₹120.50")).toBeInTheDocument();
    expect(screen.getByText("₹98.25")).toBeInTheDocument();
    expect(screen.getByText(/\+5\.00 \(4\.30%\)/)).toBeInTheDocument();
    expect(screen.getByText(/−3\.00 \(-2\.90%\)/)).toBeInTheDocument();
    expect(screen.getByText(/expiry 24 Nov 2026 \(6d\)/)).toHaveTextContent("25,000 · expiry 24 Nov 2026 (6d) · ATM");
  });

  it("marks the side the strategy selected", () => {
    ui(<PremiumCard data={buyCeDashboard()} />);
    expect(screen.getByText("SELECTED")).toBeInTheDocument();
  });

  it("explains a delayed or missing quote instead of showing a stale number as live", () => {
    const d = makeDashboard({ feed: { premiums: {
      ce: { premium: 120.5, state: "delayed", age_sec: 30, error: "timeout" }, pe: { premium: null, state: "unavailable", error: "no quote" } } } });
    ui(<PremiumCard data={d} />);
    expect(screen.getByText("DELAYED")).toBeInTheDocument();
    expect(screen.getByText(/Last good quote 30s ago: timeout/)).toBeInTheDocument();
    expect(screen.getByText("no quote")).toBeInTheDocument();
  });

  it("says there is no quote yet when the feed has no premiums at all", () => {
    ui(<PremiumCard data={makeDashboard({ feed: { premiums: undefined } })} />);
    expect(screen.getAllByText("No quote yet.")).toHaveLength(2);
  });
});

describe("StrategyCard", () => {
  it("shows the trend, EMAs, gap and latest crossover", () => {
    ui(<StrategyCard data={makeDashboard()} />);
    expect(screen.getByText("Uptrend")).toBeInTheDocument();
    expect(screen.getByText("25,010.00")).toBeInTheDocument();
    expect(screen.getByText("24,990.00")).toBeInTheDocument();
    expect(screen.getByText("+20.00")).toBeInTheDocument();
    expect(screen.getByText("Bullish 09:50")).toBeInTheDocument();
    expect(screen.getByText("5-minute")).toBeInTheDocument();
  });

  it("shows a downtrend when EMA 9 is below EMA 21, and None today without crossovers", () => {
    ui(<StrategyCard data={makeDashboard({ feed: { ema: { fast: 24900, slow: 24950, gap: -50 }, crosses: [], signal: { action: "BUY PE" } } })} />);
    expect(screen.getByText("Downtrend")).toBeInTheDocument();
    expect(screen.getByText("None today")).toBeInTheDocument();
    expect(screen.getByText("BUY PE")).toBeInTheDocument();
  });
});

describe("PerformanceCard", () => {
  const trades = [makeTrade(1, { net: 500 }), makeTrade(2, { net: -200 }), makeTrade(3, { net: 300 }), makeTrade(4, { status: "OPEN", net: null })];

  it("totals today's realised P&L with the open position and counts wins and losses", () => {
    const d = makeDashboard({ day: todayIST(), realised_today: 600, position: makePosition({ mtm: 400 }), config: makeConfig() });
    ui(<PerformanceCard data={d} trades={trades} />);
    expect(screen.getByText("Today's Performance")).toBeInTheDocument();
    expect(screen.getByText("+₹1,000.00")).toBeInTheDocument();                      // 600 realised + 400 open
    const stat = (label: string) => screen.getByText(label).parentElement!;
    expect(stat("Trades")).toHaveTextContent("4");
    expect(stat("Won")).toHaveTextContent("2");
    expect(stat("Lost")).toHaveTextContent("1");
    expect(stat("Win rate")).toHaveTextContent("67%");
  });

  it("is titled as an earlier session when the engine's day is not today", () => {
    ui(<PerformanceCard data={makeDashboard({ day: "2020-01-02", config: makeConfig({ trade_mode: "replay" }) })} trades={[]} />);
    expect(screen.getByText("Last Engine Session")).toBeInTheDocument();
    expect(screen.getByText(/REPLAY · 02 Jan 2020/)).toBeInTheDocument();
  });

  it("says the engine is off with no trades", () => {
    ui(<PerformanceCard data={makeDashboard({ day: todayIST() })} trades={[]} />);
    expect(screen.getByText("engine off")).toBeInTheDocument();
    expect(screen.getByText("Win rate").parentElement).toHaveTextContent("—");
  });
});

describe("TradingPlanCard and PatternsCard", () => {
  it("renders nothing without a plan", () => {
    const { container } = ui(<TradingPlanCard plan={null} />);
    expect(container.querySelector("section")).toBeNull();
  });

  it("shows the bias, levels and scenarios, with only the active scenario open", () => {
    ui(<TradingPlanCard plan={makePlan()} />);
    expect(screen.getByText("Bullish bias")).toBeInTheDocument();
    expect(screen.getByText("25,050.00")).toBeInTheDocument();
    expect(screen.getByText(/Bullish scenario · current/)).toBeInTheDocument();
    expect(screen.getByText("Bullish scenario · current").closest("details")).toHaveAttribute("open");
    expect(screen.getByText("Bearish scenario").closest("details")).not.toHaveAttribute("open");
    expect(screen.getByText("Pivot R1")).toBeInTheDocument();
    expect(screen.getByText(/last change 09:20: plan created/)).toBeInTheDocument();
  });

  it("states no preferred direction when the plan has none", () => {
    ui(<TradingPlanCard plan={makePlan({ preferred: "none" })} />);
    expect(screen.getByText("No preferred direction")).toBeInTheDocument();
  });

  const pattern = (o: Partial<CandlePattern>): CandlePattern => ({ name: "Bullish engulfing", bias: "bullish", why: "Body engulfs prior candle", status: "confirmed", ts: at("10:00"),
    close_ts: at("10:05"), o: 1, h: 2, l: 0.5, c: 1.8, confirmation: { rsi: 61 }, effect: "Supports the BUY CE signal", ...o });

  it("lists non-neutral patterns (newest first) and counts dojis separately", () => {
    ui(<PatternsCard items={[pattern({ name: "Hammer", ts: at("09:45") }), pattern({ name: "Shooting star", bias: "bearish", ts: at("10:05") }),
      pattern({ name: "Doji", bias: "neutral" }), pattern({ name: "Doji", bias: "neutral", ts: at("10:10") })]} />);
    const names = screen.getAllByText(/Hammer|Shooting star/).map((n) => n.textContent);
    expect(names).toEqual(["Shooting star", "Hammer"]);
    expect(screen.getByText("2 doji (indecision) today, not listed.")).toBeInTheDocument();
  });

  it("explains a pattern's confirmation and effect when expanded", async () => {
    const { user } = ui(<PatternsCard items={[pattern({})]} />);
    await user.click(screen.getByText("Bullish engulfing"));
    expect(screen.getByText("Body engulfs prior candle")).toBeVisible();
    expect(screen.getByText(/Confirmation: RSI 61/)).toBeInTheDocument();
    expect(screen.getByText("Supports the BUY CE signal")).toBeInTheDocument();
  });

  it("says none yet for an empty list, and hides entirely while loading", () => {
    const { unmount } = ui(<PatternsCard items={[]} />);
    expect(screen.getByText("No patterns on today's closed candles yet.")).toBeInTheDocument();
    unmount();
    const { container } = ui(<PatternsCard items={undefined} />);
    expect(container.querySelector("section")).toBeNull();
  });
});

describe("RecommendationCard", () => {
  it("shows a verified BUY CE with its contract, premium, stop and target", () => {
    ui(<RecommendationCard data={buyCeDashboard()} />);
    expect(screen.getByText("BUY CE")).toBeInTheDocument();
    expect(screen.getByText("Bullish: buy a call option")).toBeInTheDocument();
    expect(screen.getByText("NIFTY 25,000 CE")).toBeInTheDocument();
    expect(screen.getByText("₹120.50")).toBeInTheDocument();       // current premium
    expect(screen.getByText("₹90.00")).toBeInTheDocument();        // stop
    expect(screen.getByText("₹180.00")).toBeInTheDocument();       // target
    expect(screen.getByText(/EMA 9 crossed above EMA 21/)).toBeInTheDocument();
    expect(screen.getByText("confirms BUY CE")).toBeInTheDocument();
  });

  it("shows HOLD with no contract and 'no open signal'", () => {
    ui(<RecommendationCard data={makeDashboard()} />);
    expect(screen.getByText("HOLD")).toBeInTheDocument();
    expect(screen.getByText("No position: wait for the next crossover")).toBeInTheDocument();
    expect(screen.getByText("no open signal")).toBeInTheDocument();
    expect(screen.queryByText("Stop loss")).toBeNull();
  });

  it("recommends nothing when the contract could not be verified, and says why", () => {
    const d = buyCeDashboard({ feed: { signal: { rec: makeRecommendation({ verified: false, error: "Option quote unavailable" }) } } });
    ui(<RecommendationCard data={d} />);
    expect(screen.getByText("Option quote unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Stop loss")).toBeNull();
  });

  it("warns when the EMAs no longer agree with the signal", () => {
    ui(<RecommendationCard data={buyCeDashboard({ feed: { signal: { action: "BUY PE", direction: "Bearish" } } })} />);
    expect(screen.getByText("EMAs no longer agree")).toBeInTheDocument();
  });

  it("flashes when a fresh signal just arrived", () => {
    const { container } = ui(<RecommendationCard data={buyCeDashboard()} flash />);
    expect(container.firstElementChild).toHaveClass("flash");
  });

  it("opens 'View reason' to show each indicator check and the caution", async () => {
    const explain: Explanation = { action: "BUY CE", summary: "3 of 4 checks support", checks: [
      { key: "rsi", label: "RSI", status: "supports", text: "61 is above 50", values: {} },
      { key: "vwap", label: "VWAP", status: "against", text: "Price is below VWAP", values: {} },
      { key: "oi", label: "OI", status: "unavailable", text: "No data", values: {} }],
      caution: "Opening range not broken", why: "Crossover confirmed by RSI", note: "Checks use closed bars.", bar_close: at("10:10"),
      confidence: { score: 72, text: "Moderate confidence, 55% historical hit rate" } };
    const { user } = ui(<RecommendationCard data={buyCeDashboard({ feed: { explain } })} />);
    expect(screen.getByText("View reason ·").closest("details")).not.toHaveAttribute("open");
    await user.click(screen.getByText(/View reason/));
    expect(screen.getByText("RSI:")).toBeInTheDocument();
    expect(screen.getByText("Price is below VWAP")).toBeVisible();
    expect(screen.getByText("Opening range not broken")).toBeInTheDocument();
    expect(screen.getByText(/Moderate confidence, 55% historical hit rate/)).toBeInTheDocument();
    expect(screen.getByText(/bar closing 10:10/)).toBeInTheDocument();
  });
});

describe("CalibrationCard", () => {
  it("states the verdict, the out-of-sample size and AUC, and the bins", () => {
    ui(<CalibrationCard a={makeSignalAnalysis()} />);
    expect(screen.getByText("No measurable edge out of sample.")).toBeInTheDocument();
    expect(screen.getByText("Out-of-sample signals").parentElement).toHaveTextContent("60");
    expect(screen.getByText(/AUC \(0\.5/).parentElement).toHaveTextContent("0.520");
    expect(screen.getByText("out-of-sample only")).toBeInTheDocument();
  });

  it("renders nothing for an analysis built before calibration existed", () => {
    const a = makeSignalAnalysis(); (a.model as { verdict?: unknown }).verdict = undefined;
    const { container } = ui(<CalibrationCard a={a} />);
    expect(container.querySelector("section")).toBeNull();
  });
});

describe("OptionChainTable", () => {
  const chain = (api = mockApi()) => renderWithProviders(<OptionChainTable />, { bare: true, api });

  it("loads the chain and shows spot, ATM, expiry, open interest and put/call ratio", async () => {
    chain();
    expect(screen.getByText(/Loading the option chain from Groww/)).toBeInTheDocument();
    expect(await screen.findByText("NIFTY spot (index)")).toBeInTheDocument();
    expect(screen.getByText("Put/call OI ratio").parentElement).toHaveTextContent("1.20");
    expect(screen.getByText("ATM strike").parentElement).toHaveTextContent("25,000");
    expect(screen.getByText("Expiry", { selector: "div" }).parentElement).toHaveTextContent(/24 Nov 2026.*6 days.*lot 75/);
    const rows = screen.getAllByRole("row");
    const atm = rows.find((r) => within(r).queryByText("ATM"));
    expect(atm).toBeDefined();
    expect(within(atm!).getByText("25,000")).toBeInTheDocument();
  });

  it("requests another expiry and another width when they are changed", async () => {
    const { api, user } = chain();
    await screen.findByText("NIFTY spot (index)");
    expect(Object.fromEntries(api.callsTo("GET", "/api/options/chain")[0].query)).toEqual({ width: "10" });
    await user.selectOptions(screen.getByLabelText("Expiry"), "2026-12-01");
    await waitFor(() => expect(api.callsTo("GET", "/api/options/chain")).toHaveLength(2));
    expect(Object.fromEntries(api.callsTo("GET", "/api/options/chain")[1].query)).toEqual({ expiry: "2026-12-01", width: "10" });
    await user.selectOptions(screen.getByLabelText("Strikes"), "15");
    await waitFor(() => expect(api.callsTo("GET", "/api/options/chain")).toHaveLength(3));
    expect(api.callsTo("GET", "/api/options/chain")[2].query.get("width")).toBe("15");
  });

  it("refreshes on demand", async () => {
    const { api, user } = chain();
    await screen.findByText("NIFTY spot (index)");
    const buttons = screen.getAllByRole("button");
    await user.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(api.callsTo("GET", "/api/options/chain")).toHaveLength(2));
  });

  it("shows the error when Groww fails, without a table", async () => {
    chain(mockApi().on("GET", "/api/options/chain", () => fail("Groww rate limit", 502, "RuntimeError")));
    expect(await screen.findByRole("alert")).toHaveTextContent("Groww rate limit");
    expect(screen.queryByText("Put/call OI ratio")).toBeNull();
  });

  it("tells the user when a refresh failed but older data is still on screen", async () => {
    chain(mockApi().on("GET", "/api/options/chain", () => makeOptionChain({ chain_error: "chain timeout", quotes_error: "quotes timeout" })));
    expect(await screen.findByText(/last refresh failed: chain timeout/)).toBeInTheDocument();
    expect(screen.getByText(/failed: quotes timeout/)).toBeInTheDocument();
  });

  it("polls every 15 seconds while the market is open, but not when it is closed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const open = mockApi();
    const first = chain(open);
    await screen.findByText("NIFTY spot (index)");
    await act(async () => { await vi.advanceTimersByTimeAsync(15100); });
    expect(open.callsTo("GET", "/api/options/chain").length).toBeGreaterThanOrEqual(2);
    first.unmount();

    const closed = mockApi().on("GET", "/api/options/chain", () => makeOptionChain({ market: "closed" }));
    chain(closed);
    await screen.findByText("NIFTY spot (index)");
    await act(async () => { await vi.advanceTimersByTimeAsync(31000); });
    expect(closed.callsTo("GET", "/api/options/chain")).toHaveLength(1);
  });

  it("shows dashes for strikes Groww did not quote", async () => {
    const rows = makeOptionChain().rows.map((r, i) => (i === 0 ? { ...r, ce: null, pe: null } : r));
    chain(mockApi().on("GET", "/api/options/chain", () => makeOptionChain({ rows })));
    await screen.findByText("NIFTY spot (index)");
    const row = screen.getAllByRole("row").find((r) => within(r).queryByText("24,950"))!;
    expect(within(row).getAllByText("—")).toHaveLength(14);
  });
});

describe("shared fixtures stay consistent", () => {
  it("feed bars are in chronological order at the chosen step", () => {
    const ts = makeFeed().chart.bars.map((b) => b.t);
    expect([...ts].sort()).toEqual(ts);
  });
});

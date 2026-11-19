import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Overview from "../../pages/Overview";
import LiveTrading from "../../pages/LiveTrading";
import Options from "../../pages/Options";
import { liveCharts, seriesOf } from "../../test/fakeCharts";
import { fail, mockApi, ok, unreachable } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import {
  at, buyCeDashboard, makeAlert, makeBars, makeConfig, makeDashboard, makePlan, makePosition, makeRecommendation, makeTrade,
} from "../../test/fixtures";
import type { Dashboard, LiveTrade } from "../../types/api";
import { todayIST } from "../../utils/format";

const serve = (d: Dashboard) => mockApi().on("GET", "/api/live/dashboard", () => d);
const mainCandles = () => seriesOf(liveCharts()[0], "candlestick")[0];
afterEach(() => vi.restoreAllMocks());

describe("Overview page", () => {
  it("shows a loading state until the first dashboard arrives", async () => {
    const api = mockApi().on("GET", "/api/live/dashboard", () => new Promise(() => {}));
    renderWithProviders(<Overview />, { api });
    expect(screen.getByText("Connecting to Grow Trading…")).toBeInTheDocument();
  });

  it("shows spot, premiums, strategy, performance, recommendation and recent notifications from one feed", async () => {
    renderWithProviders(<Overview />, { api: serve(buyCeDashboard({ state: "running", config: makeConfig(), realised_today: 500, day: todayIST() })) });
    expect(await screen.findByText("NIFTY 50 Spot")).toBeInTheDocument();
    expect(screen.getByText("NIFTY Options Premium")).toBeInTheDocument();
    expect(screen.getByText("9/21 EMA Strategy")).toBeInTheDocument();
    expect(screen.getByText("Today's Performance")).toBeInTheDocument();
    expect(screen.getByText("Recommended Option")).toBeInTheDocument();
    expect(screen.getByText("NIFTY · 5-minute")).toBeInTheDocument();
    const recent = screen.getByText("Recent notifications").closest("section")!;
    expect(within(recent).getByText("BUY CE")).toBeInTheDocument();
  });

  it("draws today's candles with the crossover markers", async () => {
    renderWithProviders(<Overview />, { api: serve(makeDashboard()) });
    await screen.findByText("NIFTY 50 Spot");
    await waitFor(() => expect(liveCharts()).toHaveLength(1));
    expect(mainCandles().data).toHaveLength(6);
    expect(mainCandles().markers.map((m) => m.text)).toEqual(["9/21 ↑"]);
  });

  it("says why there is no chart when there are no candles", async () => {
    renderWithProviders(<Overview />, { api: serve(makeDashboard({ feed: { chart: { bars: [] }, bars_error: "Groww candles unavailable" } })) });
    expect(await screen.findByText("Groww candles unavailable")).toBeInTheDocument();
    expect(liveCharts()).toHaveLength(0);
  });

  it("falls back to a plain message when there are no candles and no error", async () => {
    renderWithProviders(<Overview />, { api: serve(makeDashboard({ feed: { chart: { bars: [] } } })) });
    expect(await screen.findByText("No candles for today yet.")).toBeInTheDocument();
  });

  it("warns about a Groww feed error but still shows the rest", async () => {
    renderWithProviders(<Overview />, { api: serve(makeDashboard({ feed: { error: "token expired" } })) });
    expect(await screen.findByText("Groww feed: token expired")).toBeInTheDocument();
    expect(screen.getByText("NIFTY 50 Spot")).toBeInTheDocument();
  });

  it("links to the terminal and the signals page", async () => {
    const { user } = renderWithProviders(<Overview />, { api: serve(makeDashboard()) });
    await user.click(await screen.findByRole("link", { name: /Open terminal/ }));
    expect(screen.getByTestId("path")).toHaveTextContent("/live");
  });

  it("shows only the six latest notifications", async () => {
    const alerts = Array.from({ length: 9 }, (_, i) => makeAlert(20 - i));
    renderWithProviders(<Overview />, { api: serve(makeDashboard({ alerts })) });
    const recent = (await screen.findByText("Recent notifications")).closest("section")!;
    expect(within(recent).getAllByRole("listitem")).toHaveLength(6);
  });
});

describe("Live Trading page", () => {
  it("is loading until the feed answers", () => {
    renderWithProviders(<LiveTrading />, { api: mockApi().on("GET", "/api/live/dashboard", () => new Promise(() => {})) });
    expect(screen.getByText("Connecting to the live feed…")).toBeInTheDocument();
  });

  it("assembles the terminal: spot, plan, recommendation, chart, premiums, patterns, controls, paper risk and trades", async () => {
    const d = buyCeDashboard({ feed: { plan: makePlan(), patterns: [] } });
    renderWithProviders(<LiveTrading />, { api: serve(d) });
    expect(await screen.findByText("NIFTY 50 Spot")).toBeInTheDocument();
    expect(screen.getByText("Today's Trading Plan")).toBeInTheDocument();
    expect(screen.getAllByText("Recommended Option")).toHaveLength(2);           // one for narrow, one for wide screens
    expect(screen.getByText("NIFTY 50 · 5-minute candles")).toBeInTheDocument();
    expect(screen.getByText("NIFTY Options Premium")).toBeInTheDocument();
    expect(screen.getByText("Candle Patterns")).toBeInTheDocument();
    expect(screen.getByText("Trading Controls")).toBeInTheDocument();
    expect(await screen.findByText("Risk Management")).toBeInTheDocument();     // paper mode: the risk calculator
    expect(await screen.findByText("Daily Risk")).toBeInTheDocument();
    expect(await screen.findByText("Paper Trades & Risk")).toBeInTheDocument();
    expect(screen.queryByText("Order Calculator")).toBeNull();
  });

  it("shows the order calculator instead of paper risk when the saved mode is live", async () => {
    const live = makeConfig({ trade_mode: "live" });
    renderWithProviders(<LiveTrading />, { api: serve(buyCeDashboard()), settings: { engine: live } });
    expect(await screen.findByText("Order Calculator")).toBeInTheDocument();
    expect(screen.queryByText("Risk Management")).toBeNull();
    expect(screen.queryByText("Paper Trades & Risk")).toBeNull();
  });

  it("shows the Groww error and every feed warning", async () => {
    renderWithProviders(<LiveTrading />, { api: serve(makeDashboard({ feed: { error: "quote timeout", warnings: ["Futures volume unavailable", "Using delayed bars"] } })) });
    expect(await screen.findByText("Groww feed: quote timeout")).toBeInTheDocument();
    expect(screen.getByText("Futures volume unavailable")).toBeInTheDocument();
    expect(screen.getByText("Using delayed bars")).toBeInTheDocument();
  });

  it("explains an empty chart", async () => {
    renderWithProviders(<LiveTrading />, { api: serve(makeDashboard({ feed: { chart: { bars: [] }, bars_error: "No candles yet (pre-open)" } })) });
    expect(await screen.findByText("No candles yet (pre-open)")).toBeInTheDocument();
  });

  it("changing the chart timeframe saves it and refetches the dashboard for that timeframe", async () => {
    const api = serve(makeDashboard());
    const { user } = renderWithProviders(<LiveTrading />, { api });
    await screen.findByText("NIFTY 50 · 5-minute candles");
    const group = screen.getByText("NIFTY 50 · 5-minute candles").closest("section")!;
    await user.click(within(group).getByRole("radio", { name: "15m" }));
    await waitFor(() => expect(api.callsTo("GET", "/api/live/dashboard").some((c) => c.query.get("tf") === "15")).toBe(true));
    expect(JSON.parse(localStorage.getItem("gt-settings")!).timeframe).toBe(15);
  });

  it("locks the chart timeframe while the engine runs ('Timeframe follows the running engine')", async () => {
    renderWithProviders(<LiveTrading />, { api: serve(makeDashboard({ state: "running", config: makeConfig({ timeframe: 15 }), feed: { timeframe: 15 } })) });
    const card = (await screen.findByText("NIFTY 50 · 15-minute candles")).closest("section")!;
    for (const r of within(card).getAllByRole("radio")) expect(r).toBeDisabled();
    expect(within(card).getByText(/Timeframe follows the running engine/)).toBeInTheDocument();
  });

  it("toggles VWAP and volume on the chart, and adds the RSI/MACD panels", async () => {
    const bars = makeBars(6).map((b, i) => ({ ...b, rsi: 50 + i, macd: i, macd_signal: 1, macd_hist: i - 1 }));
    const { user } = renderWithProviders(<LiveTrading />, { api: serve(makeDashboard({ feed: { chart: { bars } } })) });
    await screen.findByText("NIFTY 50 · 5-minute candles");
    const vwap = () => liveCharts()[0].series.find((s) => s.options.title === "VWAP")!.data.length;
    await waitFor(() => expect(vwap()).toBe(6));                                     // on by default
    await user.click(screen.getByLabelText("VWAP"));
    await waitFor(() => expect(vwap()).toBe(0));
    expect(liveCharts()).toHaveLength(1);
    await user.click(screen.getByLabelText("RSI & MACD"));
    await waitFor(() => expect(liveCharts()).toHaveLength(3));
  });

  it("draws the strategy's calls and the engine's own fills as chart markers", async () => {
    const d = makeDashboard({ feed: { markers: [{ ts: at("09:40"), kind: "signal", action: "BUY CE" }, { ts: at("09:55"), kind: "signal", action: "EXIT" }] } });
    const trades: LiveTrade[] = [makeTrade(1, { entry_ts: at("09:42"), exit_ts: at("09:58"), exit_reason: "stop_loss" })];
    const api = serve(d).on("GET", "/api/live/trades", () => trades);
    renderWithProviders(<LiveTrading />, { api });
    await waitFor(() => expect(mainCandles()?.markers.map((m) => m.text)).toEqual(expect.arrayContaining(["BUY CE", "EXIT", "Entry CE", "Exit (stop)"])));
  });

  it("draws the entry reference, stop, target and the plan's key levels, and lets the levels be hidden", async () => {
    const d = buyCeDashboard({ feed: { plan: makePlan() } });
    const { user } = renderWithProviders(<LiveTrading />, { api: serve(d) });
    await screen.findByText("NIFTY 50 · 5-minute candles");
    const titles = () => mainCandles().priceLines.map((l) => l.title).sort();
    await waitFor(() => expect(titles()).toEqual(["Entry ref", "Pivot R1", "Pivot S1", "Stop", "Target"]));
    expect(mainCandles().priceLines.find((l) => l.title === "Stop")!.price).toBe(24950);
    expect(mainCandles().priceLines.find((l) => l.title === "Target")!.price).toBe(25100);
    await user.click(screen.getByLabelText("Support / resistance"));
    await waitFor(() => expect(titles()).toEqual(["Entry ref", "Stop", "Target"]));
  });

  it("uses the open paper position's own premium stop and target on the chart", async () => {
    const d = makeDashboard({ state: "running", config: makeConfig(), position: makePosition() });
    renderWithProviders(<LiveTrading />, { api: serve(d) });
    await waitFor(() => expect(mainCandles()?.priceLines.map((l) => l.title).sort()).toEqual(["Stop ₹90.00", "Target ₹180.00"]));
  });

  it("lists recent notifications", async () => {
    renderWithProviders(<LiveTrading />, { api: serve(makeDashboard({ alerts: [makeAlert(2, { action: "SELL", exit_price: 130, reason: "target", net: 900 }), makeAlert(1)] })) });
    const card = (await screen.findByText("Notifications")).closest("section")!;
    expect(within(card).getByText("SELL")).toBeInTheDocument();
    expect(within(card).getByText(/exit ₹130\.00 · target hit · net \+₹900\.00/)).toBeInTheDocument();
  });

  it("paper trading end to end: start, hold a position, square off, and see the closed trade in the history", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    let phase: "idle" | "open" | "closed" = "idle";
    const closed = makeTrade(7, { net: 2100, gross: 2250 });
    const api = mockApi();
    api.on("GET", "/api/live/dashboard", () => phase === "idle" ? makeDashboard()
      : phase === "open" ? makeDashboard({ state: "running", config: makeConfig(), position: makePosition(), trades_today: 1 })
      : makeDashboard({ state: "stopped", config: makeConfig(), trades_today: 1, realised_today: 2100 }));
    api.on("GET", "/api/live/trades", () => (phase === "closed" ? [closed] : []));
    api.on("POST", "/api/live/start", () => { phase = "open"; return makeDashboard(); });
    api.on("POST", "/api/live/squareoff", () => { phase = "closed"; return makeDashboard(); });
    const { user } = renderWithProviders(<LiveTrading />, { api });

    expect(await screen.findByText("No paper trades yet")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: /Start paper trading/ }));
    expect(await screen.findByText("Open position")).toBeInTheDocument();           // the BUY: engine now holds a position
    expect(screen.getByText("Open P&L").parentElement).toHaveTextContent("+₹1,200.00");
    expect(api.callsTo("POST", "/api/live/start")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /Square off/ }));            // the SELL
    await waitFor(() => expect(screen.queryByText("Open position")).toBeNull());
    expect(api.callsTo("POST", "/api/live/squareoff")).toHaveLength(1);
    const table = (await screen.findByText("Paper Trades & Risk")).closest("section")!;
    expect(await within(table).findByText("+₹2,100.00")).toBeInTheDocument();       // stored trade, read back from the API
    expect(screen.queryByText("No paper trades yet")).toBeNull();
    expect(screen.getByRole("button", { name: /Start paper trading/ })).toBeEnabled();
  });
});

describe("Options page", () => {
  it("is loading until the feed arrives", () => {
    renderWithProviders(<Options />, { api: mockApi().on("GET", "/api/live/dashboard", () => new Promise(() => {})) });
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("says no contract is selected while the strategy says HOLD, and still loads the chain", async () => {
    renderWithProviders(<Options />, { api: serve(makeDashboard()) });
    expect(await screen.findByText("No contract selected")).toBeInTheDocument();
    expect(await screen.findByText("Put/call OI ratio")).toBeInTheDocument();
  });

  it("shows the selected contract's premium, chain LTP, OI, IV, delta and moneyness", async () => {
    renderWithProviders(<Options />, { api: serve(buyCeDashboard({ feed: { quote: { price: 25100 } } })) });
    const card = (await screen.findByText("Selected contract")).closest("section")!;
    expect(within(card).getByText("CALL")).toBeInTheDocument();
    expect(within(card).getByText("NIFTY26N2425000CE")).toBeInTheDocument();
    expect(within(card).getByText("₹120.50")).toBeInTheDocument();
    expect(within(card).getByText("₹120.40")).toBeInTheDocument();
    expect(within(card).getByText("12,00,000")).toBeInTheDocument();
    expect(within(card).getByText("0.52")).toBeInTheDocument();
    expect(within(card).getByText("Moneyness").parentElement).toHaveTextContent("ITM by 100");     // 25,100 spot vs 25,000 call
  });

  it("calls a put OTM when spot is above its strike", async () => {
    const d = buyCeDashboard({ feed: { quote: { price: 25100 }, signal: { action: "BUY PE", rec: makeRecommendation({ opt_type: "PE", strike: 25000 }) } } });
    renderWithProviders(<Options />, { api: serve(d) });
    expect((await screen.findByText("Moneyness")).parentElement).toHaveTextContent("OTM by 100");
  });

  it("shows the verification error instead of a contract when the option could not be verified", async () => {
    const d = buyCeDashboard({ feed: { signal: { rec: makeRecommendation({ verified: false, error: "No quote for the contract" }) } } });
    renderWithProviders(<Options />, { api: serve(d) });
    expect(await screen.findByText("No quote for the contract")).toBeInTheDocument();
    expect(screen.queryByText("Moneyness")).toBeNull();
  });

  it("keeps the rest of the page when the chain itself fails", async () => {
    const api = serve(makeDashboard()).on("GET", "/api/options/chain", () => fail("chain unavailable", 502));
    renderWithProviders(<Options />, { api });
    expect(await screen.findByText("chain unavailable")).toBeInTheDocument();
    expect(screen.getByText("NIFTY 50 Spot")).toBeInTheDocument();
  });

  it("does not hide the offline state: the page waits for data rather than showing zeros", async () => {
    renderWithProviders(<Options />, { api: mockApi().on("GET", "/api/live/dashboard", () => unreachable()) });
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(ok()).toBeDefined();
  });
});

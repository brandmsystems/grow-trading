import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Backtest from "../../pages/Backtest";
import Compare from "../../pages/Compare";
import Scalping from "../../pages/Scalping";
import Signals, { strength } from "../../pages/Signals";
import { liveCharts, seriesOf } from "../../test/fakeCharts";
import { fail, mockApi, ok, type MockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import {
  at, buyCeDashboard, makeAlert, makeBars, makeBtMeta, makeBtResult, makeBtTrade, makeConfig, makeDashboard, makeJob, makeResearch, makeResearchCell,
  makeScalpConfig, makeScalpRun, makeSignalAnalysis,
} from "../../test/fixtures";
import type { Job } from "../../types/api";

afterEach(() => vi.restoreAllMocks());
const alertSpy = () => vi.spyOn(window, "alert").mockImplementation(() => {});
const confirmSpy = (answer: boolean) => vi.spyOn(window, "confirm").mockReturnValue(answer);
/** Jobs that report each state in turn, then stay on the last one. */
const jobs = (api: MockApi, states: Partial<Job>[]) => api.on("GET", /^\/api\/jobs\//, () => makeJob(states.length > 1 ? states.shift() : states[0]));

describe("strength()", () => {
  it("maps a score to three plain levels", () => {
    expect(strength(null)).toMatchObject({ label: "Not scored", w: 0 });
    expect(strength(70)).toMatchObject({ label: "Strong", tone: "good" });
    expect(strength(69.9)).toMatchObject({ label: "Moderate", tone: "warn" });
    expect(strength(50).label).toBe("Moderate");
    expect(strength(49).label).toBe("Weak");
  });
});

describe("Signals page", () => {
  const page = (api = mockApi()) => renderWithProviders(<Signals />, { api });
  /** The past-signals table (the calibration card has tables of its own). */
  const signalsTable = () => screen.getByText("Strength").closest("table") as HTMLElement;

  it("shows the latest live signal as HOLD with the strategy's reason", async () => {
    page();
    expect(await screen.findByText("Latest live signal")).toBeInTheDocument();
    expect(await screen.findByText("No crossover in the entry window")).toBeInTheDocument();
    expect(screen.getByText("EMA 9 25,010.00")).toBeInTheDocument();
    expect(screen.getByText("EMA 9 above 21: bullish")).toBeInTheDocument();
  });

  it("shows a live BUY CE with the contract's entry, stop and target", async () => {
    page(mockApi().on("GET", "/api/live/dashboard", () => buyCeDashboard()));
    const card = (await screen.findByText("Latest live signal")).closest("section")!;
    await within(card).findByText("EMA 9 crossed above EMA 21");
    expect(within(card).getByText("Entry reference").parentElement).toHaveTextContent("₹121.00");
    expect(within(card).getByText("Stop loss").parentElement).toHaveTextContent("₹90.00");
    expect(within(card).getByText("Target").parentElement).toHaveTextContent("₹180.00");
    expect(within(card).getByText("Signal time").parentElement).toHaveTextContent("10:00");
  });

  it("lists exit signals only", async () => {
    const alerts = [makeAlert(3, { action: "SELL", exit_price: 130, net: 600, reason: "target" }), makeAlert(2), makeAlert(1, { action: "BUY BACK", exit_price: 90, reason: "stop" })];
    page(mockApi().on("GET", "/api/live/dashboard", () => makeDashboard({ alerts })));
    const card = (await screen.findByText("Exit signals")).closest("section")!;
    await waitFor(() => expect(within(card).getAllByRole("listitem")).toHaveLength(2));
    expect(within(card).queryByText("BUY CE")).toBeNull();
  });

  it("shows how past signals performed: counts, hit rates by strength, and each signal's result", async () => {
    page();
    expect(await screen.findByText("Hit rate (all)")).toBeInTheDocument();
    expect(screen.getByText("Hit rate (all)").parentElement).toHaveTextContent("48.0%");
    expect(screen.getByText("Weak (<50)").parentElement).toHaveTextContent("45.0%");
    expect(screen.getByText("Weak (<50)").parentElement).toHaveTextContent("30 signals");
    expect(screen.getByText("Strong (70+)").parentElement).toHaveTextContent("55.0%");
    expect(screen.getByText("Calibration check")).toBeInTheDocument();
    const rows = within(signalsTable()).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("BUY CE")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Strong")).toBeInTheDocument();
    expect(within(rows[0]).getByText("hit")).toBeInTheDocument();
    expect(within(rows[1]).getByText("BUY PE")).toBeInTheDocument();
    expect(within(rows[1]).getByText("Weak")).toBeInTheDocument();
    expect(within(rows[1]).getByText("miss")).toBeInTheDocument();
  });

  it("opens a signal's detail: reason, supporting indicators, and the calibrated odds", async () => {
    const { user } = page();
    await screen.findByText("Hit rate (all)");
    const detail = () => screen.getByText("RSI").closest("div.rounded-xl") as HTMLElement;
    expect(within(detail()).getByText("EMA 9 crossed above EMA 21")).toBeInTheDocument();       // the first signal is open by default
    expect(detail()).toHaveTextContent("similar past signals hit 55.0% of 40 (95% range 40–70%)");
    expect(detail()).toHaveTextContent("calibrated estimate 52.0%");
    await user.click(within(signalsTable()).getAllByRole("row")[2]);
    expect(within(detail()).getByText("EMA 9 crossed below EMA 21")).toBeInTheDocument();
    expect(detail()).toHaveTextContent("Result: miss");
  });

  it("asks to build the analysis when there is none, and builds it through a background job", async () => {
    let built = false;
    const api = mockApi();
    api.on("GET", "/api/signals", () => (built ? ok(makeSignalAnalysis()) : ok(null)));
    api.on("POST", "/api/signals/build", () => { built = true; return ok(undefined, { job: "sig-1" }); });
    jobs(api, [{ state: "done" }]);
    const { user } = page(api);
    expect(await screen.findByText("No analysis for this strategy and timeframe")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Build/ }));
    expect(await screen.findByText("Hit rate (all)")).toBeInTheDocument();
    expect(api.callsTo("POST", "/api/signals/build")[0].body).toEqual({ strategy: "ema_9_21", tf: 15 });
    expect(screen.getByRole("button", { name: /Rebuild/ })).toBeInTheDocument();
  });

  it("shows the job's error when the build fails", async () => {
    const alert = alertSpy();
    const api = mockApi();
    api.on("GET", "/api/signals", () => ok(null));
    api.on("POST", "/api/signals/build", () => ok(undefined, { job: "sig-2" }));
    jobs(api, [{ state: "error", error: "No stored data for 2021" }]);
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: /Build/ }));
    await waitFor(() => expect(alert).toHaveBeenCalledWith("No stored data for 2021"));
  });

  it("asks for the analysis again with the chosen timeframe and strategy", async () => {
    const api = mockApi();
    const { user } = page(api);
    await screen.findByText("Hit rate (all)");
    await user.click(screen.getByRole("radio", { name: "30m" }));
    await waitFor(() => expect(api.callsTo("GET", "/api/signals").at(-1)!.query.get("tf")).toBe("30"));
    await user.selectOptions(screen.getByLabelText("Strategy"), "ema_20_50");
    await waitFor(() => expect(api.callsTo("GET", "/api/signals").at(-1)!.query.get("strategy")).toBe("ema_20_50"));
  });

  it("tells the user to rebuild an analysis made before calibration existed", async () => {
    const a = makeSignalAnalysis(); (a.model as { verdict?: unknown }).verdict = undefined;
    page(mockApi().on("GET", "/api/signals", () => ok(a)));
    expect(await screen.findByText(/built before the calibration check existed/)).toBeInTheDocument();
  });

  it("shows an error when the analysis cannot be loaded", async () => {
    page(mockApi().on("GET", "/api/signals", () => fail("signals table missing", 500)));
    expect(await screen.findByRole("alert")).toHaveTextContent("signals table missing");
  });

  it("follows an analysis that is being built elsewhere", async () => {
    const api = mockApi();
    let done = false;
    api.on("GET", "/api/signals", () => (done ? ok(makeSignalAnalysis()) : ok(null, { job: makeJob({ id: "other", state: "running", progress: 0.4, message: "Scoring signals" }) })));
    api.on("GET", /^\/api\/jobs\//, () => { done = true; return makeJob({ id: "other", state: "done" }); });
    page(api);
    expect(await screen.findByText("Hit rate (all)", undefined, { timeout: 4000 })).toBeInTheDocument();
  });
});

describe("Backtest page", () => {
  const backtest = (api = mockApi(), settingsRoute = "/") => {
    api.on("POST", "/api/bt/run", () => ok(undefined, { hash: "hash123" }));
    api.on("GET", "/api/bt/result/hash123", () => makeBtResult());
    api.on("GET", /^\/api\/bt\/chart\/hash123\//, (req) => {
      const id = req.path.split("/").pop()!, day = id === "t2" ? "2026-10-06" : "2026-10-05";
      return { trade_id: id, spot: makeBars(12, 9 * 60 + 15, 15, day), option: makeBars(12, 9 * 60 + 15, 15, day) };
    });
    return renderWithProviders(<Backtest />, { api, route: settingsRoute });
  };

  it("runs the server's default settings on open and shows the results", async () => {
    const { api } = backtest();
    expect(await screen.findByText("Net P&L")).toBeInTheDocument();
    const body = api.callsTo("POST", "/api/bt/run")[0].body!;
    expect(body).toMatchObject({ dataset: "groww", strategy: "ema_9_21", timeframe: 15, start_date: "2026-10-01", end_date: "2026-11-17", entry_start: "09:30", cutoff: "14:30", lots: 1, capital: 100000, force: false });
    expect(body.costs).toMatchObject({ brokerage_per_order: 20 });
    expect(screen.getByText("Net P&L").parentElement).toHaveTextContent("+₹475");
    expect(screen.getByText("Total trades").parentElement).toHaveTextContent("2");
    expect(screen.getByText("Win rate").parentElement).toHaveTextContent("50.0%");
    expect(screen.getByText(/EMA 9\/21 · 01 Oct 2026 → 17 Nov 2026 · 15-minute · 2 signals/)).toBeInTheDocument();
  });

  it("shows job progress for a run that is not cached, then the result", async () => {
    const api = mockApi();
    api.on("POST", "/api/bt/run", () => ok(undefined, { job: "bt-1" }));
    jobs(api, [{ state: "running", progress: 0.4, message: "Downloading option candles" }, { state: "done", result: { hash: "hash123" } }]);
    api.on("GET", "/api/bt/result/hash123", () => makeBtResult());
    api.on("GET", /^\/api\/bt\/chart\//, () => ({ trade_id: "t1", spot: makeBars(), option: makeBars(3) }));
    renderWithProviders(<Backtest />, { api });
    expect(await screen.findByText("Downloading option candles")).toBeInTheDocument();
    expect(await screen.findByText("Net P&L", undefined, { timeout: 4000 })).toBeInTheDocument();
  });

  it("shows the failure when the run fails", async () => {
    const api = mockApi();
    api.on("POST", "/api/bt/run", () => fail("Only real Groww market data can be used."));
    renderWithProviders(<Backtest />, { api });
    expect(await screen.findByRole("alert")).toHaveTextContent("Only real Groww market data can be used.");
  });

  it("shows an error when the settings cannot be loaded", async () => {
    renderWithProviders(<Backtest />, { api: mockApi().on("GET", "/api/bt/meta", () => fail("meta failed", 500)) });
    expect(await screen.findByRole("alert")).toHaveTextContent("meta failed");
  });

  it("re-runs with edited settings and remembers them", async () => {
    const { user, api } = backtest();
    await screen.findByText("Net P&L");
    await user.selectOptions(screen.getByLabelText("Strategy"), "ema_20_50");
    await user.selectOptions(screen.getByLabelText("Timeframe"), "30");
    await user.click(screen.getByRole("button", { name: /Run backtest/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bt/run")).toHaveLength(2));
    expect(api.callsTo("POST", "/api/bt/run")[1].body).toMatchObject({ strategy: "ema_20_50", timeframe: 30 });
    expect(JSON.parse(localStorage.getItem("gt-backtest")!)).toMatchObject({ strategy: "ema_20_50", timeframe: 30 });
  });

  it("edits costs in the units the user thinks in (percent, not fractions)", async () => {
    const { user, api } = backtest();
    await screen.findByText("Net P&L");
    await user.click(screen.getByText("Expiry, lots and charges"));
    const slippage = screen.getByLabelText("Slippage %");
    expect(slippage).toHaveValue(0.5);                                                // stored 0.005
    fireEvent.change(slippage, { target: { value: "0.8" } });
    await user.click(screen.getByRole("button", { name: /Run backtest/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bt/run")).toHaveLength(2));
    expect((api.callsTo("POST", "/api/bt/run")[1].body!.costs as Record<string, number>).slippage_pct).toBeCloseTo(0.008, 6);
  });

  it("filters trades by outcome, direction and entry time, and clears the filters", async () => {
    const { user } = backtest();
    await screen.findByText("Net P&L");
    expect(screen.getByText("Trades (2)")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Outcome"), "win");
    expect(screen.getByText("Trades (1)")).toBeInTheDocument();
    expect(screen.getByText("Net P&L").parentElement).toHaveTextContent("+₹1,175");
    await user.selectOptions(screen.getByLabelText("Outcome"), "all");
    await user.selectOptions(screen.getByLabelText("Direction"), "Bearish");
    expect(screen.getByText("Trades (1)")).toBeInTheDocument();
    expect(screen.getByText("Net P&L").parentElement).toHaveTextContent("−₹700");
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("Trades (2)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Entry from", { selector: "input[type=time]" }), { target: { value: "10:15" } });         // only the 10:30 entry
    expect(screen.getByText("Trades (1)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("recomputes the headline numbers from the filtered trades (win rate, profit factor)", async () => {
    const { user } = backtest();
    await screen.findByText("Net P&L");
    await user.selectOptions(screen.getByLabelText("Outcome"), "loss");
    expect(screen.getByText("Win rate").parentElement).toHaveTextContent("0.0%");
    expect(screen.getByText("Net P&L").parentElement).toHaveTextContent("−₹700");
    expect(screen.getByText("Max drawdown").parentElement).toHaveTextContent("−₹700");
  });

  it("switches mode, and says when a mode has no trades", async () => {
    const { user } = backtest();
    await screen.findByText("Net P&L");
    await user.click(screen.getByRole("radio", { name: "ATM sell" }));
    expect(screen.getByText("Trades (0)")).toBeInTheDocument();
    expect(screen.getByText("No trades match")).toBeInTheDocument();
  });

  it("opens the chart of the first trade, and of whichever trade is picked", async () => {
    const { user, api } = backtest();
    await screen.findByText("Net P&L");
    await waitFor(() => expect(api.callsTo("GET", /^\/api\/bt\/chart\//)).toHaveLength(1));
    expect(api.callsTo("GET", /^\/api\/bt\/chart\//)[0].path).toBe("/api/bt/chart/hash123/t1");
    await waitFor(() => expect(liveCharts().filter((c) => seriesOf(c, "candlestick").length).length).toBeGreaterThanOrEqual(2));   // spot + option charts
    await user.click(screen.getByRole("button", { name: /PE.*#2/ }));
    await waitFor(() => expect(api.callsTo("GET", /^\/api\/bt\/chart\//).at(-1)!.path).toBe("/api/bt/chart/hash123/t2"));
    await screen.findByText("Option premium · NIFTY26O0625000CE");
  });

  it("marks the entry and exit on the spot chart", async () => {
    backtest();
    await screen.findByText("Net P&L");
    await waitFor(() => {
      const spot = liveCharts().map((c) => seriesOf(c, "candlestick")[0]).filter(Boolean).find((s) => s.markers.some((m) => m.text.startsWith("Entry")));
      expect(spot?.markers.map((m) => m.text)).toEqual(expect.arrayContaining(["Entry 10:01", "Exit 11:01"]));
    });
  });

  it("shows an error in place of the chart when a trade's chart cannot be loaded", async () => {
    const api = mockApi();
    api.on("POST", "/api/bt/run", () => ok(undefined, { hash: "hash123" }));
    api.on("GET", "/api/bt/result/hash123", () => makeBtResult());
    api.on("GET", /^\/api\/bt\/chart\//, () => fail("No candles for that day", 404));
    renderWithProviders(<Backtest />, { api });
    expect(await screen.findByText("No candles for that day")).toBeInTheDocument();
  });

  it("draws the equity curves for all three modes and the monthly P&L", async () => {
    backtest();
    await screen.findByText("Equity curve (cumulative net P&L)");
    await waitFor(() => {
      const line = liveCharts().find((c) => seriesOf(c, "line").some((s) => s.options.title === "ATM buy"));
      expect(line).toBeDefined();
      const atmBuy = seriesOf(line!, "line").find((s) => s.options.title === "ATM buy")!;
      expect(atmBuy.data).toEqual([{ time: "2026-10-05", value: 1175 }, { time: "2026-10-06", value: 475 }]);
    });
    const bars = liveCharts().map((c) => seriesOf(c, "histogram")[0]).find((s) => s?.data.length === 1);
    expect(bars!.data[0]).toMatchObject({ value: 475, color: "#16a34a" });
  });

  it("shows the monthly returns table and best/worst days", async () => {
    backtest();
    const card = (await screen.findByText("Yearly & monthly returns")).closest("section")!;
    expect(within(card).getByText("2026")).toBeInTheDocument();
    expect(within(card).getAllByText("+₹475").length).toBeGreaterThan(0);          // October's net and the year total
    const best = screen.getByText("Best & worst days").closest("section")!;
    expect(within(best).getByText("2026-10-05")).toBeInTheDocument();
    expect(within(best).getByText("2026-10-06")).toBeInTheDocument();
  });

  it("applies settings passed from the comparison page in the link", async () => {
    const { api } = backtest(mockApi(), "/?strategy=ema_20_50&tf=30&mode=ATM_SELL");
    await screen.findByText("Net P&L");
    expect(api.callsTo("POST", "/api/bt/run")[0].body).toMatchObject({ strategy: "ema_20_50", timeframe: 30 });
    await waitFor(() => expect(screen.getByTestId("path")).toHaveTextContent(/^\/$/));     // the query was cleared from the address
  });

  it("renders very long trade lists in steps", async () => {
    const many = Array.from({ length: 700 }, (_, i) => makeBtTrade(`m${i}`, { day: `2026-10-${String((i % 28) + 1).padStart(2, "0")}`, ordinal: 1 }));
    const api = mockApi();
    api.on("POST", "/api/bt/run", () => ok(undefined, { hash: "hash123" }));
    api.on("GET", "/api/bt/result/hash123", () => makeBtResult({ trades: { ITM5_BUY: [], ATM_BUY: many, ATM_SELL: [] } }));
    api.on("GET", /^\/api\/bt\/chart\//, () => ({ trade_id: "m0", spot: makeBars(), option: makeBars(3) }));
    renderWithProviders(<Backtest />, { api });
    const title = await screen.findByText("Trades (700)");
    const list = title.closest("section")!.querySelector(".overflow-y-auto")!;
    expect(list.querySelectorAll("button")).toHaveLength(300);                      // only the first 300 rows are in the page
    expect(makeBtMeta().timeframes).toBeDefined();
  });
});

describe("Compare page", () => {
  const withModes = () => {
    const a = makeResearchCell("ema_9_21", "EMA 9/21", 15, 1500), b = makeResearchCell("ema_20_50", "EMA 20/50", 15, -900);
    a.summary!.modes.ATM_SELL.net_pnl = 777;
    return makeResearch([a, b]);
  };
  const compare = (api = mockApi().on("GET", "/api/research", () => ok(withModes()))) => renderWithProviders(<Compare />, { api });
  /** The strategy x timeframe grid (the same figures also appear in the year-by-year table). */
  const matrix = async () => within((await screen.findByText("Net P&L by strategy and timeframe")).closest("section")!);

  it("shows net P&L for each strategy and timeframe, colour-coded, with the best highlighted", async () => {
    compare();
    const grid = await matrix();
    expect(grid.getByText("+₹1,500")).toBeInTheDocument();
    expect(grid.getByText("−₹900")).toBeInTheDocument();
    expect(grid.getByText("+₹1,500").closest("[role=button]")).toHaveClass("ring-2");
    expect(grid.getByText("−₹900").closest("[role=button]")).not.toHaveClass("ring-2");
    expect(screen.getByText(/2 of 2 configurations/)).toBeInTheDocument();
    expect(screen.getAllByText("20 trades · 45% won · PF 1.10").length).toBe(1);
  });

  it("switches the figures when a different mode is chosen", async () => {
    const { user } = compare();
    const grid = await matrix();
    await user.click(screen.getByRole("radio", { name: "ATM sell" }));
    expect(grid.getByText("+₹777")).toBeInTheDocument();
    expect(grid.queryByText("+₹1,500")).toBeNull();
  });

  it("opens a cell in Backtesting with that strategy, timeframe, dates and mode", async () => {
    const { user } = compare();
    await user.click((await matrix()).getByText("+₹1,500").closest("[role=button]")!);
    const path = screen.getByTestId("path").textContent!;
    expect(path).toContain("/backtest?strategy=ema_9_21&tf=15&start_date=2026-10-01&end_date=2026-11-17&entry_start=09:30&cutoff=14:30&mode=ATM_BUY");
  });

  it("charts the chosen configurations, and ticking one does not open the cell", async () => {
    const { user } = compare();
    await matrix();
    const legend = () => screen.getByText("Equity curves").closest("section")!.textContent;
    expect(legend()).toContain("EMA 9/21 15m");
    expect(legend()).toContain("EMA 20/50 15m");
    await user.click(screen.getByLabelText("Chart EMA 20/50 15m"));
    expect(legend()).not.toContain("EMA 20/50 15m");
    expect(screen.getByTestId("path")).toHaveTextContent(/^\/$/);                   // still on this page
  });

  it("limits the chart to four configurations at a time", async () => {
    const cells = ["a", "b", "c", "d", "e"].map((s, i) => makeResearchCell(`s_${s}`, `Strat ${s}`, 15, 1000 - i * 100));
    const { user } = compare(mockApi().on("GET", "/api/research", () => ok(makeResearch(cells))));
    await screen.findByText("Net P&L by strategy and timeframe");
    await user.click(screen.getByLabelText("Chart Strat e 15m"));
    const checked = screen.getAllByRole("checkbox").filter((c) => (c as HTMLInputElement).checked);
    expect(checked.length).toBeLessThanOrEqual(4);
    expect(screen.getByLabelText("Chart Strat e 15m")).toBeChecked();
  });

  it("asks for the results again when the entry window changes", async () => {
    const api = mockApi().on("GET", "/api/research", () => ok(withModes()));
    const { user } = compare(api);
    await matrix();
    await user.selectOptions(screen.getByLabelText("Entry from"), "10:00");
    await waitFor(() => expect(api.callsTo("GET", "/api/research").at(-1)!.query.get("entry_start")).toBe("10:00"));
    await user.selectOptions(screen.getByLabelText("Time cut"), "15:00");
    await waitFor(() => expect(api.callsTo("GET", "/api/research").at(-1)!.query.get("cutoff")).toBe("15:00"));
  });

  it("shows the empty state, and 'not run' for configurations that were never run", async () => {
    const { unmount } = compare(mockApi().on("GET", "/api/research", () => ok(makeResearch([]))));
    expect(await screen.findByText("No comparison results yet")).toBeInTheDocument();
    unmount();
    const missing = makeResearchCell("ema_20_50", "EMA 20/50", 30, 0); missing.summary = null;
    compare(mockApi().on("GET", "/api/research", () => ok(makeResearch([makeResearchCell("ema_9_21", "EMA 9/21", 15, 1500), missing]))));
    expect((await screen.findAllByText("not run")).length).toBeGreaterThan(0);
  });

  it("runs the missing configurations through a job and reloads the results", async () => {
    let ran = false;
    const api = mockApi();
    api.on("GET", "/api/research", () => ok(ran ? withModes() : makeResearch([])));
    api.on("POST", "/api/research/run", () => { ran = true; return ok(undefined, { job: "res-1" }); });
    jobs(api, [{ state: "done" }]);
    const { user } = compare(api);
    await user.click(await screen.findByRole("button", { name: /Run missing/ }));
    expect((await matrix()).getByText("+₹1,500")).toBeInTheDocument();
    expect(api.callsTo("POST", "/api/research/run")[0].body).toEqual({ entry_start: "09:30", cutoff: "14:30" });
  });

  it("shows the job's error if the run fails", async () => {
    const alert = alertSpy();
    const api = mockApi();
    api.on("GET", "/api/research", () => ok(makeResearch([])));
    api.on("POST", "/api/research/run", () => ok(undefined, { job: "res-2" }));
    jobs(api, [{ state: "error", error: "Groww is rate-limiting" }]);
    const { user } = compare(api);
    await user.click(await screen.findByRole("button", { name: /Run missing/ }));
    await waitFor(() => expect(alert).toHaveBeenCalledWith("Groww is rate-limiting"));
  });

  it("shows an error when the results cannot be loaded", async () => {
    compare(mockApi().on("GET", "/api/research", () => fail("research table missing", 500)));
    expect(await screen.findByRole("alert")).toHaveTextContent("research table missing");
  });

  it("shows year-by-year and win-rate breakdowns for the chosen timeframe", async () => {
    compare();
    await matrix();
    const year = screen.getByText(/Year by year/).closest("section")!;
    expect(within(year).getByText("2026")).toBeInTheDocument();
    expect(within(year).getAllByText("+₹1,500").length).toBeGreaterThan(0);
    expect(within(screen.getByText(/Win rate · 15m/).closest("section")!).getAllByText("45.0%")).toHaveLength(2);
  });
});

describe("Scalping page", () => {
  const withConfig = (api: MockApi) => api.on("GET", "/api/scalping/config", (req) => {
    const cfg = makeScalpRun().configs.find((c) => c.key === req.query.get("key")) ?? makeScalpConfig(req.query.get("key")!);
    return ok({ ...cfg, trade_list: [] });
  });
  const scalping = (api = mockApi()) => renderWithProviders(<Scalping />, { api: withConfig(api) });

  it("says there is no analysis yet", async () => {
    scalping(mockApi().on("GET", "/api/scalping", () => ok(null)));
    expect(await screen.findByText("No scalping analysis yet")).toBeInTheDocument();
  });

  it("states the verdict plainly: no configuration is consistently profitable after costs", async () => {
    scalping();
    expect(await screen.findByText(/No configuration has shown consistent profitability after all costs\. 0 of 2 are net positive; 2 were positive before costs\./)).toBeInTheDocument();
    expect(screen.getByText("None qualifies")).toBeInTheDocument();
  });

  it("lists every configuration ranked, and filters by contract and exit type", async () => {
    const { user } = scalping();
    await screen.findByText("All configurations");
    const table = () => screen.getByText("All configurations").closest("section")!;
    expect(within(table()).getAllByRole("row")).toHaveLength(3);
    await user.click(within(table()).getByRole("radio", { name: "ITM 5" }));
    expect(within(table()).getAllByRole("row")).toHaveLength(2);
    expect(within(table()).getByText("EMA 20/50")).toBeInTheDocument();
    await user.click(within(table()).getByRole("radio", { name: "All" }));
    await user.click(within(table()).getByRole("radio", { name: "SL / target" }));
    expect(within(table()).queryByText("EMA 9/21")).toBeNull();                    // both fixtures are fixed-time exits
  });

  it("sorts by the chosen column", async () => {
    const { user } = scalping();
    await screen.findByText("All configurations");
    const order = () => within(screen.getByText("All configurations").closest("section")!).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[1].textContent);
    expect(order()).toEqual(["EMA 9/21", "EMA 20/50"]);                          // by in-sample rank
    await user.selectOptions(screen.getByLabelText("Sort"), "net_pnl");
    expect(order()).toEqual(["EMA 20/50", "EMA 9/21"]);                          // -500 beats -2000
  });

  it("opens the full report for a configuration when its row is clicked", async () => {
    const { user, api } = scalping();
    await screen.findByText("All configurations");
    await waitFor(() => expect(api.callsTo("GET", "/api/scalping/config")[0].query.get("key")).toBe("c1"));      // the featured one by default
    await user.click(within(screen.getByText("All configurations").closest("section")!).getByText("EMA 20/50"));
    await waitFor(() => expect(api.callsTo("GET", "/api/scalping/config").at(-1)!.query.get("key")).toBe("c2"));
    expect(await screen.findByText("EMA 20/50 · ITM 5 buy · 5-min exit")).toBeInTheDocument();
    expect(screen.getByText("Not consistently profitable")).toBeInTheDocument();
  });

  it("re-runs the analysis only after confirmation, through a job", async () => {
    let runs = 0;
    const api = mockApi();
    api.on("POST", "/api/scalping/run", () => { runs += 1; return ok(undefined, { job: "sc-1" }); });
    jobs(api, [{ state: "done" }]);
    const { user } = scalping(api);
    await screen.findByText("All configurations");
    const confirm = confirmSpy(false);
    await user.click(screen.getByRole("button", { name: /Run analysis/ }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Re-run the full five-year scalping analysis?"));
    expect(runs).toBe(0);
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: /Run analysis/ }));
    await waitFor(() => expect(runs).toBe(1));
  });

  it("shows an error when the analysis cannot be loaded", async () => {
    scalping(mockApi().on("GET", "/api/scalping", () => fail("scalp_runs missing", 500)));
    expect(await screen.findByRole("alert")).toHaveTextContent("scalp_runs missing");
  });

  describe("automatic paper trading panel", () => {
    const panel = async (api = mockApi()) => {
      const r = scalping(api);
      const card = (await screen.findByText("Automatic paper trading")).closest("section")!;
      return { ...r, card, ui: within(card) };
    };

    it("warns that a configuration that failed the checks is for observation only, and asks before starting it", async () => {
      const confirm = confirmSpy(false);
      const { user, card, ui, api } = await panel();
      expect(ui.getByText(/lost .* after costs over the backtest/)).toBeInTheDocument();
      await user.click(ui.getByRole("button", { name: /Start paper scalping/ }));
      expect(confirm).toHaveBeenCalledWith(expect.stringContaining("did NOT pass the consistency checks"));
      expect(api.callsTo("POST", "/api/scalping/paper/start")).toHaveLength(0);
      expect(card).toBeInTheDocument();
    });

    it("starts paper scalping with the chosen configuration and risk settings after confirmation", async () => {
      confirmSpy(true);
      const { user, ui, api } = await panel();
      fireEvent.change(ui.getByLabelText("Risk / trade %"), { target: { value: "0.5" } });
      await user.click(ui.getByRole("button", { name: /Start paper scalping/ }));
      await waitFor(() => expect(api.callsTo("POST", "/api/scalping/paper/start")).toHaveLength(1));
      expect(api.callsTo("POST", "/api/scalping/paper/start")[0].body).toEqual({
        key: "c1", mode: "paper", risk: { risk_pct: 0.5, daily_risk_pct: 3, max_trades_per_day: 20, max_lots: 10 },
      });
    });

    it("needs a day to replay before it can start", async () => {
      confirmSpy(true);
      const { user, ui, api } = await panel();
      await user.click(ui.getByRole("radio", { name: "Replay" }));
      expect(ui.getByRole("button", { name: /Start replay/ })).toBeDisabled();
      await user.type(ui.getByLabelText("Replay day"), "2026-11-12");
      await user.click(ui.getByRole("button", { name: /Start replay/ }));
      await waitFor(() => expect(api.callsTo("POST", "/api/scalping/paper/start")).toHaveLength(1));
      expect(api.callsTo("POST", "/api/scalping/paper/start")[0].body).toMatchObject({ mode: "replay", replay_day: "2026-11-12" });
    });

    it("shows the server's refusal", async () => {
      confirmSpy(true);
      const api = mockApi().on("POST", "/api/scalping/paper/start", () => fail("Engine is already running"));
      const { user, ui } = await panel(api);
      await user.click(ui.getByRole("button", { name: /Start paper scalping/ }));
      expect(await ui.findByText("Engine is already running")).toBeInTheDocument();
    });

    it("shows a running scalp session and stops it after confirmation", async () => {
      const running = makeDashboard({ state: "running", config: makeConfig({ signal_mode: "scalp", scalp_config: "c1" }) });
      const api = mockApi().on("GET", "/api/live/dashboard", () => running);
      const { user, ui } = await panel(api);
      expect(await ui.findByText("Scalping · paper")).toBeInTheDocument();
      expect(ui.getByLabelText("Tested configuration").closest("fieldset")).toBeDisabled();
      confirmSpy(true);
      await user.click(ui.getByRole("button", { name: /Stop engine/ }));
      await waitFor(() => expect(api.callsTo("POST", "/api/live/stop")).toHaveLength(1));
    });

    it("says the engine is busy when another mode is running", async () => {
      const api = mockApi().on("GET", "/api/live/dashboard", () => makeDashboard({ state: "running", config: makeConfig({ signal_mode: "cross" }) }));
      const { ui } = await panel(api);
      expect(await ui.findByText("Engine busy (other mode)")).toBeInTheDocument();
    });

    it("shows an empty history of scalping paper trades", async () => {
      const { ui } = await panel();
      expect(await ui.findByText("No scalping paper trades yet")).toBeInTheDocument();
    });
  });

  it("walk-forward and existing-strategy tables render from the run", async () => {
    const run = makeScalpRun({
      walk_forward: { rows: [{ year: "2025", trained_on: "2022–2024", pick: null, pick_label: null, oos_net: 0, oos_trades: 0 }], total_oos: 0 },
      existing: [{ strategy: "ema_9_21", label: "EMA 9/21", timeframe: 15, contract: "ATM_BUY", trades: 500, net_pnl: -1200, win_rate: 44, profit_factor: 0.9, max_drawdown: 5000, years_positive: "1/5" }],
    });
    scalping(mockApi().on("GET", "/api/scalping", () => ok(run)));
    expect(await screen.findByText("none qualified: no trading")).toBeInTheDocument();
    const ex = screen.getByText("Against the existing strategies").closest("section")!;
    expect(within(ex).getByText("EMA 9/21")).toBeInTheDocument();
    expect(at("10:00")).toBeDefined();
  });
});

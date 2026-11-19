import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AutoTrading from "../../pages/AutoTrading";
import { fail, mockApi, type MockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import {
  makeBiasAnalysis, makeBiasPrediction, makeBiasStatus, makeBiasSummary, makeBiasTrade, makeBiasTradeDetail, makePosition,
} from "../../test/fixtures";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

const running = (api: MockApi, over = {}) => api.on("GET", "/api/bias/status", () => makeBiasStatus(over));
const page = (api = mockApi()) => renderWithProviders(<AutoTrading />, { api });
/** The first row of the trades table (the same "BUY CE" text also appears in the bias panel). */
const firstTrade = async () => (await within((await screen.findByText("Orders and positions")).closest("section")!).findAllByRole("row"))[1];

describe("Automated Paper Trading page, engine stopped", () => {
  it("states that it is paper only and reads the bias from the latest candles", async () => {
    page();
    expect(await screen.findByTestId("bias-label")).toHaveTextContent("BULLISH");
    expect(screen.getByTestId("bias-confidence")).toHaveTextContent("78%");
    expect(screen.getByText(/this page cannot place a real order/i)).toBeInTheDocument();
    expect(screen.getAllByText(/not a probability/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Stopped")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: /Start paper trading/ })).toBeEnabled());
    expect(screen.queryByText(/LIVE/)).not.toBeInTheDocument();                       // no live mode and no confirmation phrase exist here
    expect(screen.getByTestId("validation-note")).toHaveTextContent(/50\.9%.*coin flip.*lost ₹36,004/);       // the page says what validation found
  });

  it("shows 15m and 5m trends, the next-candle forecast, the signal and every strategy's vote", async () => {
    page();
    await screen.findByTestId("bias-label");
    expect(screen.getByText("15m trend (primary)").parentElement).toHaveTextContent("Bullish");
    expect(screen.getByText("Next 5m candle").parentElement).toHaveTextContent("UP");
    expect(screen.getByText("Entry signal").parentElement).toHaveTextContent("BUY CE");
    const table = screen.getByText("Strategy confirmations").closest("section")!;
    const first = within(table).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0].textContent ?? "");
    expect(first).toHaveLength(12);
    for (const l of ["EMA 9/21", "EMA 5/20", "EMA 8/21", "EMA 20/50", "200 EMA", "VWAP", "RSI", "RSI divergence", "MACD", "Bollinger Bands", "Volume expansion", "Support / resistance"]) {
      expect(first.some((c) => c.startsWith(l))).toBe(true);
    }
    expect(within(table).getByText("n/a")).toBeInTheDocument();                         // an abstaining indicator is not shown as neutral
  });

  it("explains a HOLD with its reasons", async () => {
    const api = mockApi().on("GET", "/api/bias/analysis", { as_of_day: "2026-11-18", live: true, futures: true, error: null, recent: [],
      analysis: makeBiasAnalysis({ signal: "HOLD", direction: 0, bias: "NEUTRAL", confidence: 0, hold_reasons: ["5m and 15m disagree"] }) });
    page(api);
    expect((await screen.findByText(/Why HOLD:/)).closest("p")).toHaveTextContent("5m and 15m disagree");
  });

  it("reads the last session when the market is closed and says so", async () => {
    const api = mockApi().on("GET", "/api/bias/analysis", { as_of_day: "2026-11-17", live: false, futures: true, error: null, recent: [], analysis: makeBiasAnalysis() });
    page(api);
    expect(await screen.findByText(/last session 2026-11-17/)).toBeInTheDocument();
  });

  it("starts PAPER trading with the saved settings and refuses nothing it should not", async () => {
    const api = mockApi();
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: /Start paper trading/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/start")).toHaveLength(1));
    const body = api.callsTo("POST", "/api/bias/start")[0].body as { trade_mode: string; config: Record<string, unknown> };
    expect(body.trade_mode).toBe("paper");
    expect(body.config.max_trades_per_day).toBe(20);
    expect(body.config.bias_allow).toEqual(["BUY_CE", "BUY_PE"]);
  });

  it("replays a finished day only when one is chosen", async () => {
    const api = mockApi();
    const { user } = page(api);
    const btn = await screen.findByRole("button", { name: /Replay day/ });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Replay day"), { target: { value: "2026-11-12" } });
    await user.click(btn);
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/start")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/bias/start")[0].body).toMatchObject({ trade_mode: "replay", replay_day: "2026-11-12" });
  });

  it("shows the server's refusal when starting fails", async () => {
    const api = mockApi().on("POST", "/api/bias/start", () => fail("Groww login failed", 502));
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: /Start paper trading/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Groww login failed");
  });

  it("lets the analysis interval and the confirmation timeframe be chosen, keeping them consistent", async () => {
    const api = mockApi();
    const { user } = page(api);
    const tf = await screen.findByLabelText("Analysis interval");
    const confirm = screen.getByLabelText("Confirmation timeframe");
    expect(tf).toHaveValue("5");
    expect(confirm).toHaveValue("15");
    expect(within(confirm).getAllByRole("option").map((o) => o.textContent)).toEqual(["15 minutes", "30 minutes", "60 minutes"]);
    await user.selectOptions(tf, "15");                                              // a 15-minute analysis needs a longer confirmation
    expect(screen.getByLabelText("Confirmation timeframe")).toHaveValue("30");
    expect(within(screen.getByLabelText("Confirmation timeframe")).getAllByRole("option").map((o) => o.textContent)).toEqual(["30 minutes", "60 minutes"]);
    await user.click(screen.getByRole("button", { name: /Start paper trading/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/start")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/bias/start")[0].body).toMatchObject({ config: { timeframe: 15, bias_confirm_tf: 30 } });
  });

  it("labels the panels with the timeframes the engine really uses", async () => {
    const api = mockApi().on("GET", "/api/bias/analysis", { as_of_day: "2026-11-18", live: true, futures: true, error: null, recent: [],
      analysis: makeBiasAnalysis({ tf_primary: 15, tf_confirm: 60 }) });
    page(api);
    expect(await screen.findByText("60m trend (primary)")).toBeInTheDocument();
    expect(screen.getByText("15m trend (entry)")).toBeInTheDocument();
    expect(screen.getByText("Next 15m candle")).toBeInTheDocument();
    expect(screen.getAllByText("60m vote").length).toBeGreaterThan(0);
  });

  it("locks the analysis interval while the engine runs (it applies from the next start)", async () => {
    page(running(mockApi()));
    expect(await screen.findByLabelText("Analysis interval")).toBeDisabled();
    expect(screen.getByLabelText("Confirmation timeframe")).toBeEnabled();
  });

  it("saves settings for the next start without touching the engine", async () => {
    const api = mockApi();
    const { user } = page(api);
    await user.click(await screen.findByLabelText("Sell (write) CE"));
    expect(await screen.findByText(/Writing options can lose many times/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save for next start" }));
    expect(await screen.findByRole("status")).toHaveTextContent(/Saved/);
    expect(api.callsTo("POST", "/api/bias/settings")).toHaveLength(0);
    expect(JSON.parse(localStorage.getItem("gt.auto.settings")!).bias_allow).toContain("SELL_CE");
  });
});

describe("Automated Paper Trading page, engine running", () => {
  const withEngine = (extra = {}) => {
    const api = running(mockApi(), extra);
    api.on("GET", "/api/bias/summary", makeBiasSummary());
    api.on("GET", "/api/bias/predictions", [
      makeBiasPrediction(), makeBiasPrediction({ bar_close: "2026-11-18T10:15:00", predicted: "DOWN", actual: "UP", outcome: "INCORRECT" }),
      makeBiasPrediction({ bar_close: "2026-11-18T10:10:00", predicted: "NEUTRAL", actual: "FLAT", outcome: "NEUTRAL" }),
      makeBiasPrediction({ bar_close: "2026-11-18T10:25:00", actual: null, outcome: null, next_close: null })]);
    api.on("GET", "/api/bias/trades", [makeBiasTrade(), makeBiasTrade({ id: 32, direction: "Bearish", opt_type: "PE", action: "BUY PE", exit_price: null, exit_ts: null, exit_reason: null, net: null, status: "OPEN" })]);
    return api;
  };

  it("shows the daily limit, wins, losses, win rate and net P&L", async () => {
    page(withEngine());
    expect(await screen.findByText("3 of 20")).toBeInTheDocument();
    const today = screen.getByText("Today").closest("section")!;
    expect(today).toHaveTextContent("17 remaining · never forced");
    expect(today).toHaveTextContent("3 / 1");
    expect(today).toHaveTextContent("75%");
    expect(today).toHaveTextContent("+₹1,250.50");
    expect(screen.getByText("Running · paper")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Stop engine/ })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /Start paper trading/ })).not.toBeInTheDocument();
  });

  it("compares each prediction with the actual next candle: CORRECT, INCORRECT, NEUTRAL, pending", async () => {
    page(withEngine());
    const t = (await screen.findByText("Predictions vs actual")).closest("section")!;
    await waitFor(() => expect(within(t).getAllByRole("row").length).toBe(5));
    expect(within(t).getByText("CORRECT")).toBeInTheDocument();
    expect(within(t).getByText("INCORRECT")).toBeInTheDocument();
    expect(within(t).getAllByText("NEUTRAL").length).toBeGreaterThan(0);
    expect(within(t).getByText("pending")).toBeInTheDocument();
    expect(t).toHaveTextContent("1 correct, 1 incorrect (50%), 1 neutral");
  });

  it("lists orders and positions; clicking one opens its full reasoning", async () => {
    const { user } = page(withEngine());
    await user.click(await firstTrade());
    const d = await screen.findByRole("dialog", { name: "Trade reasoning" });
    expect(await within(d).findByText("Why it was entered")).toBeInTheDocument();
    expect(within(d).getByText(/15m bullish \(0\.45\)/)).toBeInTheDocument();
    expect(within(d).getByText("EMA 9/21 5m (+0.60)")).toBeInTheDocument();
    expect(within(d).getByText(/bid\/ask not available: spread not checked/)).toBeInTheDocument();
    expect(within(d).getByText(/\|delta\| 0\.20 < the minimum 0\.25/)).toBeInTheDocument();
    expect(within(d).getByText("Every strategy at entry")).toBeInTheDocument();
    expect(within(d).getByText("Risk calculation")).toBeInTheDocument();
    expect(within(d).getByText(/trailing stop \(trailing 10% from the best premium 120\.00\)/)).toBeInTheDocument();
    expect(within(d).getByText(/target at ₹131\.00; best premium seen ₹132\.50/)).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("reports a trade whose reasoning cannot be loaded", async () => {
    const api = withEngine().on("GET", /^\/api\/bias\/trade\//, () => fail("Trade not found.", 404));
    const { user } = page(api);
    await user.click(await firstTrade());
    expect(await within(await screen.findByRole("dialog")).findByRole("alert")).toHaveTextContent("Trade not found.");
  });

  it("shows the active position with stop and target and lets a paper position be adjusted or closed", async () => {
    const pos = makePosition({ side: "BUY", trading_symbol: "NIFTY26N2425000CE", opt_type: "CE", entry_price: 120.5, ltp: 126, mtm: 330.2, stop_premium: 100, target_premium: 140, risk_reward: 2, max_loss: 1600 });
    const api = withEngine({ position: pos });
    api.on("POST", "/api/live/squareoff", { state: "running" });
    const { user } = page(api);
    const card = (await screen.findByText("Active position")).closest("section")!;
    expect(card).toHaveTextContent("NIFTY26N2425000CE");
    expect(card).toHaveTextContent("₹100.00");
    expect(card).toHaveTextContent("₹140.00");
    await user.type(within(card).getByLabelText("New target premium"), "150");
    await user.click(within(card).getByRole("button", { name: "Set target" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/paper/position/target")[0]?.body).toEqual({ target: 150 }));
    expect(await within(card).findByRole("status")).toHaveTextContent("Target 140.00 → 150.00");
    await user.type(within(card).getByLabelText("New stop-loss premium"), "105");
    await user.click(within(card).getByRole("button", { name: "Set stop" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/paper/position/stop")[0]?.body).toEqual({ stop: 105 }));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await user.click(within(card).getByRole("button", { name: "Close now" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/squareoff")).toHaveLength(1));
  });

  it("does not offer stop/target edits or a manual close for a replay", async () => {
    page(withEngine({ trade_mode: "replay", position: makePosition() }));
    const card = (await screen.findByText("Active position")).closest("section")!;
    expect(within(card).queryByRole("button", { name: "Close now" })).not.toBeInTheDocument();
  });

  it("applies only the changed settings to the running engine, without a restart", async () => {
    const api = withEngine();
    const { user } = page(api);
    const conf = await screen.findByLabelText("Minimum confidence");
    await user.clear(conf);
    await user.type(conf, "72");
    await user.click(screen.getByRole("button", { name: "Apply to running engine" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/settings")).toHaveLength(1));
    const sent = api.callsTo("POST", "/api/bias/settings")[0].body as Record<string, unknown>;
    expect(sent.bias_min_confidence).toBe(72);
    expect(sent).not.toHaveProperty("trail_pct");                                    // equal to the running value: not resent
    expect(api.callsTo("POST", "/api/bias/start")).toHaveLength(0);
    expect(api.callsTo("POST", "/api/live/stop")).toHaveLength(0);
  });

  it("shows the engine's refusal of a bad setting", async () => {
    const api = withEngine().on("POST", "/api/bias/settings", () => fail("bias min confidence must be between 0 and 100"));
    const { user } = page(api);
    const conf = await screen.findByLabelText("Minimum confidence");
    await user.clear(conf);
    await user.type(conf, "90");
    await user.click(screen.getByRole("button", { name: "Apply to running engine" }));
    expect(await screen.findByText(/must be between 0 and 100/)).toBeInTheDocument();
  });

  it("shows a halt reason and the engine log", async () => {
    page(withEngine({ state: "halted", halt_reason: "Daily loss limit reached: no more trades today" }));
    expect(await screen.findByText(/Daily loss limit reached/)).toBeInTheDocument();
    expect(screen.getByText("Halted · paper")).toBeInTheDocument();
    expect(screen.getByText(/10:25 BULLISH: signal/)).toBeInTheDocument();
  });

  it("stops the engine", async () => {
    const api = withEngine().on("POST", "/api/live/stop", { state: "stopped" });
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: /Stop engine/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/stop")).toHaveLength(1));
  });
});

describe("accuracy and breakdown panels", () => {
  it("reports accuracy per strategy and timeframe with the coin-flip caveat, and can switch to stored history", async () => {
    const api = mockApi();
    const { user } = page(api);
    const panel = (await screen.findByText("Prediction accuracy by strategy and timeframe")).closest("section")!;
    expect(await within(panel).findByTestId("combined-accuracy")).toHaveTextContent("52.0%");
    expect(panel).toHaveTextContent("1,000 calls");
    expect(within(panel).getByText("EMA 9/21").closest("tr")).toHaveTextContent("51.0%");
    expect(within(panel).getByText("EMA 9/21").closest("tr")).toHaveTextContent("54.5%");
    expect(panel).toHaveTextContent(/50% is a coin flip/);
    await user.click(within(panel).getByRole("radio", { name: /Last 60 days/ }));
    await waitFor(() => expect(api.callsTo("GET", "/api/bias/history-accuracy")).toHaveLength(1));
  });

  it("says plainly when nothing can be scored yet", async () => {
    const api = mockApi().on("GET", "/api/bias/accuracy", { candles: 0, rows: [] });
    page(api);
    expect(await screen.findByText("Nothing to score yet")).toBeInTheDocument();
  });

  it("breaks closed trades down by instrument, exit, confidence and supporting strategy, with the attribution caveat", async () => {
    const api = mockApi().on("GET", "/api/bias/summary", makeBiasSummary());
    page(api);
    const card = (await screen.findByText("Performance breakdown")).closest("section")!;
    await waitFor(() => expect(card).toHaveTextContent("By supporting strategy"));
    expect(card).toHaveTextContent("BUY CE");
    expect(card).toHaveTextContent("70-85%");
    expect(card).toHaveTextContent(/credited with every trade it supported/);
  });

  it("reports an unreachable backend", async () => {
    const api = mockApi().on("GET", "/api/bias/status", () => fail("Backend unreachable", 500));
    page(api);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent(/Backend unreachable/);
  });
});

describe("trade detail data", () => {
  it("the fixture detail carries every part the dialog promises", () => {
    const d = makeBiasTradeDetail();
    expect(d.trade.analysis?.contract_checks?.map((c) => c.ok)).toEqual([true, null, false]);
    expect(d.stop_changes.map((s) => s.source)).toEqual(["entry", "trail"]);
  });
});

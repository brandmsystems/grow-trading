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

  it("lets the pre-market bias be logged, used to skip opposed trades, or ignored, applied without a restart", async () => {
    const api = withEngine();
    const { user } = page(api);
    const sel = await screen.findByLabelText("Pre-market bias");
    expect(sel).toHaveValue("log");
    await user.selectOptions(sel, "block_opposed");
    await user.click(screen.getByRole("button", { name: "Apply to running engine" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/settings")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/bias/settings")[0].body).toMatchObject({ premarket_mode: "block_opposed" });
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


describe("continuous automation: threshold, net profit target, phases, pause", () => {
  const withEngine = (extra = {}, trades: ReturnType<typeof makeBiasTrade>[] = []) => {
    const api = running(mockApi(), extra);
    api.on("GET", "/api/bias/summary", makeBiasSummary());
    api.on("GET", "/api/bias/trades", trades);
    return api;
  };
  const phase = (label: string, detail: string, over = {}) => ({ bias: { automation: { phase: "waiting", label, detail, ...over } } });

  it("defaults to a 70% Market Bias threshold and a ₹1,500 net profit target, and sends both on start", async () => {
    const api = mockApi();
    const { user } = page(api);
    expect(await screen.findByLabelText("Market Bias threshold")).toHaveValue(70);
    expect(screen.getByLabelText("Net profit target per trade")).toHaveValue(1500);
    expect(screen.getByText("Not running")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause" })).not.toBeInTheDocument();
    expect(screen.getByText(/per trade, after brokerage, taxes and slippage; it is not a daily target/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Start paper trading/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/start")).toHaveLength(1));
    expect((api.callsTo("POST", "/api/bias/start")[0].body as { config: Record<string, unknown> }).config).toMatchObject({ bias_min_confidence: 70, profit_target_net: 1500 });
  });

  it("starts with an edited threshold and target", async () => {
    const api = mockApi();
    const { user } = page(api);
    fireEvent.change(await screen.findByLabelText("Market Bias threshold"), { target: { value: "75" } });
    fireEvent.change(screen.getByLabelText("Net profit target per trade"), { target: { value: "2000" } });
    await user.click(screen.getByRole("button", { name: /Start paper trading/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/start")).toHaveLength(1));
    expect((api.callsTo("POST", "/api/bias/start")[0].body as { config: Record<string, unknown> }).config).toMatchObject({ bias_min_confidence: 75, profit_target_net: 2000 });
  });

  it("takes the new 70% default over a 55% saved before this feature existed, but keeps a deliberate later choice", async () => {
    localStorage.setItem("gt.auto.settings", JSON.stringify({ bias_min_confidence: 55 }));
    page();
    expect(await screen.findByLabelText("Market Bias threshold")).toHaveValue(70);
  });

  it("keeps a threshold saved after this feature existed", async () => {
    localStorage.setItem("gt.auto.settings", JSON.stringify({ bias_min_confidence: 80, profit_target_net: 1000 }));
    page();
    expect(await screen.findByLabelText("Market Bias threshold")).toHaveValue(80);
    expect(screen.getByLabelText("Net profit target per trade")).toHaveValue(1000);
  });

  it("shows the current bias against the threshold and says whether it is eligible", async () => {
    page(withEngine());
    expect(await screen.findByTestId("automation-bias")).toHaveTextContent(/BULLISH.*78%.*minimum 70%.*eligible for BUY CE/);
  });

  it("says a bias below the threshold gets no entry", async () => {
    page(withEngine({ bias: { latest: makeBiasAnalysis({ confidence: 62, signal: "HOLD", direction: 0 }) } }));
    expect(await screen.findByTestId("automation-bias")).toHaveTextContent(/62%.*minimum 70%.*below the threshold or no confirmed signal: no entry/);
  });

  it("says what the engine is doing: ready for re-entry, waiting, holding, exiting, paused, limit, halted", async () => {
    page(withEngine());
    expect(await screen.findByTestId("automation-phase")).toHaveTextContent(/Ready for re-entry.*at least 70%/);
  });

  it.each([
    ["holding", "Holding a position", "Holding the open paper position until the net profit reaches ₹1,500"],
    ["exiting", "Exiting", "Closing the position; an exit is being retried"],
    ["waiting", "Waiting", "Waiting for a new candle after the last exit (the 11:10 candle contains it); earliest next entry on the 11:15 candle."],
    ["paused", "Paused", "Paused: the analysis keeps running but no new entry is taken."],
    ["limit", "Daily limit reached", "Daily trade limit (20) reached: no new entries today."],
    ["halted", "Halted", "Daily loss limit reached: no more trades today"],
  ])("shows the %s phase", async (ph, label, detail) => {
    page(withEngine(phase(label, detail, { phase: ph, paused: ph === "paused" })));
    await waitFor(() => expect(screen.getByTestId("automation-phase")).toHaveTextContent(label));
    expect(screen.getByTestId("automation-phase")).toHaveTextContent(detail.slice(0, 30));
  });

  it("pauses and resumes automation without stopping the engine", async () => {
    const api = withEngine().on("POST", "/api/bias/pause", { paused: true }).on("POST", "/api/bias/resume", { paused: false });
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: "Pause" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/pause")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/live/stop")).toHaveLength(0);
    expect(api.callsTo("POST", "/api/bias/resume")).toHaveLength(0);
  });

  it("resumes a paused automation", async () => {
    const api = withEngine(phase("Paused", "Paused: no new entry", { phase: "paused", paused: true })).on("POST", "/api/bias/resume", { paused: false });
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/resume")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/bias/pause")).toHaveLength(0);
  });

  it("applies a changed target and threshold to the running engine at once", async () => {
    const api = withEngine();
    const { user } = page(api);
    fireEvent.change(await screen.findByLabelText("Net profit target per trade"), { target: { value: "1800" } });
    fireEvent.change(screen.getByLabelText("Market Bias threshold"), { target: { value: "74" } });
    await user.click(screen.getByRole("button", { name: "Apply threshold & target" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/bias/settings")).toHaveLength(1));
    const sent = api.callsTo("POST", "/api/bias/settings")[0].body as Record<string, unknown>;
    expect(sent).toMatchObject({ profit_target_net: 1800, bias_min_confidence: 74 });
    expect(api.callsTo("POST", "/api/bias/start")).toHaveLength(0);
  });

  it("shows the open position with its entry reason, CE/PE, entry price, live paper P&L and progress to the target", async () => {
    const pos = makePosition({ entry_reason: "BULLISH: 15m bullish (0.45), 5m bullish (0.38); BUY CE candidate", entry_confidence: 78, mtm: 750, entry_price: 120 });
    page(withEngine({ position: pos }));
    expect(await screen.findByTestId("entry-reason")).toHaveTextContent(/Why it was entered:.*15m bullish.*agreement 78%/);
    const card = screen.getByText("Active position").closest("section")!;
    expect(within(card).getByText("BUY CE")).toBeInTheDocument();
    expect(within(card).getByText("₹120.00")).toBeInTheDocument();
    expect(within(card).getByText("Open P&L (net)").parentElement).toHaveTextContent("750");
    expect(within(card).getByText("Net profit target").parentElement).toHaveTextContent(/₹1,500.*50% reached/);
  });

  it("shows completed trades, profit target hits, total trades, net P&L and the last exit reason", async () => {
    const t = makeBiasTrade({ exit_reason: "profit_target", net: 1534.2, exit_ts: "2026-11-18T10:47:00" });
    page(withEngine({}, [t]));
    const stats = await screen.findByTestId("automation-stats");
    await waitFor(() => expect(stats).toHaveTextContent(/Completed trades4.*Profit target hits1.*Total trades today3.*Net paper P&L/));
    expect(await screen.findByTestId("last-exit")).toHaveTextContent(/Last exit 10:47: net profit target · net.*1,534/);
  });
});

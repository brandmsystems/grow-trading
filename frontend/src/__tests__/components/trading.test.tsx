import { act, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EnginePanel } from "../../components/trading/EnginePanel";
import { OrderCalculator } from "../../components/trading/OrderCalculator";
import { PaperTrades } from "../../components/trading/PaperTrades";
import { PendingOrder } from "../../components/trading/PendingOrder";
import { DailyRisk, RiskCalculator } from "../../components/trading/RiskManagement";
import { renderWithProviders } from "../../test/render";
import { fail, mockApi, ok } from "../../test/mockApi";
import {
  at, buyCeDashboard, makeAccount, makeConfig, makeDashboard, makePosition, makeRecommendation, makeRisk, makeTrade,
} from "../../test/fixtures";
import type { Dashboard, PendingOrder as PendingOrderT } from "../../types/api";

const serve = (d: Dashboard) => mockApi().on("GET", "/api/live/dashboard", () => d);
const confirmSpy = (answer: boolean) => vi.spyOn(window, "confirm").mockReturnValue(answer);
const engine = async (d: Dashboard, opts: { settings?: Parameters<typeof renderWithProviders>[1] extends infer O ? (O extends { settings?: infer S } ? S : never) : never } = {}) => {
  const api = serve(d);
  const r = renderWithProviders(<EnginePanel />, { api, settings: opts.settings });
  await screen.findByText("Trading Controls");
  return { ...r, api };
};
afterEach(() => vi.restoreAllMocks());

describe("EnginePanel: starting paper trading", () => {
  it("starts a paper session with the chosen settings, without any confirmation prompt", async () => {
    const confirm = confirmSpy(true);
    const { user, api } = await engine(makeDashboard());
    expect(screen.getByText("Stopped")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Option"), "ATM_SELL");
    await user.selectOptions(screen.getByLabelText("Timeframe"), "15");
    await user.click(screen.getByRole("radio", { name: "1.5%" }));                    // Moderate preset
    await user.click(screen.getByRole("button", { name: /Start paper trading/ }));

    await waitFor(() => expect(api.callsTo("POST", "/api/live/start")).toHaveLength(1));
    const body = api.callsTo("POST", "/api/live/start")[0].body as { config: Record<string, unknown>; confirm: string; replay_speed: number };
    expect(body.config).toMatchObject({ trade_mode: "paper", exec_mode: "ATM_SELL", timeframe: 15, risk_pct: 1.5, order_confirmation: "manual", signal_mode: "cross" });
    expect(body.confirm).toBe("");
    expect(body.replay_speed).toBe(120);
    expect(confirm).not.toHaveBeenCalled();
  });

  it("shows the risk settings only for paper mode, and lots only for live/replay", async () => {
    const { user } = await engine(makeDashboard());
    expect(screen.getByText("Risk per trade (lots are calculated)")).toBeInTheDocument();
    expect(screen.queryByLabelText("Lots")).toBeNull();
    await user.click(screen.getByRole("radio", { name: "Replay" }));
    expect(screen.queryByText("Risk per trade (lots are calculated)")).toBeNull();
    expect(screen.getByLabelText("Lots")).toBeInTheDocument();
  });

  it("switches the stop-loss input to match the stop method", async () => {
    const { user } = await engine(makeDashboard());
    expect(screen.getByLabelText("ATR multiple")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Stop-loss"), "pct");
    expect(screen.getByLabelText("Stop % below premium")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Stop-loss"), "points");
    expect(screen.getByLabelText("Stop ₹ below premium")).toBeInTheDocument();
  });

  it("prediction mode asks for a minimum score and a strategy from the server's list", async () => {
    const { user, api } = await engine(makeDashboard());
    await user.selectOptions(screen.getByLabelText("Signals"), "prediction");
    expect(screen.getByLabelText("Min score")).toHaveValue(50);
    await user.selectOptions(screen.getByLabelText("Strategy"), "ema_20_50");
    await user.click(screen.getByRole("button", { name: /Start paper trading/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/start")).toHaveLength(1));
    expect((api.callsTo("POST", "/api/live/start")[0].body as { config: Record<string, unknown> }).config).toMatchObject({ signal_mode: "prediction", strategy: "ema_20_50" });
  });

  it("shows the backend's refusal and re-enables the button", async () => {
    const api = serve(makeDashboard());
    api.on("POST", "/api/live/start", () => fail("Engine is already running"));
    const { user } = renderWithProviders(<EnginePanel />, { api });
    await user.click(await screen.findByRole("button", { name: /Start paper trading/ }));
    expect(await screen.findByText("Engine is already running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start paper trading/ })).toBeEnabled();
  });
});

describe("EnginePanel: replay", () => {
  it("sends the replay day with the start request", async () => {
    const { user, api } = await engine(makeDashboard());
    await user.click(screen.getByRole("radio", { name: "Replay" }));
    await user.type(screen.getByLabelText("Replay day"), "2026-11-10");
    await user.click(screen.getByRole("button", { name: /Start replay/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/start")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/live/start")[0].body).toMatchObject({ config: { trade_mode: "replay" }, replay_day: "2026-11-10" });
  });
});

describe("EnginePanel: live (real-money) safeguards", () => {
  it("makes the risk obvious: red warning, the lot cap, manual confirmation, and the phrase to type", async () => {
    const { user } = await engine(makeDashboard({ live_max_lots: 2 }));
    await user.click(screen.getByRole("radio", { name: "Live" }));
    expect(screen.getByText(/Real money\./)).toBeInTheDocument();
    expect(screen.getByText(/capped at 2 lot\(s\)/)).toBeInTheDocument();
    expect(screen.getByText("Manual confirmation ON: you approve every entry order.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Type LIVE to start/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Start LIVE trading/ })).toBeInTheDocument();
  });

  it("asks for a final confirmation, and places nothing when it is declined", async () => {
    const confirm = confirmSpy(false);
    const { user, api } = await engine(makeDashboard());
    await user.click(screen.getByRole("radio", { name: "Live" }));
    await user.type(screen.getByLabelText(/Type LIVE to start/), "LIVE");
    await user.click(screen.getByRole("button", { name: /Start LIVE trading/ }));
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/Start LIVE trading with 1 lot\(s\)\? You will confirm each order\./));
    expect(api.callsTo("POST", "/api/live/start")).toHaveLength(0);
  });

  it("starts live only after the confirmation, sending the typed phrase and manual confirmation", async () => {
    confirmSpy(true);
    const { user, api } = await engine(makeDashboard());
    await user.click(screen.getByRole("radio", { name: "Live" }));
    await user.type(screen.getByLabelText(/Type LIVE to start/), "LIVE");
    await user.click(screen.getByRole("button", { name: /Start LIVE trading/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/start")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/live/start")[0].body).toMatchObject({ confirm: "LIVE", config: { trade_mode: "live", order_confirmation: "manual" } });
  });

  it("warns loudly before enabling automatic order placement", async () => {
    const confirm = confirmSpy(false);
    const { user } = await engine(makeDashboard());
    await user.click(screen.getByRole("radio", { name: "Live" }));
    await user.click(screen.getByLabelText(/Place entry orders automatically/));
    expect(screen.getByText("Automatic entries ON")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Start LIVE trading/ }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Orders will be placed AUTOMATICALLY."));
  });

  it("never restores automatic ordering from a previous visit: manual confirmation is the starting point", async () => {
    await engine(makeDashboard(), { settings: { engine: makeConfig({ trade_mode: "live", order_confirmation: "auto" }) } });
    expect(screen.getByText("Manual confirmation ON: you approve every entry order.")).toBeInTheDocument();
  });

  it("surfaces the server's refusal when the phrase is wrong (the server, not the page, enforces it)", async () => {
    confirmSpy(true);
    const api = serve(makeDashboard());
    api.on("POST", "/api/live/start", () => fail('Type "LIVE" to confirm real-money trading.', 400, "PermissionError"));
    const { user } = renderWithProviders(<EnginePanel />, { api });
    await user.click(await screen.findByRole("radio", { name: "Live" }));
    await user.type(screen.getByLabelText(/Type LIVE to start/), "nope");
    await user.click(screen.getByRole("button", { name: /Start LIVE trading/ }));
    expect(await screen.findByText(/Type "LIVE" to confirm real-money trading\./)).toBeInTheDocument();
    expect(api.callsTo("POST", "/api/live/start")[0].body).toMatchObject({ confirm: "nope" });
  });
});

describe("EnginePanel: a running engine", () => {
  const running = (o?: Parameters<typeof makeDashboard>[0]) => makeDashboard({ state: "running", config: makeConfig(), ...o });

  it("replaces Start with Square off and Stop, and locks the settings", async () => {
    await engine(running());
    expect(screen.queryByRole("button", { name: /Start/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Square off/ })).toBeDisabled();           // no open position
    expect(screen.getByRole("button", { name: /Stop/ })).toBeEnabled();
    expect(screen.getByLabelText("Option").closest("fieldset")).toBeDisabled();
    expect(screen.getByText("Running · paper")).toBeInTheDocument();
  });

  it("live mode with an open real position: details hidden, but you are told and can still square off", async () => {
    const live = running({ config: makeConfig({ trade_mode: "live" }), position: null, live_position_open: true, live_details_hidden: true });
    const { user, api } = await engine(live);
    expect(screen.getByText(/A live position is open\. Its details are not shown/)).toBeInTheDocument();
    expect(screen.queryByText("Open position")).toBeNull();
    expect(screen.queryByText("Open P&L")).toBeNull();
    expect(screen.queryByText(/Entry → LTP/)).toBeNull();
    const confirm = confirmSpy(true);
    await user.click(screen.getByRole("button", { name: /Square off/ }));          // the safety control stays usable
    expect(confirm).toHaveBeenCalled();
    expect(api.callsTo("POST", "/api/live/squareoff")).toHaveLength(1);
  });

  it("stops only after the user confirms", async () => {
    const confirm = confirmSpy(false);
    const { user, api } = await engine(running());
    await user.click(screen.getByRole("button", { name: /Stop/ }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Stop the engine?"));
    expect(api.callsTo("POST", "/api/live/stop")).toHaveLength(0);
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: /Stop/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/stop")).toHaveLength(1));
  });

  it("shows the open position with its P&L and squares it off on request", async () => {
    confirmSpy(true);
    const { user, api } = await engine(running({ position: makePosition() }));
    expect(screen.getByText("Open position").parentElement).toHaveTextContent("25,000 CE");
    expect(screen.getByText("Open P&L").parentElement).toHaveTextContent("+₹1,200.00");
    expect(screen.getByText("Entry → LTP").parentElement).toHaveTextContent("₹120.00 → ₹128.00");
    await user.click(screen.getByRole("button", { name: /Square off/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/squareoff")).toHaveLength(1));
  });

  it("shows why the engine halted", async () => {
    await engine(running({ state: "halted", halt_reason: "Daily loss limit reached" }));
    expect(screen.getByText("Daily loss limit reached")).toBeInTheDocument();
    expect(screen.getByText(/^Halted/)).toBeInTheDocument();
  });

  it("summarises the session's trades and realised P&L", async () => {
    await engine(running({ trades_today: 3, realised_today: -450 }));
    expect(screen.getByText(/3 trade\(s\), realised/)).toHaveTextContent("−₹450.00");
  });
});

describe("EnginePanel: paper stop-loss editing", () => {
  const withPosition = () => makeDashboard({ state: "running", config: makeConfig(), position: makePosition({ stop_premium: 90 }) });

  it("shows entry, stop, target, max risk and method for the open paper position", async () => {
    await engine(withPosition());
    const panel = within(screen.getByText("Entry premium").closest(".col-span-2") as HTMLElement);
    expect(panel.getByText("Entry premium").parentElement).toHaveTextContent("₹120.00");
    expect(panel.getByText("Stop-loss").parentElement).toHaveTextContent("₹90.00");
    expect(panel.getByText("Target").parentElement).toHaveTextContent("₹180.00");
    expect(panel.getByText("Max risk").parentElement).toHaveTextContent("₹4,500");
    expect(panel.getByText("Method").parentElement).toHaveTextContent("ATR x delta");
  });

  it("asks for a value before calling the backend", async () => {
    const { user, api } = await engine(withPosition());
    await user.click(screen.getByRole("button", { name: "Change stop" }));
    expect(screen.getByText("Enter a stop-loss premium.")).toBeInTheDocument();
    expect(api.callsTo("POST", "/api/paper/position/stop")).toHaveLength(0);
  });

  it("sends the new stop and reports the old and new risk", async () => {
    const { user, api } = await engine(withPosition());
    await user.type(screen.getByPlaceholderText("New stop ₹"), "95");
    await user.click(screen.getByRole("button", { name: "Change stop" }));
    await waitFor(() => expect(screen.getByText(/Stop 90\.00 → 95\.00; max loss ₹4,500 → ₹4,000/)).toBeInTheDocument());
    expect(api.callsTo("POST", "/api/paper/position/stop")[0].body).toEqual({ stop: 95 });
    expect(screen.getByPlaceholderText("New stop ₹")).toHaveValue(null);          // cleared after saving
  });

  it("shows the backend's refusal when the change would exceed the risk limit", async () => {
    const api = serve(withPosition());
    api.on("POST", "/api/paper/position/stop", () => fail("New stop would exceed today's loss limit"));
    const { user } = renderWithProviders(<EnginePanel />, { api });
    await user.type(await screen.findByPlaceholderText("New stop ₹"), "10");
    await user.click(screen.getByRole("button", { name: "Change stop" }));
    expect(await screen.findByText("New stop would exceed today's loss limit")).toBeInTheDocument();
  });
});

describe("EnginePanel: confirming a live order", () => {
  const pending: PendingOrderT = { id: "ord-1", side: "BUY", trading_symbol: "NIFTY26N2425000CE", strike: 25000, opt_type: "CE", expiry: "2026-11-24", qty: 75, ltp: 121.5,
    nifty: 25001, signal_ts: at("10:00"), expires: at("10:15:30".slice(0, 5)) , stop_ref: null, target_ref: null };
  const live = () => makeDashboard({ state: "running", config: makeConfig({ trade_mode: "live" }), pending_order: { ...pending, expires: "2026-11-18T10:15:30" } });

  it("shows the order and places it only when 'Place order' is pressed", async () => {
    const { user, api } = await engine(live());
    const dlg = screen.getByRole("alertdialog", { name: "Order awaiting confirmation" });
    expect(dlg).toHaveTextContent("BUY 25,000 CE");
    expect(dlg).toHaveTextContent("LTP ₹121.50");
    expect(api.callsTo("POST", "/api/live/confirm")).toHaveLength(0);                 // nothing happens by itself
    await user.click(within(dlg).getByRole("button", { name: /Place order/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/confirm")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/live/confirm")[0].body).toEqual({ id: "ord-1" });
    expect(api.callsTo("POST", "/api/live/reject")).toHaveLength(0);
  });

  it("'Skip' rejects the order and never confirms it", async () => {
    const { user, api } = await engine(live());
    await user.click(screen.getByRole("button", { name: /Skip/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/live/reject")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/live/reject")[0].body).toEqual({ id: "ord-1" });
    expect(api.callsTo("POST", "/api/live/confirm")).toHaveLength(0);
  });

  it("shows the server's error if the order could not be placed", async () => {
    const api = serve(live());
    api.on("POST", "/api/live/confirm", () => fail("Order rejected: insufficient margin", 409, "RuntimeError"));
    const { user } = renderWithProviders(<EnginePanel />, { api });
    await user.click(await screen.findByRole("button", { name: /Place order/ }));
    expect(await screen.findByText("Order rejected: insufficient margin")).toBeInTheDocument();
  });
});

describe("PendingOrder countdown", () => {
  const order: PendingOrderT = { id: "x", side: "BUY", trading_symbol: "SYM", strike: 25000, opt_type: "PE", expiry: "2026-11-24", qty: 75, ltp: null, nifty: 24990,
    signal_ts: at("10:00"), expires: "2026-11-18T10:15:30", stop_ref: null, target_ref: null };

  it("counts down against the server clock and disables Place order at zero", () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    const onConfirm = vi.fn();
    renderWithProviders(<PendingOrder order={order} now="2026-11-18T10:15:00" busy={false} onConfirm={onConfirm} onReject={() => {}} />, { bare: true });
    expect(screen.getByText("30s left")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Place order/ })).toBeEnabled();
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(screen.getByText("20s left")).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(40_000); });
    expect(screen.getByText("0s left")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Place order/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Skip/ })).toBeEnabled();              // you can still dismiss it
  });

  it("disables both buttons while a request is in flight, and omits LTP when unknown", () => {
    renderWithProviders(<PendingOrder order={order} now="2026-11-18T10:15:00" busy onConfirm={() => {}} onReject={() => {}} />, { bare: true });
    expect(screen.getByRole("button", { name: /Place order/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Skip/ })).toBeDisabled();
    expect(screen.queryByText(/LTP/)).toBeNull();
  });
});

describe("OrderCalculator", () => {
  const calc = (d: Dashboard) => renderWithProviders(<OrderCalculator data={d} />, { bare: true });

  it("explains it only sizes after a BUY signal", () => {
    calc(makeDashboard());
    expect(screen.getByText("Sizing appears when the strategy recommends BUY CE or BUY PE.")).toBeInTheDocument();
  });

  it("shows the backend's sizing for the recommended contract", () => {
    calc(buyCeDashboard());
    const val = (label: string) => screen.getByText(label).parentElement!;
    expect(val("Recommended lots")).toHaveTextContent("2");
    expect(val("Recommended lots")).toHaveTextContent("limited by risk");
    expect(val("Lot size × lots")).toHaveTextContent("75 × 2");
    expect(val("Lot size × lots")).toHaveTextContent("150 quantity");
    expect(val("Capital used")).toHaveTextContent("₹1,00,000");                        // the capital entered or the paper account's
    expect(document.body.textContent).not.toMatch(/Groww margin/i);
    expect(val("Max stop-loss risk")).toHaveTextContent("−₹960.00");
    expect(val("Est. target profit")).toHaveTextContent("+₹8,500.00");
    expect(screen.getByText(/BROKERAGE 40\.00/)).toBeInTheDocument();
  });

  it("shows why sizing is unavailable instead of numbers", () => {
    calc(buyCeDashboard({ feed: { signal: { rec: makeRecommendation({ sizing: undefined, sizing_error: "Margin lookup failed" }) } } }));
    expect(screen.getByText("Margin lookup failed")).toBeInTheDocument();
    expect(screen.queryByText("Recommended lots")).toBeNull();
  });

  it("saves capital and risk % in the browser", async () => {
    const { user } = calc(makeDashboard());
    await user.type(screen.getByLabelText("Available capital ₹"), "250000");
    const risk = screen.getByLabelText("Risk per trade %");
    await user.clear(risk);
    await user.type(risk, "2");
    const saved = JSON.parse(localStorage.getItem("gt-settings")!);
    expect(saved).toMatchObject({ capital: 250000, riskPct: 2 });
  });

  it("lets a fractional risk such as 0.5 be typed key by key", async () => {
    const { user } = calc(makeDashboard());
    const risk = screen.getByLabelText("Risk per trade %");
    await user.clear(risk);
    await user.type(risk, "0.5");
    expect(risk).toHaveValue(0.5);
    expect(JSON.parse(localStorage.getItem("gt-settings")!).riskPct).toBe(0.5);
  });

  it("never saves an invalid risk (zero or empty), so the live feed keeps working while typing", async () => {
    const { user } = calc(makeDashboard());
    const risk = screen.getByLabelText("Risk per trade %");
    await user.clear(risk);
    expect(JSON.parse(localStorage.getItem("gt-settings")!).riskPct).toBe(1);
    await user.type(risk, "0");
    expect(JSON.parse(localStorage.getItem("gt-settings")!).riskPct).toBe(1);
    await user.tab();                                                       // leaving the box shows the saved value again
    expect(risk).toHaveValue(1);
  });
});

describe("RiskCalculator", () => {
  const calc = (api = mockApi(), d = buyCeDashboard(), acct = makeAccount()) => renderWithProviders(<RiskCalculator data={d} acct={acct} />, { bare: true, api });

  it("fills capital, entry premium and lot size from the account and live recommendation, then asks the backend to calculate", async () => {
    const { api } = calc();
    await waitFor(() => expect(api.callsTo("POST", "/api/paper/risk-calc")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/paper/risk-calc")[0].body).toEqual({ capital: 90000, risk_pct: 1, entry: 120.5, lot_size: 75, max_lots: 10, stop_pct: 30 });
    expect(await screen.findByText("TRADE · 2 lot(s)")).toBeInTheDocument();
    expect(screen.getByText("7. Recommended lots").closest("div.flex")).toHaveTextContent("2");
    expect(screen.getByText("11. Maximum possible loss").closest("div.flex")).toHaveTextContent("−₹4,500.00");
  });

  it("recalculates when a preset is chosen (Conservative = 0.5%)", async () => {
    const { api, user } = calc();
    await screen.findByText("TRADE · 2 lot(s)");
    await user.click(screen.getByRole("radio", { name: "0.5%" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/paper/risk-calc").at(-1)!.body).toMatchObject({ risk_pct: 0.5 }));
    expect(screen.getByText(/Preset:/)).toHaveTextContent("Conservative");
  });

  it("switches to an absolute stop price", async () => {
    const { api, user } = calc();
    await screen.findByText("TRADE · 2 lot(s)");
    await user.selectOptions(screen.getByDisplayValue("% below"), "price");
    await user.type(screen.getAllByRole("spinbutton").find((i) => (i as HTMLInputElement).value === "")!, "95");
    await waitFor(() => expect(api.callsTo("POST", "/api/paper/risk-calc").at(-1)!.body).toMatchObject({ stop: 95 }));
    expect(api.callsTo("POST", "/api/paper/risk-calc").at(-1)!.body).not.toHaveProperty("stop_pct");
  });

  it("shows NO TRADE with the reason when the risk rules refuse it", async () => {
    const api = mockApi().on("POST", "/api/paper/risk-calc", () => makeRisk({ decision: "NO TRADE", reason: "One lot exceeds the risk budget", lots: 0, qty: 0 }));
    calc(api);
    expect(await screen.findByText("One lot exceeds the risk budget")).toBeInTheDocument();
    expect(screen.getAllByText("NO TRADE").length).toBeGreaterThan(0);
  });

  it("shows the backend's validation error", async () => {
    calc(mockApi().on("POST", "/api/paper/risk-calc", () => fail("stop must be below entry")));
    expect(await screen.findByText("stop must be below entry")).toBeInTheDocument();
  });

  it("does not call the backend without capital", async () => {
    const api = mockApi();
    renderWithProviders(<RiskCalculator data={makeDashboard()} acct={null} />, { bare: true, api });
    expect(screen.getByText("Enter capital and risk % to see the calculation.")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 300));
    expect(api.callsTo("POST", "/api/paper/risk-calc")).toHaveLength(0);
  });
});

describe("DailyRisk and virtual account", () => {
  const view = (acct = makeAccount(), reload = vi.fn(), api = mockApi()) => ({ reload, ...renderWithProviders(<DailyRisk acct={acct} err={null} reload={reload} />, { bare: true, api }) });

  it("shows today's risk figures and the virtual account", () => {
    view();
    const stat = (l: string) => screen.getByText(l).parentElement!;
    expect(stat("Today's P&L")).toHaveTextContent("+₹1,200.00");
    expect(stat("Daily loss limit")).toHaveTextContent("₹3,000");
    expect(stat("Remaining risk budget")).toHaveTextContent("₹1,800");
    expect(stat("Max drawdown")).toHaveTextContent("−₹1,500");
    expect(screen.getByText("40% used")).toBeInTheDocument();
    expect(screen.getByText(/Virtual account #1/)).toHaveTextContent("balance ₹1,02,000.00");
  });

  it("flags when the daily limit is reached", () => {
    view(makeAccount({ limit_reached: true, risk_used_pct: 100 }));
    expect(screen.getByText("Limit reached")).toBeInTheDocument();
  });

  it("will not reset unless the user types RESET", async () => {
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("reset please");
    const { user, api, reload } = view();
    await user.type(screen.getByPlaceholderText("New capital ₹"), "200000");
    await user.click(screen.getByRole("button", { name: /Reset account/ }));
    expect(prompt).toHaveBeenCalledWith(expect.stringContaining("Type RESET to confirm"));
    expect(api.callsTo("POST", "/api/paper/account")).toHaveLength(0);
    expect(reload).not.toHaveBeenCalled();
  });

  it("resets the virtual account with the typed capital after RESET is typed", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("RESET");
    const { user, api, reload } = view();
    await user.type(screen.getByPlaceholderText("New capital ₹"), "200000");
    await user.click(screen.getByRole("button", { name: /Reset account/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/paper/account")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/paper/account")[0].body).toEqual({ capital: 200000, confirm: "RESET" });
    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(screen.getByPlaceholderText("New capital ₹")).toHaveValue(null);
  });

  it("asks for a capital first", async () => {
    const prompt = vi.spyOn(window, "prompt");
    const { user } = view();
    await user.click(screen.getByRole("button", { name: /Reset account/ }));
    expect(screen.getByText("Enter the new virtual capital.")).toBeInTheDocument();
    expect(prompt).not.toHaveBeenCalled();
  });

  it("is disabled while the paper engine runs", () => {
    view(makeAccount({ engine_running: true }));
    expect(screen.getByRole("button", { name: /Reset account/ })).toBeDisabled();
    expect(screen.getByText("Stop the paper engine to reset the account.")).toBeInTheDocument();
  });

  it("shows the server's error if the reset is refused", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("RESET");
    const api = mockApi().on("POST", "/api/paper/account", () => fail("Stop the engine first"));
    const { user } = view(makeAccount(), vi.fn(), api);
    await user.type(screen.getByPlaceholderText("New capital ₹"), "50000");
    await user.click(screen.getByRole("button", { name: /Reset account/ }));
    expect(await screen.findByText("Stop the engine first")).toBeInTheDocument();
  });

  it("shows the error card when the account could not be loaded, and nothing while loading", () => {
    const { unmount } = renderWithProviders(<DailyRisk acct={null} err="account fetch failed" reload={() => {}} />, { bare: true });
    expect(screen.getByRole("alert")).toHaveTextContent("account fetch failed");
    unmount();
    const { container } = renderWithProviders(<DailyRisk acct={null} err={null} reload={() => {}} />, { bare: true });
    expect(container.querySelector("section")).toBeNull();
    expect(ok()).toBeDefined();
  });
});

describe("PaperTrades", () => {
  const trades = () => [
    makeTrade(2, { entry_ts: at("11:00"), net: -300, gross: -150, exit_reason: "stop_loss", direction: "Bearish", opt_type: "PE", strike: 24900 }),
    makeTrade(1),
    makeTrade(3, { status: "OPEN", exit_ts: null, exit_price: null, gross: null, net: null, exit_reason: null, risk: null }),
  ];
  const table = (list = trades(), api = mockApi().on("GET", "/api/live/trades", () => list)) => renderWithProviders(<PaperTrades refreshKey={0} />, { bare: true, api });

  it("lists each trade with its risk, lots and net P&L, and 'open' for a position still held", async () => {
    table();
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(within(rows[2]).getByText("+₹2,100.00")).toBeInTheDocument();
    expect(within(rows[2]).getByText("2 × 75")).toBeInTheDocument();
    expect(within(rows[2]).getByText("1:2.0")).toBeInTheDocument();
    expect(within(rows[1]).getByText("−₹300.00")).toBeInTheDocument();
    expect(within(rows[3]).getByText("open")).toBeInTheDocument();
  });

  it("requests only paper trades", async () => {
    const { api } = table();
    await screen.findAllByRole("row");
    expect(api.callsTo("GET", "/api/live/trades")[0].query.get("mode")).toBe("paper");
  });

  it("opens a trade's stored risk calculation, checks and stop-loss history", async () => {
    const api = mockApi().on("GET", "/api/live/trades", () => trades()).on("GET", "/api/paper/stop-changes", () => [
      { ts: at("10:05"), old_stop: null, new_stop: 90, old_max_loss: null, new_max_loss: 4500, source: "entry", note: null },
      { ts: at("10:20"), old_stop: 90, new_stop: 100, old_max_loss: 4500, new_max_loss: 3000, source: "user", note: null }]);
    const { user } = table(undefined, api);
    await user.click((await screen.findAllByRole("row"))[2]);
    expect(await screen.findByText(/NIFTY26N2425000CE · BUY/)).toBeInTheDocument();
    expect(screen.getByText("Exit reason").parentElement).toHaveTextContent("target");
    expect(screen.getByText(/Risk calculation at entry/)).toBeInTheDocument();
    expect(screen.getByText("✓ risk within limit")).toBeInTheDocument();
    expect(screen.getByText("1. Available capital").closest("div.flex")).toHaveTextContent("₹1,00,000");
    expect(await screen.findByText("Stop-loss history")).toBeInTheDocument();
    expect(screen.getByText(/set at entry/)).toBeInTheDocument();
    expect(screen.getByText(/changed by you/)).toBeInTheDocument();
    expect(api.callsTo("GET", "/api/paper/stop-changes")[0].query.get("trade_id")).toBe("1");
    await user.click(within(screen.getByText(/NIFTY26N2425000CE · BUY/).closest("div.rounded-xl")!).getAllByRole("button")[0]);
    expect(screen.queryByText("Stop-loss history")).toBeNull();
  });

  it("says a trade from before risk sizing has no stored calculation", async () => {
    const { user } = table();
    await user.click((await screen.findAllByRole("row"))[3]);
    expect(await screen.findByText(/taken before risk sizing existed/)).toBeInTheDocument();
  });

  it("shows an empty state, and an error", async () => {
    const { unmount } = table([]);
    expect(await screen.findByText("No paper trades yet")).toBeInTheDocument();
    unmount();
    table(undefined, mockApi().on("GET", "/api/live/trades", () => fail("db down", 500)));
    expect(await screen.findByRole("alert")).toHaveTextContent("db down");
  });

  it("reloads when its refresh key changes (a trade was opened or closed)", async () => {
    const api = mockApi().on("GET", "/api/live/trades", () => []);
    const { rerender } = renderWithProviders(<PaperTrades refreshKey="1|0" />, { bare: true, api });
    await screen.findByText("No paper trades yet");
    rerender(<PaperTrades refreshKey="2|1" />);
    await waitFor(() => expect(api.callsTo("GET", "/api/live/trades")).toHaveLength(2));
  });
});

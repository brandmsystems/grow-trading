import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PositionTrading from "../../pages/PositionTrading";
import { fail, mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { makePosAnalysis, makePosPosition, makePosState, posStats } from "../../test/positionFixtures";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
const page = (api = mockApi()) => renderWithProviders(<PositionTrading />, { api });

describe("Position Trading page", () => {
  it("says it is paper only and that the score is not a probability, with a colour-coded decision and its reasons", async () => {
    page();
    expect(await screen.findByTestId("pos-decision")).toHaveTextContent("BUY CE");
    expect(screen.getByTestId("pos-paper-note")).toHaveTextContent(/cannot place a real order.*not a probability of winning.*no strategy here has a validated edge/s);
    expect(screen.getByTestId("pos-score")).toHaveTextContent("71.4");
    expect(screen.getByTestId("pos-reasons")).toHaveTextContent(/at least 60.*negative validated result/s);
    expect(screen.queryByText(/LIVE/)).not.toBeInTheDocument();
  });

  it("shows the weekly, daily, 4-hour and 1-hour trend, the regime and why VIX and global data are missing", async () => {
    page();
    expect(await screen.findByTestId("pos-regime")).toHaveTextContent("Uptrend");
    const tf = screen.getByTestId("pos-timeframes");
    for (const w of ["Weekly", "Daily", "4-hour", "1-hour", "strong up"]) expect(tf).toHaveTextContent(w);
    expect(screen.getByTestId("pos-context")).toHaveTextContent(/VIX, global markets, crude and FII\/DII: no stored pre-market report/);
  });

  it("compares BUY CE with BUY PE and explains the choice, flagging missing data", async () => {
    page();
    const c = await screen.findByTestId("pos-comparison");
    expect(c).toHaveTextContent("BUY CE"); expect(c).toHaveTextContent("BUY PE");
    expect(c).toHaveTextContent(/quality 7\.4 of 10/); expect(c).toHaveTextContent(/no usable contract: only 1 days to expiry/);
    expect(c).toHaveTextContent(/IV ≈ 13\.7%.*model estimate/s); expect(c).toHaveTextContent(/spread: not stored historically/i);
  });

  it("lists every score component with its reason and the full plan with warnings", async () => {
    page();
    const t = await screen.findByTestId("pos-components-CE");
    expect(t).toHaveTextContent("Weekly trend"); expect(t).toHaveTextContent("15.0 / 15"); expect(t).toHaveTextContent(/not available: 0 points/);
    const plan = screen.getByTestId("pos-plan-CE");
    for (const w of ["Entry range", "Premium stop", "Target 1 / 2", "NIFTY invalidation", "Holding", "Risk / reward", "1.86R", "Lots / qty", "Max loss", "Capital required", "theta"]) expect(plan).toHaveTextContent(w);
    expect(plan).toHaveTextContent(/not backtested/);
  });

  it("opens a paper position from a BUY idea and shows a refusal with its exact reason", async () => {
    const api = mockApi().on("POST", "/api/position/open", () => fail("portfolio risk would be ₹4,000, above the limit of 3% of capital", 409));
    page(api);
    fireEvent.click(await screen.findByRole("button", { name: /Open paper position \(CE\)/ }));
    expect(await screen.findByTestId("pos-msg")).toHaveTextContent(/portfolio risk would be ₹4,000/);
    expect(api.callsTo("POST", "/api/position/open")[0].body).toEqual({ direction: 1 });
    const ok = mockApi();
    page(ok);
    fireEvent.click((await screen.findAllByRole("button", { name: /Open paper position \(CE\)/ })).pop()!);
    await waitFor(() => expect(screen.getAllByTestId("pos-msg").pop()).toHaveTextContent(/Paper position opened for CE/));
  });

  it("never offers an entry when the decision is HOLD or NO TRADE and says nothing is forced", async () => {
    page(mockApi().on("GET", "/api/position/analysis", () => makePosAnalysis({ decision: "NO TRADE", direction: 0, score: null, opportunities: [], reasons: ["the weekly trend is not available yet (needs 50 weekly bars)"] })));
    expect(await screen.findByTestId("pos-decision")).toHaveTextContent("NO TRADE");
    expect(screen.getByTestId("pos-reasons")).toHaveTextContent(/weekly trend is not available/);
    expect(screen.getByTestId("pos-no-opps")).toHaveTextContent(/Nothing is forced/);
    expect(screen.queryByRole("button", { name: /Open paper position/ })).not.toBeInTheDocument();
  });

  it("lists the strategies with their signals and validated results and saves a changed setting", async () => {
    const api = mockApi();
    page(api);
    const t = await screen.findByTestId("pos-strategies");
    expect(t).toHaveTextContent("Daily EMA trend-following"); expect(t).toHaveTextContent("BUY CE"); expect(t).toHaveTextContent("negative validated result");
    fireEvent.click(screen.getByLabelText("Enable ADX trend strength"));
    fireEvent.change(screen.getByLabelText("Maximum open positions"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.callsTo("PUT", "/api/position/settings")).toHaveLength(1));
    const body = api.callsTo("PUT", "/api/position/settings")[0].body as { config: { strategies: Record<string, { enabled: boolean }>; risk: { max_open_positions: number } } };
    expect(body.config.strategies.adx_trend.enabled).toBe(false); expect(body.config.risk.max_open_positions).toBe(4);
  });

  it("calculates lots from capital, risk and the stop (approximate) and the virtual account", async () => {
    page(mockApi().on("GET", "/api/position/account", () => ({ state: makePosState({ balance: 512000, open_positions: 1, open_risk: 14800, open_risk_pct: 2.9 }), summary: { overall: posStats(), by_strategy: {} } })));
    const out = await screen.findByTestId("pos-calc-out");
    expect(out).toHaveTextContent(/Risk per lot ₹3,413 · 1 lot\(s\)/);
    fireEvent.change(screen.getByLabelText("Capital ₹"), { target: { value: "1000000" } });
    expect(screen.getByTestId("pos-calc-out")).toHaveTextContent(/2 lot\(s\)/);
    expect(await screen.findByTestId("pos-account")).toHaveTextContent(/5,12,000/);
  });

  it("shows open and completed positions with the exit plan, or says nothing is open", async () => {
    page();
    expect(await screen.findByTestId("pos-no-positions")).toHaveTextContent(/Nothing is forced/);
    page(mockApi().on("GET", "/api/position/positions", () => [makePosPosition(), makePosPosition({ id: 2, status: "CLOSED", exit_price: 250, exit_reason: "stop_loss", net: -9000, mtm: undefined, last_price: 250 })]));
    const t = (await screen.findAllByTestId("pos-positions")).pop()!;
    const rows = within(t).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2); expect(rows[0]).toHaveTextContent("OPEN"); expect(rows[1]).toHaveTextContent("stop_loss");
  });

  it("reports the backtest honestly: net by hold, per period, not-simulated counts, and no robust strategy", async () => {
    page();
    const b = await screen.findByTestId("pos-backtest");
    expect(b).toHaveTextContent(/3-day holds.*₹4,04,222/s);
    expect(b).toHaveTextContent(/No strategy and hold combination is robust/);
    expect(b).toHaveTextContent(/not simulated and are counted, never filled with a made-up price/);
    expect(b).toHaveTextContent(/IV and Greeks are not stored historically/);
    const rows = within(b).getAllByRole("row");
    expect(rows.length).toBeGreaterThan(2);
  });

  it("explains a missing backtest and an empty decision history", async () => {
    page(mockApi().on("GET", "/api/position/backtest", () => fail("The position backtest has not been run yet", 404)));
    expect(await screen.findByTestId("pos-bt-missing")).toBeInTheDocument();
    expect(await screen.findByTestId("pos-no-decisions")).toHaveTextContent(/No decision recorded yet/);
  });

  it("shows an error when the analysis cannot be built", async () => {
    page(mockApi().on("GET", "/api/position/analysis", () => fail("database is down", 500)));
    expect(await screen.findByText(/database is down/)).toBeInTheDocument();
  });
});

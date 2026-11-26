import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScannerPanel } from "../../components/auto/ScannerPanel";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { makeBiasConfig, makePosition } from "../../test/fixtures";
import type { BiasSettings, ScanBlock, ScanOpp } from "../../types/api";

const NEG = { status: "negative", label: "negative validated result", points: 0, trades: 379, oos_net: -56591, note: "net -₹97,628 over 379 trades" } as const;
const comp = (key: string, label: string, max: number, points: number, note = "n") => ({ key, label, max, points, available: true, note });
const opp = (o: Partial<ScanOpp>): ScanOpp => ({ strategy: "ema_9_21", label: "EMA 9/21 crossover", kind: "crossover", state: "signal", direction: 1, action: "BUY CE", decision: "ENTER",
  reasons: ["entered BUY CE"], quality: 61.5, components: [comp("trend", "Trend confirmation", 15, 12), comp("signal", "Entry signal quality", 15, 11.5)], evidence: NEG, episode_start: null, ...o });
const scan = (opps: ScanOpp[], rejected: ScanBlock["rejected"] = []): ScanBlock => ({
  state: { bar_close: "2026-11-26T10:35:00", scanned_at: "2026-11-26T10:35:05", min_quality: 55, decision: opps.some((o) => o.decision === "ENTER") ? "BUY" : "HOLD", opportunities: opps, open_positions: 1, max_open_positions: 3 },
  rejected, candles_scanned: 14, open_risk: 750, open_positions: 1, max_open_positions: 3 });
const settings = (over: Partial<BiasSettings> = {}) => ({ ...makeBiasConfig().defaults, entry_strategy: "scanner", max_open_positions: 3, max_trades_per_day: 0, scan_min_quality: 55, ...over }) as BiasSettings;
const cfg = makeBiasConfig({ scanner: { note: "Strategies with a negative or missing validated result trade only if you allow them.", components: [], strategies: [
  { key: "ema_9_21", label: "EMA 9/21 crossover", kind: "crossover", evidence: NEG }, { key: "m_orb", label: "Opening range breakout", kind: "method", evidence: NEG }] } }).scanner;

function show(block: ScanBlock | null, over: Partial<BiasSettings> = {}, extra: Partial<Parameters<typeof ScannerPanel>[0]> = {}) {
  const set = vi.fn();
  renderWithProviders(<ScannerPanel scan={block} s={settings(over)} set={set} cfg={cfg} running onApply={vi.fn()} busy={false} msg={null} tradesToday={9} cap={null} {...extra} />, { api: mockApi() });
  return set;
}

describe("Continuous opportunity scanner panel", () => {
  it("says what it is: no fixed trade count, not a probability, no edge", () => {
    show(null);
    const p = screen.getByTestId("scanner");
    expect(p).toHaveTextContent(/no fixed daily trade count/);
    expect(p).toHaveTextContent(/not a probability of winning/);
    expect(p).toHaveTextContent(/no strategy has shown an edge/);
    expect(screen.getByTestId("scan-empty")).toBeInTheDocument();
    expect(screen.getByTestId("scan-trades")).toHaveTextContent("9");                    // a count with no "of N" when there is no cap
    expect(screen.getByTestId("scan-stats")).toHaveTextContent("no count cap");
  });

  it("lists every strategy's decision with its score, validated result and the reason", () => {
    show(scan([opp({}), opp({ strategy: "m_orb", label: "Opening range breakout", decision: "REJECTED", action: "BUY PE", direction: -1, quality: 40, reasons: ["quality 40 of 100 is below the minimum 55 (weak: Option liquidity 0/10)"] }),
      opp({ strategy: "cross_5_20", label: "EMA 5/20 crossover", state: "no signal", decision: "HOLD", action: null, quality: null, components: [], reasons: ["no entry condition met on this candle"] })]));
    const enter = screen.getByTestId("scan-row-ema_9_21");
    expect(enter).toHaveTextContent("BUY"); expect(enter).toHaveTextContent("BUY CE"); expect(enter).toHaveTextContent("61.5 / 100"); expect(enter).toHaveTextContent("negative validated result");
    expect(screen.getByTestId("scan-row-m_orb")).toHaveTextContent(/REJECTED.*below the minimum 55/);
    expect(screen.getByTestId("scan-row-cross_5_20")).toHaveTextContent("HOLD");
  });

  it("shows each score component and its reason when the score is opened", () => {
    show(scan([opp({})]));
    expect(screen.queryByTestId("scan-components-ema_9_21")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Score of EMA 9/21 crossover" }));
    const list = screen.getByTestId("scan-components-ema_9_21");
    expect(list).toHaveTextContent("Trend confirmation"); expect(list).toHaveTextContent("12.0/15"); expect(list).toHaveTextContent("Entry signal quality");
  });

  it("filters by strategy, CE/PE and buy/sell", () => {
    show(scan([opp({}), opp({ strategy: "m_orb", label: "Opening range breakout", action: "SELL PE", decision: "REJECTED", reasons: ["x"] }),
      opp({ strategy: "cross_8_21", label: "EMA 8/21 crossover", action: "BUY PE", direction: -1, decision: "REJECTED", reasons: ["y"] })]));
    const rows = () => within(screen.getByTestId("scan-opps")).getAllByRole("row").length - 1;
    expect(rows()).toBe(3);
    fireEvent.change(screen.getByLabelText("Filter by buy or sell"), { target: { value: "SELL" } });
    expect(rows()).toBe(1); expect(screen.getByTestId("scan-row-m_orb")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by buy or sell"), { target: { value: "BUY" } });
    fireEvent.change(screen.getByLabelText("Filter by CE or PE"), { target: { value: "PE" } });
    expect(rows()).toBe(1); expect(screen.getByTestId("scan-row-cross_8_21")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter by CE or PE"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Filter by buy or sell"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Filter by strategy"), { target: { value: "ema_9_21" } });
    expect(rows()).toBe(1);
  });

  it("separates option buying from option writing in the open positions", () => {
    show(scan([]), {}, { positions: [{ ...makePosition(), id: 1, side: "BUY", opt_type: "CE", strategy: "ema_9_21", quality: 63, risk_amount: 750, stop_premium: 80, target_premium: 140 },
      { ...makePosition(), id: 2, side: "SELL", opt_type: "PE", strategy: "ema_5_20", quality: 58, risk_amount: 400, stop_premium: 120, target_premium: 60 }] });
    const t = screen.getByTestId("scan-positions");
    const rows = within(t).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("buying"); expect(rows[1]).toHaveTextContent("writing");
    expect(rows[0]).toHaveTextContent("ema_9_21"); expect(rows[1]).toHaveTextContent("SELL PE");
  });

  it("lists the rejected signals with the exact reason and the risk limits are editable", () => {
    const set = show(scan([], [{ bar_close: "2026-11-26T10:30:00", strategy: "ema_9_21", direction: "Bullish", reason: "Total open risk would be ₹1,800 (₹1,000 open + ₹800 new), above the limit of 1% of capital (₹1,000)." }]));
    expect(screen.getByTestId("scan-rejected")).toHaveTextContent(/Total open risk would be ₹1,800.*above the limit of 1%/);
    fireEvent.change(screen.getByLabelText("Maximum open positions"), { target: { value: "5" } });
    expect(set).toHaveBeenCalledWith({ max_open_positions: 5 });
    fireEvent.change(screen.getByLabelText("Daily trade cap"), { target: { value: "12" } });
    expect(set).toHaveBeenCalledWith({ max_trades_per_day: 12 });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(set).toHaveBeenCalledWith({ scan_allow_unvalidated: true });
    expect(screen.getByTestId("scan-evidence-note")).toHaveTextContent(/negative or missing validated result/);
  });
});

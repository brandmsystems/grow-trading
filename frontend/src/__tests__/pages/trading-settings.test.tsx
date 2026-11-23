import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Link, useLocation } from "react-router-dom";
import TradingSettings from "../../pages/TradingSettings";
import { fail, mockApi, type MockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { makeTsConfig, makeTsMeta, makeTsState, makeTsSummary } from "../../test/fixtures";
import type { TsConfig } from "../../types/api";

afterEach(() => { vi.restoreAllMocks(); });

const page = (api: MockApi = mockApi()) => renderWithProviders(<TradingSettings />, { api });
const sw = (name: string) => screen.getByRole("switch", { name: new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")} (ON|OFF)$`) });
const saved = (api: MockApi) => api.callsTo("PUT", "/api/trading-settings")[0].body as { config: TsConfig; base_version: number };
const loaded = async () => { await screen.findByRole("heading", { name: "Trading Settings" }); await screen.findByRole("button", { name: "Enable all strategies" }); };

describe("Trading Settings page", () => {
  it("lists every strategy, timeframe, indicator and rule with its ON/OFF state, and is paper only", async () => {
    page();
    await loaded();
    const meta = makeTsMeta();
    expect(meta.strategies).toHaveLength(32);
    expect(screen.getAllByRole("switch").length).toBe(32 + 4 + 11);                          // one switch per strategy, timeframe and indicator
    for (const s of meta.strategies) expect(sw(s.label)).toBeInTheDocument();
    for (const t of ["1 minute", "5 minutes", "15 minutes", "30 minutes"]) expect(sw(t)).toBeInTheDocument();
    for (const i of meta.indicators) expect(sw(i.label)).toBeInTheDocument();
    expect(sw("EMA 9/21")).toHaveAttribute("aria-checked", "true");
    expect(sw("EMA 9/21 fresh crossover")).toHaveAttribute("aria-checked", "false");           // research methods are OFF by default
    expect(sw("1 minute")).toHaveAttribute("aria-checked", "false");
    expect(sw("RSI")).toHaveAttribute("aria-checked", "true");
    const rules = screen.getByTestId("rules");
    for (const l of ["Maximum trades a day", "Risk per trade (% of virtual capital)", "Stop-loss method", "Trading starts", "Trading ends", "Allow re-entry after an exit", "Daily loss limit (% of capital)", "Trailing stop"]) {
      expect(within(rules).getByLabelText(l)).toBeInTheDocument();
    }
    expect(screen.getByText(/nothing on this page can place a real order/)).toBeInTheDocument();
    expect(screen.getByText("Version 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();                // nothing changed yet
  });

  it("shows the active configuration summary and when it was last saved", async () => {
    page();
    await loaded();
    const s = screen.getByTestId("summary");
    expect(s).toHaveTextContent("10 active of 10 ON");
    expect(s).toHaveTextContent("5m · 15m · 30m enabled");
    expect(s).toHaveTextContent("trend 15m · entry 5m · exit on the entry candle");
    expect(s).toHaveTextContent("11 ON · 0 OFF");
    expect(s).toHaveTextContent("09:30-14:30 · 6 trades a day");
    expect(s).toHaveTextContent("risk 1% · atr stop · 2R target · daily loss 3%");
    expect(screen.getByTestId("saved-at")).toHaveTextContent(/version 3 · saved 21\/11\/2026|version 3 · saved 21 Nov 2026|version 3 · saved/);
    expect(screen.getByTestId("actions")).toHaveTextContent(/Last saved: .*2026/);
  });

  it("a toggled strategy is an unsaved change until saved, then saved as a new version with the version it was based on", async () => {
    const api = mockApi();
    const { user } = page(api);
    await loaded();
    await user.click(sw("EMA 5/20"));
    expect(sw("EMA 5/20")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByTestId("unsaved")).toHaveTextContent(/unsaved changes: they are not used until you save/);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Save settings" })).toBeEnabled());      // after the server checked the draft
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.callsTo("PUT", "/api/trading-settings")).toHaveLength(1));
    expect(saved(api).base_version).toBe(3);
    expect(saved(api).config.strategies.ema_5_20.enabled).toBe(false);
    expect(saved(api).config.strategies.ema_9_21.enabled).toBe(true);
    expect(await screen.findByTestId("msg")).toHaveTextContent("Saved as version 4. A running engine applies it on its next tick.");
    expect(screen.queryByTestId("unsaved")).not.toBeInTheDocument();
    expect(screen.getByText("Version 4")).toBeInTheDocument();
    expect(screen.getByTestId("saved-at")).toHaveTextContent("version 4");
  });

  it("edits a strategy's parameters without touching source code and sends them", async () => {
    const api = mockApi();
    const { user } = page(api);
    await loaded();
    const card = screen.getByTestId("item-ema_9_21");
    await user.click(within(card).getByRole("button", { name: /Parameters \(9 · 21\)/ }));
    fireEvent.change(within(card).getByLabelText("Fast EMA"), { target: { value: "12" } });
    fireEvent.change(within(card).getByLabelText("Slow EMA"), { target: { value: "34" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save settings" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.callsTo("PUT", "/api/trading-settings")).toHaveLength(1));
    expect(saved(api).config.strategies.ema_9_21.params).toEqual({ fast: 12, slow: 34 });
  });

  it("edits indicator parameters, rules and timeframe roles and sends all of them", async () => {
    const api = mockApi();
    const { user } = page(api);
    await loaded();
    const rsi = screen.getByTestId("item-ind-rsi");
    await user.click(within(rsi).getByRole("button", { name: /Parameters/ }));
    fireEvent.change(within(rsi).getByLabelText("Period"), { target: { value: "9" } });
    fireEvent.change(within(rsi).getByLabelText("Overbought"), { target: { value: "80" } });
    const rules = screen.getByTestId("rules");
    fireEvent.change(within(rules).getByLabelText("Risk per trade (% of virtual capital)"), { target: { value: "0.5" } });
    fireEvent.change(within(rules).getByLabelText("Maximum trades a day"), { target: { value: "3" } });
    fireEvent.change(within(rules).getByLabelText("Trading ends"), { target: { value: "13:00" } });
    await user.selectOptions(within(rules).getByLabelText("Stop-loss method"), "pct");
    await user.click(within(rules).getByLabelText("Allow re-entry after an exit"));
    await user.selectOptions(screen.getByLabelText("Trend confirmation timeframe"), "30");
    await user.selectOptions(screen.getByLabelText("Entry signal timeframe"), "15");
    await user.selectOptions(screen.getByLabelText("Exit confirmation"), "trend");
    await waitFor(() => expect(screen.getByRole("button", { name: "Save settings" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.callsTo("PUT", "/api/trading-settings")).toHaveLength(1));
    const c = saved(api).config;
    expect(c.indicators.rsi.params).toMatchObject({ period: 9, overbought: 80, oversold: 25 });
    expect(c.rules).toMatchObject({ risk_pct: 0.5, max_trades_per_day: 3, end: "13:00", stop_mode: "pct", reentry_enabled: false });
    expect(c.timeframes).toMatchObject({ trend: 30, entry: 15, exit: "trend" });
  });

  it("toggles a timeframe and an indicator independently", async () => {
    const api = mockApi();
    const { user } = page(api);
    await loaded();
    await user.click(sw("1 minute"));
    await user.click(sw("30 minutes"));
    await user.click(sw("Bollinger Bands"));
    expect(sw("1 minute")).toHaveAttribute("aria-checked", "true");
    expect(sw("30 minutes")).toHaveAttribute("aria-checked", "false");
    await waitFor(() => expect(screen.getByRole("button", { name: "Save settings" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(api.callsTo("PUT", "/api/trading-settings")).toHaveLength(1));
    const c = saved(api).config;
    expect(c.timeframes.enabled).toEqual({ "1": true, "5": true, "15": true, "30": false });
    expect(c.indicators.bollinger.enabled).toBe(false);
    expect(c.indicators.rsi.enabled).toBe(true);
  });

  it("enable all and disable all work for strategies, indicators and timeframes", async () => {
    const { user } = page();
    await loaded();
    await user.click(screen.getByRole("button", { name: "Enable all strategies" }));
    expect(screen.getAllByRole("switch").filter((e) => e.getAttribute("aria-checked") === "true").length).toBe(32 + 3 + 11);   // all 32 + the 3 enabled timeframes + 11 indicators
    await user.click(screen.getByRole("button", { name: "Disable all strategies" }));
    expect(screen.getByTestId("item-ema_9_21").querySelector("[role=switch]")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByTestId("item-m_orb").querySelector("[role=switch]")).toHaveAttribute("aria-checked", "false");
    await user.click(screen.getByRole("button", { name: "Disable all indicators" }));
    expect(screen.getByTestId("item-ind-rsi").querySelector("[role=switch]")).toHaveAttribute("aria-checked", "false");
    await user.click(screen.getByRole("button", { name: "Enable all indicators" }));
    expect(screen.getByTestId("item-ind-rsi").querySelector("[role=switch]")).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("button", { name: "Enable all timeframes" }));
    expect(sw("1 minute")).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("button", { name: "Disable all timeframes" }));
    expect(sw("15 minutes")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("says which strategies are blocked by a disabled indicator and why, from the server's check", async () => {
    const cfg = makeTsConfig();
    cfg.indicators.vwap.enabled = false;
    const api = mockApi().on("POST", "/api/trading-settings/validate", () => ({
      valid: true, errors: [], config: cfg,
      warnings: [{ path: "strategies.ema_9_21_vwap", message: "EMA 9/21 + VWAP is ON but cannot trade: needs VWAP (disabled)." }],
      summary: makeTsSummary(cfg, { strategies_blocked: { ema_9_21_vwap: ["needs VWAP (disabled)"], scored: ["needs VWAP (disabled)"] }, strategies_active: ["ema_9_21"], indicators_off: ["vwap"] }),
    }));
    const { user } = page(api);
    await loaded();
    await user.click(sw("VWAP"));
    expect(await screen.findByTestId("blocked-ema_9_21_vwap")).toHaveTextContent("Cannot trade: needs VWAP (disabled).");
    expect(screen.getByTestId("blocked-scored")).toBeInTheDocument();
    expect(screen.queryByTestId("blocked-ema_9_21")).not.toBeInTheDocument();                    // a strategy that does not use VWAP is not blocked
    expect(screen.getByTestId("warnings")).toHaveTextContent(/EMA 9\/21 \+ VWAP is ON but cannot trade: needs VWAP \(disabled\)/);
    expect(screen.getByTestId("summary")).toHaveTextContent(/off: vwap/);
    expect(screen.getByRole("button", { name: "Save settings" })).toBeEnabled();                 // blocked is a warning: it can be saved (the engine will not trade it)
  });

  it("shows every validation error with its field and blocks saving until fixed", async () => {
    const api = mockApi().on("POST", "/api/trading-settings/validate", (req) => ({
      valid: false, config: (req.body as { config: TsConfig }).config, summary: null, warnings: [],
      errors: [{ path: "strategies.ema_9_21.params.fast", message: "the fast EMA must be shorter than the slow EMA" }, { path: "rules.risk_pct", message: "must be between 0.05 and 100" }],
    }));
    const { user } = page(api);
    await loaded();
    await user.click(within(screen.getByTestId("item-ema_9_21")).getByRole("button", { name: /Parameters/ }));
    fireEvent.change(within(screen.getByTestId("item-ema_9_21")).getByLabelText("Fast EMA"), { target: { value: "30" } });
    const box = await screen.findByTestId("issues");
    expect(box).toHaveTextContent("2 problems to fix before saving");
    expect(box).toHaveTextContent("the fast EMA must be shorter than the slow EMA");
    expect(within(screen.getByTestId("item-ema_9_21")).getByRole("alert")).toHaveTextContent("shorter than the slow EMA");      // next to the field
    expect(within(screen.getByTestId("rules")).getByRole("alert")).toHaveTextContent("between 0.05 and 100");
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
    expect(api.callsTo("PUT", "/api/trading-settings")).toHaveLength(0);
  });

  it("reports a refused save with the server's list and keeps the edits", async () => {
    const api = mockApi().on("PUT", "/api/trading-settings", () => fail("The settings are invalid (1 problem); nothing was saved.", 400, "SettingsError",
      { errors: [{ path: "rules.max_trades_per_day", message: "must be between 1 and 200" }] }));
    const { user } = page(api);
    await loaded();
    await user.click(sw("EMA 8/21"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save settings" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByTestId("msg")).toHaveTextContent("nothing was saved");
    expect(screen.getByTestId("issues")).toHaveTextContent("rules.max_trades_per_day");
    expect(sw("EMA 8/21")).toHaveAttribute("aria-checked", "false");                              // the edit is still there
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("a stale page cannot overwrite settings changed elsewhere and offers a reload", async () => {
    const api = mockApi().on("PUT", "/api/trading-settings", () => fail("The settings were changed elsewhere since you opened this page. Reload to see them.", 409, "Conflict"));
    const { user } = page(api);
    await loaded();
    await user.click(sw("EMA 8/21"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save settings" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    const m = await screen.findByTestId("msg");
    expect(m).toHaveTextContent("changed elsewhere");
    api.on("GET", "/api/trading-settings", () => makeTsState({ version: 9 }));
    await user.click(within(m).getByRole("button", { name: "Reload" }));
    expect(await screen.findByText("Version 9")).toBeInTheDocument();
  });

  it("resets to the defaults only after confirmation and saves that as a new version", async () => {
    const api = mockApi();
    const { user } = page(api);
    await loaded();
    await user.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(api.callsTo("POST", "/api/trading-settings/reset")).toHaveLength(0);                   // asked first
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(api.callsTo("POST", "/api/trading-settings/reset")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Reset to defaults" }));
    await user.click(screen.getByRole("button", { name: "Yes, reset" }));
    await waitFor(() => expect(api.callsTo("POST", "/api/trading-settings/reset")).toHaveLength(1));
    expect(await screen.findByTestId("msg")).toHaveTextContent("Reset to the defaults and saved as version 4.");
    expect(screen.getByText("Version 4")).toBeInTheDocument();
  });

  it("discard changes restores the saved configuration", async () => {
    const { user } = page();
    await loaded();
    await user.click(sw("EMA 5/20"));
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(sw("EMA 5/20")).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByTestId("unsaved")).not.toBeInTheDocument();
  });

  it("warns before the browser closes or an in-app link is followed while changes are unsaved, and not otherwise", async () => {
    const Where = () => <span data-testid="where">{useLocation().pathname}</span>;
    const { user } = renderWithProviders(<><Link to="/auto">Go to Auto</Link><Where /><TradingSettings /></>, { api: mockApi() });
    await loaded();
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);                                                    // nothing unsaved: no warning
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await user.click(screen.getByRole("link", { name: "Go to Auto" }));
    expect(confirm).not.toHaveBeenCalled();
    expect(screen.getByTestId("where")).toHaveTextContent("/auto");                                // clean: the link is followed freely
    await user.click(sw("EMA 5/20"));
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);                                                     // the browser asks before closing or refreshing
    await user.click(screen.getByRole("link", { name: "Go to Auto" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringMatching(/unsaved changes/));
    expect(sw("EMA 5/20")).toHaveAttribute("aria-checked", "false");                               // the edit survived: the user said no
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("link", { name: "Go to Auto" }));
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("tells the user when the saved configuration is invalid and the engine will not trade", async () => {
    page(mockApi().on("GET", "/api/trading-settings", () => makeTsState({ error: "rules.risk_pct: must be between 0.05 and 100", summary: makeTsSummary(makeTsConfig(), { valid: false, strategies_active: [] }) })));
    await loaded();
    expect(screen.getByText(/The saved configuration is invalid .*places no orders until you save a valid one/)).toBeInTheDocument();
  });

  it("explains an unreachable backend instead of showing an empty form", async () => {
    page(mockApi().on("GET", "/api/trading-settings", () => fail("Backend unreachable", 500)));
    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unreachable");
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  });
});

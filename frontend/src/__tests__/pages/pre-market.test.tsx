import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import PreMarket from "../../pages/PreMarket";
import { fail, mockApi, type MockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { makePmHistory, makePmReport } from "../../test/fixtures";

afterEach(() => { vi.restoreAllMocks(); });

const withReport = (api: MockApi, report: unknown) =>
  api.on("GET", "/api/premarket/report", () => ({ day: "2026-11-19", report, now: "2026-11-19T08:45:00", thresholds: {}, unavailable: {} }));
const page = (api = mockApi()) => renderWithProviders(<PreMarket />, { api });

describe("Pre-Market Analysis page", () => {
  it("says it is context, not a trade signal, and cannot place an order", async () => {
    page();
    expect(await screen.findByTestId("pm-total")).toHaveTextContent("+3");
    expect(screen.getByText(/this is context, not a trade signal/i)).toBeInTheDocument();
    expect(screen.getByText(/cannot place an order/i)).toBeInTheDocument();
    expect(screen.queryByText(/LIVE/)).not.toBeInTheDocument();
  });

  it("shows the total on a -5..+5 meter, the bias and the preference", async () => {
    page();
    expect(await screen.findByTestId("pm-bias")).toHaveTextContent("BULLISH");
    const meter = screen.getByRole("meter", { name: /pre-market directional score/i });
    expect(meter).toHaveAttribute("aria-valuenow", "3");
    expect(meter).toHaveAttribute("aria-valuemin", "-5");
    expect(within(screen.getByTestId("pm-bias").closest("section")!).getByText("BUY CE")).toBeInTheDocument();      // the history table also says BUY CE
    expect(screen.getByText(/preference, not an order/i)).toBeInTheDocument();
    expect(screen.getAllByText(/4 of 5 factors had data/).length).toBeGreaterThan(0);          // under the meter and in the confidence note
  });

  it("shows five separate factor cards with score, status, data time and source", async () => {
    page();
    await screen.findByTestId("pm-total");
    for (const [key, score] of [["global", "+1"], ["fii_dii", "0"], ["crude", "+1"], ["vix", "0"], ["structure", "+1"]]) {
      expect(screen.getByTestId(`score-${key}`)).toHaveTextContent(score);
    }
    const card = screen.getByText(/1\. Global markets/).closest("section")!;
    expect(within(card).getByText("BULLISH")).toBeInTheDocument();
    expect(within(card).getByText(/data 2026-11-19 08:30/)).toBeInTheDocument();
    expect(within(card).getByText(/Yahoo Finance/)).toBeInTheDocument();
    expect(within(card).getByText(/may lag up to 15 minutes/)).toBeInTheDocument();
  });

  it("flags unavailable data, gives it no point and warns", async () => {
    page();
    await screen.findByTestId("pm-total");
    const card = screen.getByText(/2\. FII \/ DII flows/).closest("section")!;
    expect(within(card).getByText("UNAVAILABLE")).toBeInTheDocument();
    expect(within(card).getByText(/no source/)).toBeInTheDocument();
    expect(screen.getByTestId("pm-warnings")).toHaveTextContent(/Gift Nifty is unavailable/);
    expect(screen.getByTestId("risks")).toHaveTextContent(/FII \/ DII flows data is unavailable/);
  });

  it("shows today's events with the news and keeps the headline evidence on the factor card", async () => {
    page();
    const news = await screen.findByTestId("news");
    expect(within(news).getByRole("link", { name: "Wall Street rallies as Fed signals rate cut" })).toHaveAttribute("href", "https://example.com/a");
    expect(screen.getByTestId("events")).toHaveTextContent(/Weekly NIFTY options expiry/);
    expect(within(screen.getByTestId("evidence-global")).getByText("supports")).toBeInTheDocument();
  });

  it("shows levels, risks and the confidence note without calling it a probability of winning", async () => {
    page();
    await screen.findByTestId("pm-bias");
    expect(screen.getByText("25,390.7")).toBeInTheDocument();
    expect(screen.getAllByText("25,141.8").length).toBeGreaterThan(0);
    expect(screen.getByTestId("confidence-note")).toHaveTextContent(/not a probability/i);
    expect(screen.getByText(/not an order/i, { selector: "p" })).toBeInTheDocument();
  });

  it("offers to generate a report when none exists, and shows it after generating", async () => {
    const api = mockApi();
    withReport(api, null);
    page(api);
    expect(await screen.findByText(/No report for today yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Generate report/ }));
    expect(await screen.findByTestId("pm-total")).toHaveTextContent("+3");
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/api/premarket/refresh")).toBe(true);
  });

  it("shows a refresh failure instead of inventing data", async () => {
    const api = mockApi();
    api.on("POST", "/api/premarket/refresh", () => fail("source down", 502, "ConnectionError"));
    page(api);
    await screen.findByTestId("pm-total");
    fireEvent.click(screen.getByRole("button", { name: /Refresh data/ }));
    expect(await screen.findByText(/source down/)).toBeInTheDocument();
    expect(screen.getByTestId("pm-total")).toHaveTextContent("+3");              // the last good report stays
  });

  it("shows a bearish day in red with BUY PE and a negative marker", async () => {
    const api = mockApi();
    withReport(api, makePmReport({ total: { total: -4, bias: "STRONG BEARISH" }, conclusion: { direction: "STRONG BEARISH", preference: "BUY PE" } }));
    page(api);
    expect(await screen.findByTestId("pm-total")).toHaveTextContent("-4");
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "-4");
    expect(within(screen.getByTestId("pm-bias").closest("section")!).getByText("BUY PE")).toBeInTheDocument();
  });

  it("saves FII/DII figures entered by hand and shows the recalculated report", async () => {
    const api = mockApi();
    page(api);
    await screen.findByTestId("pm-total");
    fireEvent.change(screen.getByLabelText("FII net cash (₹ cr)"), { target: { value: "-2500" } });
    fireEvent.change(screen.getByLabelText("DII net cash (₹ cr)"), { target: { value: "1800" } });
    fireEvent.click(screen.getByRole("button", { name: /Save FII\/DII figures/ }));
    await waitFor(() => expect(api.calls.some((c) => c.path === "/api/premarket/input")).toBe(true));
    const call = api.calls.find((c) => c.path === "/api/premarket/input")!;
    expect(call.body).toMatchObject({ kind: "fii_dii", fii_net_cash: -2500, dii_net_cash: 1800, fii_index_fut_long: null });
  });

  it("adds a scheduled event only when a title is typed, and shows a server refusal", async () => {
    const api = mockApi();
    api.on("POST", "/api/premarket/input", () => fail("FII/DII figures must be for a day before today.", 400));
    page(api);
    await screen.findByTestId("pm-total");
    expect(screen.getByRole("button", { name: "Add event" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Scheduled event today"), { target: { value: "RBI policy 10:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Add event" }));
    expect(await screen.findByText(/must be for a day before today/)).toBeInTheDocument();
  });

  it("shows the history: bias versus the actual day, paper result, and how agreement performed", async () => {
    page();
    const table = await screen.findByTestId("pm-history");
    const row = within(table).getByText("18 Nov 2026").closest("tr")!;
    expect(within(row).getByText("CORRECT")).toBeInTheDocument();
    expect(row).toHaveTextContent(/\+0\.91% UP/);
    expect(screen.getByTestId("pm-accuracy-note")).toHaveTextContent(/Too few days/);
    expect(screen.getByTestId("effectiveness")).toHaveTextContent(/agreed.*3 trades/);
    expect(screen.getByTestId("effectiveness")).toHaveTextContent(/opposed.*2 trades/);
  });

  it("states what validation found, including the weak recent result", async () => {
    page();
    expect(await screen.findByTestId("pm-validation")).toHaveTextContent(/56\.9%.*51\.1% in 2025.26.*no relation to the score/s);
  });

  it("says so when no day has been stored yet", async () => {
    const api = mockApi();
    api.on("GET", "/api/premarket/history", () => makePmHistory({ days: [], effectiveness: [], accuracy: { days: 0, settled: 0, calls: 0, correct: 0, hit_pct: null } }));
    page(api);
    expect(await screen.findByText(/No stored days yet/)).toBeInTheDocument();
  });
});

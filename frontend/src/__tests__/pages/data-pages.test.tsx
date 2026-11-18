import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Account from "../../pages/Account";
import HistoryCharts from "../../pages/HistoryCharts";
import MarketData from "../../pages/MarketData";
import { liveCharts, seriesOf } from "../../test/fakeCharts";
import { fail, mockApi, ok, type MockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { at, makeDataOverview, makeJob, makeLotSizes, makeOptionsCoverage } from "../../test/fixtures";
import type { Job } from "../../types/api";

afterEach(() => vi.restoreAllMocks());
const jobs = (api: MockApi, states: Partial<Job>[]) => api.on("GET", /^\/api\/jobs\//, () => makeJob(states.length > 1 ? states.shift() : states[0]));

describe("Market Data page", () => {
  const page = (api = mockApi()) => renderWithProviders(<MarketData />, { api });

  it("is loading until the overview arrives, and reports a failure", async () => {
    const { unmount } = page(mockApi().on("GET", "/api/data/overview", () => new Promise(() => {})));
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    unmount();
    page(mockApi().on("GET", "/api/data/overview", () => fail("database offline", 500)));
    expect(await screen.findByRole("alert")).toHaveTextContent("database offline");
  });

  it("summarises what is stored: sessions, candles, gaps and coverage", async () => {
    page();
    expect(await screen.findByText("Sessions stored")).toBeInTheDocument();
    const stat = (l: string) => screen.getAllByText(l)[0].closest("section")!;           // "Candles" also appears in the options card
    expect(stat("Sessions stored")).toHaveTextContent("1,200");
    expect(stat("Candles")).toHaveTextContent("4,50,000");
    expect(stat("Complete days")).toHaveTextContent("1,190");
    expect(stat("Missing minutes")).toHaveTextContent("30");
    expect(stat("Coverage")).toHaveTextContent("100%");
    expect(screen.getByText("Full coverage")).toBeInTheDocument();
  });

  it("shows spot, futures and options availability", async () => {
    page();
    await screen.findByText("NIFTY 50 spot");
    expect(screen.getByText(/1,200 sessions · 4,50,000 candles/)).toBeInTheDocument();
    expect(screen.getByText(/63 contracts · 4,00,000 candles/)).toBeInTheDocument();
    expect(screen.getByText(/21,750 contracts · 6,70,00,000 candles/)).toBeInTheDocument();
    expect(screen.getByText(/Intervals:/)).toHaveTextContent("1m, 5m, 15m, 30m");
  });

  it("links each month of the coverage grid to that month's chart", async () => {
    const { user } = page();
    await user.click(await screen.findByRole("link", { name: "21/21" }));
    expect(screen.getByTestId("path")).toHaveTextContent("/history?from=2026-10-01&to=2026-10-31");
  });

  it("lists missing periods and days with missing candles (each linking to its chart)", async () => {
    const d = makeDataOverview({ coverage: {
      not_downloaded: [{ from: "2026-11-01", to: "2026-11-03", days: 3 }], no_data: [{ from: "2026-11-09", to: "2026-11-09", days: 1 }],
      partial_days: [{ day: "2026-10-07", candles: 370, missing: 5, ranges: [["10:00", "10:04"]] }] } });
    const { user } = page(mockApi().on("GET", "/api/data/overview", () => d));
    expect(await screen.findByText("01 Nov 2026 → 03 Nov 2026")).toBeInTheDocument();
    expect(screen.getByText("09 Nov 2026")).toBeInTheDocument();
    expect(screen.getByText(/5 missing: 10:00–10:04/)).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "07 Oct 2026" }));
    expect(screen.getByTestId("path")).toHaveTextContent("/history?from=2026-10-07&to=2026-10-07&tf=1");
  });

  it("says when nothing is missing", async () => {
    page();
    expect(await screen.findByText("No missing periods.")).toBeInTheDocument();
    expect(screen.getByText("None.")).toBeInTheDocument();
  });

  it("downloads the target window through a job, shows progress, then refreshes the overview", async () => {
    const api = mockApi();
    jobs(api, [{ state: "running", progress: 0.5, message: "Downloading 2026-11-10" }, { state: "done" }]);
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: /Download or resume$/ }));
    expect(await screen.findByText("Downloading 2026-11-10")).toBeInTheDocument();
    expect(api.callsTo("POST", "/api/data/download")[0].body).toEqual({ from: "2021-11-11", to: "2026-11-17" });
    expect(screen.getByRole("button", { name: /Download or resume$/ })).toBeDisabled();           // no second download while one runs
    await waitFor(() => expect(screen.queryByText("Downloading 2026-11-10")).toBeNull(), { timeout: 4000 });
    expect(api.callsTo("GET", "/api/data/overview").length).toBeGreaterThanOrEqual(2);
  });

  it("downloads for the dates the user typed", async () => {
    const api = mockApi();
    const { user } = page(api);
    await screen.findByText("Sessions stored");
    const [from, to] = screen.getAllByLabelText(/^(From|To)$/) as HTMLInputElement[];
    fireEvent.change(from, { target: { value: "2026-11-01" } });
    fireEvent.change(to, { target: { value: "2026-11-05" } });
    await user.click(screen.getByRole("button", { name: /Download or resume$/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/data/download")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/data/download")[0].body).toEqual({ from: "2026-11-01", to: "2026-11-05" });
  });

  it("shows a failed download's error", async () => {
    const api = mockApi();
    jobs(api, [{ state: "error", error: "Groww rate limit reached" }]);
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: /Download or resume$/ }));
    expect(await screen.findByText("Groww rate limit reached")).toBeInTheDocument();
  });

  it("shows the failure when the download cannot even start", async () => {
    const api = mockApi().on("POST", "/api/data/download", () => fail("A download is already running", 409));
    const { user } = page(api);
    await user.click(await screen.findByRole("button", { name: /Download or resume$/ }));
    expect(await screen.findByText("A download is already running")).toBeInTheDocument();
  });

  it("follows a download already running when the page opens, and can stop it", async () => {
    let state: "running" | "done" = "running";
    const api = mockApi();
    api.on("GET", "/api/data/overview", () => makeDataOverview({ job: makeJob({ id: "dl-9", state: "running" }) }));
    api.on("GET", /^\/api\/jobs\//, () => makeJob({ id: "dl-9", state, progress: 0.3, message: "Downloading 2026-10-02" }));
    const { user } = page(api);
    expect(await screen.findByText("Downloading 2026-10-02")).toBeInTheDocument();
    state = "done";                                                      // so the page's polling loop ends after the stop
    await user.click(screen.getByRole("button", { name: /^Stop$/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/data/stop")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByText("Downloading 2026-10-02")).toBeNull(), { timeout: 4000 });
  });

  it("shows option history coverage and downloads options through a job", async () => {
    const api = mockApi();
    jobs(api, [{ state: "done" }]);
    const { user } = page(api);
    expect(await screen.findByText("100% downloaded")).toBeInTheDocument();
    expect(screen.getByText("Contracts in scope").parentElement).toHaveTextContent("21,750");
    expect(screen.getByText("Contract-days downloaded").parentElement).toHaveTextContent("1,00,000 / 1,00,000");
    await user.click(screen.getByRole("button", { name: /Download or resume options/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/data/options/download")).toHaveLength(1));
    expect(api.callsTo("POST", "/api/data/options/download")[0].body).toEqual({ from: "2021-11-11", to: "2026-11-17" });
  });

  it("flags partial option coverage and reports the last run", async () => {
    const oc = makeOptionsCoverage({ summary: { pct: 60 }, last_run: { id: 4, symbol: "NIFTY-OPTIONS", start_date: "2026-11-01", end_date: "2026-11-17", status: "failed",
      chunks_total: 100, chunks_done: 90, rows_received: 0, rows_new: 0, rows_duplicate: 0, rows_rejected: 10, error: "timeout", started_at: at("09:00"), finished_at: null } });
    page(mockApi().on("GET", "/api/data/options", () => oc));
    expect(await screen.findByText("60% downloaded")).toBeInTheDocument();
    expect(screen.getByText(/Last run/)).toHaveTextContent("failed, 90/100 requests, 10 failed");
  });

  it("shows option and lot-size failures without breaking the rest of the page", async () => {
    const api = mockApi().on("GET", "/api/data/options", () => fail("options coverage failed", 500)).on("GET", "/api/data/lot-sizes", () => fail("lot sizes failed", 500));
    page(api);
    expect(await screen.findByText("options coverage failed")).toBeInTheDocument();
    expect(await screen.findByText("lot sizes failed")).toBeInTheDocument();
    expect(screen.getByText("Sessions stored")).toBeInTheDocument();
  });

  it("lists NIFTY lot sizes by expiry cycle", async () => {
    page(mockApi().on("GET", "/api/data/lot-sizes", () => [...makeLotSizes(), { cycle: "weekly", first_expiry: "2026-05-05", lot_size: 75, source: "NSE circular" }]));
    const card = (await screen.findByText("NIFTY lot sizes (NSE)")).closest("section")!;
    const rows = await within(card).findAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("05 May 2026");                           // newest first
    expect(rows[1]).toHaveTextContent("weekly");
    expect(rows[1]).toHaveTextContent("75");
    expect(rows[2]).toHaveTextContent("27 Jan 2026");
    expect(rows[2]).toHaveTextContent("monthly");
    expect(rows[2]).toHaveTextContent("65");
  });

  it("lists past downloads with status and error", async () => {
    const run = { id: 1, symbol: "NIFTY", start_date: "2026-11-01", end_date: "2026-11-05", status: "failed", chunks_total: 10, chunks_done: 4, rows_received: 100, rows_new: 80,
      rows_duplicate: 20, rows_rejected: 0, error: "rate limited", started_at: at("09:00"), finished_at: null };
    page(mockApi().on("GET", "/api/data/overview", () => makeDataOverview({ downloads: [run] })));
    const card = (await screen.findByText("Download history")).closest("section")!;
    expect(within(card).getByText("failed")).toBeInTheDocument();
    expect(within(card).getByText("rate limited")).toBeInTheDocument();
    expect(within(card).getByText("4/10")).toBeInTheDocument();
  });
});

describe("Historical Charts page", () => {
  const page = (api = mockApi(), route = "/") => renderWithProviders(<HistoryCharts />, { api, route });
  const candlesCalls = (api: MockApi) => api.callsTo("GET", "/api/data/candles");

  it("opens on the last stored week, 5-minute candles, and writes that range in the address", async () => {
    const api = mockApi();
    page(api);
    await waitFor(() => expect(candlesCalls(api)).toHaveLength(1));
    expect(Object.fromEntries(candlesCalls(api)[0].query)).toEqual({ from: "2026-11-11", to: "2026-11-17", tf: "5" });
    await waitFor(() => expect(screen.getByTestId("path")).toHaveTextContent("/?from=2026-11-11&to=2026-11-17&tf=5"));
    expect(screen.getByText(/NIFTY 50 · 5-minute · 11 Nov 2026 → 17 Nov 2026/)).toBeInTheDocument();
  });

  it("draws the stored candles with EMAs calculated in the browser, and summary statistics", async () => {
    page();
    await screen.findByText("Range high");
    await waitFor(() => expect(liveCharts()).toHaveLength(1));
    const c = liveCharts()[0];
    expect(seriesOf(c, "candlestick")[0].data).toHaveLength(2);
    expect(c.series.find((s) => s.options.title === "EMA 9")!.data.map((d) => d.value)).toEqual([105, 105.6]);
    expect(screen.getByText("Bars").parentElement).toHaveTextContent("2");
    expect(screen.getByText("Range high").parentElement).toHaveTextContent("112.00");
    expect(screen.getByText("Range low").parentElement).toHaveTextContent("95.00");
    expect(screen.getByText("Last close").parentElement).toHaveTextContent("108.00");
  });

  it("hides the EMAs when unticked", async () => {
    const { user } = page();
    await screen.findByText("Range high");
    await user.click(screen.getByLabelText("EMA 9 / 21"));
    await waitFor(() => expect(liveCharts()[0].series.find((s) => s.options.title === "EMA 9")!.data).toEqual([]));
  });

  it("starts from the range and timeframe in the link (used by the Market Data page)", async () => {
    const api = mockApi();
    page(api, "/?from=2026-10-01&to=2026-10-05&tf=15");
    await waitFor(() => expect(candlesCalls(api)).toHaveLength(1));
    expect(Object.fromEntries(candlesCalls(api)[0].query)).toEqual({ from: "2026-10-01", to: "2026-10-05", tf: "15" });
  });

  it("asks for another timeframe", async () => {
    const api = mockApi();
    const { user } = page(api);
    await screen.findByText("Range high");
    await user.click(screen.getByRole("radio", { name: "15m" }));
    await waitFor(() => expect(candlesCalls(api).at(-1)!.query.get("tf")).toBe("15"));
  });

  it("pages Earlier and Later by the width of the range, and Latest jumps back", async () => {
    const api = mockApi();
    const { user } = page(api);
    await screen.findByText("Range high");
    await user.click(screen.getByRole("button", { name: /Earlier/ }));
    await waitFor(() => expect(candlesCalls(api).at(-1)!.query.get("from")).toBe("2026-11-04"));
    expect(candlesCalls(api).at(-1)!.query.get("to")).toBe("2026-11-10");
    await user.click(screen.getByRole("button", { name: /Later/ }));
    await waitFor(() => expect(candlesCalls(api).at(-1)!.query.get("to")).toBe("2026-11-17"));
    await user.click(screen.getByRole("button", { name: /Earlier/ }));
    await user.click(screen.getByRole("button", { name: "Latest" }));
    await waitFor(() => expect(candlesCalls(api).at(-1)!.query.get("from")).toBe("2026-11-11"));
  });

  it("accepts typed dates", async () => {
    const api = mockApi();
    page(api);
    await screen.findByText("Range high");
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2026-11-13" } });
    await waitFor(() => expect(candlesCalls(api).at(-1)!.query.get("from")).toBe("2026-11-13"));
  });

  it("says when there are no candles in the range", async () => {
    page(mockApi().on("GET", "/api/data/candles", () => ({ bars: [] })));
    expect(await screen.findByText("No candles in this range")).toBeInTheDocument();
    expect(screen.getByText("Range high").parentElement).toHaveTextContent("—");
  });

  it("shows an error when candles cannot be loaded", async () => {
    page(mockApi().on("GET", "/api/data/candles", () => fail("candles query failed", 500)));
    expect(await screen.findByText("candles query failed")).toBeInTheDocument();
  });

  it("tells the user to download data when nothing is stored", async () => {
    const empty = makeDataOverview({ coverage: { summary: { last: null } } });
    page(mockApi().on("GET", "/api/data/overview", () => empty));
    expect(await screen.findByText("No stored NIFTY data")).toBeInTheDocument();
  });
});

describe("Account & Settings page", () => {
  const page = (api = mockApi()) => renderWithProviders(<Account />, { api, bare: true });

  it("shows the Groww connection status without revealing credentials", async () => {
    page();
    expect(await screen.findByText("Credentials configured")).toBeInTheDocument();
    expect(screen.getByText("keys.txt found")).toBeInTheDocument();
    expect(screen.getByText(/never shown in the browser/)).toBeInTheDocument();
  });

  it("says plainly when credentials are missing", async () => {
    page(mockApi().on("GET", "/api/status", () => ok(undefined, { keys: false, message: "keys.txt not found" })));
    expect(await screen.findByText("Credentials missing")).toBeInTheDocument();
    expect(screen.getByText("keys.txt not found")).toBeInTheDocument();
  });

  it("shows funds, with the option-buying balance the calculator uses", async () => {
    page();
    const funds = (await screen.findByText("Funds")).closest("section")!;
    await within(funds).findByText("Cash");
    expect(within(funds).getByText("Cash").parentElement).toHaveTextContent("₹1,50,000.00");
    expect(within(funds).getByText("Margin used").parentElement).toHaveTextContent("₹20,000.00");
    expect(within(funds).getByText("F&O option buying").parentElement).toHaveTextContent("₹90,000.00");
    expect(within(funds).getByText("Collateral available").parentElement).toHaveTextContent("₹5,000.00");
  });

  it("shows the profile with readable labels and values", async () => {
    page();
    const card = (await screen.findByText("Profile")).closest("section")!;
    expect(await within(card).findByText("Name")).toBeInTheDocument();
    expect(within(card).getByText("Test User")).toBeInTheDocument();
    expect(within(card).getByText("FNO, CASH")).toBeInTheDocument();
    expect(within(card).getByText("Yes")).toBeInTheDocument();
  });

  it("shows errors for funds and profile separately", async () => {
    page(mockApi().on("GET", "/api/funds", () => fail("margin API down", 502)).on("GET", "/api/profile", () => fail("profile API down", 502)));
    expect(await screen.findByText("margin API down")).toBeInTheDocument();
    expect(await screen.findByText("profile API down")).toBeInTheDocument();
    expect(screen.getByText("Credentials configured")).toBeInTheDocument();
  });

  it("re-logs in to Groww and refreshes status, profile and funds", async () => {
    const api = mockApi();
    const { user } = page(api);
    await screen.findByText("Credentials configured");
    await user.click(screen.getByRole("button", { name: /Re-login to Groww/ }));
    await waitFor(() => expect(api.callsTo("POST", "/api/login")).toHaveLength(1));
    await waitFor(() => {
      expect(api.callsTo("GET", "/api/status")).toHaveLength(2);
      expect(api.callsTo("GET", "/api/profile")).toHaveLength(2);
      expect(api.callsTo("GET", "/api/funds")).toHaveLength(2);
    });
  });

  it("still refreshes (and shows the new state) when the re-login fails", async () => {
    const api = mockApi().on("POST", "/api/login", () => fail("TOTP rejected", 502));
    const { user } = page(api);
    await screen.findByText("Credentials configured");
    api.on("GET", "/api/status", () => ok(undefined, { keys: false, message: "login failed" }));
    await user.click(screen.getByRole("button", { name: /Re-login to Groww/ }));
    expect(await screen.findByText("Credentials missing")).toBeInTheDocument();
  });

  it("switches and remembers the theme", async () => {
    const { user } = page();
    await screen.findByText("Credentials configured");
    expect(document.documentElement).toHaveClass("dark");
    await user.click(screen.getByRole("radio", { name: "Light" }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(JSON.parse(localStorage.getItem("gt-settings")!).theme).toBe("light");
  });

  it("turns alert sound off and saves it", async () => {
    const { user } = page();
    await user.click(await screen.findByLabelText(/Sound and browser alerts/));
    expect(JSON.parse(localStorage.getItem("gt-settings")!).sound).toBe(false);
  });

  it("offers to enable browser notifications when permission is still undecided", async () => {
    const requestPermission = vi.fn(async () => "granted");
    class N { static permission = "default"; static requestPermission = requestPermission; }
    vi.stubGlobal("Notification", N);
    const { user } = page();
    expect(await screen.findByText("default")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Allow" }));
    expect(requestPermission).toHaveBeenCalled();
    expect(await screen.findByText("granted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Allow" })).toBeNull();
  });

  it("says browser notifications are unsupported when the browser has none", async () => {
    page();
    expect(await screen.findByText("unsupported")).toBeInTheDocument();
  });

  it("saves the order calculator defaults, and lets a fractional risk be typed", async () => {
    const { user } = page();
    await screen.findByText("Order calculator defaults");
    await user.type(screen.getByLabelText("Capital ₹"), "300000");
    const risk = screen.getByLabelText("Risk per trade %");
    await user.clear(risk);
    await user.type(risk, "0.5");
    expect(JSON.parse(localStorage.getItem("gt-settings")!)).toMatchObject({ capital: 300000, riskPct: 0.5 });
    await user.clear(screen.getByLabelText("Capital ₹"));
    expect(JSON.parse(localStorage.getItem("gt-settings")!).capital).toBeNull();     // empty = use Groww's margin
  });
});

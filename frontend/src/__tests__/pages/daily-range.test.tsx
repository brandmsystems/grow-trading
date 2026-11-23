import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DailyRange, { periodStart } from "../../pages/DailyRange";
import { liveCharts, seriesOf } from "../../test/fakeCharts";
import { fail, mockApi, type MockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { makeDailyRange, makeRangeDays } from "../../test/fixtures";
import { chartTime, todayIST } from "../../utils/format";
import type { DailyRange as Data } from "../../types/api";

const calls = (api: MockApi) => api.callsTo("GET", "/api/data/daily-range");
const page = (data: Data | (() => unknown) = makeDailyRange()) => {
  const api = mockApi().on("GET", "/api/data/daily-range", typeof data === "function" ? data : () => data);
  return { ...renderWithProviders(<DailyRange />, { api }), api };
};
/** The page has answered and put the default window in the date boxes. */
const ready = async () => { await screen.findByText("Range analysis"); await waitFor(() => expect(screen.getByLabelText("To")).not.toHaveValue("")); };
const chart = () => liveCharts()[liveCharts().length - 1];
const card = (title: RegExp | string) => screen.getByText(title).closest("section") as HTMLElement;
const bodyRows = (c: HTMLElement) => within(c).getAllByRole("row").slice(1);

describe("periodStart (1M / 3M / 6M / 1Y)", () => {
  it("starts the day after the same date a period earlier", () => {
    expect(periodStart("2026-11-17", 12)).toBe("2025-11-18");
    expect(periodStart("2026-11-17", 6)).toBe("2026-05-18");
    expect(periodStart("2026-11-17", 3)).toBe("2026-08-18");
    expect(periodStart("2026-11-17", 1)).toBe("2026-10-18");
  });
  it("crosses year ends and clamps month ends", () => {
    expect(periodStart("2026-02-10", 3)).toBe("2025-11-11");
    expect(periodStart("2026-03-31", 1)).toBe("2026-03-01");      // 31 Feb does not exist: 28 Feb + 1 day
    expect(periodStart("2024-02-29", 12)).toBe("2023-03-01");
  });
});

describe("Daily Range page: loading, empty and error states", () => {
  it("shows skeletons while the first answer is on its way", () => {
    page(() => new Promise(() => {}));
    expect(screen.getByLabelText("Loading daily range")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("Range analysis")).not.toBeInTheDocument();
  });

  it("explains an empty database", async () => {
    page({ ...makeDailyRange(), window: null, days: [], summary: null, counts: { days: 0, complete: 0, partial: 0, in_progress: 0 } });
    expect(await screen.findByText("No stored NIFTY data")).toBeInTheDocument();
  });

  it("explains a window with no sessions, and still lets the dates be changed", async () => {
    const empty = { ...makeDailyRange(), days: [], summary: null, counts: { days: 0, complete: 0, partial: 0, in_progress: 0 } };
    page(empty);
    expect(await screen.findByText("No sessions in these dates")).toBeInTheDocument();
    expect(screen.getByLabelText("From")).toBeEnabled();
  });

  it("shows the server's message and retries", async () => {
    let n = 0;
    const { api, user } = page(() => (++n === 1 ? fail("Choose a range of at most 6 years.", 400) : makeDailyRange()));
    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a range of at most 6 years.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Range analysis")).toBeInTheDocument();
    expect(calls(api)).toHaveLength(2);
  });
});

describe("Daily Range page: summary cards", () => {
  it("opens on the server's default (previous 1 year) with six cards", async () => {
    const { api } = page();
    await ready();
    expect(calls(api)).toHaveLength(1);
    expect(Object.fromEntries(calls(api)[0].query)).toEqual({});               // no dates: the server picks the previous year
    const d = makeDailyRange();
    const labels = ["1-Year high", "1-Year low", "Current price", "Average daily range", "Highest daily range", "Lowest daily range"];
    for (const l of labels) expect(screen.getAllByText(l, { exact: false }).length).toBeGreaterThan(0);
    const s = d.summary!;
    const text = (re: RegExp) => screen.getAllByText(re)[0];
    expect(text(/^\d{2},\d{3}\.\d{2}$/)).toBeInTheDocument();
    expect(screen.getAllByText(`${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2 }).format(s.high.price)}`).length).toBeGreaterThan(0);
    expect(screen.getByText(/sessions · 24 complete/)).toBeInTheDocument();
  });

  it("explains every calculation with a tooltip", async () => {
    page();
    await screen.findByText("Range analysis");
    const tips = screen.getAllByRole("tooltip").map((t) => t.textContent ?? "");
    for (const re of [/highest price traded/, /lowest price traded/, /not a live quote/, /ADR: the mean/, /widest high-low/, /narrowest high-low/,
      /compares the 10-day average/i, /Range used = /, /Mean daily range .* last 10 complete sessions/]) {
      expect(tips.some((t) => re.test(t)), String(re)).toBe(true);
    }
  });

  it("labels the cards after the chosen period", async () => {
    const { user } = page();
    await ready();
    await user.click(screen.getByRole("radio", { name: "3M" }));
    await waitFor(() => expect(screen.getAllByText(/3-Month high/i).length).toBeGreaterThan(0));
    await user.clear(screen.getByLabelText("From"));
    await user.type(screen.getByLabelText("From"), "2026-09-01");
    await waitFor(() => expect(screen.getAllByText(/Period high/i).length).toBeGreaterThan(0));
  });
});

describe("Daily Range page: period and date filters", () => {
  it("1M / 3M / 6M / 1Y ask the server for that window ending on the newest stored session", async () => {
    const { api, user } = page();
    await ready();
    expect(screen.getByRole("radio", { name: "1Y" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByLabelText("To")).toHaveValue("2026-11-17");
    for (const [label, from] of [["1M", "2026-10-18"], ["3M", "2026-08-18"], ["6M", "2026-05-18"], ["1Y", "2025-11-18"]] as const) {
      await user.click(screen.getByRole("radio", { name: label }));
      await waitFor(() => expect(screen.getByRole("radio", { name: label })).toHaveAttribute("aria-checked", "true"));
      await waitFor(() => expect(Object.fromEntries(calls(api).at(-1)!.query)).toEqual({ from, to: "2026-11-17" }));
      expect(screen.getByLabelText("From")).toHaveValue(from);
    }
  });

  it("custom dates are applied and show as custom", async () => {
    const { api, user } = page();
    await ready();
    const from = screen.getByLabelText("From");
    await user.clear(from);
    await user.type(from, "2026-06-01");
    await waitFor(() => expect(Object.fromEntries(calls(api).at(-1)!.query)).toEqual({ from: "2026-06-01", to: "2026-11-17" }));
    expect(screen.getByText("custom dates")).toBeInTheDocument();
    for (const r of screen.getAllByRole("radio", { name: /^(1M|3M|6M|1Y)$/ })) expect(r).toHaveAttribute("aria-checked", "false");
  });

  it("refuses a start date after the end date without asking the server", async () => {
    const { api, user } = page();
    await ready();
    const before = calls(api).length;
    const from = screen.getByLabelText("From");
    await user.clear(from);
    await user.type(from, "2026-12-31");
    expect(await screen.findByRole("alert")).toHaveTextContent("The start date is after the end date.");
    expect(calls(api)).toHaveLength(before);
  });

  it("the chart and the table are drawn from the same response", async () => {
    page();
    await screen.findByText("Range analysis");
    const days = makeDailyRange().days;
    expect(seriesOf(chart(), "candlestick")[0].data).toHaveLength(days.length);
    expect(screen.getByText(`${days.length} of ${days.length} days`)).toBeInTheDocument();
    expect(screen.getAllByText(/24 sessions/)).not.toHaveLength(0);
  });
});

describe("Daily Range page: chart", () => {
  it("draws green candles for up days and red for down days, one per session", async () => {
    page();
    await screen.findByText("Range analysis");
    const days = makeDailyRange().days;
    const s = seriesOf(chart(), "candlestick")[0];
    expect(s.options).toMatchObject({ upColor: "#16a34a", downColor: "#dc2626" });
    expect(s.data.map((p) => p.time)).toEqual(days.map((d) => chartTime(d.date)));
    expect(s.data[1]).toMatchObject({ open: days[1].open, high: days[1].high, low: days[1].low, close: days[1].close, color: "#16a34a" });   // k=1 closes up
    expect(s.data[3]).toMatchObject({ close: days[3].close, color: "#dc2626" });                                                             // k=3 closes down
    expect(chart().options).toMatchObject({ timeScale: { timeVisible: false } });
    expect(chart().options).toMatchObject({ handleScroll: true, handleScale: true });         // zoom and pan
  });

  it("Range bars shows the range in points and the 10/20/50-day averages", async () => {
    const { user } = page();
    await screen.findByText("Range analysis");
    await user.click(screen.getByRole("radio", { name: "Range bars" }));
    const days = makeDailyRange().days;
    await waitFor(() => expect(seriesOf(chart(), "histogram")).toHaveLength(1));
    const bars = seriesOf(chart(), "histogram")[0];
    expect(bars.data.map((p) => p.value)).toEqual(days.map((d) => d.range));
    expect(bars.data.map((p) => p.color)).toEqual(days.map((d) => (d.close >= d.open ? "#16a34a" : "#dc2626")));
    const lines = seriesOf(chart(), "line");
    expect(lines.map((l) => l.options.color)).toEqual(["#3b82f6", "#f97316", "#a855f7"]);
    expect(lines[0].data).toHaveLength(days.filter((d) => d.avg10 != null).length);
    expect(lines[1].data).toHaveLength(days.filter((d) => d.avg20 != null).length);
    expect(lines[2].data).toHaveLength(0);                                                   // only 24 sessions: no 50-day average yet
    expect(screen.getByText("10-day average")).toBeInTheDocument();
  });

  it("draws incomplete and live days lighter", async () => {
    page(makeDailyRange({ days: makeRangeDays(12, "2026-11-17", { 5: "partial", 11: "in_progress" }) }));
    await screen.findByText("Range analysis");
    const data = seriesOf(chart(), "candlestick")[0].data;
    expect(data[5].color).toMatch(/^rgba\(/);
    expect(data[11].color).toMatch(/^rgba\(/);
    expect(data[4].color).toMatch(/^#/);
  });

  it("hovering a day shows its date, OHLC, range points, range % and change", async () => {
    page();
    await screen.findByText("Range analysis");
    const days = makeDailyRange().days, d = days[8];
    expect(screen.getByTestId("range-legend")).toHaveTextContent("17 Nov 2026");        // the latest day until the mouse moves
    act(() => chart().crosshair!({ time: chartTime(d.date) }));
    const lg = screen.getByTestId("range-legend");
    expect(lg).toHaveTextContent(new Date(d.date).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" }));
    expect(lg).toHaveTextContent(`O ${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2 }).format(d.open)}`);
    expect(lg).toHaveTextContent(`Range ${d.range.toFixed(2)} pts (${d.range_pct.toFixed(2)}%)`);
    expect(lg).toHaveTextContent(/Change [+−]\d/);
    act(() => chart().crosshair!({}));                                                   // pointer leaves
    expect(screen.getByTestId("range-legend")).toHaveTextContent("17 Nov 2026");
  });
});

describe("Daily Range page: range analysis", () => {
  it("shows the averages, trend, extremes and utilization", async () => {
    page();
    await screen.findByText("Range analysis");
    const c = card("Range analysis");
    expect(within(c).getByText("expanding")).toBeInTheDocument();
    expect(within(c).getByText(/10-day average \(180\.00 pts\) is 12\.5% above the 50-day average \(160\.00 pts\)/)).toBeInTheDocument();
    expect(within(c).getByText("Highest range")).toBeInTheDocument();
    expect(within(c).getByText("Lowest range")).toBeInTheDocument();
    expect(within(c).getByText("Latest session vs average")).toBeInTheDocument();
    const last = makeDailyRange().days.at(-1)!;
    const used = (100 * last.range / 180).toFixed(1) + "%";
    expect(within(c).getAllByText(used).length).toBeGreaterThan(0);
    expect(within(c).getByRole("progressbar")).toHaveAttribute("aria-valuenow", String(Math.min(100, Math.round(100 * last.range / 180))));
  });

  it("labels a running session as today and says when the day is already wider than average", async () => {
    const d = makeDailyRange();
    const cur = { ...d.analysis.current!, date: todayIST(), status: "in_progress" as const, range: 270, utilization: { "10": 150, "20": 154.3, "50": null }, remaining: { "10": 0, "20": 0, "50": null } };
    page({ ...d, analysis: { ...d.analysis, current: cur } });
    await screen.findByText("Range analysis");
    const c = card("Range analysis");
    expect(within(c).getByText("Today's range vs average")).toBeInTheDocument();
    expect(within(c).getByText(/Already 90\.00 pts wider than the average day/)).toBeInTheDocument();
    expect(within(c).getAllByText("150.0%").length).toBeGreaterThan(0);
  });

  it("says plainly when there are too few sessions for an average", async () => {
    const d = makeDailyRange({ days: makeRangeDays(5) });
    page({ ...d, analysis: { windows: [10, 20, 50], trend: null, current: { ...d.analysis.current!, adr: { "10": null, "20": null, "50": null }, utilization: { "10": null, "20": null, "50": null }, remaining: { "10": null, "20": null, "50": null } } } });
    await screen.findByText("Range analysis");
    const c = card("Range analysis");
    expect(within(c).getByText("not enough sessions")).toBeInTheDocument();
    expect(within(c).getByText(/needs 50 complete sessions/)).toBeInTheDocument();
    expect(within(c).getByText(/needs 10 earlier complete sessions/)).toBeInTheDocument();
  });

  it("warns that a session with missing minutes may understate its range", async () => {
    const d = makeDailyRange();
    page({ ...d, analysis: { ...d.analysis, current: { ...d.analysis.current!, status: "partial", note: "This session has missing minutes, so its range may be understated." } } });
    await screen.findByText("Range analysis");
    expect(screen.getByText(/missing minutes, so its range may be understated/)).toBeInTheDocument();
  });
});

describe("Daily Range page: history table", () => {
  const table = async () => { await screen.findByText("Daily history"); return card("Daily history"); };
  const dates = (c: HTMLElement) => bodyRows(c).map((r) => within(r).getAllByRole("cell")[0].textContent!.slice(0, 11));

  it("lists the days newest first with every column, 10 to a page", async () => {
    page();
    const c = await table();
    expect(within(c).getAllByRole("columnheader").map((h) => h.querySelector("button")!.textContent))
      .toEqual(["Date", "Open", "High", "Low", "Close", "Range (pts)", "Range (%)", "Change (%)"]);
    const rows = bodyRows(c);
    expect(rows).toHaveLength(10);
    const first = within(rows[0]).getAllByRole("cell").map((x) => x.textContent);
    const d = makeDailyRange().days.at(-1)!;
    expect(first[0]).toContain("17 Nov 2026");
    expect(first[5]).toBe(new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2 }).format(d.range));
    expect(first[6]).toBe(`${d.range_pct.toFixed(2)}%`);
    expect(within(c).getByText(/1–10 of 24 · page 1 of 3/)).toBeInTheDocument();
  });

  it("paginates and changes the page size", async () => {
    const { user } = page();
    const c = await table();
    await user.click(within(c).getByRole("button", { name: "Next" }));
    expect(within(c).getByText(/11–20 of 24 · page 2 of 3/)).toBeInTheDocument();
    await user.click(within(c).getByRole("button", { name: "Next" }));
    expect(bodyRows(c)).toHaveLength(4);
    expect(within(c).getByRole("button", { name: "Next" })).toBeDisabled();
    await user.selectOptions(within(c).getByLabelText("Rows per page"), "25");
    expect(bodyRows(c)).toHaveLength(24);
    expect(within(c).getByRole("button", { name: "Prev" })).toBeDisabled();
  });

  it("sorts by any column, both ways, and marks it for assistive tech", async () => {
    const { user } = page();
    const c = await table();
    await user.selectOptions(within(c).getByLabelText("Rows per page"), "25");
    const days = makeDailyRange().days;
    const col = (i: number) => bodyRows(c).map((r) => Number(within(r).getAllByRole("cell")[i].textContent!.replace(/[,%+−]/g, (m) => (m === "−" ? "-" : ""))));
    await user.click(within(c).getByRole("button", { name: /Range \(pts\)/ }));
    const desc = col(5);
    expect(desc).toEqual([...desc].sort((a, b) => b - a));
    expect(within(c).getByRole("columnheader", { name: /Range \(pts\)/ })).toHaveAttribute("aria-sort", "descending");
    await user.click(within(c).getByRole("button", { name: /Range \(pts\)/ }));
    const asc = col(5);
    expect(asc).toEqual([...asc].sort((a, b) => a - b));
    expect(Math.max(...asc)).toBe(Math.max(...days.map((d) => d.range)));
    expect(within(c).getByRole("columnheader", { name: /Range \(pts\)/ })).toHaveAttribute("aria-sort", "ascending");
    await user.click(within(c).getByRole("button", { name: /^Date/ }));
    expect(dates(c)[0]).toBe("17 Nov 2026");
  });

  it("keeps days with no previous close (the first day) last when sorting by change", async () => {
    const { user } = page();
    const c = await table();
    await user.selectOptions(within(c).getByLabelText("Rows per page"), "25");
    for (const n of [1, 2]) {
      await user.click(within(c).getByRole("button", { name: /Change \(%\)/ }));
      const cells = bodyRows(c).map((r) => within(r).getAllByRole("cell")[7].textContent);
      expect(cells.at(-1), `click ${n}`).toBe("—");
    }
  });

  it("searches by date, weekday and price", async () => {
    const { user } = page();
    const c = await table();
    const box = within(c).getByRole("searchbox");
    await user.type(box, "17 nov");
    expect(bodyRows(c)).toHaveLength(1);
    expect(within(c).getByText("1 of 24 days")).toBeInTheDocument();
    await user.clear(box);
    await user.type(box, "friday");
    const fridays = makeDailyRange().days.filter((d) => new Date(d.date + "T00:00:00Z").getUTCDay() === 5).length;
    expect(within(c).getByText(`${fridays} of 24 days`)).toBeInTheDocument();
    await user.clear(box);
    await user.type(box, String(makeDailyRange().days[2].close));
    expect(bodyRows(c).length).toBeGreaterThan(0);
    await user.clear(box);
    await user.type(box, "zzz");
    expect(within(c).getByText("No days match")).toBeInTheDocument();
  });

  it("filters green, red and incomplete days", async () => {
    const { user } = page(makeDailyRange({ days: makeRangeDays(24, "2026-11-17", { 7: "partial" }) }));
    const c = await table();
    const days = makeRangeDays(24, "2026-11-17", { 7: "partial" });
    await user.selectOptions(within(c).getByLabelText("Day type"), "up");
    expect(within(c).getByText(`${days.filter((d) => d.close >= d.open).length} of 24 days`)).toBeInTheDocument();
    await user.selectOptions(within(c).getByLabelText("Day type"), "down");
    expect(within(c).getByText(`${days.filter((d) => d.close < d.open).length} of 24 days`)).toBeInTheDocument();
    await user.selectOptions(within(c).getByLabelText("Day type"), "partial");
    expect(bodyRows(c)).toHaveLength(1);
    expect(within(bodyRows(c)[0]).getByText("incomplete")).toBeInTheDocument();
  });

  it("colours change green and red and flags live and incomplete days", async () => {
    page(makeDailyRange({ days: makeRangeDays(24, "2026-11-17", { 23: "in_progress", 22: "partial" }) }));
    const c = await table();
    const rows = bodyRows(c);
    expect(within(rows[0]).getByText("live")).toBeInTheDocument();
    expect(within(rows[1]).getByText("incomplete")).toBeInTheDocument();
    const change = (r: HTMLElement) => within(r).getAllByRole("cell")[7];
    const up = rows.find((r) => /^\+/.test(change(r).textContent!)), down = rows.find((r) => /^−/.test(change(r).textContent!));
    expect(change(up!)).toHaveClass("text-gain");
    expect(change(down!)).toHaveClass("text-loss");
  });
});

describe("Daily Range page: navigation and layout", () => {
  it("is in the sidebar and explains its limits", async () => {
    page();
    await screen.findByText("Range analysis");
    expect(screen.getByRole("heading", { level: 1, name: "Daily Range" })).toBeInTheDocument();
    expect(screen.getByText(/no minute is ever filled in/)).toBeInTheDocument();
  });

  it("uses responsive grids and a scrollable table, so nothing overflows on a phone", async () => {
    page();
    await screen.findByText("Range analysis");
    expect(screen.getByText("Average daily range").closest("section")!.parentElement!.className).toMatch(/grid-cols-1.*sm:grid-cols-2.*xl:grid-cols-3/);
    expect(within(card("Daily history")).getByRole("table").parentElement!.className).toContain("overflow-x-auto");
  });
});

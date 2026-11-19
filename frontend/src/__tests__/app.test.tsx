import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NAV } from "../components/layout/nav";
import { mockApi } from "../test/mockApi";
import { renderApp } from "../test/render";
import { buyCeDashboard } from "../test/fixtures";

/** What proves each page mounted (every page has its own heading or signature card). */
const PAGES: { path: string; label: string; marker: RegExp | string; role?: "heading" }[] = [
  { path: "/", label: "Overview", marker: "Recent notifications" },
  { path: "/live", label: "Live Trading", marker: "Trading Controls" },
  { path: "/auto", label: "Automated Paper Trading", marker: "Predictions vs actual" },
  { path: "/signals", label: "Trading Signals", marker: "Latest live signal" },
  { path: "/options", label: "Options Analysis", marker: "Selected contract" },
  { path: "/backtest", label: "Backtesting", marker: "Settings" },
  { path: "/compare", label: "Strategy Comparison", marker: "Net P&L by strategy and timeframe" },
  { path: "/scalping", label: "5-Minute Scalping", marker: "Verdict" },
  { path: "/data", label: "Market Data", marker: "Coverage by month" },
  { path: "/history", label: "Historical Charts", marker: "Range high" },
  { path: "/account", label: "Account & Settings", marker: "Groww connection" },
];

describe("the whole app", () => {
  it("covers every page in the navigation", () => {
    expect(PAGES.map((p) => p.path)).toEqual(NAV.map((n) => n.to));
    expect(PAGES.map((p) => p.label)).toEqual(NAV.map((n) => n.label));
  });

  it.each(PAGES)("opens $label at /app$path with its content and the right header", async ({ path, label, marker }) => {
    renderApp(`/app${path === "/" ? "/" : path}`);
    expect(await screen.findAllByText(marker, undefined, { timeout: 5000 })).not.toHaveLength(0);
    expect(screen.getAllByRole("heading", { level: 1, name: label }).length).toBeGreaterThan(0);
  });

  it("navigates between pages from the sidebar, keeping the shared live feed", async () => {
    const api = mockApi();
    const { user } = renderApp("/app/", api);
    await screen.findByText("Recent notifications");
    const nav = within(screen.getAllByRole("navigation", { name: "Main" })[0]);
    await user.click(nav.getByRole("link", { name: "Backtesting" }));
    expect(await screen.findByText("Settings", undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/app/backtest");
    await user.click(nav.getByRole("link", { name: "Overview" }));
    expect(await screen.findByText("Recent notifications")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/app");
    // one shared poll: moving between pages never starts a second dashboard poll
    const first = api.callsTo("GET", "/api/live/dashboard").length;
    expect(first).toBeLessThanOrEqual(2);
  });

  it("sends unknown addresses to the Overview", async () => {
    renderApp("/app/does-not-exist");
    expect(await screen.findByText("Recent notifications")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/app");
  });

  it("the Overview's links reach the Live terminal", async () => {
    const { user } = renderApp("/app/");
    await user.click(await screen.findByRole("link", { name: /Open terminal/ }));
    expect(await screen.findByText("Trading Controls")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/app/live");
  });

  it("every page loads without a missing API endpoint, a React error or a console error", async () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const api = mockApi();
    const { user } = renderApp("/app/", api);
    await screen.findByText("Recent notifications");
    for (const p of PAGES.slice(1)) {
      const nav = within(screen.getAllByRole("navigation", { name: "Main" })[0]);
      await user.click(nav.getByRole("link", { name: p.label }));
      try {
        expect((await screen.findAllByText(p.marker, undefined, { timeout: 5000 })).length).toBeGreaterThan(0);
      } catch (e) {
        throw new Error(`DIAG path=${window.location.pathname} page=${p.label} calls=${api.calls.length} main=${(document.querySelector("main")?.textContent ?? "").slice(0, 200)} :: ${(e as Error).message.slice(0, 80)}`);
      }
    }
    expect(api.unmatched).toEqual([]);                                           // no page asked for an endpoint the backend lacks
    const real = errors.mock.calls.filter(([m]) => !String(m).includes("not wrapped in act"));
    expect(real).toEqual([]);
  }, 30000);

  it("shows the WebSocket / REST indicator in the header and the offline banner when the backend dies", async () => {
    const { unreachableApi } = await import("../test/mockApi").then((m) => ({ unreachableApi: mockApi().on("GET", "/api/live/dashboard", () => m.unreachable()) }));
    renderApp("/app/", unreachableApi);
    expect(await screen.findByText("Backend offline")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/Backend unreachable/);
    expect(screen.getByText("Connecting to Grow Trading…")).toBeInTheDocument();      // the page does not pretend to have data
  });

  it("marks the current page in both navigation bars", async () => {
    renderApp("/app/signals");
    await screen.findByText("Latest live signal");
    const [sidebar, bottom] = screen.getAllByRole("navigation", { name: "Main" });
    expect(within(sidebar).getByRole("link", { name: "Trading Signals" }).className).toContain("bg-blue-600");
    expect(within(bottom).getByRole("link", { name: "Signals" }).className).toContain("text-blue-600");
  });
});

describe("responsive structure (the real widths are checked in a browser)", () => {
  it("phones get the bottom bar, tablets and desktops the sidebar, never both", async () => {
    renderApp("/app/");
    await screen.findByText("Recent notifications");
    const [sidebar, bottom] = screen.getAllByRole("navigation", { name: "Main" });
    const aside = screen.getByRole("complementary");
    expect(aside.className).toMatch(/\bhidden\b/);                 // hidden by default (phone)...
    expect(aside.className).toContain("md:flex");                  // ...shown from tablet width
    expect(sidebar.closest("aside")).toBe(aside);
    expect(bottom.className).toContain("md:hidden");                // bottom bar: phone only
    expect(bottom.className).toContain("fixed");
  });

  it("leaves room under the content for the phone bottom bar", async () => {
    renderApp("/app/");
    await screen.findByText("Recent notifications");
    const main = screen.getByRole("main");
    expect(main.className).toContain("pb-24");
    expect(main.className).toContain("md:pb-8");
  });

  it("shows the NIFTY price and signal in the phone header (hidden from small screens up)", async () => {
    renderApp("/app/", mockApi().on("GET", "/api/live/dashboard", () => buyCeDashboard()));
    const header = screen.getByRole("banner");
    const chip = await within(header).findByText(/25,001/);
    expect(chip.closest("span")!.className).toContain("sm:hidden");
    const pill = within(header).getByTitle("Latest strategy signal");
    expect(pill).toHaveTextContent("BUY CE");
    expect(pill.parentElement!.className).toContain("sm:hidden");
  });

  it("wide tables scroll inside their own box instead of widening the page", async () => {
    renderApp("/app/backtest");
    await screen.findByText("Yearly & monthly returns", undefined, { timeout: 5000 });
    const table = screen.getByText("Yearly & monthly returns").closest("section")!.querySelector("table")!;
    expect(table.parentElement!.className).toContain("overflow-x-auto");
    await waitFor(() => expect(screen.getByRole("main").className).toContain("max-w-[1600px]"));
  });
});

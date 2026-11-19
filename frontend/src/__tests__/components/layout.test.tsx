import { useState } from "react";
import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Route, Routes } from "react-router-dom";
import { AppLayout } from "../../components/layout/AppLayout";
import { MobileNav } from "../../components/layout/MobileNav";
import { NAV } from "../../components/layout/nav";
import { AlertList, NotificationPanel, alertTone } from "../../components/layout/NotificationPanel";
import { Sidebar } from "../../components/layout/Sidebar";
import { Topbar } from "../../components/layout/Topbar";
import { connectSocket, renderWithProviders } from "../../test/render";
import { mockApi, unreachable } from "../../test/mockApi";
import { at, makeAlert, makeConfig, makeDashboard, makeQuote } from "../../test/fixtures";
import type { Dashboard } from "../../types/api";

const serve = (d: Dashboard) => mockApi().on("GET", "/api/live/dashboard", () => d);
const saved = () => JSON.parse(localStorage.getItem("gt-settings") ?? "{}");

describe("navigation list", () => {
  it("has the eleven pages once each, and exactly four flagged for the phone bottom bar", () => {
    expect(NAV).toHaveLength(11);
    expect(new Set(NAV.map((n) => n.to)).size).toBe(11);
    expect(NAV.filter((n) => n.mobile).map((n) => n.short)).toEqual(["Overview", "Live", "Signals", "Backtest"]);
  });
});

describe("Sidebar (desktop and tablet)", () => {
  it("links to every page and highlights the current one", () => {
    renderWithProviders(<Sidebar />, { route: "/live" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    for (const n of NAV) expect(within(nav).getByRole("link", { name: n.label })).toHaveAttribute("href", n.to);
    expect(within(nav).getByRole("link", { name: "Live Trading" }).className).toContain("bg-blue-600");
    expect(within(nav).getByRole("link", { name: "Overview" }).className).not.toContain("bg-blue-600");
  });

  it("only highlights Overview on exactly '/', not on every page", () => {
    renderWithProviders(<Sidebar />, { route: "/" });
    expect(screen.getByRole("link", { name: "Overview" }).className).toContain("bg-blue-600");
    expect(screen.getByRole("link", { name: "Options Analysis" }).className).not.toContain("bg-blue-600");
  });

  it("is hidden below the tablet breakpoint (the phone uses MobileNav instead)", () => {
    renderWithProviders(<Sidebar />);
    const aside = screen.getByRole("complementary");
    expect(aside.className).toMatch(/\bhidden\b/);
    expect(aside.className).toContain("md:flex");
  });

  it("shows the live NIFTY quote and strategy signal from the shared feed", async () => {
    renderWithProviders(<Sidebar />, { api: serve(makeDashboard()) });
    expect(await screen.findByText("25,000.50")).toBeInTheDocument();
    expect(screen.getByText("NIFTY 50")).toBeInTheDocument();
    expect(screen.getByText(/\+120\.25 \(0\.48%\)/)).toBeInTheDocument();
    expect(screen.getByText("HOLD")).toBeInTheDocument();
  });

  it("collapses to icons and remembers it", async () => {
    const { user } = renderWithProviders(<Sidebar />, { api: serve(makeDashboard()) });
    await screen.findByText("25,000.50");
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    expect(screen.queryByText("25,000.50")).toBeNull();                         // the quote widget goes with the labels
    expect(saved().sidebarCollapsed).toBe(true);
    expect(screen.getByRole("complementary").className).toContain("w-[68px]");
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(saved().sidebarCollapsed).toBe(false);
  });
});

describe("MobileNav (phone)", () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    return <MobileNav open={open} setOpen={setOpen} />;
  }

  it("is a bottom bar with the four main pages plus More, hidden from tablet width up", () => {
    renderWithProviders(<Harness />, { bare: true });
    const bar = screen.getByRole("navigation", { name: "Main" });
    expect(bar.className).toContain("md:hidden");
    expect(within(bar).getAllByRole("link").map((a) => a.textContent)).toEqual(["Overview", "Live", "Signals", "Backtest"]);
    expect(within(bar).getByRole("button", { name: "All pages" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the More drawer lists every page and closes from its X button and backdrop", async () => {
    const { user, container } = renderWithProviders(<Harness />, { bare: true });
    await user.click(screen.getByRole("button", { name: "All pages" }));
    const dlg = screen.getByRole("dialog", { name: "Navigation" });
    expect(within(dlg).getAllByRole("link").map((a) => a.textContent)).toEqual(NAV.map((n) => n.label));
    await user.click(within(dlg).getByRole("button", { name: "Close menu" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: "All pages" }));
    await user.click(container.querySelector(".bg-slate-950\\/50")!);              // the dimmed backdrop
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("choosing a page navigates there and closes the drawer", async () => {
    const { user } = renderWithProviders(<Harness />, { bare: true });
    await user.click(screen.getByRole("button", { name: "All pages" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("link", { name: "Market Data" }));
    expect(screen.getByTestId("path")).toHaveTextContent("/data");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("marks the current page in the bottom bar", () => {
    renderWithProviders(<Harness />, { bare: true, route: "/signals" });
    expect(screen.getByRole("link", { name: "Signals" }).className).toContain("text-blue-600");
    expect(screen.getByRole("link", { name: "Live" }).className).not.toContain("text-blue-600");
  });
});

describe("Topbar: connection, WebSocket/REST and engine indicators", () => {
  const renderBar = (api = mockApi(), onBell = vi.fn()) => ({ onBell, ...renderWithProviders(<Topbar title="Overview" onBell={onBell} />, { api }) });

  it("says Connecting before the first answer, then Groww connected with the REST fallback labelled Polling", async () => {
    renderBar();
    expect(screen.getByText("Connecting")).toBeInTheDocument();
    expect(await screen.findByText("Groww connected")).toBeInTheDocument();
    // Two pills: the desktop one (hidden below 640px) and a compact phone one (hidden from 640px up).
    const pills = screen.getAllByText("Polling");
    expect(pills).toHaveLength(2);
    for (const p of pills) expect(p.closest("span[title]")).toHaveAttribute("title", expect.stringMatching(/WebSocket unavailable/));
    expect(pills.map((p) => p.closest("span[title]")!.className).sort()).toEqual(["hidden sm:inline-flex", "sm:hidden"]);
  });

  it("switches to Live push when updates arrive over the WebSocket", async () => {
    renderBar();
    const s = await connectSocket();
    act(() => s.fire("dashboard", { seq: 1, room: "r", server_time: at("10:15"), data: makeDashboard(), error: null }));
    expect(await screen.findByText("Live push")).toBeInTheDocument();
    expect(screen.queryByText("Polling")).toBeNull();
  });

  it("shows Backend offline (and no transport pill) when the API is unreachable", async () => {
    const api = mockApi().on("GET", "/api/live/dashboard", () => unreachable());
    renderBar(api);
    expect(await screen.findByText("Backend offline")).toBeInTheDocument();
    expect(screen.queryByText("Polling")).toBeNull();
    expect(screen.queryByText("Live push")).toBeNull();
  });

  it("flags a Groww feed error and a delayed quote", async () => {
    const { unmount } = renderBar(serve(makeDashboard({ feed: { error: "token expired" } })));
    expect(await screen.findByText("Groww error")).toBeInTheDocument();
    unmount();
    renderBar(serve(makeDashboard({ feed: { quote: makeQuote({ state: "delayed" }) } })));
    expect(await screen.findByText("Groww delayed")).toBeInTheDocument();
  });

  it("shows the market status and the engine state with its mode", async () => {
    const d = makeDashboard({ state: "running", config: makeConfig({ trade_mode: "replay" }), market: { state: "open", label: "Market open" } });
    renderBar(serve(d));
    expect(await screen.findByText("Market open")).toBeInTheDocument();
    expect(screen.getByText("Running · REPLAY")).toBeInTheDocument();
  });

  it("says Engine off when stopped, and ERROR when the engine failed", async () => {
    const { unmount } = renderBar(serve(makeDashboard()));
    expect(await screen.findByText("Engine off")).toBeInTheDocument();
    unmount();
    renderBar(serve(makeDashboard({ state: "error", config: makeConfig() })));
    expect(await screen.findByText("ERROR · PAPER")).toBeInTheDocument();
  });

  it("shows the unread count on the bell and calls onBell when it is pressed", async () => {
    const api = serve(makeDashboard({ alerts: [makeAlert(3), makeAlert(2)] }));
    const { user, onBell } = renderBar(api);
    const bell = await screen.findByRole("button", { name: "Notifications, 2 new" });
    expect(within(bell).getByText("2")).toBeInTheDocument();
    await user.click(bell);
    expect(onBell).toHaveBeenCalledTimes(1);
  });

  it("caps the badge at 9+", async () => {
    const alerts = Array.from({ length: 12 }, (_, i) => makeAlert(20 - i));
    renderBar(serve(makeDashboard({ alerts })));
    expect(await screen.findByRole("button", { name: "Notifications, 12 new" })).toHaveTextContent("9+");
  });

  it("toggles alert sound and saves it", async () => {
    const { user } = renderBar();
    await screen.findByText("Groww connected");
    expect(saved().sound ?? true).toBe(true);
    await user.click(screen.getByRole("button", { name: "Toggle alert sound" }));
    expect(saved().sound).toBe(false);
    expect(screen.getByRole("button", { name: "Toggle alert sound" })).toHaveAttribute("title", "Alert sound off");
  });

  it("toggles the dark theme on the page and saves it", async () => {
    const { user } = renderBar();
    await screen.findByText("Groww connected");
    expect(document.documentElement).toHaveClass("dark");
    await user.click(screen.getByRole("button", { name: "Toggle theme" }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem("gt-theme")).toBe("light");
  });
});

describe("NotificationPanel and AlertList", () => {
  it("lists signals with their action, contract and time", async () => {
    const api = serve(makeDashboard({ alerts: [makeAlert(2, { action: "BUY PE", opt_type: "PE", direction: "Bearish", strike: 24900, signal_ts: at("10:20") }), makeAlert(1)] }));
    renderWithProviders(<NotificationPanel onClose={() => {}} />, { api });
    expect(await screen.findByText("BUY PE")).toBeInTheDocument();
    expect(screen.getByText(/NIFTY 24900 PE/)).toBeInTheDocument();
    expect(screen.getByText(/10:20/)).toBeInTheDocument();
    expect(screen.getByText("BUY CE")).toBeInTheDocument();
  });

  it("says so when there are no signals yet", async () => {
    renderWithProviders(<NotificationPanel onClose={() => {}} />);
    expect(await screen.findByText(/No signal notifications yet/)).toBeInTheDocument();
  });

  it("closes from the X button and from the backdrop", async () => {
    const onClose = vi.fn();
    const { user, container } = renderWithProviders(<NotificationPanel onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Close notifications" }));
    await user.click(container.querySelector(".bg-slate-950\\/40")!);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("colours entries by direction and exits as info", () => {
    expect(alertTone(makeAlert(1, { action: "BUY CE" }))).toBe("good");
    expect(alertTone(makeAlert(1, { action: "BUY PE", direction: "Bearish" }))).toBe("bad");
    expect(alertTone(makeAlert(1, { action: "SELL", direction: "Bullish" }))).toBe("info");
    expect(alertTone(makeAlert(1, { action: "HOLD" }))).toBe("neutral");
  });

  it("AlertList honours the limit and prefixes alerts from earlier days with their date", () => {
    const alerts = [makeAlert(3), makeAlert(2, { day: "2026-11-10" }), makeAlert(1)];
    renderWithProviders(<AlertList alerts={alerts} limit={2} />, { bare: true });
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText(/2026-11-10 · /)).toBeInTheDocument();
  });

  it("shows connection and engine events with their tone in the panel", async () => {
    const api = mockApi();
    api.on("GET", "/api/live/dashboard", () => makeDashboard({ state: "running" }));
    renderWithProviders(<><Topbar title="x" onBell={() => {}} /><NotificationPanel onClose={() => {}} /></>, { api });
    await screen.findByText("Groww connected");
    api.on("GET", "/api/live/dashboard", () => makeDashboard({ state: "stopped" }));
    // the Topbar has no refresh button: a settings-free way to refetch is the socket drop path
    const s = await connectSocket();
    act(() => s.drop());
    await waitFor(() => expect(screen.getByText(/Engine running → stopped/)).toBeInTheDocument());
    expect(screen.getByText("Connection & engine")).toBeInTheDocument();
  });
});

describe("AppLayout", () => {
  const layout = (route = "/live", api = mockApi()) => renderWithProviders(
    <Routes><Route element={<AppLayout />}><Route path="*" element={<div>page body</div>} /></Route></Routes>, { route, api });

  it("puts the page inside the sidebar + header shell with the current page's title", async () => {
    layout("/options");
    expect(screen.getByText("page body")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Options Analysis" })).toBeInTheDocument();
    await screen.findByText("Groww connected");
  });

  it("warns that values may be stale when the backend is offline", async () => {
    layout("/live", mockApi().on("GET", "/api/live/dashboard", () => unreachable()));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Backend unreachable.*Retrying automatically/);
  });

  it("opens the notification panel from the bell and clears the unread badge", async () => {
    const { user } = layout("/", serve(makeDashboard({ alerts: [makeAlert(4)] })));
    const bell = await screen.findByRole("button", { name: "Notifications, 1 new" });
    await user.click(bell);
    expect(screen.getByRole("dialog", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();       // badge gone
    await user.click(screen.getByRole("button", { name: "Close notifications" }));
    expect(screen.queryByRole("dialog", { name: "Notifications" })).toBeNull();
  });

  it("falls back to the product name for unknown paths", () => {
    layout("/nowhere");
    expect(screen.getByRole("heading", { level: 1, name: "Grow Trading" })).toBeInTheDocument();
  });
});

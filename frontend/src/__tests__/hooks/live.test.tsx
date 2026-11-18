import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useLive } from "../../context/LiveContext";
import { useSettings } from "../../context/SettingsContext";
import { renderWithProviders, connectSocket } from "../../test/render";
import { fail, mockApi, ok, unreachable } from "../../test/mockApi";
import { lastSocket } from "../../test/fakeSocket";
import { at, makeAlert, makeDashboard, makeQuote } from "../../test/fixtures";
import type { Dashboard } from "../../types/api";

/** Shows what the shared live poll currently believes, and exposes its actions. */
function Probe() {
  const l = useLive();
  return (
    <div>
      <span data-testid="conn">{l.connection}</span>
      <span data-testid="transport">{l.transport}</span>
      <span data-testid="price">{l.data?.feed.quote.price ?? "none"}</span>
      <span data-testid="state">{l.data?.state ?? "none"}</span>
      <span data-testid="err">{l.error ?? ""}</span>
      <span data-testid="unread">{l.unread}</span>
      <span data-testid="trades">{l.trades.length}</span>
      <ul aria-label="events">{l.events.map((e) => <li key={e.id}>{e.text}</li>)}</ul>
      <button onClick={l.refresh}>refresh</button>
      <button onClick={l.markRead}>read</button>
    </div>
  );
}

const dash = (price: number, o?: Parameters<typeof makeDashboard>[0]) => makeDashboard({ feed: { quote: makeQuote({ price }) }, ...o });
const push = (seq: number, data: Dashboard | null, room = "r1", error: string | null = null) => ({ seq, room, server_time: at("10:15"), data, error });

describe("live data: REST fallback", () => {
  it("polls /api/live/dashboard with the saved settings when the socket never connects", async () => {
    const api = mockApi();
    api.on("GET", "/api/live/dashboard", () => dash(25123.4));
    renderWithProviders(<Probe />, { api, settings: { timeframe: 15, riskPct: 2, capital: 50000 } });
    expect(await screen.findByTestId("price")).toHaveTextContent("25123.4");
    expect(screen.getByTestId("conn")).toHaveTextContent("online");
    expect(screen.getByTestId("transport")).toHaveTextContent("polling");
    const q = api.callsTo("GET", "/api/live/dashboard")[0].query;
    expect(Object.fromEntries(q)).toEqual({ tf: "15", mode: "paper", exec_mode: "ATM_BUY", risk_pct: "2", capital: "50000" });
  });

  it("goes offline with the error when the backend is unreachable, then recovers and says so", async () => {
    const api = mockApi();
    renderWithProviders(<Probe />, { api });
    await waitFor(() => expect(screen.getByTestId("conn")).toHaveTextContent("online"));

    api.on("GET", "/api/live/dashboard", () => unreachable());
    act(() => screen.getByText("refresh").click());
    await waitFor(() => expect(screen.getByTestId("conn")).toHaveTextContent("offline"));
    expect(screen.getByTestId("err")).toHaveTextContent(/Backend unreachable/);
    await waitFor(() => expect(screen.getByRole("list", { name: "events" })).toHaveTextContent(/Lost connection to the backend/));

    api.on("GET", "/api/live/dashboard", () => dash(25200));
    act(() => screen.getByText("refresh").click());
    await waitFor(() => expect(screen.getByTestId("conn")).toHaveTextContent("online"));
    expect(screen.getByTestId("err")).toBeEmptyDOMElement();
    await waitFor(() => expect(screen.getByRole("list", { name: "events" })).toHaveTextContent("Connection restored"));
  });

  it("reports an API error response without crashing", async () => {
    const api = mockApi();
    api.on("GET", "/api/live/dashboard", () => fail("Groww is down", 502, "RuntimeError"));
    renderWithProviders(<Probe />, { api });
    await waitFor(() => expect(screen.getByTestId("conn")).toHaveTextContent("offline"));
    expect(screen.getByTestId("err")).toHaveTextContent("Groww is down");
    expect(screen.getByTestId("price")).toHaveTextContent("none");
  });
});

describe("live data: WebSocket push", () => {
  it("subscribes with the current settings once connected and takes pushed dashboards", async () => {
    const api = mockApi();
    renderWithProviders(<Probe />, { api, settings: { timeframe: 5 } });
    const s = await connectSocket();
    expect(s.subscribes()).toHaveLength(1);
    expect(s.subscribes()[0].payload).toMatchObject({ tf: 5, mode: "paper", exec_mode: "ATM_BUY", risk_pct: 1 });

    act(() => s.fire("dashboard", push(1, dash(25300))));
    expect(screen.getByTestId("price")).toHaveTextContent("25300");
    expect(screen.getByTestId("transport")).toHaveTextContent("socket");
    expect(screen.getByTestId("conn")).toHaveTextContent("online");
  });

  it("does not poll REST while the socket is healthy", async () => {
    const api = mockApi();
    renderWithProviders(<Probe />, { api });
    const s = await connectSocket();
    await waitFor(() => expect(api.callsTo("GET", "/api/live/dashboard").length).toBeGreaterThan(0));
    act(() => s.fire("dashboard", push(1, dash(25300))));
    const before = api.callsTo("GET", "/api/live/dashboard").length;
    act(() => s.fire("heartbeat", push(2, null)));
    await new Promise((r) => setTimeout(r, 150));
    expect(api.callsTo("GET", "/api/live/dashboard")).toHaveLength(before);
  });

  it("drops duplicate and out-of-order events so late data never overwrites newer data", async () => {
    renderWithProviders(<Probe />, { api: mockApi() });
    const s = await connectSocket();
    act(() => s.fire("dashboard", push(5, dash(25500))));
    act(() => s.fire("dashboard", push(5, dash(1))));      // duplicate seq
    act(() => s.fire("dashboard", push(4, dash(2))));      // older
    expect(screen.getByTestId("price")).toHaveTextContent("25500");
    act(() => s.fire("dashboard", push(6, dash(25600))));
    expect(screen.getByTestId("price")).toHaveTextContent("25600");
  });

  it("restarts the sequence when the server moves the subscription to another room", async () => {
    renderWithProviders(<Probe />, { api: mockApi() });
    const s = await connectSocket();
    act(() => s.fire("dashboard", push(9, dash(25700), "room-a")));
    act(() => s.fire("dashboard", push(1, dash(25800), "room-b")));
    expect(screen.getByTestId("price")).toHaveTextContent("25800");
  });

  it("a heartbeat keeps the connection online and surfaces a server-side error", async () => {
    renderWithProviders(<Probe />, { api: mockApi() });
    const s = await connectSocket();
    act(() => s.fire("heartbeat", push(1, null, "r1", "Groww quote timeout")));
    expect(screen.getByTestId("conn")).toHaveTextContent("online");
    expect(screen.getByTestId("transport")).toHaveTextContent("socket");
    expect(screen.getByTestId("err")).toHaveTextContent("Groww quote timeout");
  });

  it("falls back to REST at once when the socket drops, and says so in notifications", async () => {
    const api = mockApi();
    renderWithProviders(<Probe />, { api });
    const s = await connectSocket();
    act(() => s.fire("dashboard", push(1, dash(25300))));
    await waitFor(() => expect(screen.getByTestId("transport")).toHaveTextContent("socket"));
    const before = api.callsTo("GET", "/api/live/dashboard").length;

    api.on("GET", "/api/live/dashboard", () => dash(25999));
    act(() => s.drop());
    await waitFor(() => expect(screen.getByTestId("price")).toHaveTextContent("25999"));
    expect(api.callsTo("GET", "/api/live/dashboard").length).toBeGreaterThan(before);
    expect(screen.getByTestId("transport")).toHaveTextContent("polling");
    expect(screen.getByRole("list", { name: "events" })).toHaveTextContent(/Live push interrupted/);

    act(() => { s.connect(); s.fire("dashboard", push(1, dash(26000))); });
    await waitFor(() => expect(screen.getByTestId("transport")).toHaveTextContent("socket"));
    expect(screen.getByRole("list", { name: "events" })).toHaveTextContent(/WebSocket\) reconnected/);
  });

  it("treats a silent socket as stale and polls REST again", async () => {
    const api = mockApi();
    renderWithProviders(<Probe />, { api });
    const s = await connectSocket();
    act(() => { s.fire("hello", { heartbeat_stale_sec: 0.2 }); s.fire("dashboard", push(1, dash(25300))); });
    await waitFor(() => expect(screen.getByTestId("transport")).toHaveTextContent("socket"));
    const before = api.callsTo("GET", "/api/live/dashboard").length;
    // The fallback checks every 2 s; the socket has been silent for longer than 0.2 s by then.
    await waitFor(() => expect(api.callsTo("GET", "/api/live/dashboard").length).toBeGreaterThan(before), { timeout: 5000 });
    await waitFor(() => expect(screen.getByTestId("transport")).toHaveTextContent("polling"));
  }, 10000);

  it("resubscribes with the new settings when the timeframe changes", async () => {
    function Change() { const { update } = useSettings(); return <button onClick={() => update({ timeframe: 15 })}>tf15</button>; }
    renderWithProviders(<><Probe /><Change /></>, { api: mockApi() });
    const s = await connectSocket();
    expect(s.subscribes()).toHaveLength(1);
    act(() => screen.getByText("tf15").click());
    await waitFor(() => expect(s.subscribes()).toHaveLength(2));
    expect(s.subscribes()[1].payload).toMatchObject({ tf: 15 });
  });
});

describe("live data: notifications and engine events", () => {
  it("counts unread alerts and clears them once the panel is opened (and remembers it)", async () => {
    const api = mockApi();
    api.on("GET", "/api/live/dashboard", () => dash(25000, { alerts: [makeAlert(5), makeAlert(4)] }));
    renderWithProviders(<Probe />, { api });
    await waitFor(() => expect(screen.getByTestId("unread")).toHaveTextContent("2"));
    act(() => screen.getByText("read").click());
    expect(screen.getByTestId("unread")).toHaveTextContent("0");
    expect(localStorage.getItem("gt-alerts-seen")).toBe("5");

    api.on("GET", "/api/live/dashboard", () => dash(25000, { alerts: [makeAlert(6), makeAlert(5), makeAlert(4)] }));
    act(() => screen.getByText("refresh").click());
    await waitFor(() => expect(screen.getByTestId("unread")).toHaveTextContent("1"));
  });

  it("an engine state change becomes a notification naming the halt reason", async () => {
    const api = mockApi();
    api.on("GET", "/api/live/dashboard", () => dash(25000, { state: "running" }));
    renderWithProviders(<Probe />, { api });
    await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("running"));

    api.on("GET", "/api/live/dashboard", () => dash(25000, { state: "halted", halt_reason: "daily loss limit" }));
    act(() => screen.getByText("refresh").click());
    await waitFor(() => expect(screen.getByRole("list", { name: "events" })).toHaveTextContent("Engine running → halted: daily loss limit"));
  });

  it("refetches today's trades when the engine's counters change", async () => {
    const api = mockApi();
    api.on("GET", "/api/live/dashboard", () => dash(25000, { trades_today: 0 }));
    renderWithProviders(<Probe />, { api });
    await waitFor(() => expect(api.callsTo("GET", "/api/live/trades")).toHaveLength(1));
    expect(lastSocket()).toBeDefined();

    api.on("GET", "/api/live/dashboard", () => dash(25000, { trades_today: 1, realised_today: 500 }));
    api.on("GET", "/api/live/trades", () => [{ id: 1 }]);
    act(() => screen.getByText("refresh").click());
    await waitFor(() => expect(screen.getByTestId("trades")).toHaveTextContent("1"));
    expect(api.callsTo("GET", "/api/live/trades")).toHaveLength(2);
  });
});

describe("useLive", () => {
  it("refuses to be used outside its provider", () => {
    // Rendered without LiveProvider on purpose.
    expect(() => renderWithProviders(<Probe />, { bare: true })).toThrow(/useLive must be used inside LiveProvider/);
  });

  it("ok() helper wraps envelope fields", () => {
    expect(ok({ a: 1 }, { job: "j" })).toMatchObject({ status: 200, body: { ok: true, data: { a: 1 }, job: "j" } });
  });
});

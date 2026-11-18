import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";
import { resetSockets } from "./fakeSocket";
import { resetCharts } from "./fakeCharts";

// No real sockets and no real canvas: both libraries are replaced by recorders (see fakeSocket / fakeCharts).
vi.mock("socket.io-client", async () => {
  const { createFakeSocket } = await import("./fakeSocket");
  return { io: () => createFakeSocket() };
});
vi.mock("lightweight-charts", async () => {
  const { fakeCreateChart } = await import("./fakeCharts");
  return { createChart: fakeCreateChart, CrosshairMode: { Normal: 0, Magnet: 1 }, LineStyle: { Solid: 0, Dotted: 1, Dashed: 2 } };
});

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  document.documentElement.className = "";
  document.title = "Grow Trading";
  resetSockets();
  resetCharts();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

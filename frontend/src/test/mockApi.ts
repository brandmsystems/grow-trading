/**
 * A typed fake backend: stubs `fetch` and routes by method + path, so the real services/api.ts,
 * hooks and pages run unchanged against canned (or per-test) responses. Nothing touches the network.
 */
import { vi } from "vitest";
import {
  makeBars, makeBtResult, makeScalpConfig, makeAccount, makeBtMeta, makeDashboard, makeDataOverview, makeJob, makeLotSizes, makeOptionChain, makeOptionsCoverage, makeResearch, makeRisk,
  makeScalpRun, makeSignalAnalysis, makeBiasAccuracy, makeBiasAnalysis, makeBiasConfig, makeBiasSummary, makeBiasTradeDetail, makePmFeed, makePmHistory, makePmReport,
} from "./fixtures";

export interface ApiRequest { method: string; path: string; query: URLSearchParams; body: Record<string, unknown> | undefined }
/** A value, or a function of the request (may return a Promise, e.g. one that never settles to test loading states). */
export type Reply = unknown | ((req: ApiRequest) => unknown);
interface Route { method: string; match: string | RegExp; reply: Reply }

interface Wire { __wire: true; status: number; body?: unknown; network?: boolean }
const wire = (status: number, body: unknown): Wire => ({ __wire: true, status, body });
const isWire = (v: unknown): v is Wire => !!v && typeof v === "object" && (v as Wire).__wire === true;

/** `{ok: true, data, ...extra}`: `extra` carries envelope fields such as `job` or `hash`. */
export const ok = (data?: unknown, extra: Record<string, unknown> = {}) => wire(200, { ok: true, ...(data !== undefined ? { data } : {}), ...extra });
/** `{ok: false, error, kind}` with an HTTP status, the way api_error() answers. */
export const fail = (error: string, status = 400, kind = "ValueError") => wire(status, { ok: false, error, kind });
/** fetch() itself rejects: the backend is unreachable. */
export const unreachable = (): Wire => ({ __wire: true, status: 0, network: true });

export function defaultRoutes(): Route[] {
  const r = (method: string, match: string | RegExp, reply: Reply): Route => ({ method, match, reply });
  return [
    r("GET", "/api/live/dashboard", () => makeDashboard()),
    r("GET", "/api/live/trades", () => []),
    r("POST", "/api/live/start", () => makeDashboard()),
    r("POST", "/api/live/stop", () => makeDashboard()),
    r("POST", "/api/live/squareoff", () => makeDashboard()),
    r("POST", "/api/live/confirm", () => makeDashboard()),
    r("POST", "/api/live/reject", () => makeDashboard()),
    r("GET", "/api/paper/account", () => makeAccount()),
    r("POST", "/api/paper/account", () => ok(undefined)),
    r("POST", "/api/paper/position/stop", () => ({ old_stop: 90, new_stop: 95, old_max_loss: 4500, new_max_loss: 4000 })),
    r("POST", "/api/paper/risk-calc", () => makeRisk()),
    r("GET", "/api/paper/stop-changes", () => []),
    r("GET", "/api/options/chain", () => makeOptionChain()),
    r("GET", "/api/bt/meta", () => makeBtMeta()),
    r("POST", "/api/bt/run", () => ok(undefined, { hash: "hash123" })),
    r("GET", /^\/api\/bt\/result\//, () => makeBtResult()),
    r("GET", /^\/api\/bt\/chart\//, () => ({ trade_id: "t1", spot: makeBars(12, 9 * 60 + 15, 15, "2026-10-05"), option: makeBars(12, 9 * 60 + 15, 15, "2026-10-05") })),
    r("POST", "/api/research/run", () => ok(undefined, { job: "job-1" })),
    r("POST", "/api/signals/build", () => ok(undefined, { job: "job-1" })),
    r("POST", "/api/scalping/run", () => ok(undefined, { job: "job-1" })),
    r("GET", "/api/scalping/config", (req: ApiRequest) => ({ ...makeScalpConfig(req.query.get("key") ?? "c1"), trade_list: [] })),
    r("POST", "/api/data/download", () => ok(undefined, { job: "job-1" })),
    r("POST", "/api/data/options/download", () => ok(undefined, { job: "job-1" })),
    r("POST", "/api/data/stop", () => ok(undefined)),
    r("GET", "/api/status", () => ok(undefined, { keys: true, message: "keys.txt found" })),
    r("POST", "/api/login", () => ok(undefined)),
    r("GET", "/api/data/overview", () => makeDataOverview()),
    r("GET", "/api/data/options", () => makeOptionsCoverage()),
    r("GET", "/api/data/lot-sizes", () => makeLotSizes()),
    r("GET", "/api/data/candles", () => ({ bars: [{ t: "2026-11-17T09:15:00", o: 100, h: 110, l: 95, c: 105 }, { t: "2026-11-17T09:20:00", o: 105, h: 112, l: 101, c: 108 }] })),
    r("GET", "/api/research", () => ok(makeResearch())),
    r("GET", "/api/signals", () => ok(makeSignalAnalysis())),
    r("GET", "/api/scalping/paper/trades", () => []),
    r("GET", "/api/scalping", () => ok(makeScalpRun())),
    r("GET", "/api/bias/config", () => makeBiasConfig()),
    r("GET", "/api/bias/status", () => ({ running: false })),
    r("GET", "/api/bias/analysis", () => ({ as_of_day: "2026-11-18", live: true, analysis: makeBiasAnalysis(), futures: true, error: null, recent: [] })),
    r("GET", "/api/bias/predictions", () => []),
    r("GET", "/api/bias/trades", () => []),
    r("GET", "/api/bias/summary", () => makeBiasSummary({ trades: 0, wins: 0, losses: 0, win_rate: null, net: 0, gross: 0, open: 0 })),
    r("GET", "/api/bias/accuracy", () => makeBiasAccuracy()),
    r("GET", "/api/bias/history-accuracy", () => makeBiasAccuracy()),
    r("GET", /^\/api\/bias\/trade\//, () => makeBiasTradeDetail()),
    r("POST", "/api/bias/start", () => ({})),
    r("POST", "/api/bias/settings", () => ({ changed: [] })),
    r("POST", "/api/bias/pause", () => ({ paused: true })),
    r("POST", "/api/bias/resume", () => ({ paused: false })),
    r("POST", "/api/paper/position/target", () => ({ old_target: 140, new_target: 150 })),
    r("GET", "/api/premarket/report", () => ({ day: "2026-11-19", report: makePmReport(), now: "2026-11-19T08:45:00", thresholds: {}, unavailable: {} })),
    r("GET", "/api/premarket/news", () => makePmFeed()),
    r("GET", "/api/premarket/history", () => makePmHistory()),
    r("POST", "/api/premarket/refresh", () => ({ report: makePmReport() })),
    r("POST", "/api/premarket/input", () => ({ report: makePmReport() })),
    r("GET", /^\/api\/jobs\//, () => makeJob()),
  ];
}

export interface MockApi {
  /** Every request made so far, in order. */
  calls: ApiRequest[];
  /** Requests with no matching route (answered 404): tests can assert this stays empty. */
  unmatched: ApiRequest[];
  /** Add or replace a route (later calls win). The reply is a value, or a function of the request. */
  on(method: string, match: string | RegExp, reply: (req: ApiRequest) => unknown): MockApi;
  on(method: string, match: string | RegExp, reply: unknown): MockApi;
  callsTo(method: string, path: string | RegExp): ApiRequest[];
}

const matches = (m: string | RegExp, path: string) => (typeof m === "string" ? path === m : m.test(path));

export function mockApi(overrides: { method: string; match: string | RegExp; reply: Reply }[] = []): MockApi {
  const routes: Route[] = [...overrides, ...defaultRoutes()];
  const api: MockApi = {
    calls: [], unmatched: [],
    on(method: string, match: string | RegExp, reply: unknown) { routes.unshift({ method, match, reply }); return api; },
    callsTo: (method, path) => api.calls.filter((c) => c.method === method && matches(path, c.path)),
  };
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const req: ApiRequest = {
      method: (init?.method ?? "GET").toUpperCase(), path: url.pathname, query: url.searchParams,
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    api.calls.push(req);
    const route = routes.find((r) => r.method === req.method && matches(r.match, req.path));
    if (!route) {
      api.unmatched.push(req);
      return { status: 404, json: async () => ({ ok: false, error: `No mock for ${req.method} ${req.path}` }) } as Response;
    }
    const out = await (typeof route.reply === "function" ? (route.reply as (r: ApiRequest) => unknown)(req) : route.reply);
    const w = isWire(out) ? out : wire(200, { ok: true, data: out });
    if (w.network) throw new TypeError("Failed to fetch");
    return { status: w.status, json: async () => w.body } as Response;
  }));
  return api;
}

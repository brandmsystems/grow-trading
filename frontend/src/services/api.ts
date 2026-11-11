// Typed client for the Flask API. Every page goes through these functions (no direct fetch elsewhere).
import type {
  ApiErr, BtChart, BtMeta, BtParams, BtResult, Dashboard, DataOverview, EngineConfig, Envelope, Job,
  LiveTrade, Research, SignalAnalysis,
} from "../types/api";

export class ApiError extends Error {
  kind?: string;
  status: number;
  constructor(message: string, status: number, kind?: string) {
    super(message);
    this.status = status;
    this.kind = kind;
  }
}

/** Returns the whole response envelope ({ok, data, job, hash, ...}); throws ApiError on failure. */
export async function request<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<Envelope<T>> {
  const opts: RequestInit = { ...init };
  if (init?.json !== undefined) {
    opts.method = opts.method ?? "POST";
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new ApiError("Backend unreachable. Is the server running (python start.py)?", 0, "network");
  }
  const body = (await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))) as Envelope<T> | ApiErr;
  if (!body.ok) throw new ApiError(body.error || `HTTP ${res.status}`, res.status, body.kind);
  return body;
}

/** Returns just `data`. */
export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  return (await request<T>(path, init)).data as T;
}

const qs = (o: Record<string, string | number | boolean | null | undefined>) =>
  new URLSearchParams(Object.entries(o).filter(([, v]) => v != null && v !== "").map(([k, v]) => [k, String(v)])).toString();

// ------------------------------------------------------------------ live
export interface DashboardQuery { tf: number; mode: string; exec_mode: string; capital?: number | null; risk_pct: number }

export const getDashboard = (q: DashboardQuery) =>
  api<Dashboard>(`/api/live/dashboard?${qs({ tf: q.tf, mode: q.mode, exec_mode: q.exec_mode, risk_pct: q.risk_pct, capital: q.capital })}`);
export const getLiveTrades = (mode: string, day: string) => api<LiveTrade[]>(`/api/live/trades?${qs({ mode, day })}`);
export const startEngine = (config: Partial<EngineConfig>, confirm = "", replay_day?: string, replay_speed = 120) =>
  api<Dashboard>("/api/live/start", { json: { config, confirm, replay_day, replay_speed } });
export const stopEngine = () => api<Dashboard>("/api/live/stop", { json: {} });
export const squareOff = () => api<Dashboard>("/api/live/squareoff", { json: {} });
export const confirmOrder = (id: string) => api<Dashboard>("/api/live/confirm", { json: { id } });
export const rejectOrder = (id: string) => api<Dashboard>("/api/live/reject", { json: { id } });
export const getBrokerPositions = () => api<unknown>("/api/live/broker");

// ------------------------------------------------------------------ jobs
export const getJob = (id: string) => api<Job>(`/api/jobs/${encodeURIComponent(id)}`);

// ------------------------------------------------------------------ backtest
export const getMeta = () => api<BtMeta>("/api/bt/meta");
/** Returns a hash (cached run) or a job id to poll. */
export const runBacktest = (p: BtParams & { force?: boolean }) => request<never>("/api/bt/run", { json: p });
export const downloadForBacktest = (p: BtParams) => request<never>("/api/bt/data", { json: p });
export const getBtResult = (hash: string) => api<BtResult>(`/api/bt/result/${hash}`);
export const getBtChart = (hash: string, tradeId: string) => api<BtChart>(`/api/bt/chart/${hash}/${encodeURIComponent(tradeId)}`);

// ------------------------------------------------------------------ research & signals
export const getResearch = (entry_start: string, cutoff: string) =>
  request<Research>(`/api/research?${qs({ entry_start, cutoff })}`);
export const runResearch = (entry_start: string, cutoff: string) => request<never>("/api/research/run", { json: { entry_start, cutoff } });
export const getSignalAnalysis = (strategy: string, tf: number) =>
  request<SignalAnalysis | null>(`/api/signals?${qs({ strategy, tf })}`);
export const buildSignalAnalysis = (strategy: string, tf: number) => request<never>("/api/signals/build", { json: { strategy, tf } });

// ------------------------------------------------------------------ market data
export const getDataOverview = () => api<DataOverview>("/api/data/overview");
export const startDownload = (from: string, to: string) => request<never>("/api/data/download", { json: { from, to } });
export const stopDownload = () => request<never>("/api/data/stop", { json: {} });
export const getCandles = (from: string, to: string, tf: number) =>
  api<{ bars: { t: string; o: number; h: number; l: number; c: number }[] }>(`/api/data/candles?${qs({ from, to, tf })}`);

// ------------------------------------------------------------------ account
export const getCredentialStatus = async () => {
  const r = (await request<never>("/api/status")) as unknown as { keys: boolean; message: string };
  return r;
};
export const getProfile = () => api<Record<string, unknown>>("/api/profile");
export const getFunds = () => api<Record<string, unknown>>("/api/funds");
export const relogin = () => request<never>("/api/login", { json: {} });

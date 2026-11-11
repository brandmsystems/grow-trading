import type { ApiErr, ApiOk, Dashboard, EngineConfig } from "../types/api";

export class ApiError extends Error {
  kind?: string;
  status: number;
  constructor(message: string, status: number, kind?: string) {
    super(message);
    this.status = status;
    this.kind = kind;
  }
}

/** Calls the Flask JSON API. Throws ApiError with the server's message on failure. */
export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
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
  const body = (await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }))) as ApiOk<T> | ApiErr;
  if (!body.ok) throw new ApiError(body.error || `HTTP ${res.status}`, res.status, body.kind);
  return body.data;
}

export interface DashboardQuery {
  tf: number; mode: string; exec_mode: string; capital?: number | null; risk_pct: number;
}

export const getDashboard = (q: DashboardQuery) => {
  const p = new URLSearchParams({ tf: String(q.tf), mode: q.mode, exec_mode: q.exec_mode, risk_pct: String(q.risk_pct) });
  if (q.capital) p.set("capital", String(q.capital));
  return api<Dashboard>(`/api/live/dashboard?${p}`);
};

export const startEngine = (config: Partial<EngineConfig>, confirm = "", replay_day?: string, replay_speed = 120) =>
  api<Dashboard>("/api/live/start", { json: { config, confirm, replay_day, replay_speed } });
export const stopEngine = () => api<Dashboard>("/api/live/stop", { json: {} });
export const squareOff = () => api<Dashboard>("/api/live/squareoff", { json: {} });
export const confirmOrder = (id: string) => api<Dashboard>("/api/live/confirm", { json: { id } });
export const rejectOrder = (id: string) => api<Dashboard>("/api/live/reject", { json: { id } });
export const getMeta = () => api<{ strategies: Record<string, string>; timeframes: number[] }>("/api/bt/meta");

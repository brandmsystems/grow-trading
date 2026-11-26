// Typed client for the Flask API. Every page goes through these functions (no direct fetch elsewhere).
import type {
  ApiErr, BiasAccuracy, BiasAnalysisResponse, BiasConfig, BiasPrediction, BiasSettings, BiasStatus, BiasSummary, BiasTrade,
  BiasTradeDetail, BtChart, DailyRange, BtMeta, BtParams, BtResult, Dashboard, DataOverview, EngineConfig, Envelope, Job,
  LiveTrade, LotSize, OptionChain, OptionsCoverage, PaperAccount, Research, RiskCalc, ScalpConfig, ScalpPaperTrade, ScalpRun,
  ScalpTrade, SignalAnalysis, StopChange, PosAnalysis, PosBacktest, PosChart, PosConfig, PosDecisionRow, PosPosition, PosSettings, PosState, PosStats, PmHistory, PmInput, PmNewsFeed, PmReport, PmReportResponse, TsCheck, TsConfig, TsState,
} from "../types/api";

export class ApiError extends Error {
  kind?: string;
  status: number;
  /** Field-level problems the server listed (a settings save that was refused). */
  errors?: { path: string; message: string }[];
  constructor(message: string, status: number, kind?: string, errors?: { path: string; message: string }[]) {
    super(message);
    this.status = status;
    this.kind = kind;
    this.errors = errors;
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
  if (!body.ok) throw new ApiError(body.error || `HTTP ${res.status}`, res.status, body.kind, (body as { errors?: { path: string; message: string }[] }).errors);
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
export const getPaperTrades = () => api<LiveTrade[]>("/api/live/trades?mode=paper");
export const getPaperAccount = () => api<PaperAccount>("/api/paper/account");
export const resetPaperAccount = (capital: number) => request<never>("/api/paper/account", { json: { capital, confirm: "RESET" } });
export const setPaperStop = (stop: number) => api<{ old_stop: number; new_stop: number; old_max_loss: number; new_max_loss: number }>("/api/paper/position/stop", { json: { stop } });
export const getOptionChain = (expiry?: string, width?: number) => api<OptionChain>(`/api/options/chain?${qs({ expiry, width })}`);
export const getStopChanges = (tradeId: number) => api<StopChange[]>(`/api/paper/stop-changes?${qs({ trade_id: tradeId })}`);
export const riskCalc = (body: Record<string, number | string | null | undefined>) => api<RiskCalc>("/api/paper/risk-calc", { json: body });
export const getLiveTrades = (mode: string, day: string) => api<LiveTrade[]>(`/api/live/trades?${qs({ mode, day })}`);
export const startEngine = (config: Partial<EngineConfig>, confirm = "", replay_day?: string, replay_speed = 120) =>
  api<Dashboard>("/api/live/start", { json: { config, confirm, replay_day, replay_speed } });
export const stopEngine = () => api<Dashboard>("/api/live/stop", { json: {} });
export const squareOff = () => api<Dashboard>("/api/live/squareoff", { json: {} });
export const confirmOrder = (id: string) => api<Dashboard>("/api/live/confirm", { json: { id } });
export const rejectOrder = (id: string) => api<Dashboard>("/api/live/reject", { json: { id } });

// ------------------------------------------------------------------ automated multi-timeframe paper trading
export const pauseBias = () => api<{ paused: boolean }>("/api/bias/pause", { json: {} });
export const resumeBias = () => api<{ paused: boolean }>("/api/bias/resume", { json: {} });
export const getBiasConfig = () => api<BiasConfig>("/api/bias/config");
export const getBiasStatus = () => api<BiasStatus>("/api/bias/status");
/** The latest candle's analysis; the confluence settings only matter while no engine runs (a running engine uses its own). */
export const getBiasAnalysis = (cf?: Partial<BiasSettings>) => api<BiasAnalysisResponse>(`/api/bias/analysis?${qs({
  entry_strategy: cf?.entry_strategy === "scored" ? "scored" : undefined, timeframe: cf?.entry_strategy === "scored" ? cf.timeframe : undefined,
  bias_confirm_tf: cf?.entry_strategy === "scored" ? cf.bias_confirm_tf : undefined, sc_min_score: cf?.sc_min_score, sc_adr_period: cf?.sc_adr_period,
  sc_adr_max_used: cf?.sc_adr_max_used, sc_fvg_min_atr: cf?.sc_fvg_min_atr, sc_fvg_max_age: cf?.sc_fvg_max_age, sc_ctx_tf: cf?.sc_ctx_tf,
  sc_stop_min_pct: cf?.sc_stop_min_pct, sc_stop_max_pct: cf?.sc_stop_max_pct,
  cf_factors: cf?.cf_factors?.join(","), cf_require: cf?.cf_require?.join(","), cf_min_score: cf?.cf_min_score, cf_adr_filter: cf?.cf_adr_filter,
  cf_adr_period: cf?.cf_adr_period, cf_adr_max_used: cf?.cf_adr_max_used, cf_fvg_min_atr: cf?.cf_fvg_min_atr, cf_fvg_max_age: cf?.cf_fvg_max_age, cf_htf: cf?.cf_htf })}`);
/** Paper (live clock) or replay (a finished day). There is no live mode for this engine. */
export const startBias = (config: Partial<BiasSettings>, trade_mode: "paper" | "replay" = "paper", replay_day?: string, replay_speed = 120) =>
  api<unknown>("/api/bias/start", { json: { config, trade_mode, replay_day, replay_speed } });
export const updateBiasSettings = (changes: Partial<BiasSettings>) => api<{ changed: string[] }>("/api/bias/settings", { json: changes });
export const setPaperTarget = (target: number) => api<{ old_target: number | null; new_target: number }>("/api/paper/position/target", { json: { target } });
export const getBiasPredictions = (day: string, mode: string, limit = 80, session?: number | null) =>
  api<BiasPrediction[]>(`/api/bias/predictions?${qs({ day, mode, limit, session })}`);
export const getBiasAccuracy = (mode: string) => api<BiasAccuracy>(`/api/bias/accuracy?${qs({ mode })}`);
export const getBiasHistoryAccuracy = (from?: string, to?: string, tf?: number, confirm?: number) =>
  api<BiasAccuracy>(`/api/bias/history-accuracy?${qs({ from, to, tf, confirm })}`);
export const getBiasTrades = (day: string, mode: string, session?: number | null) => api<BiasTrade[]>(`/api/bias/trades?${qs({ day, mode, session })}`);
export const getBiasSummary = (day: string, mode: string, session?: number | null) => api<BiasSummary>(`/api/bias/summary?${qs({ day, mode, session })}`);
export const getBiasTrade = (id: number) => api<BiasTradeDetail>(`/api/bias/trade/${id}`);

// ------------------------------------------------------------------ Trading Settings
export const getTradingSettings = () => api<TsState>("/api/trading-settings");
export const validateTradingSettings = (config: TsConfig) => api<TsCheck>("/api/trading-settings/validate", { json: { config } });
export const saveTradingSettings = (config: TsConfig, base_version: number) => api<TsState>("/api/trading-settings", { method: "PUT", json: { config, base_version } });
export const resetTradingSettings = () => api<TsState>("/api/trading-settings/reset", { json: {} });

// ------------------------------------------------------------------ jobs
export const getJob = (id: string) => api<Job>(`/api/jobs/${encodeURIComponent(id)}`);

// ------------------------------------------------------------------ backtest
export const getMeta = () => api<BtMeta>("/api/bt/meta");
/** Returns a hash (cached run) or a job id to poll. */
export const runBacktest = (p: BtParams & { force?: boolean }) => request<never>("/api/bt/run", { json: p });
export const getBtResult = (hash: string) => api<BtResult>(`/api/bt/result/${hash}`);
export const getBtChart = (hash: string, tradeId: string) => api<BtChart>(`/api/bt/chart/${hash}/${encodeURIComponent(tradeId)}`);

// ------------------------------------------------------------------ research & signals
export const getResearch = (entry_start: string, cutoff: string) =>
  request<Research>(`/api/research?${qs({ entry_start, cutoff })}`);
export const runResearch = (entry_start: string, cutoff: string) => request<never>("/api/research/run", { json: { entry_start, cutoff } });
export const getSignalAnalysis = (strategy: string, tf: number) =>
  request<SignalAnalysis | null>(`/api/signals?${qs({ strategy, tf })}`);
export const buildSignalAnalysis = (strategy: string, tf: number) => request<never>("/api/signals/build", { json: { strategy, tf } });

// ------------------------------------------------------------------ 5-minute scalping
export const getScalping = () => request<ScalpRun | null>("/api/scalping");
export const runScalping = () => request<never>("/api/scalping/run", { json: {} });
export const getScalpConfig = (key: string) => api<ScalpConfig & { trade_list: ScalpTrade[] }>(`/api/scalping/config?${qs({ key })}`);
export const startScalpPaper = (key: string, mode: "paper" | "replay", risk: Record<string, number>, replay_day?: string) =>
  api<Dashboard>("/api/scalping/paper/start", { json: { key, mode, risk, replay_day } });
export const getScalpPaperTrades = (key?: string) => api<ScalpPaperTrade[]>(`/api/scalping/paper/trades?${qs({ key })}`);

// ------------------------------------------------------------------ market data
export const getDataOverview = () => api<DataOverview>("/api/data/overview");
export const startDownload = (from: string, to: string) => request<never>("/api/data/download", { json: { from, to } });
export const stopDownload = () => request<never>("/api/data/stop", { json: {} });
export const getOptionsCoverage = () => api<OptionsCoverage>("/api/data/options");
export const startOptionsDownload = (from: string, to: string) => request<never>("/api/data/options/download", { json: { from, to } });
export const getLotSizes = () => api<LotSize[]>("/api/data/lot-sizes");
export const getDailyRange = (from?: string, to?: string) => api<DailyRange>(`/api/data/daily-range?${qs({ from, to })}`);
export const getCandles = (from: string, to: string, tf: number) =>
  api<{ bars: { t: string; o: number; h: number; l: number; c: number }[] }>(`/api/data/candles?${qs({ from, to, tf })}`);

// ------------------------------------------------------------------ account
export const getCredentialStatus = async () => {
  const r = (await request<never>("/api/status")) as unknown as { keys: boolean; message: string };
  return r;
};
export const relogin = () => request<never>("/api/login", { json: {} });

// ------------------------------------------------------------------ pre-market analysis (information only; never places an order)
export const getPremarket = (day?: string) => api<PmReportResponse>(`/api/premarket/report?${qs({ day })}`);
export const refreshPremarket = () => api<{ report: PmReport }>("/api/premarket/refresh", { json: {} });
export const addPremarketInput = (body: PmInput) => api<{ report: PmReport }>("/api/premarket/input", { json: body });
export const getPremarketNews = (refresh = false) => api<PmNewsFeed>(`/api/premarket/news?${qs({ refresh: refresh ? 1 : undefined })}`);
export const getPremarketHistory = () => api<PmHistory>("/api/premarket/history");

// ---------------------------------------------------------------- position trading (paper only)
export const getPositionAnalysis = (refresh = false) => api<PosAnalysis>(`/api/position/analysis${refresh ? "?refresh=1" : ""}`);
export const getPositionConfig = () => api<PosConfig>("/api/position/config");
export const savePositionSettings = (config: PosSettings) => api<{ version: number }>("/api/position/settings", { method: "PUT", json: { config } });
export const getPositionAccount = () => api<{ state: PosState; summary: { overall: PosStats; by_strategy: Record<string, PosStats> } }>("/api/position/account");
export const resetPositionAccount = (capital: number) => api<unknown>("/api/position/account/reset", { json: { capital } });
export const getPositions = () => api<PosPosition[]>("/api/position/positions");
export const openPosition = (direction: 1 | -1) => api<{ id: number; entry_price: number; lots: number; qty: number; max_loss: number; fill_basis: string }>("/api/position/open", { json: { direction } });
export const managePositions = () => api<{ id: number; reason?: string; note?: string }[]>("/api/position/manage", { json: {} });
export const getPositionDecisions = () => api<PosDecisionRow[]>("/api/position/decisions");
export const recordPositionDecision = () => api<{ recorded: boolean }>("/api/position/decide", { json: {} });
export const getPositionBacktest = () => api<PosBacktest>("/api/position/backtest");
export const getPositionChart = (tf: string) => api<PosChart>(`/api/position/chart?tf=${tf}`);

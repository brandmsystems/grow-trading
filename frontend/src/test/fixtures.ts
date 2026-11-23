/** Typed, realistic builders for API payloads. Every builder takes a partial override (deep-merged). */
import type {
  PmArticle, PmFactor, PmHistory, PmNewsFeed, PmReport,
  BiasAccuracy, BiasAnalysis, BiasConfig, BiasPrediction, Confluence, Scored, TsConfig, TsMeta, TsParam, TsState, TsSummary, BiasStatus, BiasSummary, BiasTrade, BiasTradeDetail,
  Alert, Bar, BtMeta, BtResult, BtTrade, Dashboard, DataOverview, EngineConfig, Feed, HistSignal, Job, LiveTrade, LotSize, OptionChain,
  OptionsCoverage, PaperAccount, Position, Quote, Recommendation, Research, ResearchCell, RiskCalc, ScalpConfig, ScalpRun, SignalAnalysis,
  TradingPlan, DailyRange, RangeDay, DayStatus,
} from "../types/api";

type DP<V> = unknown extends V ? V : V extends (infer U)[] ? U[] : V extends object ? DeepPartial<V> : V;
export type DeepPartial<T> = { [K in keyof T]?: DP<T[K]> };

export function merge<T>(base: T, patch?: DeepPartial<T>): T {
  if (!patch) return base;
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  for (const [k, v] of Object.entries(patch)) {
    const cur = out[k];
    out[k] = v && typeof v === "object" && !Array.isArray(v) && cur && typeof cur === "object" && !Array.isArray(cur)
      ? merge(cur, v as DeepPartial<typeof cur>) : v;
  }
  return out as T;
}

export const DAY = "2026-11-18";
export const at = (hhmm: string, day = DAY) => `${day}T${hhmm}:00`;

// ------------------------------------------------------------------ live
export const makeQuote = (o?: DeepPartial<Quote>): Quote => merge<Quote>({
  price: 25000.5, change: 120.25, change_pct: 0.48, open: 24900, high: 25100, low: 24850, prev_close: 24880.25,
  state: "live", as_of: at("10:15"), age_sec: 1, error: null, from_high: -99.5, from_low: 150.5, range_pct: 60,
}, o);

export const makeBars = (n = 6, start = 9 * 60 + 15, step = 5, day = DAY): Bar[] => Array.from({ length: n }, (_, i) => {
  const m = start + i * step, base = 24950 + i * 10;
  return {
    t: at(`${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`, day),
    o: base, h: base + 12, l: base - 8, c: base + 5, e9: base + 2, e21: base - 3, vwap: base, v: 1000 + i,
  };
});

export const makeRecommendation = (o?: DeepPartial<Recommendation>): Recommendation => merge<Recommendation>({
  verified: true, strike: 25000, opt_type: "CE", strike_rule: "ATM", expiry: "2026-11-24", symbol: "NIFTY26N2425000CE", lot_size: 75,
  premium: 120.5, entry: 121, entry_basis: "best offer", quote_as_of: at("10:15"), chain_ltp: 120.4, delta: 0.52, iv: 14.2, oi: 1200000,
  stop: 90, target: 180, nifty_stop: 24950, nifty_target: 25100,
  sizing: {
    lots: 2, lot_size: 75, qty: 150, limited_by: "risk", risk_budget: 1000, risk_per_lot: 480, cost_per_lot: 9000, lots_by_risk: 2, lots_by_cash: 5,
    capital: 100000, investment: 18075, max_risk: 960, target_profit: 8500, stop_loss: 90, charges_stop: 80,
    charges_detail: { total: 80, brokerage: 40, stt: 10, exchange: 5, sebi: 1, stamp: 2, gst: 8 },
  },
}, o);

export const makeFeed = (o?: DeepPartial<Feed>): Feed => merge<Feed>({
  now: at("10:15"), market: { state: "open", label: "Market open" }, quote: makeQuote(), timeframe: 5, entry_start: "09:30", cutoff: "14:30",
  bars_error: null, warnings: [], chart: { day: DAY, bars: makeBars(), forming: null },
  ema: { fast: 25010, slow: 24990, close: 25005, bar_close: at("10:10"), gap: 20 },
  crosses: [{ ts: at("09:50"), direction: 1, close: 25000 }],
  signal: { action: "HOLD", direction: null, since: null, nifty: 25000.5, reason: "No crossover in the entry window" },
  markers: [],
  premiums: {
    strike: 25000, expiry: "2026-11-24", basis: "ATM", days_to_expiry: 6, lot_size: 75, error: null,
    ce: { premium: 120.5, change: 5, change_pct: 4.3, volume: 100000, oi: 500000, iv: 14.2, delta: 0.52, state: "live", as_of: at("10:15") },
    pe: { premium: 98.25, change: -3, change_pct: -2.9, volume: 90000, oi: 450000, iv: 14.8, delta: -0.48, state: "live", as_of: at("10:15") },
  },
}, o);

export const makeAlert = (id: number, o?: Partial<Alert>): Alert => ({
  id, ts: at("10:00"), day: DAY, action: "BUY CE", mode: "signal", signal_ts: at("10:00"), direction: "Bullish", nifty: 25000,
  strike: 25000, opt_type: "CE", premium: 120.5, status: "signal", ...o,
});

export const makeConfig = (o?: Partial<EngineConfig>): EngineConfig => ({
  trade_mode: "paper", exec_mode: "ATM_BUY", timeframe: 5, entry_start: "09:30", cutoff: "14:30", lots: 1, roll_on_expiry_day: true,
  max_daily_loss: 5000, max_trades_per_day: 6, signal_mode: "cross", strategy: "ema_9_21", min_score: 50, order_confirmation: "manual",
  risk_pct: 1, daily_risk_pct: 3, max_open_positions: 1, max_lots: 10, min_balance: 0, stop_mode: "atr", stop_atr: 1, stop_pct: 30, stop_points: 20, ...o,
});

export const makePosition = (o?: Partial<Position>): Position => ({
  trading_symbol: "NIFTY26N2425000CE", side: "BUY", direction: "Bullish", qty: 150, strike: 25000, opt_type: "CE", expiry: "2026-11-24",
  entry_price: 120, entry_ts: at("10:05"), ltp: 128, mtm: 1200, exit_failures: 0, score: null, stop_ref: 24950, target_ref: 25100,
  stop_premium: 90, target_premium: 180, max_loss: 4500, max_loss_pct: 4.5, risk_amount: 1000, risk_reward: 2, nifty_stop: 24950, nifty_target: 25100,
  stop_method: "ATR x delta", ...o,
});

export const makeDashboard = (o?: DeepPartial<Dashboard>): Dashboard => merge<Dashboard>({
  state: "stopped", day: DAY, halt_reason: null, config: null, position: null, pending_order: null, trades_today: 0, realised_today: 0,
  live_max_lots: 2, confirm_phrase: "LIVE", replay_day: null, market: { state: "open", label: "Market open" }, alerts: [], feed: makeFeed(),
}, o);

/** A dashboard whose strategy says BUY CE with a verified contract. */
export const buyCeDashboard = (o?: DeepPartial<Dashboard>): Dashboard => merge<Dashboard>(makeDashboard({
  feed: makeFeed({ signal: { action: "BUY CE", direction: "Bullish", since: at("10:00"), nifty: 25000, reason: "EMA 9 crossed above EMA 21", rec: makeRecommendation() } }),
  alerts: [makeAlert(2)],
}), o);

export const makeRisk = (o?: Partial<RiskCalc>): RiskCalc => ({
  decision: "TRADE", reason: null, capital: 100000, risk_pct: 1, risk_amount: 1000, entry: 120, stop: 90, target: 180, lot_size: 75, stop_distance: 30,
  risk_per_lot: 2400, lots_by_risk: 2, lots_by_cash: 5, lots: 2, qty: 150, limited_by: "risk", investment: 18000, charges: 130, slippage: 20, max_loss: 4500,
  risk_reward: 2, checks: { risk_within_limit: true, balance_ok: true }, calculated_at: at("10:05"), ...o,
});

export const makeTrade = (id: number, o?: Partial<LiveTrade>): LiveTrade => ({
  id, trade_mode: "paper", day: DAY, exec_mode: "ATM_BUY", direction: "Bullish", side: "BUY", trading_symbol: "NIFTY26N2425000CE", strike: 25000,
  opt_type: "CE", expiry: "2026-11-24", qty: 150, signal_ts: at("10:00"), entry_ts: at("10:05"), entry_price: 120, exit_ts: at("10:40"),
  exit_price: 135, exit_reason: "target", gross: 2250, net: 2100, status: "CLOSED", slippage: 20, charges: { total: 130 },
  risk: makeRisk(), stop_premium: 90, target_premium: 180, ...o,
});

export const makeAccount = (o?: DeepPartial<PaperAccount>): PaperAccount => {
  const settings = { risk_pct: 1, daily_risk_pct: 3, max_daily_loss: 5000, max_trades_per_day: 6, max_open_positions: 1, max_lots: 10, min_balance: 0, stop_mode: "atr" as const, stop_atr: 1, stop_pct: 30, stop_points: 20 };
  return merge<PaperAccount>({
    account_id: 1, starting_capital: 100000, started_at: at("09:00", "2026-11-10"), balance: 102000, available: 90000, invested: 12000, realised_total: 2000,
    trades_total: 5, day: DAY, day_start_capital: 101000, realised_today: 1000, mtm: 200, pnl_today: 1200, daily_limit: 3000, remaining_risk: 1800,
    risk_used_pct: 40, open_risk: 500, consecutive_losses: 1, max_drawdown: 1500, max_drawdown_pct: 1.5, risk_pct: 1, risk_amount: 900,
    limit_reached: false, engine_running: false, presets: { conservative: 0.5, low: 1 }, settings, defaults: settings,
  }, o);
};

export const makePlan = (o?: DeepPartial<TradingPlan>): TradingPlan => merge<TradingPlan>({
  day: DAY, computed_at: at("10:10"), bar_close: at("10:10"), created_at: at("09:20"), updated_at: at("10:10"), prev_close: 24880.25, prev_close_candles: 375,
  open: 24900, high: 25100, low: 24850, trend: "uptrend", ema_direction: "bullish", vwap_position: "above VWAP", rsi: 61, volatility: "normal",
  bullish_level: 25050, bearish_level: 24850, opening_range: { high: 25050, low: 24850 },
  levels: [{ name: "Pivot R1", price: 25120, kind: "resistance", source: "pivot" }, { name: "Pivot S1", price: 24800, kind: "support", source: "pivot" }],
  preferred: "bullish", votes: { bull: 3, bear: 1 },
  scenarios: [
    { key: "bullish", title: "Bullish scenario", active: true, conditions: ["Close above 25050"] },
    { key: "bearish", title: "Bearish scenario", active: false, conditions: ["Close below 24850"] },
  ],
  entry_rule: "Enter on a confirmed crossover.", note: "Plan recalculates every closed bar.", changes: [{ ts: at("09:20"), reason: "plan created", preferred: "none" }],
}, o);

// ------------------------------------------------------------------ options
export const makeOptionChain = (o?: DeepPartial<OptionChain>): OptionChain => {
  const side = (ltp: number) => ({
    symbol: "X", ltp, volume: 120000, oi: 2500000, iv: 14.1, delta: 0.5, gamma: 0, theta: 0, vega: 0, prev_close: ltp - 2, change: 2,
    change_pct: 1.5, prev_oi: 2400000, oi_change: 100000, oi_change_pct: 4.1,
  });
  return merge<OptionChain>({
    expiry: "2026-11-24", expiries: ["2026-11-24", "2026-12-01"], days_to_expiry: 6, lot_size: 75,
    spot: { price: 25000.5, change: 120.25, change_pct: 0.48, prev_close: 24880.25, state: "live", as_of: at("10:15") }, underlying_ltp: 25000.5, atm: 25000,
    width: 10, quote_width: 5,
    rows: [24950, 25000, 25050].map((k) => ({ strike: k, atm: k === 25000, ce: side(120 - (k - 25000) / 4), pe: side(100 + (k - 25000) / 4) })),
    totals: { ce_oi: 7500000, pe_oi: 9000000, ce_volume: 360000, pe_volume: 360000, pcr: 1.2 }, chain_as_of: at("10:15"), chain_error: null,
    quotes_as_of: at("10:15"), quotes_error: null, market: "open",
  }, o);
};

// ------------------------------------------------------------------ backtest / research / signals
export const makeBtMeta = (o?: DeepPartial<BtMeta>): BtMeta => merge<BtMeta>({
  defaults: {
    dataset: "groww", strategy: "ema_9_21", expiry_rule: "nearest", start_date: "2026-10-01", end_date: "2026-11-17", timeframe: 15, entry_start: "09:30",
    cutoff: "14:30", roll_on_expiry_day: true, lot_size: 0, lots: 1, capital: 100000, costs: { slippage_pct: 0.005, brokerage_per_order: 20, stt_sell_pct: 0.001 },
  },
  timeframes: [1, 5, 15, 30], starts: ["09:30", "10:00"], cutoffs: ["14:30", "15:00"],
  modes: { ITM5_BUY: "ITM 5 buy", ATM_BUY: "ATM buy", ATM_SELL: "ATM sell" }, keys: true, datasets: { groww: { first: "2021-11-11", last: "2026-11-17", days: 1200 } },
  strategies: { ema_9_21: "EMA 9/21", ema_20_50: "EMA 20/50" }, expiry_rules: { nearest: "Nearest expiry", monthly: "Monthly" },
}, o);

export const makeBtTrade = (id: string, o?: Partial<BtTrade>): BtTrade => ({
  id, mode: "ATM_BUY", day: "2026-10-05", entry_ts: at("10:00", "2026-10-05"), exit_ts: at("11:00", "2026-10-05"), direction: "Bullish", strike: 25000, opt_type: "CE",
  side: "BUY", symbol: "NIFTY26O0625000CE", expiry: "2026-10-06", dte: 1, exit_reason: "cross", fill_entry_ts: at("10:01", "2026-10-05"), fill_exit_ts: at("11:01", "2026-10-05"),
  signal_close: 25000, spot_entry: 25001, spot_exit: 25040, opt_entry: 100, opt_exit: 120, entry_fill: 100.5, exit_fill: 119.5, qty: 75, lot_size: 75, lot_source: "nse",
  ordinal: 1, bars_held: 4, whipsaw: false, outcome: "win", gross: 1425, slippage: 150, charges: { total: 100 }, friction: 250, net: 1175, ...o,
});

export const makeBtResult = (o?: DeepPartial<BtResult>): BtResult => {
  const win = makeBtTrade("t1");
  const loss = makeBtTrade("t2", {
    day: "2026-10-06", direction: "Bearish", opt_type: "PE", outcome: "loss", gross: -500, net: -700, friction: 200, ordinal: 2,
    entry_ts: at("10:30", "2026-10-06"), exit_ts: at("11:30", "2026-10-06"),
  });
  const metrics = {
    label: "ATM buy", trades: 2, wins: 1, losses: 1, win_rate: 50, gross_pnl: 925, friction: 450, net_pnl: 475, profit_factor: 1.68, payoff_ratio: 1.68, expectancy: 237.5,
    avg_win: 1175, avg_loss: 700, max_drawdown: 700, max_drawdown_pct: 0.7, equity_curve: [100000, 101175, 100475],
  };
  return merge<BtResult>({
    params: makeBtMeta().defaults, hash: "hash123", generated_at: at("10:00"), dataset_label: "Groww", strategy: "ema_9_21", strategy_label: "EMA 9/21", partial_asof: null,
    signals: 2, trade_days: 2, summary: { ITM5_BUY: { ...metrics, label: "ITM 5 buy" }, ATM_BUY: metrics, ATM_SELL: { ...metrics, label: "ATM sell" } },
    trades: { ITM5_BUY: [], ATM_BUY: [win, loss], ATM_SELL: [] }, no_trade_days: [], skipped: [],
  }, o);
};

export const makeResearchCell = (strategy: string, label: string, timeframe: number, net: number): ResearchCell => {
  const mode = (n: number) => ({
    trades: 20, wins: 9, losses: 11, win_rate: 45, gross_pnl: n + 500, friction: 500, net_pnl: n, profit_factor: n > 0 ? 1.1 : 0.8, payoff_ratio: 1, expectancy: n / 20,
    avg_win: 300, avg_loss: 250, max_drawdown: 900, max_drawdown_pct: 0.9, daily: [["2026-10-05", n / 2], ["2026-10-06", n / 2]] as [string, number][],
    yearly: { "2026": { net: n, trades: 20, win_rate: 45 } }, monthly: { "2026-10": n }, skipped: 0,
  });
  return {
    strategy, label, timeframe, start_date: "2026-10-01", end_date: "2026-11-17", updated: at("09:00"),
    summary: { signals: 40, trade_days: 30, partial_asof: null, modes: { ITM5_BUY: mode(net), ATM_BUY: mode(net), ATM_SELL: mode(net) } },
  };
};
export const makeResearch = (cells?: ResearchCell[]): Research => ({
  settings: {}, cells: cells ?? [makeResearchCell("ema_9_21", "EMA 9/21", 15, 1500), makeResearchCell("ema_20_50", "EMA 20/50", 15, -900)],
  walk_forward: {
    ITM5_BUY: { rows: [], total_oos: 0, baseline_total: 0 }, ATM_BUY: { rows: [], total_oos: 0, baseline_total: 0 }, ATM_SELL: { rows: [], total_oos: 0, baseline_total: 0 },
  },
});

export const makeHistSignal = (id: string, o?: Partial<HistSignal>): HistSignal => ({
  id, ts: at("10:00", "2026-10-05"), day: "2026-10-05", direction: "Bullish", call: "Bullish", score: 72, category: "strong", out_of_sample: true, entry: 25000, stop: 24950, target: 25100,
  risk_reward: 2, atr: 50, expires: at("15:00", "2026-10-05"), indicators: [{ name: "RSI", value: "61", supports: true }, { name: "VWAP", value: "below", supports: false }],
  reason: "EMA 9 crossed above EMA 21", regime: "uptrend", comparable: { band: "70+", n: 40, hit_rate: 55, ci: [40, 70] }, calibrated: 52, outcome: "hit",
  decided_at: at("11:00", "2026-10-05"), strong_alert: false, ...o,
});
export const makeSignalAnalysis = (o?: DeepPartial<SignalAnalysis>): SignalAnalysis => merge<SignalAnalysis>({
  strategy: "ema_9_21", strategy_label: "EMA 9/21", timeframe: 15, generated_at: at("09:00"), asof: "2026-11-17",
  counts: { signals: 120, labelled: 110, oos: 60, unconfirmed: 5, pending: 5 },
  model: { base_rate: 48, auc: 0.52, brier: 0.25, brier_base: 0.25, folds: [], verdict: { edge: false, text: "No measurable edge out of sample." } },
  calibration: [{ band: "0-49", from: 0, to: 50, n: 30, mean_score: 40, hit_rate: 45 }, { band: "70+", from: 70, to: 101, n: 20, mean_score: 75, hit_rate: 55 }],
  signals: [makeHistSignal("s1"), makeHistSignal("s2", { direction: "Bearish", score: 35, outcome: "miss", reason: "EMA 9 crossed below EMA 21" })],
}, o);

// ------------------------------------------------------------------ data
export const makeDataOverview = (o?: DeepPartial<DataOverview>): DataOverview => merge<DataOverview>({
  coverage: {
    symbol: "NIFTY", target: { from: "2021-11-11", to: "2026-11-17" }, verdict: "full",
    summary: {
      sessions: 1200, weekdays: 1250, complete: 1190, partial: 10, no_data: 50, not_downloaded: 0, candles: 450000, missing_minutes: 30, rejected: 0, spikes: 0,
      outside_session: 0, special_sessions: 2, first: "2021-11-11T09:15:00", last: "2026-11-17T15:29:00", coverage_pct: 100,
    },
    months: [{ month: "2026-10", complete: 20, partial: 1 }], not_downloaded: [], no_data: [], partial_days: [],
  },
  instruments: {
    spot: { symbol: "NIFTY", first: "2021-11-11", last: "2026-11-17T15:29:00", candles: 450000, sessions: 1200, last_success: "2026-11-17T16:00:00" },
    futures: { contracts: 63, last_day: "2026-11-17", candles: 400000, latest_contract: "NIFTY26NOVFUT", last: "2026-11-17T15:29:00", last_success: "2026-11-17T16:00:00" },
    options: { contracts: 21750, first_day: "2021-11-11", last_day: "2026-11-17", candles: 67000000, last_success: "2026-11-17T16:00:00" }, intervals: [1, 5, 15, 30],
  },
  downloads: [], job: null,
}, o);
export const makeOptionsCoverage = (o?: DeepPartial<OptionsCoverage>): OptionsCoverage => merge<OptionsCoverage>({
  scope: { from: "2021-11-11", to: "2026-11-17", strikes_each_side: 10, expiry_rules: ["nearest"], types: ["CE", "PE"] },
  summary: { contracts: 21750, contract_days: 100000, downloaded_days: 100000, empty_days: 0, candles: 67000000, complete_contracts: 21750, pct: 100, expiries: 330 },
  months: [{ month: "2026-10", contracts: 400, contract_days: 2000, downloaded_days: 2000, empty_days: 0, candles: 700000, complete_contracts: 400, pct: 100 }],
  last_run: null, last_success: "2026-11-17T16:00:00", job: null,
}, o);
export const makeLotSizes = (): LotSize[] => [{ cycle: "monthly", first_expiry: "2026-01-27", lot_size: 65, source: "NSE circular" }];

// ------------------------------------------------------------------ scalping
export const makeScalpConfig = (key: string, o?: Partial<ScalpConfig>): ScalpConfig => {
  const stats = { trades: 100, net_pnl: -2000, gross_pnl: 500, win_rate: 45, profit_factor: 0.8, max_drawdown: 3000 };
  return {
    key, strategy: "ema_9_21", strategy_label: "EMA 9/21", contract: "ATM_BUY", contract_label: "ATM buy", exit: "time5", exit_label: "5-min exit", exit_kind: "time",
    stop: null, target: null, ...stats, ce: { ...stats }, pe: { ...stats }, yearly: { "2026": { net: -2000, gross: 500, trades: 100, win_rate: 45 } }, skipped: {},
    in_sample: { trades: 60, net_pnl: -1000, profit_factor: 0.9, max_drawdown: 1500 }, out_of_sample: { trades: 40, net_pnl: -1000, profit_factor: 0.7, max_drawdown: 1500 },
    oos_net: -1000, in_sample_score: 1, score: 1, verdict: { consistent: false, checks: { net_positive: false }, years_positive: "0/1" }, ...o,
  };
};
export const makeScalpRun = (o?: Partial<ScalpRun>): ScalpRun => ({
  run_id: 3, start_date: "2021-11-11", end_date: "2026-11-17", created_at: at("09:00"), generated_at: at("09:00"),
  configs: [makeScalpConfig("c1"), makeScalpConfig("c2", { contract: "ITM5_BUY", contract_label: "ITM 5 buy", net_pnl: -500, strategy: "ema_20_50", strategy_label: "EMA 20/50" })],
  ranking: ["c1", "c2"], best: null, top_in_sample: "c1", split_day: "2025-06-01", consistent: [], selection_rule: "Pick on in-sample, test out of sample.", signals: {},
  existing: [], walk_forward: { rows: [], total_oos: 0 }, settings: {}, ...o,
});

export const makeJob = (o?: Partial<Job>): Job => ({ id: "job-1", kind: "x", state: "done", progress: 1, message: "done", result: null, error: null, ...o });
// ------------------------------------------------------------------ automated bias engine
const INDICATORS = [["ema_9_21", "EMA 9/21", 1], ["ema_5_20", "EMA 5/20", 0.5], ["ema_8_21", "EMA 8/21", 0.5], ["ema_20_50", "EMA 20/50", 1],
  ["ema_200", "200 EMA", 1], ["vwap", "VWAP", 1], ["rsi", "RSI", 0.75], ["rsi_divergence", "RSI divergence", 0.5], ["macd", "MACD", 1],
  ["bollinger", "Bollinger Bands", 0.75], ["volume", "Volume expansion", 0.5], ["sr", "Support / resistance", 1]] as const;

export const makeBiasAnalysis = (o?: DeepPartial<BiasAnalysis>): BiasAnalysis => merge<BiasAnalysis>({
  bar_close: at("10:25"), close: 25012.5, bias: "BULLISH", confidence: 78, combined: 0.42, trend_5m: "Bullish", trend_15m: "Bullish",
  score_5m: 0.38, score_15m: 0.45, conflict: false, signal: "BUY CE", direction: 1, prediction: "UP", atr: 21.5, atr_pct: 0.086, rsi_5m: 61.2, rsi_15m: 58.4, tf_primary: 5, tf_confirm: 15, values: { ema9: 25005, ema21: 24990, ema200: 24800 },
  indicators: INDICATORS.map(([key, label, weight], i) => ({
    key, label, weight, v5: i === 7 ? null : 0.6 - i * 0.08, v15: 0.5 - i * 0.07,
    status5: i === 7 ? "unavailable" : i > 9 ? "bearish" : "bullish", status15: i > 10 ? "neutral" : "bullish",
  })),
  supports: ["EMA 9/21 5m (+0.60)", "VWAP 15m (+0.40)"], against: ["Volume expansion 5m (-0.20)"], hold_reasons: [],
  summary: "BULLISH: 15m bullish (0.45), 5m bullish (0.38); BUY CE candidate (bullish); indicator agreement 78%",
  note: "Confidence is the agreement between indicators, not a probability of winning.",
}, o);

export const makeBiasConfig = (o?: DeepPartial<BiasConfig>): BiasConfig => merge<BiasConfig>({
  running: false, settings: null, note: "Weights and thresholds are fixed starting values, not fitted to any result.",
  indicators: INDICATORS.map(([key, label, weight]) => ({ key, label, weight })),
  defaults: {
    timeframe: 5, bias_confirm_tf: 15, bias_indicators: INDICATORS.map(([k]) => k), bias_min_confidence: 70, bias_trend_thr: 0.25, bias_confirm_thr: 0.2, bias_min_atr_pct: 0.04,
    bias_allow: ["BUY_CE", "BUY_PE"], bias_exit_opposite: true, bias_max_hold_min: 0, bias_cooldown_bars: 2, target_rr: 2, trail_pct: 0,
    trail_activate_pct: 10, sell_risk_pct: 0.5, min_premium: 5, min_oi: 0, max_spread_pct: 5, min_delta: 0.25, premarket_mode: "log", risk_pct: 1, daily_risk_pct: 3,
    max_daily_loss: 5000, max_trades_per_day: 20, max_lots: 10, min_balance: 0, stop_mode: "atr", stop_atr: 1, stop_pct: 30, stop_points: 20,
    entry_start: "09:30", cutoff: "14:30", exec_mode: "ATM_BUY", lots: 1, profit_target_net: 1500,
    entry_strategy: "bias", cf_factors: ["ema", "vwap", "fvg", "structure"], cf_require: [], cf_min_score: 75, cf_adr_filter: true, cf_adr_period: 10,
    cf_adr_max_used: 100, cf_fvg_min_atr: 0.1, cf_fvg_max_age: 24, cf_htf: true,
    sc_min_score: 80, sc_adr_period: 10, sc_adr_max_used: 100, sc_fvg_min_atr: 0.1, sc_fvg_max_age: 24, sc_ctx_tf: 0, sc_stop_min_pct: 5, sc_stop_max_pct: 50,
  },
  presets: { scored: { timeframe: 5, bias_confirm_tf: 15, risk_pct: 0.5, target_rr: 2, stop_mode: "atr", stop_atr: 1, daily_risk_pct: 1.5, max_trades_per_day: 5, profit_target_net: 0, sc_min_score: 80 } },
  scored_components: [{ key: "trend", label: "Market trend", max: 25 }, { key: "ema", label: "EMA 20/50/200", max: 15 }, { key: "vwap", label: "VWAP", max: 20 }, { key: "fvg", label: "Unmitigated FVG retest", max: 20 },
    { key: "momentum", label: "Momentum (RSI 14 + MACD)", max: 10 }, { key: "volume", label: "Volume vs SMA 20", max: 5 }, { key: "adr", label: "ADR", max: 5 }],
  confluence_factors: [{ key: "ema", label: "EMA trend", weight: 1 }, { key: "vwap", label: "VWAP", weight: 1 }, { key: "fvg", label: "Fair value gap", weight: 1 }, { key: "structure", label: "Market structure", weight: 1 }],
  adr_periods: [5, 10, 20],
}, o);

/** The scored strategy on the latest candle: a bullish candidate that scores 100 and passes every gate (override for a refusal). */
export const makeScored = (o?: DeepPartial<Scored>): Scored => merge<Scored>({
  score: 90, min_score: 80, candidate: "BUY CE", direction: 1, passed: true, rejections: [], score_long: 90, score_short: 15, entry_tf: 5, confirm_tf: 15, ctx_tf: 0,
  components: [
    { key: "trend", label: "Market trend", max: 25, points: 25, earned: true, condition: "15-minute trend is bullish; 5-minute structure: higher highs and lows" },
    { key: "ema", label: "EMA 20/50/200", max: 15, points: 15, earned: true, condition: "EMA 20 25,005.00, 50 24,990.00, 200 24,800.00; close 25,012.50 is above EMA 20" },
    { key: "vwap", label: "VWAP", max: 20, points: 12, earned: false, condition: "Close 25,012.50 is above VWAP 24,998.00 (+14.50); no retest or rejection on this candle" },
    { key: "fvg", label: "Unmitigated FVG retest", max: 20, points: 20, earned: true, condition: "bullish gap 25,000.00-25,008.00 mitigated, first return retested and closed out now" },
    { key: "momentum", label: "Momentum (RSI 14 + MACD)", max: 10, points: 10, earned: true, condition: "RSI 61.2, MACD histogram +1.40" },
    { key: "volume", label: "Volume vs SMA 20", max: 5, points: 5, earned: true, condition: "volume 1.35× its 20-bar average" },
    { key: "adr", label: "ADR", max: 5, points: 5, earned: true, condition: "today's range has used 62% of the 10-day ADR (limit 100%)" },
  ],
  gates: [["trend", "Confirmation-timeframe trend agrees"], ["ema", "EMA 20/50(/200) aligned"], ["vwap", "VWAP aligned"], ["fvg", "Unmitigated FVG retested and closed out"],
    ["momentum", "Momentum agrees (RSI or MACD)"], ["adr", "ADR not used up"], ["atr", "Enough volatility"], ["conflict", "No conflicting signal"], ["score", "Score at least the minimum"]]
    .map(([key, label]) => ({ key, label, ok: true, text: "met" })),
  note: "Fixed starting rules, not fitted to any result. The score is how many conditions are met, not a probability of winning.",
}, o);

/** The confluence strategy's factors on the latest candle: a bullish candidate that passes (override `passed`/`rejections` for a refusal). */
export const makeConfluence = (o?: DeepPartial<Confluence>): Confluence => merge<Confluence>({
  score: 87.5, min_score: 75, direction: 1, candidate: "BUY CE", passed: true, rejections: [],
  factors: [
    { key: "ema", label: "EMA trend", weight: 1, enabled: true, required: false, vote: 1, status: "bullish", confirmed: true, agrees: true,
      condition: "EMA 9 above 21 above 50; close 25,012.50 is above EMA 21 24,990.00", values: { ema9: 25005, ema21: 24990, ema50: 24950 } },
    { key: "vwap", label: "VWAP", weight: 1, enabled: true, required: false, vote: 0.5, status: "bullish", confirmed: false, agrees: true,
      condition: "Close 25,012.50 is above VWAP 24,998.00 (+14.50); no retest or rejection on this candle", values: { vwap: 24998, distance: 14.5, retest: false, rejection: false } },
    { key: "fvg", label: "Fair value gap", weight: 1, enabled: true, required: false, vote: 1, status: "bullish", confirmed: true, agrees: true,
      condition: "bullish gap 25,000.00-25,008.00 mitigated and retested now",
      values: { bullish: { state: "mitigated", lo: 25000, hi: 25008, age_bars: 3, retest: true, active: 1 }, bearish: null } },
    { key: "structure", label: "Market structure", weight: 1, enabled: true, required: false, vote: 1, status: "bullish", confirmed: true, agrees: true,
      condition: "Higher highs and higher lows (swing high 25,020.00, swing low 24,960.00)", values: { swing_hi: 25020, swing_lo: 24960, break_of_structure: 0 } },
  ],
  adr: { period: 10, filter: true, max_used: 100, ok: true, text: "Today's range 120.00 has used 62% of the 10-day ADR 193.50 (limit 100%).", range_today: 120,
    rows: [{ period: 5, adr: 180, used: 67 }, { period: 10, adr: 193.5, used: 62 }, { period: 20, adr: 201, used: 60 }] },
  htf: { on: true, trend15: 1, ok: true },
  note: "Fixed starting rules, not fitted to any result. The score is how many enabled factors agree, not a probability of winning.",
}, o);

export const makeBiasStatus = (o?: DeepPartial<BiasStatus>): BiasStatus => merge<BiasStatus>({
  running: true, state: "running", halt_reason: null, trade_mode: "paper", day: DAY, now: at("10:26"), position: null, realised_today: 0,
  events: [{ ts: at("10:25"), level: "info", message: "10:25 BULLISH: signal" }], next_eval: at("10:30"), nifty: { price: 25012.5, ts: at("10:26") },
  conn_error: null, session_id: 7, config: { bias_min_confidence: 70, profit_target_net: 1500, trail_pct: 0, max_trades_per_day: 20 },
  bias: {
    latest: makeBiasAnalysis(), trades_today: 3, max_trades: 20, remaining_trades: 17, cooldown_until: null,
    automation: { phase: "ready", label: "Ready for re-entry", detail: "Next analysis at 10:30: enters if the bias confidence is at least 70% and a valid, new signal exists.", paused: false,
      min_confidence: 70, profit_target_net: 1500, target_hits: 1, trades_today: 3, no_entry_through: null },
    history: [{ bar_close: at("10:25"), close: 25012.5, bias: "BULLISH", confidence: 78, signal: "BUY CE", predicted: "UP", score_5m: 0.38, score_15m: 0.45, outcome: null }],
  },
}, o);

export const makeBiasPrediction = (o?: DeepPartial<BiasPrediction>): BiasPrediction => merge<BiasPrediction>({
  day: DAY, bar_close: at("10:20"), nifty_close: 25000, bias: "BULLISH", confidence: 70, score_5m: 0.3, score_15m: 0.4, signal: "BUY CE",
  predicted: "UP", next_close: 25010, actual: "UP", outcome: "CORRECT",
}, o);

export const makeBiasTrade = (o?: DeepPartial<BiasTrade>): BiasTrade => merge<BiasTrade>({
  id: 31, trade_mode: "paper", day: DAY, exec_mode: "ATM_BUY", direction: "Bullish", side: "BUY", trading_symbol: "NIFTY26N2425000CE", strike: 25000,
  opt_type: "CE", expiry: "2026-11-24", qty: 75, signal_ts: at("10:00"), entry_ts: at("10:00"), entry_price: 120.5, exit_ts: at("10:35"), exit_price: 131,
  exit_reason: "target", gross: 787.5, net: 702.1, status: "CLOSED", slippage: 12, charges: { total: 73.4 }, stop_premium: 100, target_premium: 131,
  action: "BUY CE", confidence: 78, supporting: ["EMA 9/21 5m (+0.60)"],
}, o);

export const makeBiasTradeDetail = (o?: DeepPartial<BiasTradeDetail>): BiasTradeDetail => merge<BiasTradeDetail>({
  trade: {
    ...makeBiasTrade(), risk: makeRisk(),
    analysis: makeBiasAnalysis({
      instrument: "BUY CE", contract_checks: [
        { check: "premium", ok: true, text: "premium 120.50 ≥ the minimum 5" }, { check: "spread", ok: null, text: "bid/ask not available: spread not checked" },
        { check: "delta", ok: false, text: "|delta| 0.20 < the minimum 0.25 for a bought option" }],
    }),
    exit_detail: { reason: "target", exit_premium: 131, best_premium: 132.5, stop_at_exit: 108, target: 131, bias_at_exit: { bias: "BULLISH", trend_15m: "Bullish", trend_5m: "Neutral" } },
  },
  stop_changes: [
    { ts: at("10:00"), old_stop: null, new_stop: 100, old_max_loss: null, new_max_loss: 1600, source: "entry", note: "ATR" },
    { ts: at("10:20"), old_stop: 100, new_stop: 108, old_max_loss: 1600, new_max_loss: 900, source: "trail", note: "trailing 10% from the best premium 120.00" }],
}, o);

export const makeBiasSummary = (o?: DeepPartial<BiasSummary>): BiasSummary => merge<BiasSummary>({
  trades: 4, wins: 3, losses: 1, win_rate: 75, net: 1250.5, gross: 1600, open: 1, mode: "paper", target_hits: 1, note: "An indicator is credited with every trade it supported.",
  by_instrument: { "BUY CE": { trades: 3, wins: 2, losses: 1, win_rate: 66.7, net: 900, gross: 1100 } },
  by_exit: { target: { trades: 2, wins: 2, losses: 0, win_rate: 100, net: 1400, gross: 1500 } },
  by_confidence: { "70-85%": { trades: 4, wins: 3, losses: 1, win_rate: 75, net: 1250.5, gross: 1600 } },
  by_indicator: { "EMA 9/21 5m": { trades: 4, wins: 3, losses: 1, win_rate: 75, net: 1250.5, gross: 1600 } },
}, o);

export const makeBiasAccuracy = (): BiasAccuracy => ({
  candles: 1480, timeframes: [5, 15],
  rows: [
    { key: "combined", label: "Combined bias", timeframe: "5m+15m", correct: 520, incorrect: 480, neutral: 480, n: 1000, accuracy: 52 },
    ...INDICATORS.flatMap(([key, label]) => (["5m", "15m"] as const).map((tf) => ({
      key, label, timeframe: tf, correct: 510, incorrect: 490, neutral: 100, n: 1000, accuracy: tf === "5m" ? 51 : 54.5,
    }))),
  ],
});

// ------------------------------------------------------------------ pre-market analysis
const pmFactor = (key: PmFactor["key"], title: string, score: number, o?: Partial<PmFactor>): PmFactor => ({
  key, title, score, status: score > 0 ? "BULLISH" : score < 0 ? "BEARISH" : "NEUTRAL", available: true,
  summary: `${title} summary`, explanation: `${title} rule`, data: [{ label: `${title} value`, value: "1.00", note: "last close" }],
  asof: "2026-11-19T08:30", source: "Yahoo Finance", delayed: "may lag up to 15 minutes", warnings: [], ...o,
});

export const makePmReport = (o?: DeepPartial<PmReport>): PmReport => merge<PmReport>({
  day: "2026-11-19", generated_at: "2026-11-19T08:40:00", total: { total: 3, bias: "BULLISH", available_factors: 4, max: 5 },
  factors: [
    pmFactor("global", "Global markets", 1, { news: [{ id: "a1", headline: "Wall Street rallies as Fed signals rate cut", source: "Reuters", link: "https://example.com/a", published: "2026-11-18T22:10", nifty_impact: "bullish", impact_level: "High", relation: "supports" }] }), pmFactor("fii_dii", "FII / DII flows", 0, { status: "UNAVAILABLE", available: false, summary: "Not available: no figures entered for the previous trading day.", asof: null, source: null, delayed: null, warnings: ["NSE does not publish FII/DII data to scripts."] }),
    pmFactor("crude", "Crude oil", 1), pmFactor("vix", "India VIX", 0), pmFactor("structure", "NIFTY chart & structure", 1, { source: "Stored NIFTY 1-minute candles (Groww)" }),
  ],
  conclusion: {
    direction: "BULLISH", opening: "a flat-to-higher opening", preference: "BUY CE", confidence: 60,
    confidence_note: "3 of 5 points point the same way (4 of 5 factors had data). Confidence is agreement between factors, not a probability that NIFTY moves that way.",
    levels: { support: [{ name: "Previous-day low", price: 25141.8 }], resistance: [{ name: "Pivot", price: 25253.5 }], breakout: 25390.7, breakdown: 25141.8, pivot: 25253.5, previous_close: 25228 },
    risks: ["FII / DII flows data is unavailable, so it earned no point."], action: "This is a lean for the day, not an order. Paper entries still need a completed 5-minute candle signal confirmed by the 15-minute direction.", expiry_today: false,
  },
  news: [],
  events: [{ kind: "calendar", title: "Weekly NIFTY options expiry", basis: "from the stored expiry list" }],
  warnings: ["Gift Nifty is unavailable, so the opening gap is not estimated from it."], unavailable: { gift_nifty: "Gift Nifty is not published by any free source this app can read." },
  note: "Pre-market direction is context, not a trade signal.", snapshots: [{ at: "2026-11-19T08:40:00", total: 3, scores: { global: 1 } }], actual: null, outcome: null,
}, o);

export const makePmHistory = (o?: DeepPartial<PmHistory>): PmHistory => merge<PmHistory>({
  days: [{ day: "2026-11-18", total: 3, bias: "BULLISH", preference: "BUY CE", confidence: 60, outcome: "CORRECT", paper_trades: 2, paper_net: -450,
    actual: { open: 25100, high: 25400, low: 25050, close: 25228, prev_close: 25000, change_pct: 0.91, gap_pct: 0.4, direction: "UP", source: "stored candles" } }],
  accuracy: { days: 1, settled: 1, calls: 1, correct: 1, hit_pct: 100, note: "Too few days to say anything: a coin flip is within ±98 points of 50%." },
  effectiveness: [{ group: "agreed", trades: 3, wins: 1, win_pct: 33.3, net: -900 }, { group: "opposed", trades: 2, wins: 1, win_pct: 50, net: 120 }],
}, o);

export const makePmArticle = (o?: Partial<PmArticle>): PmArticle => ({
  id: "a1", headline: "Wall Street rallies as Fed signals rate cut", summary: "US stocks closed higher as the Federal Reserve hinted at easing.", image: "https://example.com/a.jpg",
  source: "Reuters", link: "https://example.com/a", published: "2026-11-18T22:10", via: "publisher feed", sentiment: "positive", nifty_impact: "bullish",
  impact_level: "High", why: "A firm Wall Street usually lifts global risk appetite and NIFTY's opening.", sectors: ["IT & technology"], indices: ["NIFTY IT"],
  categories: ["us", "global", "central_banks"], topic: "US Market", period: "overnight", is_new: false, is_breaking: false, coverage: 1, related: [], factor: "global",
  verified: "publisher RSS feed", ...o,
});

export const makePmFeed = (o?: Partial<PmNewsFeed>): PmNewsFeed => ({
  now: "2026-11-19T08:45:00", fetched_at: "2026-11-19T08:44:30", status: "live", cached: false,
  articles: [
    makePmArticle(),
    makePmArticle({ id: "a2", headline: "Crude oil slumps on demand fears", summary: null, image: null, source: "Bloomberg", link: "https://example.com/b", published: "2026-11-18T20:00",
      sentiment: "positive", nifty_impact: "bullish", impact_level: "Medium", categories: ["crude"], topic: "Crude Oil", factor: "crude", sectors: ["Oil & gas"], indices: ["NIFTY 50"],
      related: [{ source: "Mint", headline: "Oil falls as demand worries grow", link: "https://example.com/b2", published: "2026-11-18T20:30" }], coverage: 2 }),
    makePmArticle({ id: "a3", headline: "RBI holds repo rate steady in surprise pause", source: "The Economic Times", link: "https://example.com/c", published: "2026-11-19T07:30", period: "today_pre_market", is_new: true,
      is_breaking: true, categories: ["central_banks", "indian", "breaking"], topic: "RBI / Federal Reserve", sentiment: "neutral", nifty_impact: "neutral", factor: null, sectors: ["Banking & financials"], indices: ["Bank NIFTY"] }),
    makePmArticle({ id: "a4", headline: "FIIs sell Rs 2,000 crore of Indian shares", source: "Mint", link: "https://example.com/d", published: "2026-11-17T18:00", period: "earlier", sentiment: "negative",
      nifty_impact: "bearish", impact_level: "Low", categories: ["fii_dii", "indian"], topic: "FII / DII", factor: "fii_dii", sectors: [], indices: ["NIFTY 50"] }),
  ],
  events: [{ kind: "calendar", title: "Weekly NIFTY options expiry", basis: "from the stored expiry list" }],
  categories: [["all", "All News", 4], ["indian", "Indian Stock Market", 2], ["global", "Global Markets", 1], ["us", "US Market", 1], ["asia", "Asian Markets", 0], ["fii_dii", "FII / DII", 1],
    ["central_banks", "RBI / Federal Reserve", 2], ["crude", "Crude Oil", 1], ["economy", "Economic News", 0], ["nifty", "NIFTY / Bank NIFTY", 0], ["breaking", "Important Breaking News", 1]]
    .map(([key, label, count]) => ({ key: key as string, label: label as string, count: count as number })),
  periods: [{ key: "today_session", label: "Today, market hours" }, { key: "today_pre_market", label: "Today, pre-market" }, { key: "overnight", label: "Overnight (since the last close)" },
    { key: "previous_day", label: "Previous trading day" }, { key: "earlier", label: "Earlier" }],
  summary: { total: 4, with_summary: 3, with_image: 1, breaking: 1, periods: {}, sentiment: { positive: 2, negative: 1, neutral: 1 } },
  sources: { publishers: [{ name: "Mint", feeds_ok: 2, feeds: 2, articles: 70 }, { name: "The Economic Times", feeds_ok: 4, feeds: 4, articles: 200 }], searches_ok: 9, searches: 9 },
  warnings: [], previous_trading_day: "2026-11-18",
  method: "Sentiment, NIFTY direction, impact level, sectors and the reason it matters come from fixed keyword rules applied to the publisher's headline and summary.",
  ...o,
});

// ------------------------------------------------------------------ Trading Settings
const P = (key: string, label: string, type: TsParam["type"], min: number, max: number, def: number | string | boolean, choices?: (number | string)[]): TsParam =>
  ({ key, label, type, min, max, default: def, ...(choices ? { choices } : {}) });

const CROSS: [string, string, number, number, string[]][] = [
  ["ema_9_21", "EMA 9/21", 9, 21, ["ema"]], ["ema_5_20", "EMA 5/20", 5, 20, ["ema"]], ["ema_8_21", "EMA 8/21", 8, 21, ["ema"]], ["ema_20_50", "EMA 20/50", 20, 50, ["ema"]],
  ["ema_9_21_vwap", "EMA 9/21 + VWAP", 9, 21, ["ema", "vwap"]], ["ema_9_21_rsi", "EMA 9/21 + RSI", 9, 21, ["ema", "rsi"]], ["ema_9_21_macd", "EMA 9/21 + MACD", 9, 21, ["ema", "macd"]],
];
const METHODS: [string, string, string[]][] = [
  ["cross_9_21", "EMA 9/21 fresh crossover", ["ema"]], ["cross_5_20", "EMA 5/20 fresh crossover", ["ema"]], ["cross_8_21", "EMA 8/21 fresh crossover", ["ema"]],
  ["cross_9_21_vwap", "EMA 9/21 crossover + VWAP side", ["ema", "vwap"]], ["continuation_9_21", "EMA 9/21 trend continuation", ["ema", "atr"]], ["pullback_9_21", "EMA 9/21 pullback and rejection", ["ema", "atr"]],
  ["stack_20_50_200", "EMA 20/50/200 alignment", ["ema"]], ["rsi_divergence", "RSI divergence + price confirmation", ["rsi", "rsi_divergence"]], ["macd_cross", "MACD signal-line crossover", ["macd"]],
  ["macd_hist_trend", "MACD histogram flip with 15m trend", ["macd"]], ["bb_breakout", "Bollinger breakout with volume", ["bollinger", "volume"]], ["bb_reversal", "Bollinger reversal", ["bollinger"]],
  ["vwap_breakout", "VWAP breakout", ["vwap"]], ["vwap_retest", "VWAP retest", ["vwap", "atr"]], ["sr_breakout", "Previous-day high/low breakout", ["structure"]],
  ["sr_retest", "Previous-day high/low breakout retest", ["structure", "atr"]], ["sr_rejection", "Previous-day high/low rejection", ["structure", "atr"]],
  ["volume_momentum", "Volume-confirmed momentum candle", ["volume", "atr"]], ["atr_breakout", "ATR volatility breakout candle", ["atr"]], ["orb", "Opening range breakout", ["atr"]],
  ["consolidation_breakout", "Consolidation breakout", ["atr"]], ["trend_reversal", "15m trend reversal", ["ema"]],
];
const IND: [string, string, TsParam[], string][] = [
  ["ema", "EMA", [], "Periods are set per strategy."], ["vwap", "VWAP", [], "Session VWAP of the near-month NIFTY future."],
  ["rsi", "RSI", [P("period", "Period", "int", 2, 50, 14), P("overbought", "Overbought", "float", 55, 95, 75), P("oversold", "Oversold", "float", 5, 45, 25)], ""],
  ["macd", "MACD", [P("fast", "Fast", "int", 2, 50, 12), P("slow", "Slow", "int", 3, 100, 26), P("signal", "Signal", "int", 2, 50, 9)], ""],
  ["bollinger", "Bollinger Bands", [P("period", "Period", "int", 5, 100, 20), P("std", "Standard deviations", "float", 0.5, 4, 2)], ""],
  ["volume", "Volume / Volume SMA", [P("sma_period", "SMA period", "int", 5, 100, 20)], ""],
  ["fvg", "Fair value gap (FVG)", [P("min_atr", "Smallest gap (× ATR)", "float", 0, 5, 0.1), P("max_age", "Gap tradable for (candles)", "int", 1, 200, 24)], ""],
  ["adr", "Average daily range (ADR)", [P("period", "Sessions", "choice", 5, 20, 10, [5, 10, 20]), P("max_used", "No entry once used (%)", "float", 10, 1000, 100)], ""],
  ["atr", "ATR", [P("period", "Period", "int", 2, 50, 14)], ""], ["rsi_divergence", "RSI divergence", [P("pivot", "Pivot confirmed after (bars)", "int", 1, 10, 3), P("decay", "Valid for (bars)", "int", 1, 30, 6)], "Needs RSI."],
  ["structure", "Market structure / Support & resistance", [P("swing", "Swing pivot confirmed after (bars)", "int", 1, 10, 3)], ""],
];
const RULES: TsParam[] = [
  P("min_score", "Minimum confidence / signal score", "float", 0, 100, 0), P("max_trades_per_day", "Maximum trades a day", "int", 1, 200, 6),
  P("max_open_positions", "Maximum open positions", "int", 1, 1, 1), P("stop_mode", "Stop-loss method", "choice", 0, 0, "atr", ["atr", "pct", "points"]),
  P("stop_atr", "Stop: delta × ATR multiple", "float", 0.1, 10, 1), P("stop_pct", "Stop: % of premium", "float", 1, 99, 30), P("stop_points", "Stop: premium points", "float", 0.5, 10000, 20),
  P("target_rr", "Target (× the stop distance)", "float", 0.1, 20, 2), P("profit_target_net", "Net profit target per trade", "float", 0, 1e7, 0), P("risk_pct", "Risk per trade (% of virtual capital)", "float", 0.05, 100, 1),
  P("trail_pct", "Trailing stop", "float", 0, 99, 0), P("trail_activate_pct", "Trail starts after", "float", 0, 1000, 10), P("start", "Trading starts", "time", 0, 0, "09:30"), P("end", "Trading ends", "time", 0, 0, "14:30"),
  P("reentry_enabled", "Allow re-entry after an exit", "bool", 0, 1, true), P("cooldown_bars", "Cool-down after an exit (candles)", "int", 0, 20, 2),
  P("daily_loss_pct", "Daily loss limit (% of capital)", "float", 0, 100, 3), P("daily_loss_rupees", "Daily loss limit (₹)", "float", 0, 1e9, 5000),
];

export const makeTsMeta = (): TsMeta => ({
  strategies: [
    ...CROSS.map(([key, label, f, s, requires]) => ({ key, label, kind: "crossover" as const, requires, requires_any: [], params: [P("fast", "Fast EMA", "int", 2, 200, f), P("slow", "Slow EMA", "int", 3, 400, s)], note: `${label} crossover.` })),
    { key: "bias", label: "Bias votes (12 indicators)", kind: "bias", requires: [], requires_any: ["ema", "vwap", "rsi", "macd", "bollinger", "volume", "rsi_divergence", "structure"],
      params: [P("min_confidence", "Minimum confidence (%)", "float", 0, 100, 70), P("trend_thr", "Trend needs ± score", "float", 0, 1, 0.25), P("confirm_thr", "Entry candle needs ± score", "float", 0, 1, 0.2)], note: "Weighted vote of every enabled indicator." },
    { key: "confluence", label: "Confluence (FVG + VWAP + ADR + EMA + structure)", kind: "confluence", requires: [], requires_any: ["ema", "vwap", "fvg", "structure"],
      params: [P("min_score", "Confirmation score needed (%)", "float", 0, 100, 75), P("htf", "Trend timeframe must not be against", "bool", 0, 1, true)], note: "Each factor counts only while its indicator is ON." },
    { key: "scored", label: "Scored (structure + EMA + VWAP + FVG + ADR)", kind: "scored", requires: ["ema", "vwap", "rsi", "macd", "volume", "fvg", "adr", "atr", "structure"], requires_any: [],
      params: [P("min_score", "Minimum score (of 100)", "float", 0, 100, 80), P("ctx_tf", "Context timeframe (0 = off)", "choice", 0, 60, 0, [0, 30, 60]), P("stop_min_pct", "Stop at least (% of premium)", "float", 0, 100, 5), P("stop_max_pct", "Stop at most (% of premium)", "float", 1, 100, 50)],
      note: "Needs every indicator it scores." },
    ...METHODS.map(([key, label, requires]) => ({ key: "m_" + key, label, kind: "method" as const, requires, requires_any: [], params: [], note: "Research entry method (fixed rules)." })),
  ],
  indicators: IND.map(([key, label, params, note]) => ({ key, label, params, note, depends_on: key === "rsi_divergence" ? ["rsi"] : [] })),
  rules: RULES,
  timeframes: { all: [1, 5, 15, 30], entry: [5, 15], trend: [15, 30], exit: ["entry", "trend"],
    notes: { "1": "Cannot be used for entry, trend or exit confirmation in this engine.", "5": "Entry candle.", "15": "Entry candle or trend confirmation.", "30": "Trend confirmation." } },
});

export const makeTsConfig = (): TsConfig => {
  const meta = makeTsMeta();
  const on = new Set(["ema_9_21", "ema_5_20", "ema_8_21", "ema_20_50", "ema_9_21_vwap", "ema_9_21_rsi", "ema_9_21_macd", "bias", "confluence", "scored"]);
  return {
    strategies: Object.fromEntries(meta.strategies.map((s) => [s.key, { enabled: on.has(s.key), params: Object.fromEntries(s.params.map((p) => [p.key, p.default])) }])),
    timeframes: { enabled: { "1": false, "5": true, "15": true, "30": true }, entry: 5, trend: 15, exit: "entry", trend_filter: true },
    indicators: Object.fromEntries(meta.indicators.map((i) => [i.key, { enabled: true, params: Object.fromEntries(i.params.map((p) => [p.key, p.default])) }])),
    rules: Object.fromEntries(meta.rules.map((p) => [p.key, p.default])),
  };
};

export const makeTsSummary = (config: TsConfig = makeTsConfig(), over: Partial<TsSummary> = {}): TsSummary => {
  const on = Object.keys(config.strategies).filter((k) => config.strategies[k].enabled);
  return {
    version: 3, saved_at: "2026-11-21T10:15:30", valid: true, error: null, strategies_on: on, strategies_active: on, strategies_blocked: {},
    timeframes_enabled: [5, 15, 30], entry_tf: 5, trend_tf: 15, exit: "entry", indicators_on: Object.keys(config.indicators), indicators_off: [],
    rules: { window: "09:30-14:30", max_trades_per_day: 6, risk_pct: 1, stop: "atr", target_rr: 2, daily_loss_pct: 3, reentry: true }, ...over,
  };
};

export const makeTsState = (o: Partial<TsState> = {}): TsState => {
  const config = o.config ?? makeTsConfig();
  return { version: 3, saved_at: "2026-11-21T10:15:30", note: "saved", config, summary: makeTsSummary(config), warnings: [], error: null, meta: makeTsMeta(), defaults: makeTsConfig(), ...o };
};

// ------------------------------------------------------------------ daily range
/** `n` weekdays ending on `end`, oldest first. Day k opens at 25,000 + 40k and has a range of 150 + 10 (k mod 7) points; every third day closes down. */
export function makeRangeDays(n = 24, end = "2026-11-17", status: Partial<Record<number, DayStatus>> = {}): RangeDay[] {
  const dates: string[] = [];
  for (let d = new Date(end + "T00:00:00Z"); dates.length < n; d.setUTCDate(d.getUTCDate() - 1)) if (d.getUTCDay() % 6 !== 0) dates.unshift(d.toISOString().slice(0, 10));
  const days: RangeDay[] = [];
  dates.forEach((date, k) => {
    const open = 25000 + 40 * k, range = 150 + 10 * (k % 7), up = k % 3 !== 0;
    const close = up ? open + 60 : open - 50;
    const st = status[k] ?? "complete";
    const prev = [...days].reverse().find((x) => x.status === "complete");
    const avg = (w: number) => {
      const done = days.concat({ range } as RangeDay).filter((x, i, a) => i === a.length - 1 ? st === "complete" : x.status === "complete");
      return st === "complete" && done.length >= w ? Math.round(done.slice(-w).reduce((a, x) => a + x.range, 0) / w * 100) / 100 : null;
    };
    days.push({
      date, open, high: open + range - 40, low: open - 40, close, range, range_pct: Math.round(10000 * range / open) / 100,
      prev_close: prev?.close ?? null, prev_date: prev?.date ?? null,
      change: prev ? close - prev.close : null, change_pct: prev ? Math.round(10000 * (close - prev.close) / prev.close) / 100 : null,
      avg10: avg(10), avg20: avg(20), avg50: avg(50), candles: st === "complete" ? 375 : 120, status: st, first: "09:15", last: st === "complete" ? "15:29" : "11:14",
    });
  });
  return days;
}

/** The server's default window: the day after the same date a year earlier. */
const oneYearBack = (end: string) => { const d = new Date(end + "T00:00:00Z"); d.setUTCFullYear(d.getUTCFullYear() - 1); d.setUTCDate(d.getUTCDate() + 1); return d.toISOString().slice(0, 10); };

export const makeDailyRange = (o: Partial<DailyRange> & { days?: RangeDay[] } = {}): DailyRange => {
  const days = o.days ?? makeRangeDays();
  const done = days.filter((d) => d.status === "complete");
  const widest = done.reduce((a, b) => (b.range > a.range ? b : a)), narrowest = done.reduce((a, b) => (b.range < a.range ? b : a));
  const pick = (d: RangeDay) => ({ date: d.date, range: d.range, range_pct: d.range_pct, high: d.high, low: d.low });
  const last = days[days.length - 1];
  const hi = days.reduce((a, b) => (b.high > a.high ? b : a)), lo = days.reduce((a, b) => (b.low < a.low ? b : a));
  const adr = done.reduce((a, d) => a + d.range, 0) / done.length;
  return {
    symbol: "NSE-NIFTY", window: { from: oneYearBack(last.date), to: last.date }, as_of: `${last.date}T${last.last}:00`,
    counts: { days: days.length, complete: done.length, partial: days.filter((d) => d.status === "partial").length, in_progress: days.filter((d) => d.status === "in_progress").length },
    days,
    summary: {
      high: { price: hi.high, date: hi.date }, low: { price: lo.low, date: lo.date }, current: { price: last.close, date: last.date, time: last.last, status: last.status },
      adr: Math.round(adr * 100) / 100, adr_pct: 0.63, highest_range: pick(widest), lowest_range: pick(narrowest), median_range: 180,
      bullish_days: done.filter((d) => d.close >= d.open).length, bearish_days: done.filter((d) => d.close < d.open).length,
    },
    analysis: {
      windows: [10, 20, 50],
      trend: { avg10: 180, avg50: 160, ratio: 1.125, label: "expanding", as_of: last.date, band: 0.1 },
      current: { date: last.date, status: last.status, open: last.open, high: last.high, low: last.low, close: last.close, range: last.range, range_pct: last.range_pct, last: last.last,
        adr: { "10": 180, "20": 175, "50": null }, utilization: { "10": 100 * last.range / 180, "20": 100 * last.range / 175, "50": null }, remaining: { "10": Math.max(0, 180 - last.range), "20": Math.max(0, 175 - last.range), "50": null } },
    },
    rules: { session_minutes: 375, range_pct_of: "open", change_pct_of: "previous complete close" },
    ...o,
  };
};

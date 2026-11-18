/** Typed, realistic builders for API payloads. Every builder takes a partial override (deep-merged). */
import type {
  Alert, Bar, BtMeta, BtResult, BtTrade, Dashboard, DataOverview, EngineConfig, Feed, HistSignal, Job, LiveTrade, LotSize, OptionChain,
  OptionsCoverage, PaperAccount, Position, Quote, Recommendation, Research, ResearchCell, RiskCalc, ScalpConfig, ScalpRun, SignalAnalysis,
  TradingPlan,
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

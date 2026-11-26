import type { PosAnalysis, PosBacktest, PosCell, PosChart, PosComponent, PosConfig, PosPosition, PosState, PosStats } from "../types/api";

const comp = (key: string, label: string, max: number, points: number, note = "n"): PosComponent => ({ key, label, max, points, available: true, note });
const NEG = { status: "negative", label: "negative validated result", note: "pooled net -₹4.0 lakh over 347 trades" } as const;

export const makePosAnalysis = (o: Partial<PosAnalysis> = {}): PosAnalysis => ({
  asof: "2026-11-26T16:00:00", day: "2026-11-26", decision: "BUY CE", direction: 1, score: 71.4, paper_only: true, note: "The score counts sound conditions met; it is not a probability of winning.",
  reasons: ["score 71.4 of 100 is at least 60", "evidence: negative validated result (see the backtest): treat this as an idea to study, not an edge"],
  market: { day: "2026-11-26", close: 25856.6, regime: { label: "Uptrend", why: "daily trend up, weekly strong up, ADX 27, ATR 0.92% of price" },
    timeframes: { weekly: "strong up", daily: "up", h4: "up", h1: "flat / mixed" }, values: { rsi: 61.2, adx: 27.4, atr_pct: 0.92, macd_hist: 12.1 } },
  strategies: [
    { key: "daily_ema_trend", label: "Daily EMA trend-following", enabled: true, signal: 1, age_days: 0, params: {}, evidence: { ...NEG } },
    { key: "adx_trend", label: "ADX trend strength", enabled: true, signal: 0, age_days: null, params: { adx_min: 25 }, evidence: { ...NEG } },
  ],
  opportunities: [{
    direction: 1, type: "CE", strategies: ["daily_ema_trend"], strategy_labels: ["Daily EMA trend-following"], score: 71.4, decision: "BUY CE", why: "score 71.4 of 100 is at least 60", gates: [],
    components: [comp("weekly", "Weekly trend", 15, 15, "strong trend with the trade"), comp("daily", "Daily trend", 15, 11.3, "trend with the trade"), comp("volume", "Volume", 10, 0, "futures volume n/a (not available: 0 points)")],
    contract: { symbol: "NSE-NIFTY-10Dec26-25850-CE", expiry: "2026-12-10", strike: 25850, typ: "CE", premium: 312.5, volume: 91000, oi: 180000, dte: 14, lot_size: 65, quality: 7.4, usable: true,
      notes: ["open interest 180,000, volume 91,000 on the day"], reasons_unusable: [], estimate: { available: true, iv: 0.137, delta: 0.53, theta_day: -9.2, theta_pct_day: -2.9, note: "model estimate" }, gap_pct: 14, spread: { available: false, why: "not stored" } },
    evidence: [{ ...NEG }],
    plan: { entry: { premium: 312.5, low: 303, high: 322, note: "estimate" }, stop_premium: 203.2, target1: 531.2, target2: 750, trailing: "after Target 1 the stop moves to the entry premium", invalidation: 25410, invalidation_note: "if the daily bar closes beyond this level the idea is invalid",
      hold_days: 5, planned_exit: "2026-12-04", expiry: "2026-12-10", time_exit: "close of day 5", risk_reward: { net_at_target: 13800, net_at_stop: -7400, ratio: 1.86 }, lots: 2, qty: 130, max_loss: 14800, capital_required: 40625,
      warnings: ["theta: about ₹1,196 a day for 130 units (2.9% of the premium); a weekend costs three days of it (estimate)"], backtested_rules: "premium stop -35%, target +70%, time exit, forced exit before expiry" },
  }],
  comparison: {
    CE: { candle_score: 64, contract_quality: 7.4, total_without_levels: 71.4, best: { symbol: "x", expiry: "2026-12-10", strike: 25850, premium: 312.5, dte: 14, quality: 7.4, notes: [], estimate: { available: true, iv: 0.137, delta: 0.53, theta_pct_day: -2.9, note: "model estimate" }, gap_pct: 14 },
      alternatives: [], explanation: ["10 Dec 25850 CE: quality 7.4 of 10 (open interest 180,000)."] },
    PE: { candle_score: 22, contract_quality: null, total_without_levels: 22, best: null, alternatives: [], explanation: ["no usable contract: only 1 days to expiry"] },
  },
  context: { available: false, why: "no stored pre-market report for this day" }, ...o,
});

export const makePosConfig = (): PosConfig => ({
  settings: { version: 0, error: null, config: { strategies: { daily_ema_trend: { enabled: true, params: {} }, adx_trend: { enabled: true, params: { adx_min: 25 } } },
    risk: { risk_pct: 1, max_open_positions: 3, max_portfolio_risk_pct: 3, max_lots: 20, hold_days: 5, min_score: 60 }, auto_enter: false } },
  strategies: [{ key: "daily_ema_trend", label: "Daily EMA trend-following", params: {}, doc: "" }],
  risk_schema: { risk_pct: { type: "float", min: 0.05, max: 10, default: 1, label: "Risk per trade (% of virtual capital)" }, max_open_positions: { type: "int", min: 1, max: 20, default: 3, label: "Maximum open positions" } },
  note: "Paper trading only.",
});

export const makePosState = (o: Partial<PosState> = {}): PosState => ({ account_id: 1, starting_capital: 500000, balance: 500000, invested: 0, available: 500000, realised: 0, open_pnl: 0, equity: 500000, open_positions: 0,
  open_risk: 0, open_risk_pct: 0, exposure_pct: 0, closed_trades: 0, max_drawdown: 0, ...o });

export const posStats = (o: Partial<PosStats> = {}): PosStats => ({ trades: 0, win_rate: null, net: 0, gross: 0, costs: 0, expectancy: null, profit_factor: null, max_drawdown: 0, avg_days: null, ...o });

export const makePosPosition = (o: Partial<PosPosition> = {}): PosPosition => ({ id: 1, strategy: "daily_ema_trend", direction: "Bullish", opt_type: "CE", strike: 25850, expiry: "2026-12-10", trading_symbol: "x", lots: 2, qty: 130,
  decision_day: "2026-11-26", score: 71.4, entry_ts: "2026-11-26T16:00:00", entry_price: 312.5, stop_premium: 203.2, target1: 531.2, target2: 750, planned_exit: "2026-12-04", forced_exit: "2026-12-09", status: "OPEN",
  last_price: 330, mtm: 1800, exit_ts: null, exit_price: null, exit_reason: null, net: null, t1_hit: false, risk: { max_loss: 14800 }, ...o });

const cell = (strategy: string, hold: number, o: Partial<PosCell> = {}): PosCell => ({ ...posStats({ trades: 41, win_rate: 31.7, net: -18838, profit_factor: 0.86, expectancy: -459, max_drawdown: 50759 }), strategy, hold,
  periods: { train: posStats({ trades: 22, net: 9016 }), validation: posStats({ trades: 5, net: -17453 }), out_of_sample: posStats({ trades: 14, net: -10401 }) }, robust: false,
  by_year: { "2024": -17453 }, by_month: { "2024-03": -9000, "2025-05": 4000 }, exit_reasons: { stop_loss: 20 }, unsimulatable: { "no option candle at entry": 14 }, unsimulatable_n: 14, ...o });

export const makePosBacktest = (): PosBacktest => ({
  cells: [cell("adx_trend", 3), cell("daily_ema_trend", 5, { net: 18313 })], pooled_by_hold: { "3": posStats({ trades: 347, net: -404222, win_rate: 30 }), "5": posStats({ trades: 247, net: -136123, win_rate: 33 }),
    "10": posStats({ trades: 87, net: -16074 }), "20": posStats({ trades: 12, net: -19709 }) },
  meta: { generated_at: "2026-11-26T14:24:53", data_from: "2021-11-11", data_to: "2026-11-26", signals: 366, stop_pct: 0.35, target_pct: 0.7, holds: [3, 5, 10, 20], periods: {} }, evidence: {},
});

export const makePosChart = (): PosChart => ({ tf: "D", bars: [0, 1, 2, 3].map((i) => ({ t: `2026-11-${20 + i}T15:30:00`, o: 25000 + i, h: 25100 + i, l: 24900 + i, c: 25050 + i, e20: 24900 + i, e50: 24800, e100: 24500, e200: null })) });

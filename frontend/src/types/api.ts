// Shapes returned by the Flask API (see docs/API.md). Times are IST wall-clock ISO strings.

export interface ApiErr { ok: false; error: string; kind?: string }
/** Full response envelope: some endpoints return `job`, `hash` or `cached` beside `data`. */
export interface Envelope<T> { ok: true; data?: T; job?: string | Job | null; hash?: string; cached?: boolean }

export interface Job {
  id: string; kind: string; state: "queued" | "running" | "done" | "error";
  progress: number; message: string; result: unknown; error: string | null;
}

export interface MarketStatus { state: "open" | "preopen" | "closed"; label: string }

// ------------------------------------------------------------------ live dashboard
export interface Quote {
  price: number | null; change: number | null; change_pct: number | null;
  open: number | null; high: number | null; low: number | null; prev_close: number | null;
  state: string;            // live | delayed | closed | unavailable
  as_of: string | null; age_sec: number | null; error: string | null;
  from_high?: number; from_low?: number; range_pct?: number | null;   // price minus day high / low; position in the day's range
}

export interface Bar {
  t: string; o: number; h: number; l: number; c: number; e9?: number; e21?: number; c_ts?: string;
  vwap?: number | null; v?: number | null; rsi?: number | null; macd?: number | null; macd_signal?: number | null; macd_hist?: number | null;
}

export interface Charges {
  brokerage?: number; stt?: number; exchange?: number; sebi?: number; stamp?: number; gst?: number; total: number;
  [k: string]: number | undefined;
}

export interface Sizing {
  lots: number; lot_size: number; qty: number; limited_by: string;
  risk_budget: number; risk_per_lot: number; cost_per_lot: number;
  lots_by_risk: number; lots_by_cash: number;
  capital: number;
  investment?: number; max_risk?: number; target_profit?: number; stop_loss?: number;
  charges_target?: number; charges_stop?: number; charges_detail?: Charges;
  note?: string;
}

export interface Recommendation {
  verified: boolean;
  error?: string;
  strike?: number; opt_type?: "CE" | "PE"; strike_rule?: string; expiry?: string;
  symbol?: string; lot_size?: number; premium?: number; entry?: number; entry_basis?: string;
  quote_as_of?: string; chain_ltp?: number | null; delta?: number | null; iv?: number | null; oi?: number | null;
  stop?: number; target?: number; atr?: number; nifty_stop?: number; nifty_target?: number;
  sizing?: Sizing; sizing_error?: string;
}

export interface Signal {
  action: "BUY CE" | "BUY PE" | "HOLD";
  direction: "Bullish" | "Bearish" | null;
  since: string | null;
  nifty: number | null;
  reason: string;
  alert?: boolean;
  rec?: Recommendation;
}

export interface Cross { ts: string; direction: number; close: number }

export interface Feed {
  now: string; market: MarketStatus; quote: Quote; timeframe: number;
  entry_start: string; cutoff: string; bars_error: string | null; warnings: string[];
  chart: { day: string | null; bars: Bar[]; forming: Bar | null };
  ema?: { fast: number; slow: number; close: number; bar_close: string; gap: number };
  crosses?: Cross[];
  signal: Signal;
  markers?: { ts: string; kind: string; action: "BUY CE" | "BUY PE" | "EXIT" | "HOLD" }[];
  explain?: Explanation; plan?: TradingPlan | null; patterns?: CandlePattern[]; premiums?: Premiums;
  error?: string; kind?: string;
}

export interface Alert {
  id: number; ts: string; day: string; action: string; mode: string;
  signal_ts?: string; direction?: string | null; nifty?: number | null; reason?: string;
  strike?: number; opt_type?: string; symbol?: string; expiry?: string; premium?: number;
  entry?: number; entry_price?: number | null; exit_price?: number; stop?: number | null; target?: number | null;
  net?: number; score?: number | null; status?: string;
}

export interface Position {
  trading_symbol: string; side: string; direction: string; qty: number; strike: number; opt_type: string;
  expiry: string; entry_price: number; entry_ts: string; ltp: number | null; mtm: number | null;
  exit_failures: number; score: number | null; stop_ref: number | null; target_ref: number | null;
  // paper risk (paper positions only)
  stop_premium?: number; target_premium?: number | null; max_loss?: number; max_loss_pct?: number | null;
  risk_amount?: number; risk_reward?: number | null; nifty_stop?: number | null; nifty_target?: number | null; stop_method?: string;
}

export interface PendingOrder {
  id: string; side: string; trading_symbol: string; strike: number; opt_type: string; expiry: string;
  qty: number; ltp: number | null; nifty: number; signal_ts: string; expires: string;
  stop_ref: number | null; target_ref: number | null;
}

export interface EngineConfig {
  trade_mode: "paper" | "live" | "replay";
  exec_mode: "ITM5_BUY" | "ATM_BUY" | "ATM_SELL";
  timeframe: number; entry_start: string; cutoff: string; lots: number; roll_on_expiry_day: boolean;
  max_daily_loss: number; max_trades_per_day: number;
  signal_mode: "cross" | "trend" | "prediction" | "scalp" | "bias"; strategy: string; min_score: number;
  scalp_config?: string; scalp_exit?: "time" | "sl_target"; hold_min?: number; target_pct?: number;
  order_confirmation: "manual" | "auto";
  // paper trading risk management (ignored by live and replay)
  risk_pct: number; daily_risk_pct: number; max_open_positions: number; max_lots: number; min_balance: number;
  stop_mode: "atr" | "pct" | "points"; stop_atr: number; stop_pct: number; stop_points: number;
}

export type EngineState = "stopped" | "waiting" | "running" | "halted" | "error";

export interface Dashboard {
  state: EngineState;
  day?: string | null;          // the engine session's trading day (a replay's day for replays)
  halt_reason?: string | null;
  config: EngineConfig | null;
  position: Position | null;
  /** Live (real-money) mode only: a position is open. Its details are never sent to the browser. */
  live_position_open?: boolean;
  live_details_hidden?: boolean;
  pending_order?: PendingOrder | null;
  trades_today: number;
  realised_today: number;
  live_max_lots: number;
  confirm_phrase: string;
  replay_day?: string | null;
  market: MarketStatus;
  alerts: Alert[];
  feed: Feed;
}

export interface LiveTrade {
  id: number; trade_mode: string; day: string; exec_mode: string; direction: string; side: string;
  trading_symbol: string; strike: number; opt_type: string; expiry: string; qty: number;
  signal_ts: string | null; entry_ts: string | null; entry_price: number | null;
  exit_ts: string | null; exit_price: number | null; exit_reason: string | null;
  gross: number | null; net: number | null; status: "OPEN" | "CLOSED";
  slippage?: number | null; charges?: Record<string, number> | null;
  risk?: RiskCalc | null; stop_premium?: number | null; target_premium?: number | null; paper_account_id?: number | null;
}

/** The paper risk calculation (options/sizing.risk_size + the engine's checks). */
export interface RiskCalc {
  decision: "TRADE" | "NO TRADE"; reason: string | null; side?: string;
  capital: number; risk_pct: number; risk_amount?: number; available?: number | null; min_balance?: number; max_lots?: number | null;
  entry: number | null; stop: number | null; target?: number | null; lot_size: number | null;
  stop_distance?: number; risk_per_lot?: number; slippage_per_lot?: number; charges_per_lot?: number; cost_per_lot?: number | null;
  lots_by_risk?: number; lots_by_cash?: number | null; lots: number; qty: number; limited_by?: string;
  investment?: number; entry_charges?: number | null; charges?: number; slippage?: number; max_loss?: number; balance_after?: number | null;
  target_profit?: number; risk_reward?: number | null; margin_note?: string;
  stop_method?: string; checks?: Record<string, boolean>; contract?: string; signal_ts?: string; calculated_at?: string;
  balance?: number; day_start_capital?: number; daily_limit?: number | null; pnl_today?: number;
}

export interface PaperRiskSettings {
  risk_pct: number; daily_risk_pct: number; max_daily_loss: number; max_trades_per_day: number; max_open_positions: number;
  max_lots: number; min_balance: number; stop_mode: "atr" | "pct" | "points"; stop_atr: number; stop_pct: number; stop_points: number;
}

export interface PaperAccount {
  account_id: number; starting_capital: number; started_at: string; balance: number; available: number; invested: number;
  realised_total: number; trades_total: number; day: string; day_start_capital: number; realised_today: number;
  mtm: number | null; pnl_today: number; daily_limit: number | null; remaining_risk: number | null; risk_used_pct: number | null;
  open_risk: number; consecutive_losses: number; max_drawdown: number; max_drawdown_pct: number | null;
  risk_pct: number; risk_amount: number; limit_reached: boolean; engine_running: boolean;
  presets: Record<string, number>; settings: PaperRiskSettings; defaults: PaperRiskSettings;
}

// ------------------------------------------------------------------ backtest
export type ModeKey = "ITM5_BUY" | "ATM_BUY" | "ATM_SELL";

export interface Costs { [k: string]: number }

export interface BtParams {
  dataset: string; strategy: string; expiry_rule: string; start_date: string; end_date: string;
  timeframe: number; entry_start: string; cutoff: string; roll_on_expiry_day: boolean;
  lot_size: number; lots: number; capital: number; costs: Costs;
}

export interface BtMeta {
  defaults: BtParams; timeframes: number[]; starts: string[]; cutoffs: string[];
  modes: Record<ModeKey, string>; keys: boolean;
  datasets: Record<string, { first?: string; last?: string; rows?: number; days?: number; stale?: boolean; error?: string }>;
  strategies: Record<string, string>; expiry_rules: Record<string, string>;
}

export interface Metrics {
  trades: number; wins: number; losses: number; win_rate: number;
  gross_pnl: number; friction: number; net_pnl: number;
  profit_factor: number | null; payoff_ratio: number | null; expectancy: number;
  avg_win: number; avg_loss: number; max_drawdown: number; max_drawdown_pct: number;
}

export interface BtTrade {
  id: string; mode: ModeKey; day: string; entry_ts: string; exit_ts: string; direction: "Bullish" | "Bearish";
  strike: number; opt_type: string; side: string; symbol: string; expiry: string; dte: number;
  exit_reason: string; fill_entry_ts: string; fill_exit_ts: string; signal_close: number;
  spot_entry: number | null; spot_exit: number | null; opt_entry: number; opt_exit: number;
  entry_fill: number; exit_fill: number; qty: number; lot_size?: number; lot_source?: string; ordinal: number; bars_held: number; whipsaw: boolean;
  outcome: "win" | "loss"; gross: number; slippage: number; charges: Charges; friction: number; net: number;
}

export interface BtResult {
  params: BtParams; hash: string; generated_at: string; dataset_label: string;
  strategy: string; strategy_label: string; partial_asof: string | null;
  signals: number; trade_days: number;
  summary: Record<ModeKey, Metrics & { label: string; equity_curve: number[] }>;
  trades: Record<ModeKey, BtTrade[]>;
  no_trade_days: { day: string; reason: string }[];
  skipped: { mode: ModeKey; day: string; entry_ts: string; reason: string; strike?: number; opt_type?: string }[];
}

export interface BtChart {
  trade_id: string; spot: Bar[]; option: Bar[]; fast_label?: string; slow_label?: string;
}

// ------------------------------------------------------------------ research
export interface ModeSummary extends Metrics {
  daily: [string, number][];
  yearly: Record<string, { net: number; trades: number; win_rate: number }>;
  monthly: Record<string, number>;
  skipped: number;
}

export interface ResearchCell {
  strategy: string; label: string; timeframe: number;
  start_date: string | null; end_date: string | null; updated: string | null;
  summary: { signals: number; trade_days: number; partial_asof: string | null; modes: Record<ModeKey, ModeSummary> } | null;
}

export interface WalkForward {
  rows: { year: string; trained_on: string; pick: { strategy: string; label: string; timeframe: number };
          insample_net: number; oos_net: number; baseline_net: number;
          hindsight_best: { label: string; timeframe: number; net: number } }[];
  total_oos: number; baseline_total: number; configs?: number;
}

export interface Research { settings: Record<string, unknown>; cells: ResearchCell[]; walk_forward: Record<ModeKey, WalkForward> }

// ------------------------------------------------------------------ signals analysis
export interface Indicator { name: string; value: string; supports: boolean | null }

export interface HistSignal {
  id: string; ts: string; day: string; direction: "Bullish" | "Bearish"; call: string;
  score: number | null; category: string; out_of_sample: boolean;
  entry: number; stop: number; target: number; risk_reward: number; atr: number; expires: string;
  indicators: Indicator[]; reason: string; regime: string;
  comparable: { band: string; n: number; hit_rate: number | null; ci?: [number, number] | null } | null;
  /** Hit rate this score corresponds to, calibrated only on earlier years (null when not yet testable). */
  calibrated?: number | null;
  outcome: string; decided_at: string | null; strong_alert: boolean;
}

export interface CalibBin { from: number; to: number; n: number; mean_score: number | null; hit_rate: number | null; ci?: [number, number] | null }

export interface SignalAnalysis {
  strategy: string; strategy_label: string; timeframe: number; generated_at: string; asof: string;
  counts: { signals: number; labelled: number; oos: number; unconfirmed: number; pending: number };
  model: { base_rate: number | null; auc: number | null; brier: number | null; brier_base: number | null;
           folds: { year: number; train_signals: number; test_signals: number; hit_rate: number | null; auc: number | null }[];
           auc_ci?: [number, number] | null;
           calibration_wf?: { n: number; brier: number | null; brier_base: number | null; skill: number | null;
                              folds: { year: number; n: number; trained_on: number; brier: number | null; brier_base: number | null }[] };
           verdict?: { edge: boolean; text: string } };
  calibration: (CalibBin & { band: string })[];
  reliability?: CalibBin[];
  signals: HistSignal[];
}

// ------------------------------------------------------------------ market data
export interface DataSummary {
  sessions: number; weekdays: number; complete: number; partial: number; no_data: number; not_downloaded: number;
  candles: number; missing_minutes: number; rejected: number; spikes: number; outside_session?: number;
  special_sessions?: number; first: string | null; last: string | null; coverage_pct: number;
}

export interface Period { from: string; to: string; days: number }

export interface Coverage {
  symbol: string; target: { from: string; to: string }; verdict: "none" | "partial" | "full";
  summary: DataSummary;
  months: ({ month: string } & Record<string, number | string>)[];
  not_downloaded: Period[]; no_data: Period[]; special_sessions?: string[];
  partial_days: { day: string; candles: number; missing: number; ranges: string[][] }[];
}

export interface DownloadRun {
  id: number; symbol: string; start_date: string; end_date: string; status: string;
  chunks_total: number; chunks_done: number; rows_received: number; rows_new: number;
  rows_duplicate: number; rows_rejected: number; rows_outside_session?: number;
  error: string | null; started_at: string; finished_at: string | null;
}

export interface Instruments {
  spot: { symbol: string; first: string | null; last: string | null; candles: number; sessions: number; last_success: string | null };
  futures: { contracts: number; last_day: string | null; candles: number; latest_contract: string | null; last: string | null; last_success: string | null };
  options: { contracts: number; first_day: string | null; last_day: string | null; candles: number; last_success: string | null };
  intervals: number[];
}
export interface DataOverview { coverage: Coverage; instruments: Instruments; downloads: DownloadRun[]; job: Job | null }

export interface OptionMonth {
  month: string; contracts: number; contract_days: number; downloaded_days: number; empty_days: number;
  candles: number; complete_contracts: number; pct: number;
}
export interface OptionsCoverage {
  scope: { from: string; to: string; strikes_each_side: number; expiry_rules: string[]; types: string[] };
  summary: Omit<OptionMonth, "month"> & { expiries: number };
  months: OptionMonth[];
  last_run: DownloadRun | null; last_success: string | null; job: Job | null;
}
export interface LotSize { cycle: "weekly" | "monthly"; first_expiry: string; lot_size: number; source: string }

// ------------------------------------------------------------------ live insight (feed)
export interface ExplainCheck {
  key: string; label: string; status: "supports" | "against" | "neutral" | "unavailable"; text: string;
  values: Record<string, number | string | null>;
}
export interface Explanation {
  action?: string; bar_close?: string; direction?: string; summary: string; why?: string; caution?: string | null;
  bullets?: string[]; checks: ExplainCheck[]; note?: string; atr?: number | null;
  confidence?: { score: number | null; band?: string; hit_rate?: number | null; n?: number | null; ci?: [number, number] | null; calibrated?: number | null; edge?: boolean | null; text: string } | null;
}
export interface PlanLevel { name: string; price: number; kind: "support" | "resistance" | "pivot"; source: string }
export interface TradingPlan {
  day: string; computed_at: string; bar_close: string | null; created_at: string; updated_at: string;
  prev_close: number | null; prev_close_candles: number | null; open: number | null; high: number | null; low: number | null;
  trend: string; ema_direction: string | null; vwap_position: string | null; rsi: number | null; volatility: string | null;
  bullish_level: number | null; bearish_level: number | null; opening_range: { high: number; low: number } | null;
  levels: PlanLevel[]; preferred: "bullish" | "bearish" | "none"; votes: { bull: number; bear: number };
  scenarios: { key: string; title: string; active: boolean; conditions: string[] }[];
  entry_rule: string; note: string; changes: { ts: string; reason: string; preferred: string }[];
}
export interface CandlePattern {
  name: string; bias: "bullish" | "bearish" | "neutral"; why: string; status: string; ts: string; close_ts: string;
  o: number; h: number; l: number; c: number; confirmation: Record<string, string | number>; effect: string;
}
export interface StopChange { ts: string; old_stop: number | null; new_stop: number; old_max_loss: number | null; new_max_loss: number; source: string; note: string | null }

// ------------------------------------------------------------------ option chain (Groww, live)
export interface ChainSide {
  symbol: string | null; ltp: number | null; volume: number | null; oi: number | null;
  iv: number | null; delta: number | null; gamma: number | null; theta: number | null; vega: number | null;
  /** From the contract's own Groww quote; null outside the quoted strikes. */
  prev_close: number | null; change: number | null; change_pct: number | null;
  prev_oi: number | null; oi_change: number | null; oi_change_pct: number | null;
}
export interface OptionChain {
  expiry: string; expiries: string[]; days_to_expiry: number; lot_size: number | null;
  spot: { price: number | null; change: number | null; change_pct: number | null; prev_close: number | null; state: string; as_of: string | null };
  underlying_ltp: number | null; atm: number; width: number; quote_width: number;
  rows: { strike: number; atm: boolean; ce: ChainSide | null; pe: ChainSide | null }[];
  totals: { ce_oi: number; pe_oi: number; ce_volume: number; pe_volume: number; pcr: number | null };
  chain_as_of: string | null; chain_error: string | null; quotes_as_of: string | null; quotes_error: string | null; market: string;
}

// ------------------------------------------------------------------ CE / PE premium monitor (Phase 3)
export interface PremiumSide {
  symbol?: string; premium?: number | null; change?: number | null; change_pct?: number | null; prev_close?: number | null;
  volume?: number | null; oi?: number | null; iv?: number | null; delta?: number | null; chain_ltp?: number | null;
  last_trade?: string | null; state: "live" | "delayed" | "closed" | "unavailable"; as_of?: string | null; age_sec?: number | null; error?: string | null;
}
export interface Premiums {
  strike: number | null; expiry: string | null; basis: string | null; days_to_expiry?: number; lot_size?: number | null;
  ce: PremiumSide | null; pe: PremiumSide | null; error: string | null;
}

// ------------------------------------------------------------------ 5-minute scalping analyzer
export interface ScalpStats {
  trades: number; net_pnl: number; gross_pnl: number; win_rate: number; profit_factor: number | null; max_drawdown: number;
  max_drawdown_pct?: number; wins?: number; losses?: number; avg_win?: number; avg_loss?: number; brokerage?: number; taxes?: number;
  slippage?: number; avg_hold_min?: number | null; risk_reward?: number | null; exits?: Record<string, number>; [k: string]: unknown;
}
export interface ScalpGroup { net: number; gross: number; trades: number; win_rate: number }
export interface ScalpConfig extends ScalpStats {
  key: string; strategy: string; strategy_label: string; contract: "ATM_BUY" | "ITM5_BUY"; contract_label: string;
  exit: string; exit_label: string; exit_kind: "time" | "sl_target"; stop: number | null; target: number | null;
  ce: ScalpStats; pe: ScalpStats; yearly: Record<string, ScalpGroup>; monthly?: Record<string, ScalpGroup>; regimes?: Record<string, ScalpGroup>;
  equity?: [string, number][]; skipped: Record<string, number>;
  risk?: Record<string, { trades: number; net_pnl: number; gross_pnl: number; win_rate: number; profit_factor: number | null; max_drawdown: number; max_drawdown_pct: number; brokerage: number; taxes: number; slippage: number; avg_lots: number; too_small: number }>;
  in_sample: { trades: number; net_pnl: number; profit_factor: number | null; max_drawdown: number } | null;
  out_of_sample: { trades: number; net_pnl: number; profit_factor: number | null; max_drawdown: number } | null;
  oos_net: number | null; in_sample_score: number | null; score: number;
  verdict: { consistent: boolean; checks: Record<string, boolean>; years_positive: string };
}
export interface ScalpTrade {
  day: string; signal_ts: string; entry_ts: string; exit_ts: string; hold_min: number; direction: string; opt_type: "CE" | "PE";
  symbol: string; strike: number; expiry: string; lot_size: number; qty: number; spot: number; entry: number; exit: number;
  entry_fill: number; exit_fill: number; reason: string; gross: number; slippage: number; brokerage: number; taxes: number;
  charges: number; friction: number; net: number; regime: string;
}
export interface ScalpExisting {
  strategy: string; label: string; timeframe: number; contract: string; trades: number; net_pnl: number; win_rate: number;
  profit_factor: number | null; max_drawdown: number; years_positive: string;
}
export interface ScalpRun {
  run_id: number; start_date: string; end_date: string; created_at: string; generated_at: string;
  configs: ScalpConfig[]; ranking: string[]; best: string | null; top_in_sample: string | null; split_day: string | null;
  consistent: string[]; selection_rule: string; signals: Record<string, number>; existing: ScalpExisting[];
  walk_forward: { rows: { year: string; trained_on: string; pick: string | null; pick_label: string | null; oos_net: number; oos_trades: number }[]; total_oos: number };
  settings: Record<string, unknown>;
}
export interface ScalpPaperTrade extends LiveTrade { strategy: string | null; scalp_config: string | null; signal_mode: string }

// ------------------------------------------------------------------ automated multi-timeframe paper trading (bias engine)
export type BiasLabel = "STRONG BULLISH" | "BULLISH" | "NEUTRAL" | "BEARISH" | "STRONG BEARISH";
export type VoteStatus = "bullish" | "bearish" | "neutral" | "unavailable";
export type Outcome = "CORRECT" | "INCORRECT" | "NEUTRAL";
export type CandleDir = "UP" | "DOWN" | "NEUTRAL";

export interface BiasIndicatorRow {
  key: string; label: string; weight: number; v5: number | null; v15: number | null; status5: VoteStatus; status15: VoteStatus;
}
export interface ContractCheck { check: string; ok: boolean | null; text: string }
export interface BiasAnalysis {
  bar_close: string; close: number; bias: BiasLabel; confidence: number; combined: number | null;
  trend_5m: "Bullish" | "Bearish" | "Neutral"; trend_15m: "Bullish" | "Bearish" | "Neutral";
  score_5m: number | null; score_15m: number | null; conflict: boolean;
  signal: "BUY CE" | "BUY PE" | "HOLD"; direction: number; prediction: CandleDir;
  atr: number | null; atr_pct: number | null; rsi_5m: number | null; rsi_15m: number | null;
  /** The analysis and confirmation timeframes in minutes; the "5m"/"15m" field names are the analysis and confirmation slots. */
  tf_primary: number; tf_confirm: number; values: Record<string, number | null>;
  indicators: BiasIndicatorRow[]; supports: string[]; against: string[]; hold_reasons: string[]; summary: string; note: string;
  instrument?: string; contract_checks?: ContractCheck[]; entry_premium_seen?: number;
}
export interface BiasHistoryItem {
  bar_close: string; close: number; bias: BiasLabel; confidence: number; signal: string; predicted: CandleDir;
  score_5m: number | null; score_15m: number | null; outcome: Outcome | null;
}
export interface BiasSettings {
  timeframe: number; bias_confirm_tf: number; bias_indicators: string[]; bias_min_confidence: number; bias_trend_thr: number; bias_confirm_thr: number; bias_min_atr_pct: number;
  bias_allow: string[]; bias_exit_opposite: boolean; bias_max_hold_min: number; bias_cooldown_bars: number;
  target_rr: number; trail_pct: number; trail_activate_pct: number; sell_risk_pct: number;
  min_premium: number; min_oi: number; max_spread_pct: number; min_delta: number;
  risk_pct: number; daily_risk_pct: number; max_daily_loss: number; max_trades_per_day: number; max_lots: number; min_balance: number;
  stop_mode: "atr" | "pct" | "points"; stop_atr: number; stop_pct: number; stop_points: number;
  entry_start: string; cutoff: string; exec_mode: "ITM5_BUY" | "ATM_BUY" | "ATM_SELL"; lots: number;
}
export interface BiasConfig {
  defaults: BiasSettings; running: boolean; settings: BiasSettings | null;
  indicators: { key: string; label: string; weight: number }[]; note: string;
}
export interface EngineEvent { ts: string; level: string; message: string }
export interface BiasStatus {
  running: boolean; state?: EngineState; halt_reason?: string | null; trade_mode?: "paper" | "replay"; day?: string | null; now?: string;
  position?: Position | null; realised_today?: number; events?: EngineEvent[]; next_eval?: string | null;
  nifty?: { price: number; ts: string } | null; conn_error?: string | null; session_id?: number | null; config?: Record<string, unknown>;
  bias?: { latest: BiasAnalysis | null; history: BiasHistoryItem[]; trades_today: number; max_trades: number; remaining_trades: number; cooldown_until: string | null } | null;
}
export interface BiasAnalysisResponse {
  as_of_day: string; live: boolean; analysis: BiasAnalysis; futures: boolean; error: string | null;
  recent: { bar_close: string; close: number; bias: BiasLabel; confidence: number; predicted: CandleDir }[];
}
export interface BiasPrediction {
  day: string; bar_close: string; nifty_close: number; bias: BiasLabel; confidence: number; score_5m: number | null; score_15m: number | null;
  signal: string; predicted: CandleDir; next_close: number | null; actual: "UP" | "DOWN" | "FLAT" | null; outcome: Outcome | null;
}
export interface BiasAccuracyRow { key: string; label: string; timeframe: string; correct: number; incorrect: number; neutral: number; n: number; accuracy: number | null }
export interface BiasAccuracy { candles: number; rows: BiasAccuracyRow[]; timeframes?: [number, number]; from?: string; to?: string; note?: string }
export interface BiasTrade extends LiveTrade {
  action: string | null; confidence: number | null; supporting: string[];
  exit_detail?: { reason: string; exit_premium: number; best_premium: number | null; stop_at_exit: number | null; target: number | null;
    bias_at_exit: Partial<BiasAnalysis> } | null;
}
export interface BiasGroup { trades: number; wins: number; losses: number; win_rate: number | null; net: number; gross: number }
export interface BiasSummary extends BiasGroup {
  open: number; mode: string; note: string;
  by_instrument: Record<string, BiasGroup>; by_exit: Record<string, BiasGroup>;
  by_confidence: Record<string, BiasGroup>; by_indicator: Record<string, BiasGroup>;
}
export interface BiasTradeDetail { trade: BiasTrade & { analysis: BiasAnalysis | null }; stop_changes: StopChange[] }

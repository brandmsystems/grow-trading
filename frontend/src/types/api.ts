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
}

export interface Bar { t: string; o: number; h: number; l: number; c: number; e9?: number; e21?: number; c_ts?: string }

export interface Charges {
  brokerage?: number; stt?: number; exchange?: number; sebi?: number; stamp?: number; gst?: number; total: number;
  [k: string]: number | undefined;
}

export interface Sizing {
  lots: number; lot_size: number; qty: number; limited_by: string;
  risk_budget: number; risk_per_lot: number; cost_per_lot: number;
  lots_by_risk: number; lots_by_cash: number;
  capital: number; available: number | null;
  investment?: number; max_risk?: number; target_profit?: number; stop_loss?: number;
  charges_target?: number; charges_stop?: number; charges_detail?: Charges;
  note?: string; margin_error?: string;
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
  signal_mode: "cross" | "prediction"; strategy: string; min_score: number;
  order_confirmation: "manual" | "auto";
}

export type EngineState = "stopped" | "waiting" | "running" | "halted" | "error";

export interface Dashboard {
  state: EngineState;
  day?: string | null;          // the engine session's trading day (a replay's day for replays)
  halt_reason?: string | null;
  config: EngineConfig | null;
  position: Position | null;
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
  comparable: { band: string; n: number; hit_rate: number | null } | null;
  outcome: string; decided_at: string | null; strong_alert: boolean;
}

export interface SignalAnalysis {
  strategy: string; strategy_label: string; timeframe: number; generated_at: string; asof: string;
  counts: { signals: number; labelled: number; oos: number; unconfirmed: number; pending: number };
  model: { base_rate: number | null; auc: number | null; brier: number | null; brier_base: number | null;
           folds: { year: number; train_signals: number; test_signals: number; hit_rate: number | null; auc: number | null }[] };
  calibration: { band: string; from: number; to: number; n: number; mean_score: number | null; hit_rate: number | null }[];
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

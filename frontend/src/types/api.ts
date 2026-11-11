// Shapes returned by the Flask API (see docs/API.md). Times are IST wall-clock ISO strings.

export interface ApiOk<T> { ok: true; data: T }
export interface ApiErr { ok: false; error: string; kind?: string }

export interface MarketStatus { state: "open" | "preopen" | "closed"; label: string }

export interface Quote {
  price: number | null;
  change: number | null;
  change_pct: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
  state: string;            // live | delayed | closed | unavailable
  as_of: string | null;
  age_sec: number | null;
  error: string | null;
}

export interface Bar { t: string; o: number; h: number; l: number; c: number; e9: number; e21: number }

export interface Sizing {
  lots: number; lot_size: number; qty: number; limited_by: string;
  risk_budget: number; risk_per_lot: number; cost_per_lot: number;
  capital: number; available: number | null;
  investment?: number; max_risk?: number; target_profit?: number; stop_loss?: number;
  charges_target?: number; charges_stop?: number;
  note?: string; margin_error?: string;
}

export interface Recommendation {
  verified: boolean;
  error?: string;
  strike?: number; opt_type?: "CE" | "PE"; strike_rule?: string; expiry?: string;
  symbol?: string; lot_size?: number; premium?: number; entry?: number; entry_basis?: string;
  quote_as_of?: string; delta?: number | null; iv?: number | null; oi?: number | null;
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

export interface Feed {
  now: string;
  market: MarketStatus;
  quote: Quote;
  timeframe: number;
  entry_start: string;
  cutoff: string;
  bars_error: string | null;
  warnings: string[];
  chart: { day: string | null; bars: Bar[]; forming: Bar | null };
  ema?: { fast: number; slow: number; close: number; bar_close: string; gap: number };
  crosses?: { ts: string; direction: number; close: number }[];
  signal: Signal;
  error?: string;
  kind?: string;
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
  timeframe: number;
  entry_start: string;
  cutoff: string;
  lots: number;
  roll_on_expiry_day: boolean;
  max_daily_loss: number;
  max_trades_per_day: number;
  signal_mode: "cross" | "prediction";
  strategy: string;
  min_score: number;
  order_confirmation: "manual" | "auto";
}

export interface Dashboard {
  state: "stopped" | "waiting" | "running" | "halted" | "error";
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

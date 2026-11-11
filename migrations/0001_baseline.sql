-- Schema as it existed before migrations were introduced.
CREATE TABLE IF NOT EXISTS candles_1m (
    symbol TEXT NOT NULL,
    ts     TIMESTAMP NOT NULL,
    open   DOUBLE PRECISION, high DOUBLE PRECISION,
    low    DOUBLE PRECISION, close DOUBLE PRECISION,
    volume DOUBLE PRECISION, oi DOUBLE PRECISION,
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS expiries (
    dataset TEXT NOT NULL, expiry DATE NOT NULL, PRIMARY KEY (dataset, expiry)
);
CREATE TABLE IF NOT EXISTS contracts (
    dataset TEXT NOT NULL, symbol TEXT NOT NULL, expiry DATE NOT NULL,
    strike DOUBLE PRECISION NOT NULL, opt_type TEXT NOT NULL,
    PRIMARY KEY (dataset, expiry, strike, opt_type)
);
-- Records (symbol, day) pairs already requested so empty days are not refetched.
CREATE TABLE IF NOT EXISTS fetch_log (
    symbol TEXT NOT NULL, day DATE NOT NULL, rows INTEGER NOT NULL,
    fetched_at TIMESTAMP NOT NULL DEFAULT now(), PRIMARY KEY (symbol, day)
);
CREATE TABLE IF NOT EXISTS live_sessions (
    id SERIAL PRIMARY KEY, trade_mode TEXT NOT NULL, config JSONB NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT now(), stopped_at TIMESTAMP, stop_reason TEXT
);
CREATE TABLE IF NOT EXISTS live_trades (
    id SERIAL PRIMARY KEY, session_id INTEGER, trade_mode TEXT NOT NULL, day DATE NOT NULL,
    exec_mode TEXT NOT NULL, direction TEXT NOT NULL, side TEXT NOT NULL,
    trading_symbol TEXT NOT NULL, groww_symbol TEXT, strike DOUBLE PRECISION, opt_type TEXT,
    expiry DATE, qty INTEGER NOT NULL, signal_ts TIMESTAMP, signal_close DOUBLE PRECISION,
    entry_ts TIMESTAMP, entry_price DOUBLE PRECISION, entry_order_id TEXT,
    exit_ts TIMESTAMP, exit_price DOUBLE PRECISION, exit_order_id TEXT, exit_reason TEXT,
    gross DOUBLE PRECISION, slippage DOUBLE PRECISION, charges JSONB, net DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'OPEN'
);
CREATE TABLE IF NOT EXISTS live_events (
    id SERIAL PRIMARY KEY, session_id INTEGER, ts TIMESTAMP NOT NULL,
    level TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bt_runs (
    id SERIAL PRIMARY KEY, param_hash TEXT UNIQUE NOT NULL,
    params JSONB NOT NULL, result JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

-- One row per notification. alert_key is unique, so the same signal can never alert twice.
CREATE TABLE live_alerts (
    id SERIAL PRIMARY KEY,
    alert_key TEXT UNIQUE NOT NULL,
    session_id INTEGER,
    trade_mode TEXT NOT NULL,
    day DATE NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    action TEXT NOT NULL,          -- BUY CE | BUY PE | SELL CE | SELL PE | SELL | BUY BACK | HOLD
    payload JSONB NOT NULL
);
CREATE INDEX live_alerts_mode_id ON live_alerts (trade_mode, id DESC);

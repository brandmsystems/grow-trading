-- Automated multi-timeframe paper trading (19 Nov 2026): one row per completed 5-minute candle with the
-- bias, the prediction for the next candle and, once that candle has closed, the actual result.
-- Additive only: a new table, and columns added only if missing (an earlier build left some of them in the
-- live database; they stay as they are, a fresh database gets them here).
CREATE TABLE IF NOT EXISTS candle_bias (
    id            BIGSERIAL PRIMARY KEY,
    trade_mode    TEXT NOT NULL,                 -- paper | replay
    scope         INTEGER NOT NULL DEFAULT 0,    -- replay session id (0 for paper), so replays never overwrite each other
    day           DATE NOT NULL,
    bar_close     TIMESTAMPTZ NOT NULL,          -- close time of the 5-minute candle the analysis used
    nifty_close   DOUBLE PRECISION,
    bias          TEXT NOT NULL,
    confidence    DOUBLE PRECISION,              -- percent agreement between indicators (not a probability of winning)
    score_5m      DOUBLE PRECISION,
    score_15m     DOUBLE PRECISION,
    combined      DOUBLE PRECISION,
    signal        TEXT,                          -- BUY CE | BUY PE | HOLD
    predicted     TEXT NOT NULL,                 -- UP | DOWN | NEUTRAL (the next 5-minute candle)
    votes         JSONB,                         -- {"5m": {indicator: vote}, "15m": {...}}
    analysis      JSONB,                         -- the full explanation (indicator values, reasons)
    next_close    DOUBLE PRECISION,              -- filled when the next candle has closed
    actual        TEXT,                          -- UP | DOWN | FLAT
    outcome       TEXT,                          -- CORRECT | INCORRECT | NEUTRAL
    settled_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (trade_mode, scope, bar_close)
);
CREATE INDEX IF NOT EXISTS candle_bias_day_idx ON candle_bias (day, bar_close);

ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS action TEXT;
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION;
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS analysis JSONB;
ALTER TABLE live_trades ADD COLUMN IF NOT EXISTS exit_detail JSONB;

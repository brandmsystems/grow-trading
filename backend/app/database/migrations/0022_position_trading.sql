-- Position Trading (26 Nov 2026): a separate virtual account, its multi-day paper positions, the daily decision history and the module's settings.
-- Additive only: four new tables, nothing existing is touched or altered (a verified pg_dump was taken first: data/backups/pre_position_trading_2026-11-26.dump).
-- Paper only: nothing here is read by, or can reach, the live trading engine.
CREATE TABLE IF NOT EXISTS position_accounts (
    id          SERIAL PRIMARY KEY,
    capital     DOUBLE PRECISION NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at   TIMESTAMPTZ,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS position_trades (
    id             SERIAL PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES position_accounts(id),
    signal_key     TEXT NOT NULL,                   -- strategy | decision day | direction: one entry per signal per account
    strategy       TEXT NOT NULL,
    direction      TEXT NOT NULL,                   -- Bullish (BUY CE) | Bearish (BUY PE)
    opt_type       TEXT NOT NULL,
    expiry         DATE NOT NULL,
    strike         DOUBLE PRECISION NOT NULL,
    trading_symbol TEXT NOT NULL,
    lot_size       INTEGER NOT NULL,
    lots           INTEGER NOT NULL,
    qty            INTEGER NOT NULL,
    decision_day   DATE NOT NULL,
    score          DOUBLE PRECISION,
    entry_ts       TIMESTAMPTZ NOT NULL,
    entry_price    DOUBLE PRECISION NOT NULL,
    stop_premium   DOUBLE PRECISION NOT NULL,
    target1        DOUBLE PRECISION NOT NULL,
    target2        DOUBLE PRECISION,
    invalidation   DOUBLE PRECISION,
    planned_exit   DATE,
    forced_exit    DATE,
    status         TEXT NOT NULL DEFAULT 'OPEN',    -- OPEN | CLOSED
    best_premium   DOUBLE PRECISION,
    last_price     DOUBLE PRECISION,
    last_price_at  TIMESTAMPTZ,
    t1_hit         BOOLEAN NOT NULL DEFAULT FALSE,
    exit_ts        TIMESTAMPTZ,
    exit_price     DOUBLE PRECISION,
    exit_reason    TEXT,
    gross          DOUBLE PRECISION,
    slippage       DOUBLE PRECISION,
    charges        JSONB,
    net            DOUBLE PRECISION,
    risk           JSONB,                           -- the sizing calculation (risk percent, capital, max loss)
    analysis       JSONB,                           -- score components, contract comparison and plan at entry
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (account_id, signal_key)
);
CREATE INDEX IF NOT EXISTS position_trades_status_idx ON position_trades (status, account_id);

CREATE TABLE IF NOT EXISTS position_decisions (
    day         DATE PRIMARY KEY,                   -- the completed daily bar the decision was made on
    decided_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision    TEXT NOT NULL,                      -- STRONG BUY CE | BUY CE | STRONG BUY PE | BUY PE | HOLD | NO TRADE
    direction   INTEGER NOT NULL DEFAULT 0,
    score       DOUBLE PRECISION,
    strategies  JSONB,                              -- strategies that fired
    reasons     JSONB,                              -- why (and, for NO TRADE / HOLD, the exact reasons)
    analysis    JSONB
);

CREATE TABLE IF NOT EXISTS position_settings (
    version   SERIAL PRIMARY KEY,
    config    JSONB NOT NULL,
    saved_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    note      TEXT
);

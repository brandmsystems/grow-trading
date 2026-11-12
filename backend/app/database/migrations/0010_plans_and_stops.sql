-- Today's trading plan: one row each time the plan changes, with the reason.
CREATE TABLE trading_plans (
    id        SERIAL PRIMARY KEY,
    day       DATE NOT NULL,
    timeframe INTEGER NOT NULL,
    ts        TIMESTAMPTZ NOT NULL,
    preferred TEXT NOT NULL,
    reason    TEXT NOT NULL,
    plan      JSONB NOT NULL
);
CREATE INDEX trading_plans_day ON trading_plans (day, timeframe, id);

-- Every stop-loss set or changed on a paper position: the initial stop at entry, and each edit.
CREATE TABLE paper_stop_changes (
    id           SERIAL PRIMARY KEY,
    trade_id     INTEGER NOT NULL REFERENCES live_trades (id),
    ts           TIMESTAMPTZ NOT NULL,
    old_stop     DOUBLE PRECISION,
    new_stop     DOUBLE PRECISION NOT NULL,
    old_max_loss DOUBLE PRECISION,
    new_max_loss DOUBLE PRECISION NOT NULL,
    source       TEXT NOT NULL,             -- entry | user
    note         TEXT
);
CREATE INDEX paper_stop_changes_trade ON paper_stop_changes (trade_id, id);

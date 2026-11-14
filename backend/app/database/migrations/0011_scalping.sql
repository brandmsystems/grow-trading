-- 5-minute scalping analyzer (13 Nov 2026): one row per full run, and the trade list of each
-- configuration in that run (kept apart so the summary loads quickly).
CREATE TABLE scalp_runs (
    id SERIAL PRIMARY KEY,
    settings JSONB NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE scalp_trades (
    run_id INTEGER NOT NULL REFERENCES scalp_runs (id) ON DELETE CASCADE,
    config TEXT NOT NULL,
    trades JSONB NOT NULL,
    PRIMARY KEY (run_id, config)
);

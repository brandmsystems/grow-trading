-- Compact results of full-history runs, one row per strategy x timeframe x settings.
CREATE TABLE strategy_results (
    id SERIAL PRIMARY KEY,
    strategy TEXT NOT NULL,
    timeframe INTEGER NOT NULL,
    settings_hash TEXT NOT NULL,
    settings JSONB NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    summary JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (strategy, timeframe, settings_hash)
);

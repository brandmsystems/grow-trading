-- One row per download attempt, so failures are visible and can be resumed.
CREATE TABLE data_downloads (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',   -- running | done | failed | stopped | interrupted
    chunks_total INTEGER NOT NULL DEFAULT 0,
    chunks_done INTEGER NOT NULL DEFAULT 0,
    rows_received INTEGER NOT NULL DEFAULT 0,
    rows_new INTEGER NOT NULL DEFAULT 0,
    rows_duplicate INTEGER NOT NULL DEFAULT 0,
    rows_rejected INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ
);

-- One row per requested day: what actually arrived and how good it is.
CREATE TABLE data_day_quality (
    symbol TEXT NOT NULL,
    day DATE NOT NULL,
    candles INTEGER NOT NULL,
    missing_minutes INTEGER NOT NULL,
    missing_ranges JSONB NOT NULL DEFAULT '[]',
    rejected INTEGER NOT NULL DEFAULT 0,
    spikes INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,                     -- complete | partial | in_progress | no_data
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, day)
);

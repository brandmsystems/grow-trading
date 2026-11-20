-- Pre-market analysis (19 Nov 2026): one report per trading day (the five factors, the total, the conclusion, every
-- recalculation that changed it, and after the close what NIFTY actually did), plus figures entered by hand for sources
-- no script can read (FII/DII, scheduled events). Additive only: two new tables, nothing existing is touched.
CREATE TABLE IF NOT EXISTS premarket_reports (
    day           DATE PRIMARY KEY,
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_score   INTEGER NOT NULL,              -- -5 .. +5
    bias          TEXT NOT NULL,
    preference    TEXT NOT NULL,                 -- BUY CE | BUY PE | HOLD (a lean, never an order)
    confidence    INTEGER,
    report        JSONB NOT NULL,                -- factors, news, conclusion, warnings, data times
    snapshots     JSONB NOT NULL DEFAULT '[]',   -- {at, total, scores} each time a recalculation changed the result
    actual        JSONB,                         -- NIFTY open/high/low/close and direction, filled after the close
    outcome       TEXT                           -- CORRECT | INCORRECT | NEUTRAL, filled after the close
);

CREATE TABLE IF NOT EXISTS premarket_inputs (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,                   -- fii_dii | event
    for_day     DATE NOT NULL,                   -- fii_dii: the trading day the figures describe; event: the day it happens
    payload     JSONB NOT NULL,
    source      TEXT,
    entered_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS premarket_inputs_idx ON premarket_inputs (kind, for_day, entered_at DESC);

-- Trading Settings (21 Nov 2026): the centrally managed strategy, timeframe, indicator and risk configuration of the paper-trading engine.
-- Additive only: one new table, nothing existing is touched. Append-only: every save is a new version, so the configuration an order
-- was placed under can always be read back. The current configuration is the row with the highest version; with no rows the code's
-- defaults apply (version 0).
CREATE TABLE IF NOT EXISTS trading_settings (
    version   SERIAL PRIMARY KEY,
    config    JSONB NOT NULL,
    saved_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    note      TEXT                       -- 'saved' | 'reset to defaults'
);

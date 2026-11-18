-- PENDING, NOT APPLIED. Needs explicit approval (see docs/DATABASE.md, "Orphaned tables").
-- Drops six tables left over from features removed on 18 Nov. No code reads or writes them,
-- and nothing has a foreign key to or from them.
-- Backup (verified by restoring into a scratch database): data/backups/orphan_tables_2026-11-18.dump
-- To apply: copy this file to backend/app/database/migrations/0018_drop_orphan_tables.sql.
-- Rollback: 0018_drop_orphan_tables.down.sql, then restore data from the dump.
-- DROP TABLE IF EXISTS makes it safe on fresh databases, which never had these tables.
-- NOT touched: live_trades keeps its nine leftover columns (trading records are never altered).
DROP TABLE IF EXISTS app_settings, candle_forecasts, pattern_events, prediction_log, smc_setups, strategy_signals;

# Database

**Setup:** PostgreSQL 17, database `groww_trading`. Connection settings come from `.env` (`PG_*`).

**Migrations:** SQL files in `backend/app/database/migrations/` are applied in order by `db.init()` at startup, inside one transaction guarded by an advisory lock. Each one is recorded in `schema_migrations`. To change the schema, add the next numbered file; never edit an applied one.

**Time zone:** all timestamp columns are `TIMESTAMPTZ`. Every connection sets `timezone=Asia/Kolkata`, and a type caster turns timestamps into IST wall-clock datetimes for the app.

## Migrations
| File | Change |
|---|---|
| 0001_baseline | Original tables (below) |
| 0002_timestamptz | All timestamps → `TIMESTAMPTZ` (existing values read as IST) |
| 0003_data_management | `data_downloads`, `data_day_quality` |
| 0004_outside_session | Out-of-hours candle counts kept apart from invalid ones |
| 0005_strategy_results | `strategy_results` |
| 0006_prediction_trades | Score/stop/target/ATR columns on `live_trades` |
| 0007_live_alerts | `live_alerts` |
| 0008_lot_sizes | `lot_sizes`, seeded from NSE circulars 47854, 61415, 64625 and 70616 |
| 0009_paper_risk | `paper_accounts`; `live_trades.risk` (JSONB), `stop_premium`, `target_premium`, `paper_account_id` |
| 0010_plans_and_stops | `trading_plans` (each plan change with its reason), `paper_stop_changes` (initial and edited paper stops) |
| 0011_scalping | `scalp_runs` (settings, date range and summary JSON of each 5-minute scalping run), `scalp_trades` (trade list per run and configuration) |
| 0012_scalp_paper | `live_trades.strategy`, `live_trades.scalp_config` (set for scalp-mode engine trades) |
| 0019_bias_engine | `candle_bias` (one row per analysed candle: bias, confidence, scores, prediction, votes, analysis, and once settled the next close, actual move and outcome); `live_trades.action`, `confidence`, `analysis`, `exit_detail` added if missing (this database already had them) |
| 0021_trading_settings | `trading_settings` (version, config JSONB, saved_at, note): the centrally managed Trading Settings, append-only so every order can be traced to the version it ran under. New table only; a verified `pg_dump` (`data/backups/pre_trading_settings_2026-11-21.dump`, 1,050 MB, git-ignored) was taken (note: the migration ran when the app was first started in the session, a few minutes before the dump; it only creates one empty table and the existing rows were unchanged: 28 trades) |
| 0020_premarket | `premarket_reports` (one row per day: score, bias, report JSON, snapshots, and after the close what NIFTY did and the outcome) and `premarket_inputs` (FII/DII figures and events entered by hand). New tables only |

## Tables
| Table | Key | Holds |
|---|---|---|
| `candles_1m` | (symbol, ts) | 1-minute OHLCV + OI. Symbols: `NSE-NIFTY` (spot), `NSE-NIFTY-<ddMonyy>-FUT`, options `NSE-NIFTY-<ddMonyy>-<strike>-<CE/PE>`. Synthetic `SYNTH:*` rows exist only in the throwaway test databases |
| `fetch_log` | (symbol, day) | Days already requested from Groww, so they aren't downloaded twice |
| `expiries` | (dataset, expiry) | Groww expiry dates; dataset `groww_fut` = confirmed monthly futures expiries |
| `contracts` | (dataset, expiry, strike, opt_type) | Option symbols from Groww's contract lists |
| `data_downloads` | id | Each download attempt: status, counts, error. Option history runs use symbol `NIFTY-OPTIONS` (chunks = contract requests, `rows_rejected` = failed requests) |
| `data_day_quality` | (symbol, day) | Candles, missing minutes and ranges, rejected/out-of-hours counts, status |
| `lot_sizes` | (underlying, cycle, first_expiry) | NIFTY lot size by expiry cycle (weekly/monthly) and first expiry it applies to, with the NSE circular as `source` |
| `bt_runs` | param_hash | Cached backtest results and signal analyses (JSONB) |
| `strategy_results` | (strategy, timeframe, settings_hash) | Compact five-year comparison results |
| `live_sessions` | id | Each engine start: mode, config, stop reason |
| `live_trades` | id | Engine trades: contract, entry/exit, P&L, charges, signal mode, score, stop/target. Paper trades also store the pre-trade risk calculation (`risk`), the enforced premium stop, the target and their virtual account |
| `trading_plans` | id | Today's trading plan each time it changes: day, timeframe, time, preferred direction, reason, full plan (JSONB) |
| `paper_stop_changes` | id | Paper stop-loss history per trade: time, old/new stop, old/new maximum loss, source (entry or user) |
| `paper_accounts` | id | Virtual paper accounts: starting capital, start and close time. The active one has `closed_at` NULL; balance = capital + closed paper net P&L booked to it |
| `live_events` | id | Engine event log |
| `trading_settings` | version | Trading Settings: every saved configuration of strategies, timeframes, indicators and rules (JSONB), saved time and note. Append-only; the current one is the highest version |
| `candle_bias` | id, unique (`trade_mode`, `scope`, `bar_close`) | Automated paper trading: the analysis and next-candle prediction of every closed candle, settled with the actual result. `scope` is the replay session id (0 for paper) so replays never overwrite each other |
| `live_alerts` | id, unique `alert_key` | Notifications, stored once per signal |
| `schema_migrations` | version | Applied migrations |

## Stored data (12 Nov 2026)
| Data | Amount |
|---|---|
| NIFTY 1-minute candles | 462,805 (11 Nov 2021 → today) |
| Monthly futures contracts | 63 |
| Option contracts | 21,750 with candles (100% of the 21,702-contract ATM ±10 scope, plus earlier backtest contracts); 67.1 M option candles, 53.5 M with OI |
| Database size | 15 GB |
| Comparison results | 28 with the fixed lot of 65, plus 28 with NSE lot sizes |

**Synthetic rows removed (12 Nov 2026):** 223,305 `SYNTH:` candles, 515 fetch-log rows, 316 contracts, 18 expiries and 1 cached run were exported to `data/backups/synthetic_2026-11-12_*.csv.gz` and then deleted. The 4 synthetic engine trades in `live_trades` are kept (trade history is never deleted); the app already excludes them.

### Orphaned tables (investigated 18 Nov; **nothing dropped, approval required**)
Checked against backend, frontend, tests, docs, every migration file, SQL strings and the live database (foreign keys in and out, views, dependent objects). No code, migration file, view or foreign key references any of them.

| Table | Rows | Size | Dependencies | Why it is orphaned |
|---|---|---|---|---|
| `candle_forecasts` | 55 | 360 kB | none | Next-candle forecast, removed 18 Nov |
| `prediction_log` | 36 | 240 kB | none | Automated prediction paper trading, removed 18 Nov |
| `strategy_signals` | 2 | 64 kB | none | Prediction-system signal log, removed 18 Nov |
| `smc_setups` | 0 | 32 kB | none | SMC strategy, removed 18 Nov |
| `pattern_events` | 0 | 32 kB | none | Candle-pattern paper trading, removed 18 Nov |
| `app_settings` | 0 | 16 kB | none | Never read by the app |

**Why a fresh install differs from this database:** `schema_migrations` lists 17 versions, but only `0001`-`0012` exist as files. `0013_advanced_prediction`, `0014_candle_forecasts`, `0015_pattern_events`, `0016_smc_setups` and `0017_trend_vwap_ema` were applied here and their files were deleted with the features (they were never committed). A fresh database built from the repo has none of these six tables, so the drop migration uses `DROP TABLE IF EXISTS`. The same migrations also added nine columns to `live_trades` that only this database has: `action, analysis, confidence, exit_detail, forecast_id, lots, pattern_event_id, signal_id, smc_setup_id` (all NULL in all 27 rows; since 19 Nov the automated engine writes `action`, `confidence`, `analysis` and `exit_detail` for its own trades, and migration `0019` adds those four to fresh databases; the other five are still unused). Trading records are never altered, so they stay.

**Backup (taken before any removal):** `data/backups/orphan_tables_2026-11-18.dump` (custom format, 80 kB): the six tables plus `live_trades`. Verified by restoring it into a scratch database and comparing row counts with production (all equal: 55, 0, 0, 36, 0, 2 and 27 for `live_trades`); the scratch database was then dropped. Restoring only the tables back later: `pg_restore --data-only -d groww_trading -t <table> <dump>`.

**Prepared, not applied:** `backend/app/database/pending/0018_drop_orphan_tables.up.sql` and `.down.sql` (the rollback recreates the tables, their sequences, keys and indexes empty). Both were executed against an empty scratch database: the down script created the six tables, the up script removed them. The migration runner reads only `database/migrations/`, so nothing applies them until you approve and copy the up file there as `0018_drop_orphan_tables.sql`. A fresh full `pg_dump` of the 15 GB database was not taken because only these tables would change.

## Safety
- **Nothing is deleted** by the app except cached backtest runs, which are cleared when new data arrives (signal analyses are kept).
- **Backup:** `pg_dump -U postgres groww_trading > data/exports/groww_trading.sql`.

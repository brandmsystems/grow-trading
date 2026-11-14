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

## Safety
- **Nothing is deleted** by the app except cached backtest runs, which are cleared when new data arrives (signal analyses are kept).
- **Backup:** `pg_dump -U postgres groww_trading > data/exports/groww_trading.sql`.

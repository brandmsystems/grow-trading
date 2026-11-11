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

## Tables
| Table | Key | Holds |
|---|---|---|
| `candles_1m` | (symbol, ts) | 1-minute OHLCV + OI. Symbols: `NSE-NIFTY` (spot), `NSE-NIFTY-<ddMonyy>-FUT`, options `NSE-NIFTY-<ddMonyy>-<strike>-<CE/PE>`, and `SYNTH:*` (test data, hidden from the app) |
| `fetch_log` | (symbol, day) | Days already requested from Groww, so they aren't downloaded twice |
| `expiries` | (dataset, expiry) | Groww expiry dates; dataset `groww_fut` = confirmed monthly futures expiries |
| `contracts` | (dataset, expiry, strike, opt_type) | Option symbols from Groww's contract lists |
| `data_downloads` | id | Each download attempt: status, counts, error |
| `data_day_quality` | (symbol, day) | Candles, missing minutes and ranges, rejected/out-of-hours counts, status |
| `bt_runs` | param_hash | Cached backtest results and signal analyses (JSONB) |
| `strategy_results` | (strategy, timeframe, settings_hash) | Compact five-year comparison results |
| `live_sessions` | id | Each engine start: mode, config, stop reason |
| `live_trades` | id | Engine trades: contract, entry/exit, P&L, charges, signal mode, score, stop/target |
| `live_events` | id | Engine event log |
| `live_alerts` | id, unique `alert_key` | Notifications, stored once per signal |
| `schema_migrations` | version | Applied migrations |

## Stored data (11 Nov 2026)
| Data | Amount |
|---|---|
| NIFTY 1-minute candles | 462,595 (11 Nov 2021 → today) |
| Monthly futures contracts | 61 |
| Option contracts cached | ~7,900 |
| Comparison results | 28 |

## Safety
- **Nothing is deleted** by the app except cached backtest runs, which are cleared when new data arrives (signal analyses are kept).
- **Backup:** `pg_dump -U postgres groww_trading > data/exports/groww_trading.sql`.

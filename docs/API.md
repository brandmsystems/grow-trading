# Backend API

**Base URL:** `http://127.0.0.1:5000`.

**Response format:** every JSON endpoint answers `{"ok": true, "data": ...}`. On failure it answers `{"ok": false, "error": "message", "kind": "ErrorType"}` with HTTP 400 (bad input), 404, 409 (already running), 500 or 502 (Groww/upstream). `kind: "keys"` means the Groww credentials are missing.

**Long tasks** return `{"ok": true, "job": "<id>"}`. Poll `GET /api/jobs/<id>`; it returns `state` (queued, running, done, error), `progress` (0–1), `message`, and `result` or `error`.

## Account: `api/account.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Whether credentials are configured |
| POST | `/api/login` | Force a fresh Groww login |
| POST | `/api/logout` | Drop the cached token |
| GET | `/api/profile` | Groww user profile |
| GET | `/api/funds` | Groww margin and funds |

## Backtest: `api/backtest.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/bt/meta` | Defaults, timeframes, entry/cutoff choices, modes, strategies, expiry rules, stored-data summary |
| POST | `/api/bt/data` | Download data for a backtest range (job). Body: backtest params |
| POST | `/api/bt/run` | Run a backtest (job, or `{"hash", "cached": true}`). Body: `strategy`, `timeframe`, `start_date`, `end_date`, `entry_start`, `cutoff`, `expiry_rule`, `roll_on_expiry_day`, `lot_size` (0 = each contract's NSE lot size, the default; >0 = fixed), `lots`, `capital`, `costs`, `force` |
| GET | `/api/bt/result/<hash>` | Full result: params, per-mode summary, trades, no-trade days, skipped trades |
| GET | `/api/bt/chart/<hash>/<trade_id>` | One trade's spot bars (with fast/slow EMA) and option candles |
| GET | `/api/jobs/<id>` | Job progress |

## Data: `api/data.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/data/overview?from=&to=` | Spot coverage report, `instruments` (spot, futures and options: counts, first/last candle, last successful download, intervals), download history, running job |
| POST | `/api/data/download` | Body `{"from", "to"}`: spot + futures download (job) |
| POST | `/api/data/stop` | Stop the running download after its current request |
| GET | `/api/data/candles?from=&to=&tf=` | Stored NIFTY candles at 1/5/15/30 minutes |
| GET | `/api/data/options?from=&to=` | Option history coverage for the ATM ±10 scope: per month contracts, contract-days planned vs downloaded, empty days, candles; last run and last successful run; running job |
| POST | `/api/data/options/download` | Body `{"from", "to"}`: download option candles still missing (job, own lane; 409 while any download runs). `POST /api/data/stop` stops it |
| GET | `/api/data/lot-sizes` | NIFTY lot-size history: cycle, first expiry, lot size, NSE circular |

## Research and signals: `api/research.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/research?entry_start=&cutoff=` | All strategy × timeframe results and walk-forward |
| POST | `/api/research/run` | Compute missing configurations (job, research lane) |
| GET | `/api/signals?strategy=&tf=` | Stored signal analysis (or `null`) |
| POST | `/api/signals/build` | Body `{"strategy", "tf"}`: build the analysis (job) |

## Live: `api/live.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/live/status?mode=&tf=&strategy=` | Engine state, position, P&L, config, market status, recent alerts, NIFTY/EMA snapshot |
| GET | `/api/live/dashboard?tf=&entry_start=&cutoff=&exec_mode=&roll=&capital=&risk_pct=&mode=` | All of the above plus the live feed. `tf` 1, 5, 15 or 30. Feed contents:<br>• quote, now with `from_high`, `from_low`, `range_pct`<br>• chart bars with EMA 9/21, `vwap`, `v`, `rsi`, `macd`, `macd_signal`, `macd_hist`<br>• `markers` (BUY CE / BUY PE / EXIT / HOLD)<br>• signal, with `explain` (checks with actual values, confidence, why, caution)<br>• `plan` (today's plan, levels, scenarios, change history)<br>• `patterns` (candle patterns on closed bars, with status and effect)<br>• verified option contract and premium, stop/target, sizing |
| POST | `/api/live/start` | Body `{"config": {...}, "confirm": "LIVE", "replay_day", "replay_speed"}`. Live mode requires `confirm` and respects `LIVE_MAX_LOTS` |
| POST | `/api/live/confirm` | Body `{"id"}`: place the live entry order waiting for confirmation (409 if it expired or the engine can't enter) |
| POST | `/api/live/reject` | Body `{"id"}`: skip it; no order is placed |
| POST | `/api/live/stop` | Square off and stop |
| POST | `/api/live/squareoff` | Square off; the engine keeps running |
| GET | `/api/live/trades?mode=&day=` | Engine trades |
| GET | `/api/live/broker` | Groww's own F&O positions (for comparison) |

**Engine config fields:**
- `trade_mode` (paper, live, replay), `exec_mode` (ITM5_BUY, ATM_BUY, ATM_SELL)
- `timeframe` (5, 15, 30), `entry_start`, `cutoff`
- `lots`, `max_daily_loss`, `max_trades_per_day`, `roll_on_expiry_day`
- `signal_mode` (cross, prediction), `strategy`, `min_score`
- `order_confirmation` (manual, auto), default `manual`. It only affects Live mode; Paper and Replay fill automatically.

The status payload includes `pending_order` (id, side, contract, qty, LTP, signal time, `expires`) while a live order waits for confirmation.

## Paper risk: `api/paper.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/paper/account` | Virtual account (balance, available, starting capital) and today's risk monitor: starting daily capital, P&L, daily limit, remaining risk, consecutive losses, max drawdown, open-position risk, risk used %; presets; current and default risk settings |
| POST | `/api/paper/account` | Body `{"capital", "confirm": "RESET"}`: start a new virtual account (409 while a paper position is open). Old trades keep their account |
| POST | `/api/paper/position/stop` | Body `{"stop"}`: change the open paper position's stop-loss. 400 with the reason if it is on the wrong side of the current premium, or would exceed the trade's risk amount or today's remaining loss limit; 409 when no paper engine runs |
| GET | `/api/paper/stop-changes?trade_id=` | That trade's stop-loss history |
| POST | `/api/paper/risk-calc` | Body `capital`, `risk_pct`, `entry`, `stop` or `stop_pct`, `lot_size`, `max_lots`, optional `side`, `available`, `min_balance`, `target`: the same calculation the paper engine runs (decision, reason and every figure) |

Engine config adds paper-only fields: `risk_pct` (1), `daily_risk_pct` (3), `max_open_positions` (1), `max_lots` (10), `min_balance` (0), `stop_mode` (`atr`/`pct`), `stop_atr` (1), `stop_pct` (30). `/api/live/trades` rows include `risk`, `stop_premium`, `target_premium`, `paper_account_id`.

## React app (`api/frontend.py`)
`GET /app`, `/app/<path>` serve the built React app from `frontend/dist`. Unknown paths fall back to `index.html` for client-side routes. Nothing outside `dist` is ever served. If the app hasn't been built, it returns 404 with build instructions.

## Old page addresses (`api/pages.py`)
`/`, `/live`, `/signals`, `/compare`, `/data`, `/history`, `/account` and `/backtest` redirect (302) to the matching React page under `/app`. The server-rendered pages themselves were removed on 12 Nov.

## Planned (Phase 6)
WebSocket events over Flask-SocketIO: `quote`, `signal`, `alert`, `engine`. Not implemented yet.

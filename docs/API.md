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
| POST | `/api/bt/run` | Run a backtest (job, or `{"hash", "cached": true}`). Body: `strategy`, `timeframe`, `start_date`, `end_date`, `entry_start`, `cutoff`, `expiry_rule`, `roll_on_expiry_day`, `lot_size`, `lots`, `capital`, `costs`, `force` |
| GET | `/api/bt/result/<hash>` | Full result: params, per-mode summary, trades, no-trade days, skipped trades |
| GET | `/api/bt/chart/<hash>/<trade_id>` | One trade's spot bars (with fast/slow EMA) and option candles |
| GET | `/api/jobs/<id>` | Job progress |

## Data: `api/data.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/data/overview?from=&to=` | Coverage report, download history, running job |
| POST | `/api/data/download` | Body `{"from", "to"}`: spot + futures download (job) |
| POST | `/api/data/stop` | Stop the running download after its current request |
| GET | `/api/data/candles?from=&to=&tf=` | Stored NIFTY candles at 1/5/15/30 minutes |

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
| GET | `/api/live/dashboard?tf=&entry_start=&cutoff=&exec_mode=&roll=&capital=&risk_pct=&mode=` | All of the above plus the live feed: quote, chart bars, signal, verified option contract and premium, stop/target, sizing |
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

## React app (`api/frontend.py`)
`GET /app`, `/app/<path>` serve the built React app from `frontend/dist`. Unknown paths fall back to `index.html` for client-side routes. Nothing outside `dist` is ever served. If the app hasn't been built, it returns 404 with build instructions.

## Legacy pages: `api/pages.py`, plus `/live` in `api/live.py`
`/`, `/compare`, `/signals`, `/data`, `/history`, `/account`, `/live` serve the server-rendered pages until React replaces them.

## Planned (Phase 6)
WebSocket events over Flask-SocketIO: `quote`, `signal`, `alert`, `engine`. Not implemented yet.

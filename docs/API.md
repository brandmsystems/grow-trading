# Backend API

**Base URL:** `http://127.0.0.1:5000` (set the `PORT` environment variable to use another port).

**Privacy (18 Nov):** the API never returns your real Groww account data: no profile, funds or margin (`/api/profile`, `/api/funds` were removed), no broker positions (`/api/live/broker` was removed), no real-money trades, order ids or P&L. In Live mode the engine status carries `live_position_open: true` instead of the position and `realised_today: 0`, the event log shows "Live order activity (details are not shown)" for fills, and live alerts lose price, quantity, P&L and fill times. Only the proposal waiting for your confirmation (side, contract, quantity) and halts/errors stay visible, because live safety depends on them. See [GROWTRADING.md](../GROWTRADING.md#privacy).

**Access rules (all routes, `api/common.reject_foreign_requests`):** there is no login, because the server only listens on 127.0.0.1. Instead:
- the `Host` header must be `127.0.0.1`, `localhost` or `::1` (any port), otherwise **403** (stops DNS-rebinding pages);
- a POST/PUT/DELETE that carries an `Origin` header must come from a loopback page, otherwise **403**. Browsers send `text/plain` POSTs across sites without a preflight, and the endpoints accept any content type, so without this check a web page open in your browser could post to `/api/live/start`.

**Bodies:** POST bodies are JSON objects (`api/common.json_body`). Malformed JSON or a non-object answers a JSON 400. Every HTTP error under `/api` (404, 405, 400...) uses the same `{"ok": false, ...}` envelope.

**Response format:** every JSON endpoint answers `{"ok": true, "data": ...}`. On failure it answers `{"ok": false, "error": "message", "kind": "ErrorType"}` with HTTP 400 (bad input), 404, 409 (already running), 500 or 502 (Groww/upstream). `kind: "keys"` means the Groww credentials are missing.

**Long tasks** return `{"ok": true, "job": "<id>"}`. Poll `GET /api/jobs/<id>`; it returns `state` (queued, running, done, error), `progress` (0–1), `message`, and `result` or `error`.

## Account: `api/account.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/status` | Whether credentials are configured |
| POST | `/api/login` | Force a fresh Groww login |
| POST | `/api/logout` | Drop the cached token |

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
| GET | `/api/signals?strategy=&tf=` | Stored signal analysis (or `null`). Version 3 adds `model.auc_ci`, `model.calibration_wf` (walk-forward Brier vs average, per year), `model.calibrator`, `model.verdict`, a 95% `ci` on each band and reliability group, and `calibrated` on each signal. Older (v2) analyses are not served; rebuild them |
| POST | `/api/signals/build` | Body `{"strategy", "tf"}`: build the analysis (job) |
| GET | `/api/bias/config` | Automated paper trading: form defaults, the 12 indicators (label, weight) and the running engine's settings |
| GET | `/api/bias/status` | Engine state, latest analysis (bias, confidence, trends, prediction, every indicator's votes), recent history, position, daily counters, events |
| GET | `/api/bias/analysis` | The bias now (or at the last close) from stored and live candles, with or without the engine running (cached 15 s) |
| POST | `/api/bias/start` | Body `{"trade_mode": "paper"\|"replay", "config"?, "replay_day"?, "replay_speed"?}`. Anything else is a 400; the engine refuses live mode, so no real order is possible |
| POST | `/api/bias/pause`, `/api/bias/resume` | Stop / allow new entries; an open position is still managed. 409 when the engine is not running. `bias.automation` in the status says what the engine is doing (`phase`, `label`, `detail`, `paused`, `target_hits`, ...) |
| POST | `/api/bias/settings` | Change the running engine's settings without a restart. The whole configuration is validated first; a bad value changes nothing. `timeframe` cannot change while running |
| POST | `/api/paper/position/target` | Body `{"target"}`: change the open paper position's target premium (must stay on the profit side of the current premium) |
| GET | `/api/bias/predictions?day=&mode=&limit=&session=` | Stored candle analyses with the prediction and, once known, the actual next-candle result, newest first |
| GET | `/api/bias/accuracy?mode=&from=&to=` | Next-candle hit rate of the combined bias and of each indicator on the analysis and confirmation timeframes, from stored predictions; `timeframes` gives the real minutes |
| GET | `/api/bias/history-accuracy?from=&to=&tf=&confirm=` | The same table recomputed over stored candles (default last 60 days, at most 800); no market calls |
| GET | `/api/bias/trades?day=&mode=&session=` | Automated trades (paper/replay only, order ids removed) with confidence and supporting indicators |
| GET | `/api/bias/summary?day=&mode=` | Wins, losses, win rate, net P&L; by instrument, exit reason, confidence band and supporting indicator |
| GET | `/api/bias/trade/<id>` | One trade's complete reasoning: analysis at entry, contract checks, risk calculation, stop changes, exit detail |
| GET | `/api/scalping` | Latest 5-minute scalping run: every configuration (summary fields), ranking, best, consistency list, walk-forward, existing-strategy comparison; `job` if a run is active. `data` is `null` before the first run |
| GET | `/api/scalping/config?key=` | One configuration in full (monthly, yearly, regimes, CE/PE, equity, risk sizing) plus `trade_list` |
| POST | `/api/scalping/run` | Re-run the whole analysis (job `scalping`, research lane) |
| POST | `/api/scalping/paper/start` | Body `{"key", "mode": "paper"\|"replay", "replay_day"?, "risk": {risk_pct, daily_risk_pct, max_trades_per_day, max_lots, max_daily_loss, min_balance}}`. Starts the engine in scalp mode on a tested configuration. `live` is refused |
| GET | `/api/scalping/paper/trades?key=&mode=` | Engine trades opened in scalp mode, newest first |

Details: [SCALPING.md](SCALPING.md).

## Live: `api/live.py`
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/live/status?mode=&tf=&strategy=` | Engine state, position, P&L, config, market status, recent alerts, NIFTY/EMA snapshot |
| GET | `/api/live/dashboard?tf=&entry_start=&cutoff=&exec_mode=&roll=&capital=&risk_pct=&mode=` | All of the above plus the live feed. `tf` 1, 5, 15 or 30. Feed contents:<br>• quote, now with `from_high`, `from_low`, `range_pct`<br>• chart bars with EMA 9/21, `vwap`, `v`, `rsi`, `macd`, `macd_signal`, `macd_hist`<br>• `markers` (BUY CE / BUY PE / EXIT / HOLD)<br>• signal, with `explain` (checks with actual values, confidence, why, caution)<br>• `plan` (today's plan, levels, scenarios, change history)<br>• `patterns` (candle patterns on closed bars, with status and effect)<br>• verified option contract and premium, stop/target, sizing<br>• `premiums` (Phase 3): live CE and PE for one strike (the recommended one, else ATM of the strategy's expiry): premium, change, change %, previous close, volume, OI, last trade, IV and delta (market open only), and `state` live / delayed / closed / unavailable |
| GET | `/api/options/chain?expiry=&width=` | Live NIFTY option chain from Groww around ATM (`width` strikes each side, default 10, max 20; `expiry` defaults to the nearest). Per strike, CE and PE: LTP, volume, OI, IV, delta, gamma, theta, vega (from Groww's chain), plus previous close, change, change %, previous OI, OI change and OI change % for ATM ±5 (from each contract's Groww quote; `null` elsewhere). Also the expiry list, spot (separate from premiums), ATM, days to expiry, NSE lot size, totals and a calculated put/call OI ratio, and `chain_as_of` / `quotes_as_of` with any errors. 400 for an unlisted expiry, 502 if Groww fails. Cached: chain 10 s, quotes 60 s (10 min when closed) |
| POST | `/api/live/start` | Body `{"config": {...}, "confirm": "LIVE", "replay_day", "replay_speed"}`. Live mode requires `confirm` and respects `LIVE_MAX_LOTS` |
| POST | `/api/live/confirm` | Body `{"id"}`: place the live entry order waiting for confirmation (409 if it expired or the engine can't enter) |
| POST | `/api/live/reject` | Body `{"id"}`: skip it; no order is placed |
| POST | `/api/live/stop` | Square off and stop |
| POST | `/api/live/squareoff` | Square off; the engine keeps running |
| GET | `/api/live/trades?mode=&day=` | Paper and replay trades, without order ids. `mode=live` returns `[]` and real-money trades are never included |

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

## Real-time push (Socket.IO, `api/realtime.py`, Phase 3)
Path `/socket.io`, WebSocket transport, served by the same Flask process (`socketio.run`). Same origin only (127.0.0.1/localhost on 5000 and 5173).

| Direction | Event | Payload |
|---|---|---|
| server → client | `hello` | `{server_time, heartbeat_stale_sec}` on connect |
| client → server | `subscribe` | The `/api/live/dashboard` parameters (`tf`, `mode`, `exec_mode`, `capital`, `risk_pct`, `entry_start`, `cutoff`, `roll`). Validated the same way; resubscribing with new settings moves the client to the new room |
| server → client | `dashboard` | `{seq, room, server_time, data}`: `data` is exactly the `/api/live/dashboard` payload (NIFTY spot, CE/PE premiums, signal, engine status, position, P&L, alerts). Sent straight after `subscribe` and whenever the content changes |
| server → client | `heartbeat` | `{seq, room, server_time, error}` when nothing changed; `error` if building the data failed (the last good data stays) |
| server → client | `subscribe_error` | `{error}` for invalid settings |

**Behaviour:**
- Clients with identical settings share a room, and each room is computed once per tick: every 1 s while the market is open or an engine is running, otherwise every 5 s. Groww calls stay behind the feed's caches.
- Change detection ignores clock-only fields (`now`, `age_sec`, `computed_at`...). Every event has a per-room `seq`; the client drops anything not newer.
- Socket.IO ping every 10 s (timeout 10 s). The client treats no event for `heartbeat_stale_sec` (15 s) as stale.
- When disconnected or stale, the client falls back to REST polling; it reconnects automatically (1–10 s backoff) and subscribes again.

## Pre-market analysis (`api/premarket.py`)
Information only; nothing here places an order. Details: [PREMARKET.md](PREMARKET.md).

| Route | Purpose |
|---|---|
| GET `/api/premarket/report?day=` | The stored report of a day (default today) or `report: null`, thresholds, unavailable sources |
| GET `/api/premarket/news?refresh=` | Live news: analysed articles (summary, image, source, time, sentiment, NIFTY direction, impact level, why, sectors, indices, categories, period, related coverage, original link), category counts, today's events, per-source state, `status` live / stale / unavailable and the fetch time. `refresh=1` skips the two-minute cache |
| POST `/api/premarket/refresh` | Fetch outside data again and recalculate today's report |
| POST `/api/premarket/input` | `{kind: "fii_dii", day, fii_net_cash, dii_net_cash, fii_index_fut_long, fii_index_fut_short, source}` (day must be before today) or `{kind: "event", title}`; recalculates at once |
| GET `/api/premarket/history` | Stored days with the actual NIFTY day, outcome, paper result, accuracy so far, and paper trades grouped by whether the bias agreed |

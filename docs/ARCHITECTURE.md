# Architecture

## Overview

```
 Browser ──HTTP──► Flask (backend/app.py, port 5000)
                    ├─ api/            blueprints: thin request/response handling
                    ├─ services/       all logic (no Flask imports)
                    │    groww ──► Groww Trade API (login, candles, quotes, option chain, orders)
                    │    market_data ─ history (PostgreSQL) + live (Groww) + feed (dashboard)
                    │    strategy     ─ rules, indicators, strategies, signal engine
                    │    options      ─ contract lookup, position sizing
                    │    trading      ─ charges, brokers (orders), engine, manager
                    │    backtest     ─ backtest engine, metrics, research
                    │    notifications─ alerts (stored once per signal)
                    ├─ workers/jobs    background jobs (downloads, backtests, research)
                    └─ database        PostgreSQL 17 (groww_trading), SQL migrations
```

## Layers and rules
1. **API layer (`app/api`):** parses parameters, calls one service, returns JSON `{"ok": true, "data": ...}` or `{"ok": false, "error": ..., "kind": ...}`.
2. **Services:** hold all trading logic. Calculations (`strategy/rules`, `indicators`, `charges`, `metrics`) are pure functions with no I/O.
3. **Separation the spec requires:**

| Concern | Module |
|---|---|
| Historical market data | `market_data/history.py`, `providers.py` |
| Live market data | `market_data/live.py`, `feed.py` |
| Options contract selection | `strategy/rules.option_for` (strike) + `options/contracts.py` (chain lookup) + `market_data/live.contract` |
| Strategy signals | `strategy/rules.generate_legs`, `strategies.py`, `signals.py` |
| Position sizing | `options/sizing.py` |
| Brokerage and charges | `trading/charges.py` |
| Order execution | `trading/brokers.py` |
| Stop-loss / target rules (pure) | `trading/stops.py` |
| Engine settings and validation | `trading/engine_config.py` |
| Live signal state, market hours, data checks (pure) | `market_data/signal_state.py` |
| Scalping statistics and walk-forward (pure) | `backtest/scalping_stats.py` |
| Performance reporting | `backtest/metrics.py`, `research.py` |

4b. **Trading Settings:** one persisted configuration (`services/trading/trading_settings.py`, table `trading_settings`) that every entry passes through (`Engine._settings_gate`) and that the `configured` entry strategy applies live; see [TRADING_SETTINGS.md](TRADING_SETTINGS.md).
4a. **Automated bias mode:** `strategy/bias.py` analyses the whole series in one pass (the engine uses the last row, the prediction log and the validation scripts use the same code); it is causal and paper/replay only. It is a separate signal mode of the same engine, so paper risk sizing, stops, charges, the daily loss limit and the 15:00 square-off are reused, not duplicated. See [AUTO_TRADING.md](AUTO_TRADING.md).
4b. **Pre-market analysis:** `services/premarket/` (sources, pure scoring, service) builds one report per day from Yahoo Finance, Google News, stored NIFTY candles and hand-entered FII/DII figures; a background thread refreshes it from 08:30 IST and settles it after the close. The engine reads the stored result through `premarket.stamp()` only to log (or, if you choose, to skip opposed trades); it never creates an entry from it. See [PREMARKET.md](PREMARKET.md).
4. **One source of trading rules:** the backtester, the live/paper engine and the live feed all call `strategy/rules.generate_legs`. A test replays days through the engine and requires the same trades as the backtest.
5. **Local-only access:** the server binds to 127.0.0.1 and `api/common.reject_foreign_requests` refuses foreign `Host` and cross-site `Origin` values (see API.md).
6. **Privacy:** real-money details never reach the browser. `services/privacy.py` redacts the engine status (the single `Engine.status()` choke point, so REST and WebSocket are covered), live alerts and trade rows; there are no endpoints for the Groww profile, funds or positions, and the feed never reads your margin (sizing uses the capital you enter or the paper account). The database keeps every record.
7. **Order safety:** only `trading/brokers.LiveBroker` places orders.
   - It is used only when Live mode was started with the `LIVE` confirmation and within `LIVE_MAX_LOTS`.
   - **By default every live entry waits for your confirmation** (`Engine._propose` → `POST /api/live/confirm`), and it lapses with its signal.
   - Protective exits stay automatic.

## Data flow
- **History:**
  1. Data page → `POST /api/data/download` → job → `history.download_all`
  2. Groww candles → validated → `candles_1m`
  3. Quality recorded in `data_day_quality`
  4. The live market refreshes spot **and** near-month futures once a day, and stores today's completed futures candles as it reads them
- **Option history:**
  1. Data page → `POST /api/data/options/download` → job (options lane) → `options_history.download`
  2. Plan: each stored session's spot low/high → ATM ±10 strikes, CE and PE, for every expiry a backtest can pick
  3. One Groww request per contract window (≤30 days) → `candles_1m`; each requested day logged in `fetch_log` (0 rows = no trades)
- **Backtest:**
  1. `POST /api/bt/run` → job → `backtest/engine.run`
  2. Spot from the DB → strategy legs → option contracts (Groww, cached) → NSE lot size of the contract (`lot_sizes`) → charges → metrics
  3. Result cached in `bt_runs`
- **Live:**
  1. `trading/manager` starts one `Engine(market, broker)`
  2. Each signal bar → `generate_legs` (or prediction score) → broker order → `live_trades`
  3. An alert is recorded in `live_alerts`

## Frontend ↔ backend
- **React app** (`frontend/`, served at `/app`):
  - calls the REST API through `src/services/api.ts`
  - the live dashboard receives `dashboard` events over Socket.IO (`/socket.io`, see API.md, Real-time push); REST polling of `GET /api/live/dashboard` (2 s open / 10 s closed, with backoff) is the fallback while the socket is down or stale
  - in development, Vite (5173) proxies `/api` and `/socket.io` to Flask (5000)
- **One interface:** the old server-rendered pages were removed; `/` and old addresses redirect to `/app`.
- **Server:** `backend/app.py` runs `socketio.run` (Werkzeug, threads, `simple-websocket`) on 127.0.0.1:5000.

See [FRONTEND.md](FRONTEND.md).

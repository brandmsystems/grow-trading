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
| Performance reporting | `backtest/metrics.py`, `research.py` |

4. **One source of trading rules:** the backtester, the live/paper engine and the live feed all call `strategy/rules.generate_legs`. A test replays days through the engine and requires the same trades as the backtest.
5. **Order safety:** only `trading/brokers.LiveBroker` places orders. It is used only when Live mode was started with the `LIVE` confirmation and within `LIVE_MAX_LOTS`. Per-order manual confirmation is planned ([TODO.md](TODO.md)).

## Data flow
- **History:**
  1. Data page → `POST /api/data/download` → job → `history.download_all`
  2. Groww candles → validated → `candles_1m`
  3. Quality recorded in `data_day_quality`
- **Backtest:**
  1. `POST /api/bt/run` → job → `backtest/engine.run`
  2. Spot from the DB → strategy legs → option contracts (Groww, cached) → charges → metrics
  3. Result cached in `bt_runs`
- **Live:**
  1. `trading/manager` starts one `Engine(market, broker)`
  2. Each signal bar → `generate_legs` (or prediction score) → broker order → `live_trades`
  3. An alert is recorded in `live_alerts`

## Frontend ↔ backend
- **Now:** the legacy pages poll the JSON API (e.g. the Live page polls `/api/live/dashboard` every few seconds).
- **Planned (Phases 5–6):**
  - a React app (Vite) calls the same REST endpoints
  - Flask-SocketIO pushes live quotes, signals and alerts
  - the client reconnects automatically
  - in development, Vite proxies `/api` and `/socket.io` to port 5000

See [FRONTEND.md](FRONTEND.md).

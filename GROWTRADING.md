# Grow Trading: master documentation

The complete record of Grow Trading: what it does, how it's built, what has been verified, and what's pending. Detailed topics live in [docs/](docs/); this file summarises them and links to each.

*Last updated: 11 Nov 2026, after Phase 5 (React live dashboard).*

---

## 1. Status

| Area | Status |
|---|---|
| Groww connection | **Working:** paid Trading API plan, TOTP key, token roles include `live_data` and `back_test` |
| Historical data | **Done:** NIFTY spot and near-month futures, 1-minute, 11 Nov 2021 → today; validated |
| Strategies, backtest, comparison | **Done:** 7 strategies × 4 timeframes, all 28 computed with real option prices |
| Signal engine | **Done:** scores tested only on years the model hadn't seen |
| Paper / replay engine (crossover and prediction modes) | **Done and tested** |
| Live (real-money) engine | Built with safety rails. **Every entry order waits for your confirmation by default**; tested on replays, no real order placed yet |
| Alerts | Stored once per signal (`live_alerts`), shown on the Live page |
| Backend restructure (Phases 1–4) | **Done:** `backend/app`, blueprints, services split |
| React frontend (Phase 5) | **Live dashboard done** at `/app`. The other six pages are still the server-rendered versions |
| WebSocket updates (Phase 6) | **Not started** |
| Tests | **140 pass**; React production build and type check pass |
| Git | `main` has the baseline; all later work is on branch `level-1-data`, committed per phase |

**Main research finding:** after real option prices and all costs, 82 of 84 strategy × mode results lost money over five years. The two positive ones, EMA 20/50 on 30m, are close to break-even. See [docs/BACKTESTING.md](docs/BACKTESTING.md).

---

## 2. Install and run
Full steps: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

```powershell
cd frontend; npm install; npm run build   # once, and after frontend changes
python start.py                         # http://127.0.0.1:5000 (React dashboard at /app)
cd backend; ..\.venv\Scripts\python -m pytest     # tests
```

**Credentials:** `GROWW_API_KEY` + `GROWW_TOTP_SECRET` in `.env`, or `keys.txt` in the project root. Both are git-ignored and never logged or documented.

**Configuration:** `.env` (template: [.env.example](.env.example)). Variables are listed in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## 3. Architecture
Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md).

```
backend/app/
  api/            Flask blueprints: account, backtest, data, research, live, pages (+ common helpers)
  config/         settings: paths, PostgreSQL, credentials (env first, keys.txt fallback)
  database/       engine (Asia/Kolkata), migration runner, queries, migrations/0001–0007
  services/
    groww/          Groww login and API calls
    market_data/    history (download/validate), providers, live market, live dashboard feed
    options/        option-chain lookup, position sizing
    strategy/       9/21 rules, indicators, 7 strategies, signal engine
    trading/        charges, brokers (order execution), engine, manager
    backtest/       backtest engine, metrics, comparison/walk-forward
    notifications/  alerts (stored once per signal)
  workers/        background jobs
  utils/          shared helpers
backend/legacy/   server-rendered pages, removed as React replaces each one
frontend/src/     React: pages/, components/{dashboard,charts,trading,common}/, hooks/, services/, context/, types/, utils/
backend/tests/    pytest suite
data/             historical/, exports/, logs/ (git-ignored)
docs/             documentation
```

**Communication:**
- **Now:** the React app calls the REST API. The live dashboard polls `/api/live/dashboard` with backoff and automatic recovery ([docs/API.md](docs/API.md)).
- **Planned (Phase 6):** Socket.IO push ([docs/FRONTEND.md](docs/FRONTEND.md)).

---

## 4. Features

### Data ([docs/BACKTESTING.md](docs/BACKTESTING.md))
- **Downloads:** resumable, with duplicate detection and validation.
- **Out-of-hours candles** are kept apart, and gaps are listed, never filled.
- **Pages:** Data (coverage, missing periods, download history) and History (candlestick chart).

### Strategy and backtesting ([docs/STRATEGY.md](docs/STRATEGY.md))
- **Rules:** EMA crossover on closed bars, fill at the next minute's open, inclusive entry window, opposite-cross exit/reversal, 15:00 square-off.
- **Strategies:** seven (9/21, 5/20, 8/21, 20/50, and 9/21 + VWAP/RSI/MACD) on 1/5/15/30-minute bars.
- **Execution modes:** ITM 5 buy, ATM buy, ATM sell. Expiry rules: nearest, next or monthly.
- **Costs:** slippage plus the full charge stack.
- **Prices:** real option candles only; a missing candle skips the trade.
- **Compare page:** all 28 configurations, with yearly/monthly P&L, win rate, drawdown, equity curves and walk-forward.

### Signals and prediction
- **Signals page:** entry reference, stop (1 × ATR), target (2 × ATR), indicator checklist, score with the hit rate its band achieved on unseen data, strong-alert rule.
- **Prediction mode** in the engine trades only signals scoring at or above your minimum. Live scores were verified to match offline scores exactly.

### React live dashboard (`/app`)
- **Shows:** NIFTY price, 5-minute candles with EMA 9/21 and crossovers, trend, BUY CE / BUY PE / HOLD with the verified contract, live premium, entry/stop/target, lots and quantity, investment and risk, today's P&L, connection and market status.
- **Notifications:** sound, browser alert and flash, once per signal.
- **Engine controls:** with live-order confirmation. Details: [docs/FRONTEND.md](docs/FRONTEND.md).

### Live / paper / replay engine
- **Modes:** Paper (Groww prices, simulated fills), Live (MIS market orders), Replay (stored day, fast clock).
- **Safety:**
  - `LIVE` confirmation and `LIVE_MAX_LOTS`
  - **each live entry order needs your confirmation** (default; automatic entries are an opt-in for each start)
  - daily loss limit and trades-per-day limit
  - stale-signal skip and restart recovery
  - exit retries, and an ERROR state on unconfirmed orders
  - Check Groww positions
- **Alerts:** BUY CE / BUY PE / SELL CE / SELL PE / SELL (exit) / BUY BACK / HOLD, each stored once.

---

## 5. Groww integration
Details: [docs/GROWW_API.md](docs/GROWW_API.md).
- **Calls used:** login (TOTP or key + secret), historical candles (spot, futures, expired options from 2020), expiries, contracts, LTP/quote, option chain, margin, orders and order status, positions.
- **Free plan:** returns 403 for all market data.
- **Expired-contract lists can miss strikes,** so the standard symbol is used.

---

## 6. Database
Details: [docs/DATABASE.md](docs/DATABASE.md).

**Setup:** PostgreSQL 17 `groww_trading`, 7 migrations, timestamps in IST.

**Main tables:**

| Group | Tables |
|---|---|
| Market data | `candles_1m`, `fetch_log`, `expiries`, `contracts` |
| Downloads and quality | `data_downloads`, `data_day_quality` |
| Research cache | `bt_runs`, `strategy_results` |
| Engine | `live_sessions`, `live_trades`, `live_events`, `live_alerts` |

**No existing records were deleted during the restructure.**

---

## 7. API
All endpoints with parameters: [docs/API.md](docs/API.md).

| Area | Prefix |
|---|---|
| Account | `/api/status`, `/api/login`, `/api/logout`, `/api/profile`, `/api/funds` |
| Backtest | `/api/bt/*`, `/api/jobs/<id>` |
| Data | `/api/data/*` |
| Research | `/api/research*`, `/api/signals*` |
| Live | `/api/live/*` |

---

## 8. Tests
- **Count:** 140 tests in `backend/tests` (10 files), all passing after Phase 5.
- **Baseline before the restructure:** 134 passing. Added since: env-var credentials (1), live order confirmation (3), React app serving (2).
- **Frontend:** `npm run build` (type check + production build) passes.
- **What they cover:** credentials, trading rules, charges, providers, backtest end-to-end, data manager, research and signals, live engine (it must equal the backtest), prediction mode, alerts, live feed.
- **Not yet tested:** WebSocket updates (Phase 6). The React dashboard was checked in a browser at desktop and phone width against live Groww data and a replay.

---

## 9. Restructure log (Grow Trading)
| Phase | Result |
|---|---|
| 1. Inspect | Baseline of 134 tests; no circular imports; duplicates and the mixed Live page found |
| 2. Dependencies | Mapping from every old file to its new module (see [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md), "Previously" column) |
| 3. Structure | `backend/`, `frontend/` (pending), `data/`, `scripts/`, `docs/`, `start.py`, `.env.example` |
| 4. Backend migration | `git mv` + mechanical import rewrite, no logic changes. Then blueprints, brokers/options/notifications split, shared helpers, env credentials, Grow Trading naming. 135 tests pass, and all pages and APIs answer |
| 5. React | Live dashboard at `/app` with engine controls and live-order confirmation. Other pages next |
| 6. WebSockets | Not started |
| 7. Verification | Backend done; frontend pending |
| 8. Docs | This file, README and docs/* updated |

**Decisions recorded:**
- Every page is ported to React, and legacy pages are removed one by one.
- Live orders need a manual confirmation per order by default.
- The work is committed at each phase.

Dated details: [docs/CHANGELOG.md](docs/CHANGELOG.md).

---

## 10. Known issues and pending work
Full list: [docs/TODO.md](docs/TODO.md).

**Pending:**
- port the remaining six pages to React
- Socket.IO push (Phase 6)
- remove `backend/legacy/` after porting

**Known issues:**
- **Legacy `/live` page:** mixed from two sessions' edits; superseded by `/app`.
- **No holiday calendar.**
- **Lot size:** fixed for all years.
- **Prediction rule:** its option P&L hasn't been backtested.

**Not a guarantee:** the app supports decisions. Past results don't predict future returns, and no strategy tested here was clearly profitable after costs.

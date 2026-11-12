# Grow Trading: master documentation

The complete record of Grow Trading: what it does, how it's built, what has been verified, and what's pending. Detailed topics live in [docs/](docs/); this file summarises them and links to each.

*Last updated: 12 Nov 2026, Phase 1 (historical data) of the master programme.*

---

## 1. Status

| Area | Status |
|---|---|
| Groww connection | **Working:** paid Trading API plan, TOTP key, token roles include `live_data` and `back_test` |
| Historical data | **Done:** NIFTY spot and near-month futures, 1-minute, 11 Nov 2021 → today; validated. Option history (ATM ±10, CE/PE, all expiries) downloading; NSE lot-size history stored |
| Strategies, backtest, comparison | **Done:** 7 strategies × 4 timeframes, all 28 computed with real option prices |
| Signal engine | **Done:** scores tested only on years the model hadn't seen |
| Paper / replay engine (crossover and prediction modes) | **Done and tested** |
| Live (real-money) engine | Built with safety rails. **Every entry order waits for your confirmation by default**; tested on replays, no real order placed yet |
| Alerts | Stored once per signal (`live_alerts`), shown on the Live page |
| Backend restructure (Phases 1–4) | **Done:** `backend/app`, blueprints, services split |
| React frontend (Phase 5 + redesign) | **All 9 pages in React** at `/app`: sidebar layout, colour system, notifications, phone/tablet/desktop. The old server-rendered pages were removed on 12 Nov; this is the only interface. |
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
  database/       engine (Asia/Kolkata), migration runner, queries, migrations/0001–0008
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

### React app (`/app`)
- **Pages:** Overview, Live Trading, Trading Signals, Options Analysis, Backtesting, Strategy Comparison, Market Data, Historical Charts, Account & Settings.
- **Layout:** collapsible sidebar on desktop, icon rail on tablets, bottom bar and drawer on phones. The header shows Groww connection, market status, engine state and a notification bell.
- **Colours:** green for gains, BUY and CE; red for losses and PE; blue for spot; purple for strategy; orange for risk.
- **Live Trading:** spot vs option premium shown separately; chart with EMA 9/21, crossovers, trade markers and stop/target lines; recommendation; order calculator; controls with live-order confirmation.
- **Notifications:** sound, browser alert, flash and badge, once per signal.
- **Backend limitations** (single recommended contract, no option chain endpoint, NIFTY-only history) are stated on the pages.

Details: [docs/FRONTEND.md](docs/FRONTEND.md).

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
- **Frontend:**
  - `npm run build` (type check + production build) passes
  - all 9 pages at 6 widths (1920–360 px): no overflow and no console errors
  - controls and notifications checked in a real browser
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
| 5. React | All pages in React after the frontend redesign (sidebar layout, 54/54 responsive checks pass). Live-order confirmation in the UI |
| 6. WebSockets | Not started |
| 7. Verification | Backend done; frontend pending |
| 8. Docs | This file, README and docs/* updated |

**Decisions recorded:**
- Every page is ported to React; the old server-rendered pages were removed on 12 Nov at your request. `/` and old addresses redirect to `/app`.
- Live orders need a manual confirmation per order by default.
- The work is committed at each phase.

Dated details: [docs/CHANGELOG.md](docs/CHANGELOG.md).

---

## 10. Phase 0 audit (12 Nov 2026): master programme

Read-only audit before the "master development" programme. No working code was changed.

### Baseline claims checked
| Claim | Verified result |
|---|---|
| Groww paid API works | **Yes.** Token roles: `order`, `live_data`, `non_trading`, `order_read_only`, `back_test` |
| 5 years of NIFTY spot + futures 1-minute data | **Yes for spot:** 462,743 candles, 11 Nov 2021 → today, 1,229 complete days, 8 partial (4 special sessions + 4 real Groww gaps), 72 no-data weekdays. **Futures: 61 contracts, but stale** (see issues) |
| 7 strategies × 4 timeframes, 28 configurations computed | **Yes:** 28 rows in `strategy_results` |
| Signal scoring with out-of-sample testing | **Yes:** 4 stored analyses (5/15/30m EMA 9/21 + one other) |
| Paper and replay engines tested; live confirmation | **Yes** in tests (manual confirmation, limits, retries, error state). **No real Groww order has been placed yet** |
| Alerts stored and shown | **Yes:** `live_alerts` (unique key) |
| 9 React pages | **Yes;** type check passes |
| 7 migrations | **Yes:** 0001–0007 applied |
| 140 tests | **Yes: 140 passed** (365 s) |
| WebSockets pending | **Confirmed:** `flask-socketio` not installed, no socket code |

### Data integrity (database)
- **Spot candles:** 0 duplicates, 0 invalid OHLC rows, 0 out-of-hours candles stored. The only index is the `(symbol, ts)` primary key, which fits every current query.
- **Size:** `candles_1m` is 3.07 GB.
- **Options:** 7,927 contracts, 12.7 M candles, 16 Nov 2021 → today, with OI.
  - **Only the contracts that backtests needed** (ATM / ITM 5 at each signal). This is not a full option chain.
  - 1,426 of 36,713 contract-days returned no candles.
- **Expiries:** 269 weekly/monthly (2021-11-03 → 2026-12-29), including 61 confirmed monthly futures expiries. The contracts table has 54,294 symbols across 263 expiries.
- **Test data in the live database:** 223,305 synthetic `SYNTH:` candles, unused by the app.

### Groww capabilities (verified live, 12 Nov, market open)
| Capability | Available | Used by the app today |
|---|---|---|
| Option chain per expiry (all strikes: LTP, OI, volume, IV, delta/gamma/theta/vega/rho) | **Yes** (264 strikes for 17 Nov) | Only to verify the recommended strike |
| Option quote: LTP, day change, % change, volume, OI, OI change | **Yes** | LTP only |
| Greeks per contract | **Yes** | No |
| Expired option candles with OI (back to Nov 2021) | **Yes** | Yes, per backtest need |
| Expired contract lists | Yes, but some strikes are missing | Standard symbol used as fallback |
| **Historical lot sizes** | **No** (the instrument master knows only current contracts) | Phase 1: taken from NSE circulars (`lot_sizes`) |
| **Historical option-chain snapshots (IV/Greeks history)** | **No** | n/a |
| Real-time feed (`GrowwFeed` in the SDK) | **Available, not used** | The app polls instead |

### Gaps and issues found
1. **Futures are stale (bug)** (**fixed in Phase 1**). 11 Nov futures stop at 14:50 and today's are missing. Automatic refreshes (`GrowwProvider.ensure_spot`) update spot only, so VWAP/volume strategies and signal features read incomplete futures.
2. **CE/PE premiums:** the live feed returns one recommended contract. Groww's chain has live CE **and** PE premiums, change, volume, OI, OI change, IV and Greeks, none of which the app exposes yet.
3. **No option-chain or expiry-list endpoint** for the frontend.
4. **Historical lot sizes are not modelled** (**fixed in Phase 1**): NIFTY's lot size has changed several times since 2021. Backtest P&L uses one size for every year, so per-year rupee figures are scaled wrong for years with a different lot size. Groww has no lot-size history, so an authoritative source (NSE circulars) is needed.
5. **No Telegram integration:** only a mention in `notifications/alerts.py`.
6. **No WebSockets:** polling every 2 s (open) or 10 s (closed).
7. **Live chart:** EMA 9/21 only. No VWAP, volume, RSI or MACD panels; no 1-minute live chart (the feed accepts 5/15/30).
8. **Duplicates:**
   - `manager.snapshot()` (used by `/api/live/status`) and `feed.Feed` both compute a NIFTY quote and EMAs.
   - `_now()` in 3 modules (kept because tests patch each one).
   - Legacy server-rendered pages still served alongside React (**removed on 12 Nov**).
9. **Live trading:** never exercised against Groww with a real order.
10. **Synthetic test candles** (223k rows) sit in the production database (**removed in Phase 1**, backup kept).

### Proposed plan (each phase stops at its gate for review)
| Phase | Work | Needs your decision |
|---|---|---|
| 1. Data | Fix the futures refresh. Add an index-free coverage report for futures and options. Option-chain history download (scope below). Contract metadata table (symbol, expiry, strike, type, lot size, source). Historical lot-size table from NSE circulars. Remove synthetic rows from the production DB | **Option-history scope; lot-size source; deleting synthetic rows** |
| 2. Research | Backtests use the historical lot size (changes ₹ results); calibration per band shown on screen; option-analysis endpoints (chain, expiries, CE+PE) | **Approve re-running results with historical lot sizes** |
| 3. Live + WebSockets | Flask-SocketIO push (spot, CE/PE premiums, signals, engine, P&L, alerts) with heartbeat, stale detection, reconnect and polling fallback. Live chart: VWAP, volume, RSI, MACD, 1-minute | Groww feed vs polling inside the server |
| 4. Telegram | Bot alerts with thresholds, quiet hours, retries, history, test message | **Bot token + chat ID (in `.env`)** |
| 5. Paper | Virtual funds, positions, multiple strategies | — |
| 6. Live | Funds/position verification, partial fills, emergency stop-all, logs. First real order only with you present | **Approval for a supervised 1-lot live test** |
| 7. Final | Full tests, build, browser checks, docs | — |

### Phase 1: historical data (12 Nov 2026)
Decisions you made at the gate: option scope ATM ±10 strikes, CE and PE, all weekly and monthly expiries; NSE lot-size history used in backtests and the 28 configurations re-run; synthetic rows backed up, then deleted.

| Item | Result |
|---|---|
| Synthetic test rows | **Removed:** 223,305 `SYNTH:` candles plus their fetch-log, contract, expiry and cached-run rows, exported first to `data/backups/synthetic_2026-11-12_*.csv.gz` (row counts verified before deleting). 4 synthetic engine trades kept, as trade history is never deleted. A test now checks the production database has no `SYNTH:` candles |
| Historical lot sizes | **Done:** migration 0008 `lot_sizes`, copied from NSE/FAOP/47854, 61415, 64625 and 70616 (read from the PDFs). NIFTY: 50 → 25 (weekly 2 May 2024, monthly 30 May 2024) → 75 (weekly 2 Jan 2025, monthly 27 Feb 2025) → 65 (weekly 6 Jan 2026, monthly 27 Jan 2026). Groww's current instrument list (18 expiries, all 65) matches |
| Backtests | Default lot size is now each contract's NSE lot size; a fixed lot size is still available. Each trade records `lot_size` and `lot_source`. All 28 configurations re-run (old fixed-65 results kept) |
| Option history | **New** `market_data/options_history.py`: for every stored session, CE and PE within 10 strikes of that day's ATM (from the day's spot low/high), for every expiry a backtest can pick. 21,702 contracts, 264 expiries, 172,120 contract-days. Resumable (only never-requested days are fetched), stoppable, failed requests reported and retried on the next run; 0-row days recorded, never filled |
| Futures freshness | **Fixed:** the daily live refresh now updates futures as well as spot, and today's completed futures candles are stored as they are read |
| Data page | Spot, futures and options cards (counts, range, latest candle, last successful download), intervals, option coverage by month with download/resume/stop, NSE lot-size table |
| Contract metadata | Kept in the existing `contracts` and `expiries` tables (no duplicate table); cycle (weekly/monthly) is derived from the expiry list and lot size from `lot_sizes` |
| Tests | New `tests/test_options_data.py` and two backtest tests (see CHANGELOG for counts) |

**Not available from any source used:** historical IV/Greeks snapshots (Groww has no option-chain history). OI is stored with every option candle.

## 11. Known issues and pending work
Full list: [docs/TODO.md](docs/TODO.md).

**Pending:**
- Socket.IO push (Phase 6)
- backend endpoints for option chain/expiries and CE+PE premiums (see [docs/TODO.md](docs/TODO.md))

**Known issues:**
- **No holiday calendar.**
- **Prediction rule:** its option P&L hasn't been backtested.

**Not a guarantee:** the app supports decisions. Past results don't predict future returns, and no strategy tested here was clearly profitable after costs.

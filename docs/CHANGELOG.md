# Changelog

All dates are 2026, IST.

## 18 Nov (evening): remaining audit issues
- **1. Orphaned tables:** investigated, backed up, migration prepared, **nothing dropped (needs your approval)**. Six unreferenced tables (`candle_forecasts` 55 rows, `prediction_log` 36, `strategy_signals` 2, `smc_setups`, `pattern_events`, `app_settings` empty) with no foreign keys, views or migration files. Backup `data/backups/orphan_tables_2026-11-18.dump` verified by restoring into a scratch database (counts equal). Pending migration and rollback in `backend/app/database/pending/`, both run against an empty scratch database. Also found: migrations `0013`-`0017` were applied here but their files were deleted, so a fresh database differs from this one (six tables and nine `live_trades` columns, all NULL). Full report: [DATABASE.md](DATABASE.md).
- **2. React tests:** 346 Vitest + React Testing Library tests (was 14) over hooks, components, charts and all ten pages, with shared utilities in `src/test/`. They found and fixed three bugs: the risk-% box could not be typed key by key (`0` became `1`, so `0.5` was impossible; new `PercentInput`), the Backtest page flashed "Couldn't load backtest settings." on every open, and Historical Charts could cancel a click on another page's link. One test was flaky on a cold start (chart effect race); fixed with `waitFor` and then run 8 times in a row green.
- **3. Browser verification (Playwright, installed Edge, 106 tests, 106 passed, 4.6 min):** all ten pages at 1920, 1440, 1280, 1024, 768, 430, 390 and 360 px: no horizontal overflow, no console or page errors, no failed API calls; navigation by sidebar and by phone bottom bar/drawer; the live chart drawn at every width; WebSocket "Live push" and REST "Polling" indicators; paper Start/Stop. **Found and fixed:** the Live push/Polling indicator was hidden below 640 px, so on a phone nothing showed that the app had fallen back to polling; a compact "Polling" pill now appears on phones when the WebSocket is down (checked at 360 px: no header overflow). I looked at one phone screenshot; the rest were judged by the automated checks only. Three of my earlier runs failed because the tests did not wait for slow first loads (about 9 s after a server start, 1.7 s whenever the cache expires) and because the first indicator test could not block a WebSocket: test bugs, not app bugs.
- **4. Live-market verification (market closed, 18:07-18:09 IST, Wednesday):** verified against real Groww: login, NIFTY spot 25,227.95 (identical to a direct `get_quote`), CE 150.10 / PE 175.80 and OI of NIFTY26NOV25250CE/PE identical to direct quotes, `closed` states and the "Closed for the day" label, the 15:00 square-off signal state, stored alerts, WebSocket and REST fallback in a real browser. **Not verified (needs a session): 1 s push while open, LIVE/DELAYED premium states, a new signal producing one alert, reconnect/stale-data with a live feed.** Those paths are covered by replay and integration tests (`test_realtime`, `test_live_feed`, `test_live_engine`, `hooks/live.test.tsx`) but not by a real market. Marked pending in TODO.
- **5a. API audit** (all 8 blueprints, 41 routes). **Fixed:** (1) a cross-site request could drive the API: POST handlers accept any content type, browsers send `text/plain` across sites without a preflight, and there is no login, so a web page open in your browser could post to `http://127.0.0.1:5000/api/live/start` (the `LIVE` phrase is just a field in the body). A new `before_request` guard refuses a non-loopback `Host` (DNS rebinding) and a state-changing request whose `Origin` is not loopback. (2) Malformed JSON got Flask's HTML 400; `json_body()` and a JSON error handler now answer `{"ok": false}` for every HTTP error under `/api`. (3) Duplicated date validation and "download running" check in the two download endpoints moved to `date_range()` / `_download_running()`. **Checked, no change:** responses all use the `{ok, data}` envelope; every frontend call has a route; four routes are not called by the React app and were kept on purpose (`/api/logout`, `/api/bt/data`, `/api/live/status`, `/api/live/broker`); there is no authentication by design (127.0.0.1 only); 25 routes had no direct test before, 29 smoke tests now cover the account, live-control, guard, validation and not-found paths (`/api/live/status` is not tested because it logs in to Groww).
- **5b. Trading engine audit** (all 1,100 lines read). Checked: entry/exit order, duplicate-order prevention (deterministic entry reference per signal bar, `processed_until`, one-position check, confirm-once), paper/replay/live separation (scalp never live; live needs the phrase, lot cap and manual confirmation), position sizing and the daily limit, stop/target, restart recovery (`_load_day_state`), state under the RLock. **No trading-rule bug found.** Fixed: `stop()` could leave a live position open after a failed exit with no message (now logs an error naming the contract); three attributes created lazily with `getattr` are now set in `__init__`; a malformed `HH:MM` gave a cryptic unpack error (now "Time must look like 09:30"); the bars/last-evaluation block and the in-window cross scan were each written three times. Noted, not changed: ticks hold the lock during Groww calls, `paper.py` uses private engine names.
- **6. Refactoring (public names unchanged, re-exported):** `trading/engine.py` 1,100 to 936 lines: `EngineConfig` to `engine_config.py`, stop/target rules to `stops.py` (pure, 12 new tests), three duplicated evaluator blocks to `_record_bars` / `_window_crosses`. `market_data/feed.py` 757 to 640: pure signal/market-status/data-check functions to `signal_state.py`. `backtest/scalping.py` 569 to 473: statistics and walk-forward to `scalping_stats.py`. `pages/Scalping.tsx` 485 to 178: `components/scalping/{ConfigDetail,PaperPanel,shared}`. Not split: the `Feed` class (shared caches), `scalping.run`/`summarise` (long, but one pipeline), the other React pages (under 330 lines).
- **7. Regression:** a snapshot of real-data backtests (EMA 9/21 at 15m and 5m, 1 Oct-12 Nov 2026), sizing, round-trip charges and five engine replays (cross, trend, paper pct stop, paper points stop, scalp; 3, 8, 3, 7 and 16 trades) was **byte-identical before and after** the engine, feed and scalping-statistics splits. Prediction mode is covered by `test_live_engine.py`, not by the snapshot. Backend, frontend, Playwright, `tsc -b` and `npm run build` results are in [TESTING.md](TESTING.md). The app entry chunk is still 99.6 kB.
- **Also:** `PORT` environment variable for the server (the Socket.IO origin list follows it); `CLAUDE.md` and `docs/TESTING.md` created; `@playwright/test` and the React Testing Library packages added as dev dependencies.
- **Mistakes during this pass, for the record:** a probe call started three real background jobs (research, signals, scalping) before I noticed; they were killed at process exit and only append data. My browser tests wrote one paper-engine session (`live_sessions` row) to the production database per run that reached the Start/Stop test (no trade, no order).

## 18 Nov: audit, small cleanup, API and frontend tests
- **Audit result:** every Python symbol and import, every exported TypeScript name, all 41 `/api` routes against the React client (every client call has a route; four routes are not called by the React app, kept on purpose as before), every table against the code, and secrets/live-order paths. The 14 Nov cleanup left little dead code: no unused Python imports or functions, no unused TypeScript imports (`noUnusedLocals` is on).
- **Duplicates removed (no behaviour change):** four copies of `IST = ZoneInfo("Asia/Kolkata")` (db, groww client, live, providers) and four `_now()` bodies are now `utils/timeutil.IST` and `timeutil.now_naive`. Each module keeps its own `_now` name because tests patch it per module.
- **Frontend build:** libraries are split into `react-vendor`, `charts` and `realtime` chunks. The entry chunk went from 548 kB (171 kB gzip, with a Vite size warning) to 100 kB (29 kB gzip); no warning. Pages and behaviour are unchanged.
- **Tests added:** `backend/tests/test_api_smoke.py` (18 cases then; 29 after the evening pass): account endpoints with Groww mocked, live controls refuse when no engine runs, live start needs the `LIVE` phrase and the lot cap before any key is read, 404s for unknown jobs/results, read-only research/signals/scalping endpoints. The fixture fails any test that reaches the real Groww client. Frontend: Vitest (`npm test`, 14 tests) for `utils/format.ts` and `services/api.ts`.
- **Results:** backend **310 passed** (292 before; 8 min 6 s alone). Frontend 14 passed; `tsc -b` and `npm run build` pass.
- **Database:** nothing changed. Six tables have no code references (listed in DATABASE.md and TODO.md); all are kept because they hold history.
- **Docs fixed:** migration range `0001`-`0012`, the stale "no WebSockets" and "three `_now`" notes, test commands in README/DEPLOYMENT.
- **Not done:** no data-bearing table was dropped, no trading rule or calculation changed, no real order was placed. Browser/responsive checks were not re-run in this pass.

## 14 Nov: performance pass (no behaviour change)
- **Where the time went:** a one-year backtest spent about 9 of 16 s in `db.load_candles` (776,000 rows turned into Python objects three times over), plus 2,400 contract lookups (two per priced trade) and full-frame mask scans in `rules.price_at`.
- **`db.load_candles`:** PostgreSQL returns the IST wall-clock time as integer microseconds, and numpy builds the frame in one pass. This replaces `pd.read_sql` plus a Python cast on every timestamp. The output is identical: values and dtypes checked bit for bit on spot, futures and 40 option contracts, including empty results. The database has no NULL candle values and no fractional seconds (checked over all 68 M rows).
- **`rules.price_at`:** for frames sorted by time (every caller passes stored candles, oldest first), a binary search finds the fill candle. Unsorted frames use the original code unchanged.
- **`GrowwProvider.option_symbol`:** remembers contracts it found for the life of one provider (one backtest or one replay). Contracts are never deleted or renamed, so a remembered answer cannot go stale. Misses are not remembered.
- **Backtest page:** the trade list renders 300 rows at a time as you scroll (same box, same rows; the title still shows the full count), and rows are memoised, so picking a trade no longer re-renders every row. A five-year 1-minute run has up to 22,807 trades.
- **`requirements.txt`:** declares `numpy` and `requests`, which the code imports directly but which were only installed as dependencies of pandas and growwapi. No new packages.
- **Measured (same machine, best of 2 runs, old code vs new):**

  | Run | Before | After | Speed-up |
  |---|---|---|---|
  | EMA 9/21 15m, 1 year | 12.4 s | 8.2 s | 1.51× |
  | EMA 8/21 1m, 2.5 months | 16.6 s | 9.9 s | 1.69× |
  | EMA 9/21 + VWAP 5m, 6 months | 10.5 s | 7.2 s | 1.45× |
  | EMA 20/50 30m, 2 years | 6.5 s | 4.7 s | 1.39× |
  | Scalping analyzer, Aug–Nov 2026 | 5.0 s | 4.8 s | 1.05× (already loads in bulk) |

  Loading five years of NIFTY spot needs 29% less peak memory (244 → 174 MB). The full test suite ran in 6 min 29 s (9–10 min before).
- **Verified identical:** all four backtests, and the scalping analyzer output (old vs new code in one process, compared in full); the same three server backtests and three risk-sizing cases as before the cleanup; **292 tests pass**; the React type check and build pass.

## 14 Nov: codebase cleanup (no behaviour change)
- **Audit method:** a module import graph from every entry point (`app.py`, `start.py`, the tests), every top-level Python symbol and every exported TypeScript name searched across the code, every Flask route matched against the React client and the tests, and every table matched against the queries. Each hit was read, and its git history checked, before anything was removed.
- **Removed (dead or obsolete):**
  - `backend/app/models/`: an empty package nothing imports (tables are defined by the SQL migrations).
  - `settings.BACKEND_DIR`: unused since the legacy pages were deleted on 12 Nov.
  - `backtest.engine.WARMUP_DAYS`: replaced by `strategies.warmup_sessions()`.
  - `options_history.UNDERLYING` and `insight.plan_key`: never used.
  - React client wrappers `getBrokerPositions` and `downloadForBacktest`: never called. The endpoints stay (`/api/bt/data` is tested; `/api/live/broker` is for checking against Groww).
  - Untracked leftovers from before the 11 Nov restructure: root `__pycache__/` (compiled modules that no longer exist), root `server.log` (logs are now in `data/logs/`), `backend/tests_tmp/` and the empty `scripts/` folder.
- **Kept on purpose:** `/api/live/status` and `/api/logout` (documented endpoints, not used by the React app); the four `_now()` helpers (tests patch each one); `lot_sizes.clear_cache` (used by tests); `keys.txt` support (fallback when the Groww variables are not in `.env`).
- **Docs and comments:**
  - The engine docstring now says which strategy each mode trades: `cross` and `trend` always use EMA 9/21; `prediction` and `scalp` use the selected strategy. This matches the Live page, which shows the strategy picker in prediction mode only. The same note is in STRATEGY.md.
  - Added docstrings to the backtest run, parameter normalisation, data download, metrics, engine config/validation/tick, engine start and the scalping run/summary.
  - Fixed a stale reference (`strategy.generate_legs` → `rules.generate_legs`). PROJECT_STRUCTURE.md updated.
- **Verified unchanged:**
  - Backtests (EMA 9/21, EMA 8/21, EMA 9/21 + VWAP; 15m; 1 Oct–12 Nov): identical before and after the cleanup, trade by trade, net P&L included.
  - Risk sizing: three risk-calculator cases identical.
  - **292 tests pass** (292 before). The React type check and build pass.
  - Groww login, profile, funds and option chain respond. Live start without the "LIVE" phrase and scalping in live mode are both refused. The Socket.IO handshake works. All 10 pages return 200.

## 13 Nov: 5-minute options scalping analyzer
- **New analyzer, `services/backtest/scalping.py`:**
  - **Configurations:** 6 EMA strategies (9/21, 5/20, 20/50, and 9/21 + VWAP, RSI or MACD) × ATM / ITM 5 × 10 exit rules (fixed 5-minute hold, or stop 5/10/15% × target 5/10/20% with a 5-minute maximum) = 120. Stop/target rules are also sized at 0.5/1/2% risk.
  - **Data and costs:** completed 5-minute NIFTY bars; entry at the next option candle's open; real premiums; NSE lot sizes; slippage, brokerage and taxes.
  - **Safeguards:** no look-ahead or repainting; one position at a time for each configuration.
  - **Selection:** ranked by in-sample net ÷ drawdown, then checked on the out-of-sample 40% of days; year-by-year walk-forward; a five-check consistency verdict; comparison with the existing strategies. Win rate is not used.
- **Result:** 0 of 120 configurations was net positive over five years (296,170 trades). None was positive even with no slippage. See [SCALPING.md](SCALPING.md).
- **Engine `signal_mode="scalp"`:** paper and replay only; live is refused. It exits after 5 minutes, or earlier at the premium stop or target. Trades are tagged with `strategy` and `scalp_config` (migration 0012). Replay sets the stop and target from the entry fill.
- **API:** `/api/scalping`, `/api/scalping/config`, `/api/scalping/run`, `/api/scalping/paper/start`, `/api/scalping/paper/trades`.
- **React:** a new **5-Minute Scalping** page (`/app/scalping`). The engine panel lists the scalp mode (started from the Scalping page), and the trades table names the time exit.
- **Tests:** `tests/test_scalping.py` (15). **292 passed** in total. The React type check and build pass.

## 13 Nov: trend entry mode, dashboard sizing fix
- **New engine signal mode `trend`** ("Whenever the trend agrees"), added at the user's request: at each bar close inside the entry window, if no position is open, the engine enters in the direction of EMA 9 vs EMA 21 (BUY CE above, BUY PE below) without waiting for a crossover. It exits when the trend flips and re-enters the other way. Risk sizing, the premium stop, the daily trade and loss limits and the 15:00 square-off all still apply. `cross` and `prediction` are unchanged. This mode has not been backtested: the backtester still tests crossover entries only.
- **Fix:** the live dashboard stopped updating when Groww reported a zero or negative option-buy balance and no capital was entered ("capital must be positive"). It now shows "Groww option-buy balance is ₹X, so no size can be given" and keeps updating.
- **Tests:** a zero/negative balance test (feed) and two trend-mode engine tests.

## 12 Nov: Phase 3, live data and WebSockets
- **Socket.IO push:** new `api/realtime.py` (Flask-SocketIO, threading mode, `simple-websocket`). Pushes the `/api/live/dashboard` payload per settings room; heartbeats, sequence numbers, change detection, 1 s / 5 s ticks. `app.py` runs `socketio.run`. New dependencies: `flask-socketio`, `simple-websocket` (backend), `socket.io-client` 4.8.1 (frontend).
- **One builder:** `live.dashboard_args` and `live.dashboard_payload` are shared by the REST endpoint and the socket (no duplicate API).
- **CE/PE premium monitor:** `Feed.premiums` (in the dashboard as `premiums`). While the market is closed it uses the instrument master and the quote only (no option-chain call), keeping the existing "no chain call when closed" behaviour.
- **React:** `useDashboard` uses the socket with REST polling as fallback; header *Live push / Polling* badge; premium card rewritten on live CE and PE data.
- **Tests:** `tests/test_realtime.py` (14): hello, immediate state on subscribe, invalid settings, heartbeat vs change, shared rooms, room moves and cleanup, build errors, tick speed, REST and socket sharing one builder, premium monitor (ATM on HOLD, follows the recommendation, closed, failures, index-like price rejected, delayed). **273 passed.** React build passes.
- **Checked for real:** a Node Socket.IO client against the running server (WebSocket transport, increasing sequence numbers, reconnect after a server restart); browser: *Live push* with 0 REST dashboard calls in 30 s, and with WebSocket blocked, *Polling* at about one call per 10 s. Market closed during these checks.

## 12 Nov: Phase 2, strategy and backtesting
- **Calibration (signals.py, analysis v3):** Wilson 95% ranges on band and score-group hit rates; bootstrap AUC range; walk-forward Platt calibration compared with the historical average (Brier skill); per-signal calibrated estimate; plain verdict. Raw scores are unchanged (checked: all 15-minute v2 and v3 scores identical), so prediction mode trades exactly as before. EMA 9/21 analyses rebuilt for 5, 15 and 30 min.
- **Live confidence text** shows the band's 95% range, the calibrated estimate and the verdict.
- **Option chain:** `Feed.option_chain` and `GET /api/options/chain`, using Groww's chain plus per-contract quotes for ATM ±5. OI change is computed as OI minus previous OI, because Groww's `oi_day_change` came back scaled by 0.65.
- **Options Analysis page:** the live chain replaces the "not available" note.
- **Backtest page:** payoff ratio, average win/loss, brokerage & taxes vs slippage, and filters for direction, crossover number and entry time.
- **Signals page:** Calibration check card.
- **Tests:** `tests/test_phase2.py` (15): Wilson values, calibrator bounds, no look-ahead in walk-forward calibration, informative vs noise scores, reproducible AUC range, verdict cases, unchanged raw score, live confidence text, and the chain (ATM centring, spot separate, OI change, quotes only near ATM, nothing invented on failure, errors, other expiry, width limit, caching). **259 passed.** React build passes.

## 12 Nov: Live market & paper trading improvements (5 items)
- **NIFTY high / low:** the quote adds `from_high`, `from_low` and `range_pct`. The spot card shows the points from the high and low, change %, previous close, a day-range bar, the updated time and age, and Delayed / Disconnected states.
- **Prediction explanations:** new `strategy/insight.explain` shows EMA 9/21, VWAP, RSI, MACD, volume and trend with actual values, plus the model confidence with its out-of-sample hit rate, why the call isn't HOLD (or what HOLD needs), and a caution on weak confirmation. It never changes the signal. The *View reason* panel is on the recommendation card.
- **Paper stop-loss:** fixed-points stop mode; the stop on an open paper position can be edited and is refused beyond the trade's risk amount or the remaining daily loss limit; every stop is logged (`paper_stop_changes`); stale prices (> 15 s) never trigger an exit; one exit per position; the stop and target are drawn on the chart.
- **Today's Trading Plan:** `insight.trading_plan` adds Groww quote values, calculated pivots, previous day and opening-range levels, trend, EMA, VWAP, volatility, preferred direction and three scenarios. Changes are judged on closed bars and stored with reasons (`trading_plans`).
- **Candles and patterns:**
  - 1-minute chart, VWAP (basis-adjusted futures VWAP), futures volume, RSI and MACD panels, support/resistance lines, and BUY CE / BUY PE / EXIT / HOLD markers
  - `strategy/patterns.py` (10 patterns, closed bars only, no repainting, confirmation status, effect on the signal)
- **Feed:** bars now come from `strategies.prepare` (the EMAs are identical to before), with futures for VWAP and volume. A feed built around an injected market (tests) never touches the database.
- **Fix:** the recommendation card could stay dimmed, because its flash and its fade-in fought over the CSS `animation` property; the flash moved to a wrapper.
- **Migration 0010:** `trading_plans`, `paper_stop_changes`. `test_live_engine.py` cleanup now truncates with CASCADE, because `paper_stop_changes` references `live_trades`; no assertion changed.
- **Tests:** `tests/test_insight.py` (20) covers high/low against the quote, explanations against the bar values, the BUY/HOLD reasons, model confidence, pivots, opening range, plan changes and their recording, each candle pattern, closed bars only and no repainting, pattern effect, chart bars and markers, the 1-minute chart, and missing candles. 5 stop-management tests cover the points mode, the initial stop record, tighten/refuse/record, exiting at the edited stop with costs, stale prices with no double exit, and the API. **244 passed.** React build (type check) passes. Live page checked at 1440, 768 and 390 px with no overflow or console errors.

## 12 Nov: Phase 1 complete (option history downloaded)
- **Option history:** 22,042 requests, 0 failed, about 3 h. Scope coverage 100% (172,120 contract-days; 2,061 with no trades). 67.1 M option candles in total, 53.5 M with OI. Integrity: 0 invalid prices or OHLC, 0 non-minute timestamps; 165 older 15:30 candles flagged, not deleted.
- **Fix:** the provider now records weekend special sessions (Budget days, Muhurat) in the fetch log when they return candles; back-filled 1,288 rows from stored candles and 32 no-trade days (3 re-checked with Groww).

## 12 Nov: Paper trading risk management
- **Your decisions:** premium stop-loss enforced on paper trades (ATR × delta by default, or % of premium); daily-limit halt lasts until the next session; virtual account with a running balance.
- **Sizing core:** `options/sizing.risk_size` (risk amount, risk per lot incl. slippage and charges, lots capped by risk, cash after minimum balance and max lots, TRADE / NO TRADE with reason). The Live dashboard's `size_position` now calls it (its formula and results are unchanged).
- **Engine (paper only):** before every entry, `_paper_risk` runs the calculation on the contract's live premium, plus the daily-limit, remaining-daily-risk, balance, lot and open-position checks; failures are a HOLD alert with every reason and the calculation. Accepted trades store `risk`, `stop_premium`, `target_premium` and `paper_account_id`. Premium stop-loss exits; daily limit = min(₹ limit, daily risk % of the day's starting capital). Live and replay unchanged.
- **Virtual account:** `paper_accounts` (migration 0009), `trading/paper_account.py`; `GET/POST /api/paper/account`, `POST /api/paper/risk-calc`.
- **Market data:** `GrowwMarket.option_delta` (option chain, cached 30 s) for the ATR stop.
- **Frontend:** Risk Management, Daily Risk and Paper Trades & Risk cards; risk settings in Trading Controls.
- **Tests:** `tests/test_paper_risk.py` (56): 0.5/1/1.5/2% and custom, capital amounts, premiums, stop distances, lot sizes 25/50/65/75, insufficient capital, minimum balance, one lot over budget, max lots, missing premium/stop, slippage and charges included, every trade stores its calculation, premium stop exits, ATR stop with and without delta, remaining-daily-risk refusal, daily limit halt and next-day resume, open-position limit, replay unchanged, API.
- **Existing engine tests:** they test mechanics in paper mode with fixed lots, which paper trading no longer uses. Their shared `make()` helper now passes risk settings that size exactly `lots` and keep the premium stop and daily limit out of the way (the calculation still runs); `test_daily_loss_limit_halts` runs in replay mode, where the open-loss halt still applies as before. No assertion was changed. **219 passed** (163 + 56). React build passes; Live page checked at 1440 and 390 px with no overflow or console errors.

## 12 Nov: Phase 1, historical data
- **Synthetic rows:** backed up to `data/backups/synthetic_2026-11-12_*.csv.gz` (counts verified), then deleted from the production database: 223,305 candles, 515 fetch-log rows, 316 contracts, 18 expiries, 1 cached run. 4 synthetic engine trades kept.
- **Lot sizes:** migration `0008_lot_sizes` with NIFTY lot sizes from NSE/FAOP/47854, 61415, 64625 and 70616, by expiry cycle and first expiry. `services/options/lot_sizes.py` looks up a contract's lot size. Groww's current instrument list matches (65 on all 18 listed expiries).
- **Backtests:** `lot_size` defaults to 0 = each contract's NSE lot size (`ENGINE_VERSION` 3); a fixed lot size is still accepted. Each trade records `lot_size` and `lot_source`. The Backtesting page offers "NSE history" or "Fixed" and shows quantity per trade.
- **Replay:** replayed contracts use their NSE lot size too (was a fixed 65), so replay and backtest still produce identical trades.
- **Option history:** `services/market_data/options_history.py`: ATM ±10 strikes, CE and PE, every expiry a backtest can pick, for every stored session. Resumable, stoppable, failed requests reported and retried next run. New `GET /api/data/options`, `POST /api/data/options/download` (own job lane), `GET /api/data/lot-sizes`; `GET /api/data/overview` gains `instruments`.
- **Futures freshness:** the daily live refresh updates futures as well as spot, and today's completed futures candles are stored.
- **Market Data page:** spot/futures/options cards, intervals, option coverage by month with download/resume/stop, NSE lot-size table.
- **Tests:** `tests/test_options_data.py` (lot sizes at every NSE cutover, plan, windows, resumable download with a failure, stop, API, no synthetic rows in production) and two backtest lot-size tests. **163 passed** (141 before + 22 new). React build passes.

## 12 Nov: One interface (old pages removed)
- **Removed:** at your request, `backend/legacy/` (7 Jinja templates, 10 JS/CSS files), the `/live` page route and Flask's static folder.
- **Redirects:** `api/pages.py` now redirects `/` and the old addresses (`/live`, `/signals`, `/compare`, `/data`, `/history`, `/account`, `/backtest`) to the matching React page under `/app`.
- **Account & Settings:** the note linking to the old pages was removed.
- **Tests:** the route tests now expect redirects, and a new test checks every old address and that old page assets are gone.

## 12 Nov: Phase 0 audit (master programme)
- Read-only audit; no code changes. Baseline: 140 tests pass, TypeScript check passes.
- **Found:**
  - stale futures (refresh only updates spot)
  - CE/PE premium, option chain and Greeks available from Groww but not exposed
  - no historical lot sizes
  - no Telegram, no WebSockets
  - live chart lacks VWAP/volume/RSI/MACD
  - synthetic test rows in the production DB
- Details and plan: GROWTRADING.md §10.

## 11 Nov: Frontend redesign (frontend only)
- **New app shell:**
  - collapsible left sidebar (icon rail on tablets)
  - phone header with NIFTY price and latest signal, a bottom bar and a menu drawer
  - header with Groww connection, market status, engine state, notification bell with unread badge, sound and theme
- **Colour system:** green gains/BUY/CE, red losses/PE, blue spot, purple strategy, orange risk, grey neutral. Light and dark themes.
- **Nine React pages:** Overview, Live Trading, Trading Signals, Options Analysis, Backtesting, Strategy Comparison, Market Data, Historical Charts, Account & Settings. Every legacy page now has a React equivalent.
- **Live Trading:**
  - spot card; large chart with EMA 9/21, crossover arrows, engine entry/exit markers and stop/target lines
  - separate CE/PE premium panel ("spot = index, premium = contract")
  - recommendation card; order calculator with tooltips and charge breakdown; trading controls with manual order confirmation
- **Notification panel:**
  - signal/trade alerts plus connection and engine events from real state changes
  - sound, browser notifications, flash, unread badge; no duplicates
- **One shared live poll** (`LiveContext`) instead of one per page.
- **Performance figures** now use the engine session's own mode and day: a stopped replay shows as "Last engine session · REPLAY · <day>" instead of being mixed with today's paper trades.
- **Backend limitations** are stated on the pages rather than worked around: single recommended contract, no option chain or expiry endpoint, no option volume or premium change, NIFTY-only history.
- **Removed:** `components/dashboard/*` and `pages/LiveDashboard.tsx`, replaced by the new components.
- **Tests:**
  - TypeScript check and production build pass
  - all 9 pages at 1920/1440/1024/768/390/360 px: no overflow, no console errors (54/54)
  - Paper start/stop and replay notifications checked in a real browser
  - no backend file changed

## 11 Nov: Phase 5, React frontend
- **New `frontend/`:** React 19 + TypeScript + Vite 8 + Tailwind 4 + Lucide + Lightweight Charts 4.2, served by Flask at `/app` (`api/frontend.py`).
- **Live dashboard:**
  - NIFTY price
  - 5-minute candles with EMA 9/21 and cross markers
  - trend
  - BUY CE/PE/HOLD recommendation with strike, expiry, live premium, entry/stop/target, lots/qty, investment and risk
  - today's P&L
  - notifications with sound and browser alerts
  - connection and market status
  - engine controls
  - Dark/light themes; works at phone width.
- **Per-order confirmation in Live mode, now the default:**
  - `EngineConfig.order_confirmation = "manual"`
  - entry orders wait for `POST /api/live/confirm` and lapse with the signal; `POST /api/live/reject` skips
  - Paper and Replay are unchanged
  - 3 new engine tests
- **Tests:** 2 new tests for serving the React app (including path-traversal protection). **140 tests pass**; the production build and type check pass.

## 11 Nov: Grow Trading restructure, Phases 1–4
- **Phase 1–2:** inspected the whole project and recorded a baseline of 134 passing tests. Found no circular imports, plus duplicated helpers (`_hm` ×3, alert storage ×3, quote snapshot ×2) and a Live page left mixed by two sessions.
- **Commit `25ef0aa`:** all earlier work (Levels 1–2, prediction mode, alerts) committed before moving anything.
- **Phase 3–4, commit `a678fe3`:** every Python module moved into `backend/app/` (api, config, database, services/*, workers, utils) with `git mv`, so history is kept. Imports were rewritten mechanically and no function bodies changed. Tests moved to `backend/tests`, and the old pages to `backend/legacy`. **134 tests pass.**
- **Phase 4, commit `a297fb3`:**
  - routes split into blueprints (`api/account, backtest, data, research, live, pages, common`); the app factory is in `app/__init__.py`
  - order execution moved to `services/trading/brokers.py`
  - position sizing to `services/options/sizing.py`; option-chain lookup to `services/options/contracts.py`
  - alert storage merged into `services/notifications/alerts.py` (engine, feed and manager use it)
  - `_hm` merged into `utils/timeutil.parse_hm`; `to_float` into `utils/numbers.py`
  - three unused imports removed
  - **134 tests pass, the linter is clean, and every page and API answers 200.**
- **Config:**
  - Groww credentials can come from `GROWW_API_KEY` + `GROWW_TOTP_SECRET`/`GROWW_API_SECRET` (`keys.txt` is the fallback; new test added)
  - added `.env.example` and `start.py`
  - the instrument cache moved to `data/historical/`
  - page titles and brand renamed to **Grow Trading**
  - the unused `index.html` placeholder was removed
- **Docs:** added the `docs/` set and updated README and GROWTRADING.md.

## 11 Nov: Live dashboard and alerts (before the restructure)
- **Alerts:** `live_alerts` table (migration 0007). The engine records BUY CE/PE, SELL CE/PE, SELL/BUY BACK (exit) and HOLD alerts, once per signal.
- **Status data:** market and connection status, plus a NIFTY/EMA snapshot even while the engine is stopped.
- **Fix:** replaying the same day twice used to skip every signal the second time. Replay state is now kept per session.
- **Two sessions at once:** a second session edited the Live page at the same time, adding `live_feed.py` and `/api/live/dashboard`. Its page files and this session's don't fully match.

## 11 Nov: Prediction-based paper trading
- **Prediction mode:** a new engine signal source. Only crossovers scoring ≥ the minimum are traded; exits are at the NIFTY stop (1 × ATR), the target (2 × ATR) or 15:00.
- **Verified:** live and offline scores matched exactly on three replayed real days.
- **Fix:** data refreshes no longer delete signal analyses.

## 11 Nov: Level 2, strategy research
- **Strategies and indicators:** seven strategies, Wilder RSI/ATR, MACD, futures VWAP.
- **NIFTY futures:** five years downloaded; holiday-moved monthly expiries confirmed against Groww.
- **Backtester:**
  - strategy and expiry rule options, 1-minute timeframe
  - parallel whole-contract option downloads
  - standard option symbols when Groww's contract list is incomplete
  - no fallback to an earlier price on a missing exit
- **New pages:** Compare (28 configurations, walk-forward) and Signals (out-of-sample scoring).

## 11 Nov: Level 1, data
- **Database:** migrations, `TIMESTAMPTZ` in IST.
- **Download manager:** resumes after failures, validates candles, keeps out-of-hours candles separate.
- **New pages:** Data and History.
- **Five years of NIFTY 1-minute data** downloaded once the paid plan was active.

## 10–11 Nov: first build
- **Core app:** Flask app, Groww TOTP login, 9/21 EMA backtester and trade viewer.
- **Live engine:** live/paper/replay with safety rails; synthetic demo data (now tests-only).

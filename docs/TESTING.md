# Testing

Three layers, all runnable locally. Counts are from the runs on 19 Nov 2026.

| Layer | Tool | Where | Tests | Time |
|---|---|---|---|---|
| Backend unit + integration | pytest | `backend/tests/` | **639** | about 28 min (replays real days; the bias engine tests add about 8) |
| Frontend unit + component + page | Vitest 4, jsdom, React Testing Library | `frontend/src/__tests__/` | **463** | about 12-25 s |
| Browser (real Edge) | Playwright | `frontend/e2e/` | **116** | about 5-12 min |

**Browser result (19 Nov):** 114 of 116 passed in the last clean full run (12.4 min); the two failures were the Live-page chart test and the "Polling" indicator test at 430 px timing out while the Groww dashboard was slow (market still open). The 16 Live-chart and indicator tests (all widths) passed when run alone, twice (4.0 and 4.4 min). An earlier full run that overlapped with a heavy replay had 5 failures, all in those same two tests. They wait for the cold Groww dashboard (about 9-13 s), so they are sensitive to a slow Groww; the new automated trading page, navigation and privacy tests passed in every run.

Also: `npx tsc -b` (strict type check) and `npm run build` (production build) both pass.

## Rules for running them
- **Windows path casing:** start `npm`/`npx` from a path with an upper-case drive letter (`C:\Amruthesh\...`). From `c:\...` Vitest loads itself twice and every suite fails with "failed to find the current suite".
- **One pytest session at a time.** The tests create and drop their own `groww_trading_test*` databases and never touch `groww_trading`; two sessions collide on those databases and fail with `OperationalError`.
- **Nothing here can place a real order.** Backend tests mock Groww (`tests/test_api_smoke.py` fails any test that reaches the real client); Playwright only starts and stops a **paper** engine.
- Python tools are in the project's `.venv`: `..\.venv\Scripts\python -m pytest` from `backend/`.

## Backend (pytest)
| File | Covers |
|---|---|
| test_setup.py | Credentials (file and env), routes without keys |
| test_strategy.py, test_research.py | Core rules, indicators, strategies, signals, walk-forward |
| test_costs_metrics.py | Charges, slippage, metrics |
| test_providers.py, test_options_data.py, test_data_manager.py | Candle parsing, option symbols and history, lot sizes, migrations, time zones, downloads, validation |
| test_backtest_integration.py | End-to-end backtest, unfinished sessions |
| test_live_engine.py | Replay through the engine equals the backtest; safety rails; trend and prediction modes; alerts once per signal; manual confirmation |
| test_paper_risk.py | Paper sizing, stop-loss, daily limits, account reset, stop edits |
| test_scalping.py | Scalping analyzer and scalp engine mode |
| test_live_feed.py, test_insight.py, test_realtime.py | Live feed, signal state, data checks, Socket.IO push, heartbeat, rooms |
| test_frontend.py | React build served at /app, route fallback, no files outside `dist` |
| test_api_smoke.py (33) | Account endpoints with Groww mocked; live-control guard rails; `LIVE` phrase and lot cap checked before any key is read; Host/Origin guard; JSON errors; download validation; not-found cases; read endpoints |
| test_stops.py (12) | `trading/stops.py` rules and `EngineConfig` validation messages |
| test_bias.py (33) | Bias analysis (pure): no look-ahead (appending or changing later candles never changes an earlier row), each analysis candle sees only closed confirmation candles, the 15m candle is exactly its three 5m candles, every indicator alone, every timeframe pair, labels and thresholds, conflict = NEUTRAL, confidence, accuracy table, explanation |
| test_bias_engine.py (24) | Bias engine replayed on stored candles: every candle stored once and settled against the next candle of the same day, entries match the stored analysis, one entry per signal episode, one position at a time, no reversal on the exit candle, daily cap and no forced trades, enabled instruments and writing, time exit, trailing stop only tightens, target and stop for buy and sell, stale price, settings change without a restart, contract checks skip unavailable data, live refused |
| test_bias_api.py (8) | `/api/bias/*`: paper/replay only (live and other modes refused, trade mode and signal mode not overridable), settings and target need a running engine, report shapes, accuracy tally |
| test_privacy.py (8) + 2 in test_live_engine.py | What live mode may show the browser: redacted status, events and alerts, safety information kept, order ids removed, real trades never served while the database keeps them; paper/replay unchanged |

Not covered by an automated test: stopping the engine while a live exit order fails (it now logs an error; checked by reading), prediction mode in the before/after snapshot (covered by `test_live_engine.py`).

## Frontend (Vitest)
373 tests in 14 files: formatters, API client, hooks (`useApi`, `useAlerts`, the live data layer with WebSocket and REST fallback), every reusable component, charts (what is drawn), and all eleven pages including paper-trading start, position, square-off and the stored trade, and the automated paper trading page. Shared utilities in `src/test/`: a fake backend that stubs `fetch`, typed fixtures, a controllable fake WebSocket and a chart recorder. File table: [FRONTEND.md](FRONTEND.md#testing-11-nov-2026). jsdom has no layout engine, so real widths are checked by Playwright.

## Browser (Playwright, `frontend/e2e/app.spec.ts`)
`npx playwright test` starts (or reuses) the backend on **port 5001** and drives the installed Edge against the built app (`npm run build` first). It uses the real database and real Groww quotes (read-only).
- **Every page at 1920, 1440, 1280, 1024, 768, 430, 390 and 360 px (88 tests):** no horizontal overflow, content present, no error text, no console errors, no page errors, no failed API calls.
- **Navigation (8):** every page reachable by the sidebar (768+) or the bottom bar and "More" drawer (phones).
- **Live chart (8):** the chart canvas is drawn and sized sensibly at each width.
- **Connection indicator (8):** "Live push" on desktop while the WebSocket is up; with the WebSocket blocked the app shows "Polling" (desktop pill, or the compact phone pill) with no header overflow.
- **Privacy (2):** every page is visited at 1280 px; the test fails if any page text, tooltip, `aria-label`, hidden element, console line, API response or WebSocket frame contains account data (funds, margin, collateral, profile, order ids, labels such as "Groww margin"), if the removed endpoints (`/api/funds`, `/api/profile`, `/api/live/broker`) are ever requested, or if `/api/live/trades` returns a real-money trade.
- **Automated Paper Trading page (8 widths, in the 88 page tests above):** the new `/auto` route has no overflow, no console error and no failed API call at any width; it is also in the navigation and privacy tests.
- **Trading controls (2):** Start paper trading, state Waiting/Running, Stop; and the live-start refusal without the `LIVE` phrase.
- The first request after a server start takes about 9 s (cold Groww calls), so the tests wait for every "Connecting…"/"Loading…" text to disappear before checking.

## Before/after checks used for refactors (not part of the suite)
A snapshot script ran real-data backtests (EMA 9/21, 15m and 5m, 1 Oct-12 Nov 2026, read-only), position sizing, round-trip charges and five engine replays (cross, trend, paper pct stop, paper points stop, scalp) in a scratch database, then compared the JSON byte for byte before and after the engine, feed and scalping splits. See the 18 Nov entry in [CHANGELOG.md](CHANGELOG.md).

## Validation scripts for the automated engine (not part of the suite)
`scripts/validate_bias_accuracy.py` (read-only next-candle accuracy over stored candles, by year and by indicator) and `scripts/validate_bias_trades.py` (replays finished sessions through the engine on real premiums; writes only to a scratch database that it drops). Results: [AUTO_TRADING.md](AUTO_TRADING.md#validation-19-nov-2026-real-stored-candles-nothing-fitted).

`scripts/validate_premarket.py` (read-only; rebuilds the pre-market factors that have history for every session since 2022 and compares them with NIFTY's day) and `scripts/research_entries.py` (five-year entry-method research). Results: [PREMARKET.md](PREMARKET.md), [ENTRY_RESEARCH.md](ENTRY_RESEARCH.md).

## Market-hours verification (not yet done)
Real market-hours behaviour (the automated engine's 5-minute cadence, open-interest/spread/Greeks checks and live premium stop with Groww connected, 1 s push, premiums LIVE/DELAYED, a real signal producing one alert, reconnect with a live feed) can only be verified during a session. It is listed in [TODO.md](TODO.md); the closed-market checks and the replay/integration tests above are done.

**Pre-market addition (19 Nov):** backend 436 passed (34 new in `test_premarket.py`, 4 in `test_entries.py`); frontend 389 passed (14 new page tests, 1 new settings test), `tsc` and the build clean. Playwright was run only for the new page, navigation and privacy (18 tests): 17 passed first time, and the one failure (a Groww-dependent `/api/bias/analysis` 502 on a cold server) passed alone. The full 124-test Playwright suite was not re-run after adding the page. An old server left on the test port made the first run fail with 404s on the new routes: stop any old server before running Playwright.

**News addition (19 Nov):** backend 480 (the 78 pre-market tests plus smoke and privacy re-run after the change; the full suite was not re-run), frontend 408 passed (19 new), `tsc` and the production build clean. Playwright: the three news tests (1280, 768, 390 px) passed against live feeds. The news analysis is keyword rules and is not validated.

**Continuous automation (20 Nov):** full backend suite 493 passed (28 min), Vitest 426 passed (18 new), `tsc` and the production build clean. New backend tests cover the net profit target (net not gross, buy and sell side, stale price), the 70% threshold (inclusive boundary, replayed days), no re-entry on the exit candle, release after a target hit, repeated sequential trades, pause, phases, daily loss limit, restart recovery and the API defaults.

**Confluence strategy (21 Nov):** full backend suite 521 passed, Vitest 437 passed (11 new), `tsc` and the production build clean. New backend tests: `test_confluence.py` (hand-built bars for bullish and bearish gaps, unfilled / mitigated / filled status, retest, minimum size, expiry and session reset; ADR excluding today; swing structure and break of structure; every study and the strategy causal and non-repainting when later candles are appended or changed; gates and rejection reasons; a missing futures feed leaves VWAP out), 5 replay tests in `test_bias_engine.py` (validation, trades explained with every factor, an unsatisfiable setting trades nothing and says why, settings and strategy changed live, the default strategy unchanged) and 3 in `test_bias_api.py`. `entries.signals` was compared before and after the shared VWAP geometry was extracted: identical on 1,050 bars. One full Vitest run failed one test while the backend suite was starting up and loading the CPU; it passed in the four runs after and was not reproduced. Playwright was not re-run for the new panel. The five-year backtest is in [ENTRY_RESEARCH.md](ENTRY_RESEARCH.md): 0 of 12 pairs positive.

**Daily Range (23 Nov):** `test_daily_range.py` 28 passed on a throwaway database (OHLC against independently computed minute values, shuffled insert order, previous close, weekends/holiday/gap/short session, invalid prices, IST midnight, in-progress day and the forming minute, 10/20/50 averages and trend labels, highest/lowest, utilization above 100%, default window including 29 Feb, empty results, errors, cache hit and expiry, API contract, a year of 93,750 minutes aggregated in under 3 s). Vitest 494 passed (30 new in `daily-range.test.tsx`), `tsc` and the production build clean. Checked against the real database (read-only): all 246 sessions of the default window equal an independent pandas aggregation of the raw 1-minute candles (open, high, low, close, candle count); first call 0.5 s; 1 partial and 1 live day flagged. Viewed in Edge at 1440, 820 and 390 px: no horizontal overflow, no console errors, hover legend works.

**Trading Settings (21 Nov):** full backend suite 639 passed (639 collected: 88 in the new `test_trading_settings.py`, 8 replay tests added to `test_bias_engine.py`), Vitest 463 passed (17 new in `trading-settings.test.tsx` and `auto-trading.test.tsx`; two navigation tests updated for the extra page), `tsc` and the production build clean, Playwright: the new page at all eight widths and the privacy tests passed (no overflow, no console errors, no account data); the full Playwright suite was not re-run. Every strategy (32) was run alone at both entry timeframes (5/15 and 15/30), every strategy was blocked by each indicator it requires, an OFF strategy never signalled or ordered, settings were changed while a replay engine ran (applied at the next candle, session record updated), invalid or unreadable stored settings produced no orders. **Before** the final suite one stale assertion from the scored work was fixed (a validation message that gained `scored`); the earlier scored-strategy work had only been run in parts. The migration was applied to the real database by starting the app, a few minutes before the verified `pg_dump` (additive: one empty table; 28 trades and all candles unchanged).

**Scored strategy (21 Nov):** the full suites (backend 639, Vitest 463) were run once more after the Trading Settings work below and pass; `tsc` and the production build are clean. New backend tests for this strategy: 14 in `test_confluence.py` (the first-return FVG rule; the exact points of a hand-set candle and each gate failing on its own condition; conflict rejection; the optional context gate; causality on 5m and 15m by appending and by changing later candles; every entry meets the score and every gate; a higher minimum only removes entries; explanation; overlay keeps the bias prediction; strategy selection; the premium stop range; per-strategy statistics), 5 replay tests in `test_bias_engine.py` (validation, every candle analysed and near misses logged with nothing forced, a qualifying candle traded with its snapshot and reported separately, a stop outside 5-50% of the premium refused, settings changed live) and 3 in `test_bias_api.py`. The premium test found a real defect (replay set its stop after the fill and fell back to a percentage stop, so an out-of-range stop was not refused and the fallback could leave no stop); the check now runs before entry in paper and replay and the fallback can never leave a position without a stop. `entries.signals` was compared before and after each of the two refactors that generalized the entry timeframe and shared the trend rule: identical; the refactored research harness reproduces the earlier confluence backtest trade for trade. Results: [ENTRY_RESEARCH.md](ENTRY_RESEARCH.md): 0 of 80 pairs positive.


## Scanner and Position Trading tests (26 Nov 2026)
- `backend/tests/test_scanner.py` (15): the 0-100 quality score and its missing-data rules, independent strategies with capped concurrency, duplicate signals, risk limits, no daily trade cap, restart recovery, paper only.
- `backend/tests/test_position_analysis.py` (9, no database): bars and the NSE session split, no value depends on a later candle (causality and repainting), swing pivots, ADX, warm-up rows, the nine strategies, configurability, no volume data means no volume signal.
- `backend/tests/test_position_core.py` (17, no database): the option simulator (stop on a low, gap fills at the open, target, stop first on a double touch, time exit, expiry exit, every "cannot be priced" reason), statistics and the robust rule, Black-Scholes round trip, score components and decisions, contract quality and live quotes, the plan, settings validation.
- `backend/tests/test_position_account.py` (15, own database): the migration, sizing, duplicate and limit refusals, stop / Target 1 / trailing / Target 2 / time / expiry exits, restart recovery, settings versions, the API, and a static check that nothing in the module imports a broker or the live engine.
- `frontend/src/__tests__/pages/scanner-panel.test.tsx` (6) and `position-trading.test.tsx` (12); `vitest.config.ts` now sets a 15 s test timeout because the Trading Settings page tests take about 5 s when the whole suite runs in parallel.
- Run the database tests of one file at a time and never two pytest sessions at once. The full backend suite takes well over half an hour now (replays real days).

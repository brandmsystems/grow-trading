# Testing

Three layers, all runnable locally. Counts are from the runs on 18 Nov 2026.

| Layer | Tool | Where | Tests | Time |
|---|---|---|---|---|
| Backend unit + integration | pytest | `backend/tests/` | **333** | about 5-9 min (replays real days) |
| Frontend unit + component + page | Vitest 4, jsdom, React Testing Library | `frontend/src/__tests__/` | **346** | about 12-20 s |
| Browser (real Edge) | Playwright | `frontend/e2e/` | **106** | about 4-5 min |

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
| test_api_smoke.py (29) | Account endpoints with Groww mocked; live-control guard rails; `LIVE` phrase and lot cap checked before any key is read; Host/Origin guard; JSON errors; download validation; not-found cases; read endpoints |
| test_stops.py (12) | `trading/stops.py` rules and `EngineConfig` validation messages |

Not covered by an automated test: stopping the engine while a live exit order fails (it now logs an error; checked by reading), prediction mode in the before/after snapshot (covered by `test_live_engine.py`).

## Frontend (Vitest)
346 tests in 13 files: formatters, API client, hooks (`useApi`, `useAlerts`, the live data layer with WebSocket and REST fallback), every reusable component, charts (what is drawn), and all ten pages including paper-trading start, position, square-off and the stored trade. Shared utilities in `src/test/`: a fake backend that stubs `fetch`, typed fixtures, a controllable fake WebSocket and a chart recorder. File table: [FRONTEND.md](FRONTEND.md#testing-11-nov-2026). jsdom has no layout engine, so real widths are checked by Playwright.

## Browser (Playwright, `frontend/e2e/app.spec.ts`)
`npx playwright test` starts (or reuses) the backend on **port 5001** and drives the installed Edge against the built app (`npm run build` first). It uses the real database and real Groww quotes (read-only).
- **Every page at 1920, 1440, 1280, 1024, 768, 430, 390 and 360 px (80 tests):** no horizontal overflow, content present, no error text, no console errors, no page errors, no failed API calls.
- **Navigation (8):** every page reachable by the sidebar (768+) or the bottom bar and "More" drawer (phones).
- **Live chart (8):** the chart canvas is drawn and sized sensibly at each width.
- **Connection indicator (8):** "Live push" on desktop while the WebSocket is up; with the WebSocket blocked the app shows "Polling" (desktop pill, or the compact phone pill) with no header overflow.
- **Trading controls (2):** Start paper trading, state Waiting/Running, Stop; and the live-start refusal without the `LIVE` phrase.
- The first request after a server start takes about 9 s (cold Groww calls), so the tests wait for every "Connecting…"/"Loading…" text to disappear before checking.

## Before/after checks used for refactors (not part of the suite)
A snapshot script ran real-data backtests (EMA 9/21, 15m and 5m, 1 Oct-12 Nov 2026, read-only), position sizing, round-trip charges and five engine replays (cross, trend, paper pct stop, paper points stop, scalp) in a scratch database, then compared the JSON byte for byte before and after the engine, feed and scalping splits. See the 18 Nov entry in [CHANGELOG.md](CHANGELOG.md).

## Market-hours verification (not yet done)
Real market-hours behaviour (1 s push, premiums LIVE/DELAYED, a real signal producing one alert, reconnect with a live feed) can only be verified during a session. It is listed in [TODO.md](TODO.md); the closed-market checks and the replay/integration tests above are done.

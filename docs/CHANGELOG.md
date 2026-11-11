# Changelog

All dates are 2026, IST.

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

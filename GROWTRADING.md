# Groww Trading System: changes, implementation and status

This is the running record of everything built in this project: what each file does, every change made, what has been verified, the research results, and what is still open. [README.md](README.md) is the shorter how-to-use guide.

*Last updated: 11 Nov 2026, about 15:45 IST.*

---

## 1. Current status

| Area | Status |
|---|---|
| Groww connection | **Working.** Paid Trading API plan, TOTP key. The login token has `order`, `live_data`, `non_trading` and `back_test` permissions |
| Level 1: data | **Passed.** Five years of NIFTY 1-minute data stored and validated |
| Level 2: research | **Mostly done.** Seven strategies and the signal engine are built and tested. 26 of 28 strategy × timeframe runs are complete (the last two 1-minute runs are still running) |
| Prediction-based paper trading | **Built and verified** on replayed real days |
| Live dashboard simplification and alerts | **Unfinished: two sessions edited it at once** (see section 10) |
| Level 3: Telegram, live trading terminal | Not started |
| Git | Baseline commit `057d4dd` on `main`. Everything since is **uncommitted** on branch `level-1-data` |

**Main finding so far:** after real option prices and all costs, none of the 26 completed strategy setups made money over five years. The best, EMA 20/50 on 30-minute bars, roughly broke even. See section 7.

---

## 2. How to run

```powershell
.venv\Scripts\python app.py
```

| Page | Address | Purpose |
|---|---|---|
| Backtest | http://127.0.0.1:5000/ | Run one strategy over a date range and inspect every trade |
| Compare | http://127.0.0.1:5000/compare | All strategies × timeframes over five years, plus walk-forward |
| Signals | http://127.0.0.1:5000/signals | Signal engine: scores, stop/target levels, accuracy checks |
| Live / Paper | http://127.0.0.1:5000/live | Start paper, live or replay trading |
| Data | http://127.0.0.1:5000/data | Download history; coverage and quality report |
| History | http://127.0.0.1:5000/history | Candlestick chart of stored data (1, 5, 15, 30 minutes) |
| Account | http://127.0.0.1:5000/account | Groww profile and funds |

**Credentials** live only in `keys.txt`, which git ignores:
- `API_KEY=` holds the TOTP token.
- `TOTP_SECRET=` holds the TOTP code from the QR screen.
- An approval-type key uses `API_SECRET=` instead.

**Tests:** `.venv\Scripts\python -m pytest`. They create and drop their own `groww_trading_test*` databases.

---

## 3. Timeline of changes

### Stage 1: setup, backtester, live engine (first build)
- Flask app; Groww TOTP login with a token cached until 06:00 IST; profile and funds page.
- 9/21 EMA crossover strategy:
  - entry window and cutoff
  - opposite cross exits and reverses
  - 15:00 square-off
  - three execution modes: ITM 5 buy, ATM buy, ATM sell
- Backtester with the full Indian charge stack and slippage, metrics, and a trade viewer.
- Live / paper / replay engine with safety rails:
  - `LIVE` confirmation phrase and lot cap
  - daily loss limit and trade limit
  - stale-signal skip and restart recovery
  - exit retries, and an error state for unconfirmed orders
- A synthetic dataset for demos. It has since been removed from all pages and is used only by tests.

### Stage 2: Groww access
- Login supports both TOTP and API key + secret. The app detects which one `keys.txt` holds.
- **The free plan returns 403 for all market data.** After you bought the paid plan and generated a TOTP key, market data and history opened.

### Stage 3: Level 1, data
- **Git:** repository created; baseline committed; secrets excluded and scanned for.
- **Migrations:** numbered SQL files in `migrations/`, applied automatically at startup and recorded in `schema_migrations`.
- **Time zones:** all timestamps are stored as `TIMESTAMPTZ` and connections use Asia/Kolkata. The app works in IST wall-clock time.
- **Download manager** ([data_manager.py](data_manager.py)):
  - 30-day requests, downloading only missing days
  - resumes after failures, stops or restarts
  - counts duplicates and rejects invalid candles
  - keeps pre-open, after-close and Muhurat candles out of the stored regular session (counted separately)
  - lists every missing minute and never fills gaps
- **Data and History pages.**
- **Availability report:** 1,237 sessions from 11 Nov 2021, 0 days left to download, 0 invalid candles.
  - The 1-minute data rebuilds Groww's official daily OHLC exactly on all 19 days checked.
  - 72 weekday holidays, 2 Muhurat sessions and 4 short special sessions.
  - 4 real gaps in Groww's data: 7 Mar 2022, 28 Mar 2023, 26 Sep 2025, 29 Sep 2026.

### Stage 4: Level 2, research
- **Indicators** ([indicators.py](indicators.py)): EMA, Wilder RSI and ATR (RSI checked against Wilder's published example), MACD, session VWAP.
- **Seven strategies** ([strategies.py](strategies.py)): EMA 9/21, 5/20, 8/21, 20/50, and 9/21 confirmed by VWAP, RSI or MACD. Timeframes 1, 5, 15 and 30 minutes.
- **NIFTY futures** downloaded for VWAP and volume, because the index has no volume. Near-month contract, rolled on its expiry day.
- **Backtester upgrades:**
  - strategy choice and expiry rule (nearest weekly, next weekly, nearest monthly)
  - 40-day indicator history
  - option contracts downloaded 4 at a time, one request per contract
  - Groww's incomplete expired-contract lists handled by using the standard symbol
  - no more falling back to an earlier price when an exit candle is missing; the trade is skipped and logged
- **Compare page** ([research.py](research.py)): every strategy × timeframe over five years, with yearly and monthly P&L, win rate, drawdown, equity curves and walk-forward selection.
- **Signal engine** ([signals.py](signals.py), Signals page):
  - each signal gets an entry reference, a stop (1 × ATR) and a target (2 × ATR)
  - seven indicators, each marked as supporting or against
  - outcome = target reached before stop
  - logistic model trained walk-forward and checked on years it hadn't seen
  - score bands: <50, 50–69, 70–84, 85+

### Stage 5: prediction-based paper trading
- **Engine:** new **Prediction score** signal source. Only crossovers scoring at or above your minimum are traded. Exits at the NIFTY stop or target, checked on completed 1-minute candles, or at 15:00.
- **Same code offline and live:** shared `signals.features` / `signal_bars` / `Scorer` are used by both the Signals page and the engine.
- **Verified:** on three replayed real days, every live score matched the offline score exactly, and every exit matched the predicted outcome.
- **Fix:** a data refresh no longer deletes Signals analyses.

### Stage 6: dashboard simplification and alerts (unfinished, see section 10)
- **Alerts:** `live_alerts` table (migration 0007). Every engine entry, exit or skipped signal records one alert: BUY CE / BUY PE / SELL CE / SELL PE / SELL (exit) / BUY BACK / HOLD. It includes NIFTY level, strike, entry price, stop, target, score and time. A unique key prevents duplicates.
- **Status data:** market status, connection status, NIFTY price and EMAs, even while the engine is off.
- **Simplified Live page:** status bar, latest-signal card, four essential tiles, notification history with sound, flash and browser notification, and a settings side panel.
- **Fix:** replaying the same day twice used to skip every signal the second time. Replays are now self-contained.
- **Speed fix:** replay quote lookups are cached.

---

## 4. File inventory

### Python modules
| File | Lines | Role |
|---|---|---|
| [app.py](app.py) | 464 | Flask routes: pages and JSON API (section 9) |
| [config.py](config.py) | 74 | Paths, Postgres settings, `keys.txt` parsing |
| [groww_client.py](groww_client.py) | 85 | Groww login (TOTP or secret), token cache, one re-login on an auth error |
| [db.py](db.py) | 201 | Engine (IST session time zone), migration runner, candle and contract storage, backtest cache |
| [data_manager.py](data_manager.py) | 448 | Historical download (spot and futures), validation, coverage report, chart candles |
| [providers.py](providers.py) | 319 | Groww data provider (candles, expiries, contracts, option fetch); synthetic provider for tests only |
| [indicators.py](indicators.py) | 58 | EMA, Wilder RSI and ATR, MACD, session VWAP |
| [strategy.py](strategy.py) | 228 | Core trade rules: resampling, crosses, leg sequencing, strikes, expiry rules, fill prices |
| [strategies.py](strategies.py) | 96 | The seven compared strategies and their confirmation rules |
| [costs.py](costs.py) | 92 | Slippage and the Indian options charge stack |
| [metrics.py](metrics.py) | 43 | Win rate, profit factor, payoff, expectancy, drawdown |
| [backtest.py](backtest.py) | 334 | Backtest orchestration with real option prices; chart payloads; handles today's unfinished session |
| [research.py](research.py) | 157 | Full-history comparison and walk-forward selection |
| [signals.py](signals.py) | 387 | Signal engine: features, outcomes, walk-forward model, scorer |
| [jobs.py](jobs.py) | 47 | Background jobs with progress; separate lane for long research runs |
| [live_market.py](live_market.py) | 332 | Live Groww market data (spot, futures, LTP, contracts), paper and live brokers, replay market |
| [live_engine.py](live_engine.py) | 609 | Live / paper / replay engine: crossover and prediction modes, risk rails, alerts |
| [live_manager.py](live_manager.py) | 218 | Single engine instance, start/stop safety checks, dashboard status, alert history |
| [live_feed.py](live_feed.py) | 485 | **Added by the other session:** live quote, signal state, contract choice, position sizing, data checks for its version of the dashboard |

### Pages (templates and static)
| Page | Files |
|---|---|
| Backtest | [templates/dashboard.html](templates/dashboard.html), [static/dashboard.js](static/dashboard.js) |
| Compare | [templates/compare.html](templates/compare.html), [static/compare.js](static/compare.js), [static/research.css](static/research.css) |
| Signals | [templates/signals.html](templates/signals.html), [static/signals.js](static/signals.js), [static/research.css](static/research.css) |
| Live / Paper | [templates/live.html](templates/live.html), [static/live.js](static/live.js), [static/live.css](static/live.css). **These conflict: see section 10** |
| Data | [templates/data.html](templates/data.html), [static/data.js](static/data.js), [static/data.css](static/data.css) |
| History | [templates/history.html](templates/history.html), [static/history.js](static/history.js), [static/data.css](static/data.css) |
| Account | [templates/account.html](templates/account.html) |
| Shared | [static/app.css](static/app.css): colours (light and dark), layout, components |

### Other files
| File | Role |
|---|---|
| `migrations/0001`–`0007` | Database schema history (section 5) |
| [README.md](README.md) | How-to-use guide |
| [requirements.txt](requirements.txt), [pytest.ini](pytest.ini) | Dependencies and test settings |
| `keys.example.txt` | Template for `keys.txt` |
| `.env` | Postgres connection and `LIVE_MAX_LOTS` (git-ignored) |
| `index.html` | Original placeholder; unused |

---

## 5. Database (PostgreSQL 17, `groww_trading`)

| Migration | Adds |
|---|---|
| 0001_baseline | Candles, expiries, contracts, fetch log, live sessions / trades / events, backtest cache |
| 0002_timestamptz | Every timestamp converted to `TIMESTAMPTZ` (existing values read as IST) |
| 0003_data_management | `data_downloads` (each download attempt) and `data_day_quality` (per-day quality) |
| 0004_outside_session | Out-of-hours candle counts kept apart from invalid ones |
| 0005_strategy_results | Compact five-year results per strategy × timeframe |
| 0006_prediction_trades | Score, stop, target and ATR on prediction-mode trades |
| 0007_live_alerts | Notification history with a unique key per signal |

**Stored now:**
- 462,595 NIFTY 1-minute candles
- 61 monthly futures contracts
- 7,927 option contracts downloaded (cached, so later runs are fast)
- 26 comparison results

---

## 6. Trading rules (unchanged core)

- **Signal:** EMA cross on a closed bar, aligned to 09:15. Equal EMAs are never a cross.
- **Fill:** the open of the 1-minute candle starting when the signal bar closes.
- **Entry window:** inclusive, default 09:30–14:30.
- **Exits:**
  - opposite cross (inside the window, it also reverses the trade)
  - 15:00 square-off
- **Strikes:** ATM rounds to the nearest 50. ITM 5 = 250 points in the money.
- **Expiry:** nearest weekly by default; rolls on expiry day.
- **Costs:**

| Item | Rate |
|---|---|
| Slippage | 0.5% + 0.5 points per fill |
| Brokerage | ₹20 per order |
| STT | 0.15% of sell premium |
| Exchange fee | 0.03503% |
| SEBI fee | ₹10 per crore |
| Stamp duty | 0.003% of buy value |
| GST | 18% |

- **Lot size:** 65 for every year (historical lot sizes are not applied).
- **Missing data:** a missing option candle (none within 3 minutes) skips the trade with a logged reason. No price is ever estimated.

---

## 7. Research results (11 Nov 2021 → 11 Nov 2026, 1 lot, after all costs)

**15 and 30-minute, ATM buy:**

| Strategy | 30m net | 15m net |
|---|---|---|
| EMA 20/50 | **+₹2,048** (PF 1.01) | −₹20,863 |
| EMA 9/21 + MACD | −₹21,403 | −₹1,43,280 |
| EMA 9/21 | −₹64,795 | −₹1,80,326 |
| EMA 9/21 + VWAP | −₹88,041 | −₹1,26,130 |
| EMA 5/20 | −₹1,14,046 | −₹3,16,191 |

**Shorter timeframes lose much more:**
- 5-minute ATM buy loses ₹3.3–7.7 lakh.
- 1-minute loses ₹12.7 lakh to ₹49 lakh, because there are far more trades and so far more costs.

**Best of all 78 results** (26 setups × 3 modes): EMA 20/50 30m ATM sell, **+₹8,807**.

**Walk-forward** (each year uses the setup that did best on earlier years only):
- ATM buy: −₹52,537
- ITM 5 buy: −₹82,819
- ATM sell: −₹52,684

**Your original 9/21 at 15m, ATM buy:** lost every year from 2021 to 2025 (₹32k–51k a year). 2026 so far: +₹9,931.

**Signal engine, 15m** (568 signals scored on years the model hadn't seen):

| Measure | Value |
|---|---|
| Base hit rate | 26% |
| Score 50+ | 29 signals, 38% hit |
| Score 70+ | 1 signal (too few to judge) |
| Ranking skill (AUC) | 0.587 |

At 5m the model is no better than chance; 30m has too few signals.

**These are past results. They don't predict future returns.**

---

## 8. Live / paper engine

| Setting | Options |
|---|---|
| Trading mode | **Paper** (live Groww prices, simulated fills), **Live** (real MIS orders), **Replay** (a stored day on a fast clock) |
| Signal source | **Every crossover** (original rules), or **Prediction score** (only crosses scoring ≥ your minimum; exits at stop, target or 15:00) |
| Safety | `LIVE` confirmation, `LIVE_MAX_LOTS` cap, daily loss limit, trades-per-day limit, stale-signal skip, restart recovery, 5 exit retries, ERROR state on unconfirmed orders, Check Groww positions |

**Before trading real money:**
- Run paper for several sessions first.
- The prediction rule has not been backtested on option P&L yet.

---

## 9. API endpoints ([app.py](app.py))

| Area | Endpoints |
|---|---|
| Pages | `/`, `/compare`, `/signals`, `/live`, `/data`, `/history`, `/account` |
| Account | `GET /api/status`, `POST /api/login`, `POST /api/logout`, `GET /api/profile`, `GET /api/funds` |
| Backtest | `GET /api/bt/meta`, `POST /api/bt/data`, `POST /api/bt/run`, `GET /api/bt/result/<h>`, `GET /api/bt/chart/<h>/<trade_id>`, `GET /api/jobs/<id>` |
| Data | `GET /api/data/overview`, `POST /api/data/download`, `POST /api/data/stop`, `GET /api/data/candles` |
| Research | `GET /api/research`, `POST /api/research/run`, `GET /api/signals`, `POST /api/signals/build` |
| Live | `GET /api/live/status`, `GET /api/live/dashboard` (added by the other session), `POST /api/live/start`, `POST /api/live/stop`, `POST /api/live/squareoff`, `GET /api/live/trades`, `GET /api/live/broker` |

---

## 10. Open issue: two sessions edited the Live dashboard at once

The same dashboard request ran in two Claude sessions at the same time (this one and `grow-trading-9e`). Both changed the Live page.

| File | This session | Other session |
|---|---|---|
| `static/live.css` | Wrote a simplified layout | **Overwrote it** with a different layout (`.dash`, `.s-chart`, `.s-signal`) |
| `templates/live.html`, `static/live.js` | Rewrote both | Unknown; may also have changed them |
| `live_feed.py`, `tests/test_live_feed.py` | — | Added (quote feed, contract choice, sizing, data checks) |
| `app.py`, `live_manager.py` | Added alert and status helpers | Changed them too (`/api/live/dashboard`, imports `market_status` from `live_feed`) |
| Test databases | Shared | Its test runs dropped `groww_trading_test_live` during this session's runs |

**State:**
- The app still imports and starts.
- The Live page's HTML, JS and CSS may come from different sessions and may not match.
- The live engine tests could not finish cleanly while both sessions were running.

**To resolve:** let only one session continue the Live dashboard. Then rerun the full test suite once, with nothing else running, and check the Live page on desktop and phone.

---

## 11. Tests

| File | Tests | Covers |
|---|---|---|
| test_setup.py | 4 (+ parametrised) | Keys file formats, routes without keys |
| test_strategy.py | 17 | Resampling, crosses, window, reversal, square-off, strikes, expiry, fill prices |
| test_costs_metrics.py | 6 | Fills, charges, metrics |
| test_providers.py | 3 | Candle parsing, option symbols |
| test_backtest_integration.py | 10 | End-to-end backtest, today's unfinished session, auto-refresh timing |
| test_data_manager.py | 24 | Migrations, time zones, downloads, resume, duplicates, gaps, validation, out-of-hours candles, chart, API |
| test_research.py | 17 | Indicators, confirmation rules, expiry rules, futures roll, outcomes, model, walk-forward, cache |
| test_live_engine.py | 16 | Engine = backtest, rejected and failed orders, limits, restart, prediction mode, alerts, market status |
| test_live_feed.py | 21 | Added by the other session |

**Last clean full run:** 108 passed (before the dashboard and alerts work). The alert and prediction tests passed individually. The full live engine file has to be rerun once only one session is active.

---

## 12. Grow Trading restructure: plan (Phases 1–2 done 11 Nov 2026; nothing moved yet)

**Baseline before any change:** all **134 tests pass** (`pytest`, 270 s, run with no other session active). The comparison grid finished all 28 configurations. The other dashboard session (`grow-trading-9e`) has ended; files have been unchanged since 15:38.

### Phase 1–2 findings
- **Dependencies:** there are no circular imports.
  - `strategy`, `indicators`, `costs` and `metrics` are pure.
  - `db` and `groww_client` depend only on `config`.
  - Moving files is mechanical: import paths change; logic doesn't.
- **Duplicates to merge (after checking usage):**
  - `_hm` in backtest, live_engine and live_feed → one helper.
  - `_now` in backtest, data_manager and providers. Tests patch each one separately, so merging them means updating those tests too.
  - NIFTY quote/EMA snapshot in both `live_manager.snapshot` and `live_feed.Feed`: keep one.
- **The Live page is mixed between the two sessions:** `live.html` is from this session, `live.js` and `live.css` from the other. The React dashboard will replace all three.
- `index.html` is an unused "Hello World" placeholder.
- `flask-socketio` is not installed. Node 24.11 and npm 11.6 are available for React.

### Planned file moves (`git mv`, so history is kept)
| Old file | New location |
|---|---|
| config.py | backend/app/config/settings.py: finds `keys.txt`, `.env` and the token cache at the project root, so they don't move. Adds `GROWW_API_KEY` / `GROWW_TOTP_SECRET` environment variables, with `keys.txt` as fallback |
| db.py, migrations/ | backend/app/database/ (engine, migration runner, queries). The file names stay the same, so `schema_migrations` is unaffected |
| groww_client.py | backend/app/services/groww/client.py |
| data_manager.py, providers.py | backend/app/services/market_data/history.py, providers.py |
| live_market.py | backend/app/services/market_data/live.py (Groww and replay markets); brokers → services/trading/brokers.py |
| live_feed.py | services/options/ (contract choice, premium, sizing) + services/market_data/ (quote) |
| strategy.py, strategies.py, indicators.py, signals.py | backend/app/services/strategy/ |
| costs.py | backend/app/services/trading/charges.py |
| live_engine.py, live_manager.py | backend/app/services/trading/engine.py, manager.py |
| backtest.py, metrics.py, research.py | backend/app/services/backtest/ (an extra folder the plan allows) |
| jobs.py | backend/app/workers/jobs.py; the new SocketIO broadcaster lives here too |
| app.py routes | backend/app/api/ blueprints (account, data, backtest, research, signals, live) + backend/app.py |
| tests/ | backend/tests/ |
| templates/, static/ | Replaced by frontend/ (React 19, TypeScript, Vite, Tailwind, Lucide, Lightweight Charts) |

### Risks and safeguards
- **Database:** no schema or data changes are needed, and nothing is deleted.
- **Credentials:** `keys.txt` and `.env` stay where they are and remain git-ignored.
- **Order safety:** live orders stay behind the existing confirmation. Adding per-order manual confirmation needs a decision (below).
- **Verification:** after the move, the same 134 tests must pass before any new feature is added.

### Decisions needed before Phase 3
1. **Pages:** port all existing pages (Backtest, Compare, Signals, Data, History, Account) to React, or only the live dashboard?
2. **Order confirmation:** what "manual confirmation by default" should mean for live orders.
3. **Git:** permission to commit the current work first, so the restructure can be rolled back cleanly.

## 13. Known limitations and next steps

**Limitations:**
- **Lot size:** a fixed 65 for every year.
- **Holidays:** no holiday calendar, so a weekday holiday looks like "no candles returned", and market status shows "open" on holidays.
- **Option-chain data:** OI, IV and Greeks have no history on Groww, so they can't be tested or used in the score.
- **Exit timing:** prediction-mode exits happen once the deciding minute has closed, up to about 1 minute after the touch.
- **Comparison:** the last two 1-minute runs are still computing.

**Next steps:**
1. Resolve the two-session conflict on the Live dashboard (section 10), then rerun all tests.
2. Add a "Prediction score ≥ X" filter to the Backtest page, to measure the prediction rule's real option P&L.
3. Commit the work to git once tests pass.
4. Level 3 (Telegram, live terminal) only after paper trading has been tested.
5. Revoke the old Groww keys that were pasted into chat.

# Frontend

**Stack:** React 19, TypeScript 5, Vite 8, Tailwind CSS 4, Lucide React, TradingView Lightweight Charts 4.2, React Router 7. There are no other dependencies.

**Address:** the app runs under **`/app`**:
- **Production:** http://127.0.0.1:5000/app, served by Flask from `frontend/dist`.
- **Development:** http://127.0.0.1:5173/app, via Vite, which proxies `/api` and `/socket.io` to Flask.

**Design pass (11 Nov 2026):** the redesign was frontend only. No backend file, route, response, database table or trading rule changed.

## Layout and navigation
| Screen | Navigation |
|---|---|
| Desktop (≥1024 px) | Left sidebar with names. It collapses to icons (button at the bottom; the choice is saved) and shows a live NIFTY/signal tile |
| Tablet (768–1023 px) | Sidebar as an icon rail |
| Phone (<768 px) | Compact header showing NIFTY price and the latest signal. Bottom bar with Overview, Live, Signals, Backtest and **More**, which opens a drawer with every page |

**Header (all sizes):**
- page title
- Groww connection (connected, delayed, error, backend offline)
- market status and engine state
- notification bell with an unread badge
- sound toggle and theme toggle (on phones, sound and theme are under Account & Settings)

## Colour system
Colours mean the same thing on every page (`src/index.css`):

| Colour | Meaning |
|---|---|
| Green | Up moves, BUY signals, CE, profits |
| Red | Down moves, losses, PE, risk of loss |
| Blue | NIFTY spot and primary actions |
| Purple | Strategy and indicators (EMAs, signals) |
| Orange | Warnings, risk, charges |
| Grey | Neutral |

Light and dark themes are both supported; dark is the default.

## Pages
| Page | Route | API calls | Shows |
|---|---|---|---|
| Overview | `/app/` | shared live feed + `GET /api/live/trades` | NIFTY spot card, option premium (CE/PE), 9/21 strategy card (EMAs, trend, latest cross, signal), today's or last-session performance (P&L, trades, won, lost, win rate), 5-min chart, recommendation, recent notifications |
| Live Trading | `/app/live` | shared live feed + trades, `POST /api/live/start, stop, squareoff, confirm, reject` | Spot card; large candle chart (5/15/30 min) with EMA 9/21, crossover arrows, engine entry/exit markers and stop/target lines (zoom, pan, crosshair); CE/PE premium; recommendation; order calculator; trading controls with manual order confirmation; notifications |
| Trading Signals | `/app/signals` | shared live feed, `GET /api/signals`, `POST /api/signals/build`, `GET /api/bt/meta` | Latest live signal with entry, stop, target, time and EMA confirmation; exit signals; past signals with a strength bar (Weak / Moderate / Strong), outcomes and indicator checklist, labelled as history; **Calibration check** (Phase 2): verdict, AUC with range, calibrated vs average, band hit rates with 95% ranges and a range bar, ten score groups, walk-forward by year |
| Options Analysis | `/app/options` | shared live feed, `GET /api/options/chain` | Spot vs the selected contract (strike, expiry, premium, chain LTP, OI, IV, delta, moneyness); **live option chain** (Phase 2): expiry and ATM ±5/10/15/20 selectors, spot shown apart from premiums, CE and PE side by side (LTP, change, IV, delta, volume, OI change, OI), ATM outlined, in-the-money shaded, call/put OI totals and a calculated put/call ratio; refreshes every 15 s while open |
| Backtesting | `/app/backtest` | `GET /api/bt/meta`, `POST /api/bt/run`, `GET /api/jobs/<id>`, `GET /api/bt/result/<h>`, `GET /api/bt/chart/<h>/<id>` | Settings (strategy, timeframe, dates, window, expiry, lot size: NSE history or fixed, lots, charges); KPIs (net P&L, win rate, trades, max drawdown, costs split into brokerage & taxes and slippage, profit factor with payoff ratio and average win/loss); filters for year, winners/losers, direction (CE/PE side), crossover number of the day and entry time range; equity curves for all three modes; monthly P&L bars; year × month table; best and worst days; trade list with spot and option charts (quantity and lot-size source per trade); no-trade days and skipped trades |
| Strategy Comparison | `/app/compare` | `GET /api/research`, `POST /api/research/run`, `GET /api/bt/meta` | 7 strategies × 4 timeframes coloured green/red by net P&L; tick up to 4 for equity curves; win rate and drawdown bars; year-by-year table; walk-forward table. Clicking a cell opens it in Backtesting |
| Trading Settings | `/app/trading-settings` | `GET /api/trading-settings`, `POST /api/trading-settings/validate`, `PUT /api/trading-settings`, `POST /api/trading-settings/reset`. Summary of the active configuration and last saved time; ON/OFF switch and parameters for each of the 32 strategies (grouped), the four timeframes with trend / entry / exit roles, the 11 indicators and the paper-trading rules; Save, Discard, Reset to defaults (asks first), Enable all / Disable all, live validation messages next to the fields, blocked-strategy reasons, unsaved-changes warning (banner, browser warning, in-app link confirmation). See [TRADING_SETTINGS.md](TRADING_SETTINGS.md) |
| Automated Paper Trading | `/app/auto` | `GET /api/bias/config`, `/api/bias/status` (3 s), `/api/bias/analysis` (30 s, engine stopped), `/api/bias/predictions`, `/trades`, `/summary` (8 s), `/accuracy`, `/history-accuracy`, `/trade/<id>`, `POST /api/bias/start`, `/api/bias/pause`, `/api/bias/resume`, `/api/bias/settings`, `/api/paper/position/target` and `/stop`, `/api/live/stop`, `/api/live/squareoff` | Paper-only notice; Start paper trading / replay a finished day / Pause / Resume / Stop; **continuous automation panel** (phase and a plain sentence: ready for entry or re-entry, holding, exiting, waiting, paused, daily limit, halted; current bias against the editable Market Bias threshold, default 70%; the editable net profit target per trade, default ₹1,500; completed trades, profit-target hits, total trades, net paper P&L, last exit and its reason); the open position also shows why it was entered and how much of the net target is reached; **scored strategy panel** (settings, the one-click risk preset, score out of 100 with long and short, each component's points and condition, every entry gate, the refused near-miss signals with reasons; a trade's dialog shows its points); **per-strategy performance** (trades, win rate, net expectancy, profit factor, drawdown); **confluence strategy panel** (entry strategy switch, per-factor On / Required boxes, vote, status and condition, confirmation score against the minimum, bullish and bearish fair value gap with status and retest, 5/10/20-day ADR and the range used today, why no entry; previews the latest candle with the chosen settings before the engine starts, applies live while it runs); market bias (label, indicator agreement %, 15m and 5m trend, next-candle forecast, signal, supporting and opposing indicators, why HOLD); every strategy's vote on both timeframes; daily trade count and remaining limit, wins, losses, win rate, net P&L; the active position with stop/target edit and Close now; the day's orders (click one for its complete reasoning); predictions vs actual candle results; accuracy per strategy and timeframe (this app's predictions or the last 60 days of stored candles); performance breakdown; all settings (applied to the running engine without a restart); engine log. Components in `components/auto/`. See [AUTO_TRADING.md](AUTO_TRADING.md) |
| Pre-Market Analysis | `/app/premarket` | `GET /api/premarket/report` (60 s), `/api/premarket/news` (120 s, refresh button forces), `/api/premarket/history` (120 s), `POST /api/premarket/refresh`, `/api/premarket/input` | Not-a-signal notice; total score on a -5..+5 meter; final conclusion (direction, CE/PE/HOLD lean, levels, risks); five factor cards (result, score, data, time, source, warnings); news with impact; live market news section (tabs, search, date filter, breaking highlight, summaries, impact, original links) and news evidence on each factor card; entry form for FII/DII and events; history of bias versus actual day and paper result; validation note. Components in `components/premarket/`. See [PREMARKET.md](PREMARKET.md) |
| 5-Minute Scalping | `/app/scalping` | `GET /api/scalping`, `/api/scalping/config`, `/api/scalping/paper/trades`, `POST /api/scalping/run`, `/api/scalping/paper/start`, `/api/live/stop`, shared live feed | Verdict (consistent configurations, best under the selection rule, top in-sample, walk-forward total); CE vs PE per strategy; walk-forward table; all 120 configurations, filterable by contract and exit and sortable (in-sample rank, net, out-of-sample, PF, drawdown, win rate, trades); the selected configuration's KPIs (net, gross, brokerage, taxes, wins/losses, win rate, PF, max DD, average hold, risk/reward), consistency checks, CE vs PE, in- vs out-of-sample, equity, yearly, by market regime, monthly bars, risk % sizing, and a paginated, clickable BUY/SELL trade list; comparison with the existing strategies; automatic paper trading (pick a tested configuration, paper or replay, risk settings, start/stop, clickable transaction table). See [SCALPING.md](SCALPING.md) |
| Market Data | `/app/data` | `GET /api/data/overview`, `/api/data/options`, `/api/data/lot-sizes`, `POST /api/data/download`, `/api/data/options/download`, `/api/data/stop`, `GET /api/jobs/<id>` | Coverage KPIs; spot, futures and options cards (counts, date range, latest candle, last successful download); intervals; month grid (links to Historical Charts); missing periods; days with gaps; spot download with progress and stop; option history (scope, % downloaded, per-month table, download/resume and stop, last run); NSE lot-size table with sources; download history |
| Daily Range | `/app/range` | `GET /api/data/daily-range` | Period buttons 1M / 3M / 6M / 1Y (ending on the newest stored session) and custom From / To dates; six summary cards (period high and low, current price, average, highest and lowest daily range); interactive chart (daily candles, or range bars with 10/20/50-day average range lines; green = closed above its open, red = below, lighter = incomplete or live day; hover legend with date, OHLC, range points and %, change; wheel/pinch zoom, drag to pan); **range analysis** (ADR, 10/20/50-day averages, trend, highest/lowest/median range, today's or the latest session's range against the average with range used % and points left); history table with sorting, search, green/red/incomplete filter and pagination. Chart and table share one response; every calculation has a tooltip. Components `components/charts/RangeChart.tsx`, `components/range/DailyTable.tsx`. Aggregated on the server: the browser never loads 1-minute candles |
| Historical Charts | `/app/history` | `GET /api/data/overview`, `GET /api/data/candles` | Stored NIFTY candles at 1/5/15/30 min with optional EMA 9/21, date range, earlier/later/latest, zoom and pan |
| Account & Settings | `/app/account` | `GET /api/status`, `POST /api/login` | Groww connection status and re-login (no funds, balance or profile: removed 18 Nov); theme, sound and browser notification permission; order calculator defaults (capital empty = the paper account) |

**Live Trading page order (12 Nov 2026):** the price, high and low, then today's plan, the current prediction, the live chart, and paper positions and stop-loss. On phones, the prediction card moves between the plan and the chart.
- **NIFTY 50 Spot:**
  - price, change and change %
  - day high / low with points from each
  - previous close
  - a day-range bar showing where the price sits between low and high
  - the updated time and age, with clear *Delayed* / *Disconnected* states
- **Today's Trading Plan:**
  - previous close, open, high, low, and the bullish and bearish levels
  - trend, EMA 9/21, VWAP, RSI and volatility
  - three expandable scenarios (the current one highlighted and open)
  - support/resistance table and plan-change history (expandable); the creation time and latest change with its reason
- **Recommended Option → View reason** (expandable):
  - each check with its actual value, marked supports / against / neutral / unavailable
  - confidence with its band's out-of-sample hit rate
  - why the call isn't HOLD (or why it is HOLD and what's needed), and a caution on weak confirmation
- **Chart:**
  - 1 / 5 / 15 / 30-minute candles
  - toggles: VWAP, futures volume, support/resistance lines (pivot R1/S1, previous day high/low, opening range), and RSI & MACD panels time-synced with the chart
  - markers: crossovers (9/21 ↑/↓), strategy calls (BUY CE / BUY PE / EXIT / HOLD) and engine fills
  - lines: the signal's entry reference, stop and target (the paper position's premium stop and target as NIFTY levels via delta)
- **Candle Patterns:** today's patterns on closed candles, each expandable with OHLC, rule, confirmation (RSI, VWAP, EMA), status and effect on the current call. Doji are counted, not listed.
- **Paper position (Trading Controls):** entry premium, stop, target, R:R, maximum risk ₹ and %, risk budget, stop method, and a **Change stop** field. The backend refuses changes beyond the risk limits, with the reason. Stop-loss methods include fixed premium points.
- **Paper Trades detail:** stop-loss history (set at entry, each change, maximum loss before and after).

**Paper trading risk (Live Trading page, paper mode):**
- **Risk Management card** (replaces the Order Calculator in paper mode):
  - presets 0.5/1/1.5/2% or custom
  - inputs: virtual capital (defaults to available balance), risk %, entry premium (defaults to the recommended contract's Groww premium), stop-loss as % below or a price, lot size (the contract's), max lots
  - shows the 11 figures and TRADE / NO TRADE with the reason, recalculated as you type (`POST /api/paper/risk-calc`, the engine's own function)
- **Daily Risk card:** starting daily capital, today's P&L, daily loss limit, remaining risk budget, consecutive losses, max drawdown, open-position risk, risk used % with a bar, next trade's risk, virtual account balance/available and **Reset account** (type RESET; disabled while the paper engine runs).
- **Paper Trades & Risk:** every paper trade with risk %, capital, risk ₹, stop distance, lots × lot size, max loss, gross, charges + slippage, net and R:R. Clicking a trade shows the full risk calculation saved at entry, its checks, exit reason and net vs max loss.
- **Trading Controls (paper):** risk per trade (presets/custom), daily risk %, max lots, max open positions, minimum balance, stop-loss method (ATR × delta or % of premium) and its value. Lots are calculated, not entered.

**One shared live poll:** `context/LiveContext.tsx` polls `/api/live/dashboard` once for the whole app, every 2 s while the market is open or the engine runs, otherwise every 10 s, with backoff when the backend is unreachable. The header, Overview, Live Trading, Signals and Options all read that one response, so changing pages never duplicates calls.

## Live updates (Phase 3)
- **Push first:** one Socket.IO connection for the whole app (in `LiveProvider`). The header shows **Live push** while it delivers, or **Polling** when the app has fallen back to REST.
- **Fallback:** when the socket is disconnected or no event arrived for 15 s, the app polls `/api/live/dashboard` (2 s open, 10 s closed). While the socket is healthy, no dashboard requests are made.
- **Notifications:** "Live push interrupted" and "reconnected" appear in the notification panel.
- **CE/PE premium card:** both sides for one strike (the recommended contract, else ATM): premium, change, volume, OI, IV, delta and a LIVE / DELAYED / CLOSED / UNAVAILABLE label. Delayed premiums are dimmed with the age of the last good quote.

## Notifications
- **Sources:**
  - signal and trade alerts from the server (`live_alerts`, stored once per signal, so never duplicated)
  - connection-lost/restored and engine-state-change events, created by the app from real state changes
- **On a new alert:**
  - a sound (different tones for entry, exit and warnings)
  - a browser notification, if permitted
  - a flash on the recommendation card
  - the tab title changes while the tab is hidden
  - the unread badge goes up (cleared when the panel is opened)
- **Duplicates:** alerts that existed when the page opened never trigger sound or notifications.
- **Where they're shown:** the bell's panel shows the full history. Overview and Live Trading show the latest.

## Live order safety
- **Starting Live:** requires typing `LIVE` and is capped by `LIVE_MAX_LOTS`.
- **Manual confirmation is the default:** each entry appears as **Confirm live order** with a countdown. Nothing is sent unless you click *Place order*.
- **Automatic entries:** need a checkbox ticked before each start. The setting is never restored from storage.
- **Protective exits** (stop, square-off, 15:00, loss limit) are automatic.

## Components (`frontend/src`)
| Folder | Components |
|---|---|
| `components/layout/` | `AppLayout` (shell), `Sidebar`, `Topbar`, `MobileNav` (bottom bar + drawer), `NotificationPanel` (+ reusable `AlertList`), `nav.ts` (one list for every navigation) |
| `components/market/` | `MarketCards`: `SpotCard`, `PremiumCard`, `StrategyCard`, `PerformanceCard` |
| `components/trading/` | `RecommendationCard`, `OrderCalculator`, `EnginePanel` (controls), `PendingOrder` (confirm with countdown) |
| `components/charts/` | `CandleChart` (candles, optional EMAs, cross/trade markers, price levels), `SeriesChart`: `LineChart` (equity) and `BarsChart` (monthly P&L), `RangeChart` (daily candles or range bars with 10/20/50-day average lines) |
| `components/common/` | `Card` (with colour accent), `Stat`, `InfoTip`, `Pill`, `Dot`, `BigValue`; `Controls`: `Field`, `Segmented`, `Button`, `PageHeader`, `inputCls`/`selectInline`; `States`: `Loading`, `Empty`, `ErrorNote`, `Warning`, `Limitation`, `Progress` |
| `context/` | `SettingsContext` (theme, sound, timeframe, capital, risk %, engine form, sidebar state; saved per browser), `LiveContext` (shared live poll, today's trades, alerts, status events, unread count) |
| `hooks/` | `useDashboard` (Socket.IO push with sequence checks and stale detection; REST polling with backoff as fallback; socket closed on unmount), `useAlerts` (new-alert detection, sound, notifications, `describe`), `useApi` (load/reload with loading and error) + `waitForJob` |
| `services/api.ts` | Every API call. `request` returns the full envelope (`data`, `job`, `hash`); `api` returns `data` |
| `types/api.ts` | Types for every response used |
| `utils/format.ts` | ₹ (incl. lakh/crore), numbers, %, IST dates and times, chart time |

**Removed in this redesign** (replaced, not duplicated): `components/dashboard/{Header, MarketSummary, SignalCard, Notifications}.tsx` and `pages/LiveDashboard.tsx`.

## Backend limitations (shown on the pages, not worked around)
| Request | Status |
|---|---|
| CE **and** PE premiums at the same time | **Done in Phase 2** on Options Analysis (option chain). The live dashboard still returns only the recommended contract |
| Premium change, OI change | From each contract's Groww quote, for ATM ±5 only (rate limits); other strikes show "—" |
| Option chain, list of expiries | **Done in Phase 2:** `GET /api/options/chain` |
| Historical IV / Greeks | Not available from Groww; only live values |
| Historical charts for other instruments | `/api/data/candles` serves NIFTY spot only |
| EMAs on historical charts | Calculated in the browser on the loaded range (same formula); the first bars differ slightly from the strategy's EMAs, which carry over from earlier days. Labelled on the page |
| Live strength score | Live crossover signals have no score; strength bars apply to the historical analysis |

## Testing (11 Nov 2026)
- **Build:** `npm run build` (TypeScript strict type check + production build) passes. Each page loads only when first opened. Libraries are split into long-lived chunks (`react-vendor` 258 kB, `charts` 158 kB, `realtime` 41 kB), so the app's own entry chunk is 100 kB (it was one 548 kB file and Vite warned about the size).
- **Component, hook and page tests:** `npm test` runs Vitest 4 with jsdom and React Testing Library: **463 tests in 17 files** (about 12 s; 4 full runs in a row all green). Run from `frontend/`; `npm run test:watch` re-runs on change. **On Windows start it from a path with an upper-case drive letter** (`C:\...`); from `c:\...` Vitest loads itself twice and every suite fails with "failed to find the current suite".

  | File (`src/__tests__/`) | Tests | What it checks |
  |---|---|---|
  | `format.test.ts`, `api.test.ts` | 8 + 6 | Indian number/date formatting; the API client's envelope, error and unreachable handling |
  | `hooks/useApi-useAlerts.test.tsx` | 19 | `useApi` (loading, error, reload, stale responses ignored); `waitForJob`; alert text; `useAlerts` notifies once per new alert, never for alerts present at load, respects sound and browser permission |
  | `hooks/live.test.tsx` | 16 | The live data layer: REST fallback, WebSocket subscribe/push, duplicate and out-of-order events dropped, stale-socket detection, drop and reconnect, offline and recovery, engine-state and connection notifications, unread badge |
  | `components/common.test.tsx` | 22 | Card, Stat, Pill, Segmented, Button, Field, PageHeader and the loading/empty/error states |
  | `components/layout.test.tsx` | 30 | Sidebar, MobileNav (drawer, bottom bar), Topbar (Live push vs Polling vs Backend offline, bell, sound, theme), NotificationPanel, AppLayout |
  | `components/charts.test.tsx` | 15 | What `CandleChart`, `LineChart` and `BarsChart` draw: candles, EMAs, VWAP, volume, crossover and trade markers, price levels, RSI/MACD panels, cleanup |
  | `components/market.test.tsx` | 37 | Spot, premium, strategy and performance cards; trading plan and patterns; recommendation and "view reason"; calibration; the option chain (expiry/width requests, refresh, polling only while open) |
  | `components/trading.test.tsx` | 52 | Engine panel (start paper/replay/live, Live confirm phrase and lot cap, stop, square off, paper stop-loss edit), pending live order confirm/skip and countdown, order calculator, risk calculator, daily risk and `RESET` account reset, paper trades table |
  | `pages/live-pages.test.tsx` | 28 | Overview, Live Trading (chart markers and levels, toggles, paper trading start → position → square off → stored trade), Options |
  | `pages/trading-settings.test.tsx` | 16 | Every strategy, timeframe, indicator and rule drawn with its state, the summary and last saved time, toggles and edits sent on save with the base version, blocked strategies and warnings, server validation errors next to their fields, refused and stale saves, reset with confirmation, discard, enable / disable all, the unsaved-changes guards, an invalid saved configuration, an unreachable backend |
  | `pages/auto-trading.test.tsx` | 65 | Scored strategy (preview request, points and gates, failed gates, risk preset and start settings, running engine, rejected signals, per-strategy statistics, trade dialog), the Configured option; confluence strategy (every factor's vote and condition, gap and ADR tables, rejection reasons, unavailable factors as n/a, strategy and filters sent on start, required factors, debounced preview, applied to a running engine, the confluence snapshot in a trade's reasoning dialog); continuous automation (70% and ₹1,500 defaults sent on start, edits applied live, every phase, pause and resume, entry reason, profit-target progress, hits and last exit, saved-settings migration) and  Automated Paper Trading: paper-only start, replay, bias and strategy votes, HOLD reasons, predictions vs actual, trade reasoning dialog, position edit and close, settings (saved or applied live), timeframes, accuracy and breakdown |
  | `pages/pre-market-news.test.tsx` | 19 | News feed: article fields, missing summary or picture, related coverage, tabs, breaking, periods, search, date filter, refresh, unavailable / stale / error / loading states, factor evidence, helpers |
  | `pages/pre-market.test.tsx` | 14 | Pre-Market Analysis: not-a-signal notice, score meter, five cards, unavailable data, news, levels and risks, generate and refresh, failures, manual FII/DII and events, history, validation note |
  | `pages/research-pages.test.tsx` | 54 | Signals, Backtest (run, job progress, filters, charts, cost units), Compare, Scalping (including the paper panel) |
  | `pages/daily-range.test.tsx` | 30 | Daily Range: period windows and month-end clamping, custom and reversed dates, skeleton / empty / error and retry, six cards and tooltips, candle colours and range bars with averages, lighter incomplete days, hover legend, range analysis (trend, utilization, too few sessions, partial note), table sorting / search / filter / pagination, responsive grids |
  | `pages/data-pages.test.tsx` | 38 | Market Data (downloads, jobs, stop, coverage), Historical Charts (range, timeframe, paging, URL), Account |
  | `app.test.tsx` | 21 | The whole app: every route mounts, sidebar navigation, unknown path, no missing API endpoint and no console error across all pages, responsive structure |

  Shared utilities are in `src/test/`: `mockApi.ts` (a fake backend that stubs `fetch` by method and path, records every call, and answers all default routes), `fixtures.ts` (typed builders for every payload), `fakeSocket.ts` (a controllable WebSocket), `fakeCharts.ts` (records what is drawn with lightweight-charts), `render.tsx` (`renderWithProviders`, `renderApp`) and `setup.ts`. Nothing touches the network or a canvas. jsdom has no layout engine, so the responsive tests check structure (which elements are hidden at which breakpoint); real widths need a browser.
  Bugs these tests found and fixed: the risk-% box could not be typed key by key (`0` became `1`, so `0.5` was impossible; now `PercentInput`, used by the Order calculator and Account); the Backtest page flashed "Couldn't load backtest settings." for a moment on every open; Historical Charts could cancel a click on another page's link by re-writing its own address.
- **Browser tests (19 Nov, Playwright with the installed Edge, 114 of 116 passed in the last clean full run (the 2 failures: Live-page chart and "Polling" indicator at 430 px, timing out on a slow Groww dashboard; they pass when run alone), including the privacy checks and the automated trading page at all eight widths):** `npx playwright test` (see [TESTING.md](TESTING.md)). Every page at 1920, 1440, 1280, 1024, 768, 430, 390 and 360 px: no horizontal overflow, no console or page errors, no failed API calls, content present. Navigation by the sidebar (768+) and by the phone bottom bar and "More" drawer; the live chart is drawn at every width; "Live push" while the WebSocket is up and "Polling" when it is blocked; paper Start/Stop. This replaced the 11 Nov puppeteer check below (54 of 54), which covered 6 widths and 9 pages.
- **Phone connection indicator (18 Nov):** the "Live push / Polling" pill is hidden below 640 px; on phones a compact "Polling" pill now appears in the header only while the WebSocket is down (a green dot shows Groww status as before).
- **Scalping page (18 Nov):** split into `pages/Scalping.tsx` (178 lines) and `components/scalping/` (`ConfigDetail`, `PaperPanel`, `shared`); behaviour unchanged, covered by `research-pages.test.tsx`.
- **Every page at every required width:** a headless check with puppeteer-core and the installed Edge loaded all 9 pages at 1920, 1440, 1024, 768, 390 and 360 px. **54 of 54 had no horizontal overflow and no console errors.** Screenshots of each were reviewed.
- **Controls and notifications in a real browser:**
  - Start Paper and Stop (with its confirm dialog) work.
  - During a replay, the page showed the engine's BUY CE / SELL / BUY PE alerts and the open position from the live API.
- **Live data:** NIFTY spot, quote time, EMAs and crossovers were checked against Groww data. The market was closed, so a live verified CE/PE premium couldn't be shown; the premium path is the same code as before, and the replay showed real contract prices.
- **Backend:** unchanged; its test suite was re-run (see CHANGELOG).

## Build and run
```powershell
cd frontend
npm install
npm run build      # type check + production build to frontend/dist (served at /app)
npm run dev        # development server at http://127.0.0.1:5173/app
```

## Old pages (removed)
The old server-rendered pages (`backend/legacy/`) were removed on 12 Nov. The React app is the only interface: http://127.0.0.1:5000 opens it, and old addresses (`/live`, `/compare`, `/signals`, `/data`, `/history`, `/account`) redirect to the matching React page.

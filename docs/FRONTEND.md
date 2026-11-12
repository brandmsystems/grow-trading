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
| Market Data | `/app/data` | `GET /api/data/overview`, `/api/data/options`, `/api/data/lot-sizes`, `POST /api/data/download`, `/api/data/options/download`, `/api/data/stop`, `GET /api/jobs/<id>` | Coverage KPIs; spot, futures and options cards (counts, date range, latest candle, last successful download); intervals; month grid (links to Historical Charts); missing periods; days with gaps; spot download with progress and stop; option history (scope, % downloaded, per-month table, download/resume and stop, last run); NSE lot-size table with sources; download history |
| Historical Charts | `/app/history` | `GET /api/data/overview`, `GET /api/data/candles` | Stored NIFTY candles at 1/5/15/30 min with optional EMA 9/21, date range, earlier/later/latest, zoom and pan |
| Account & Settings | `/app/account` | `GET /api/status, /api/profile, /api/funds`, `POST /api/login` | Groww connection and re-login; funds; profile; theme, sound and browser notification permission; order calculator defaults |

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
| `components/charts/` | `CandleChart` (candles, optional EMAs, cross/trade markers, price levels), `SeriesChart`: `LineChart` (equity) and `BarsChart` (monthly P&L) |
| `components/common/` | `Card` (with colour accent), `Stat`, `InfoTip`, `Pill`, `Dot`, `BigValue`; `Controls`: `Field`, `Segmented`, `Button`, `PageHeader`, `inputCls`/`selectInline`; `States`: `Loading`, `Empty`, `ErrorNote`, `Warning`, `Limitation`, `Progress` |
| `context/` | `SettingsContext` (theme, sound, timeframe, capital, risk %, engine form, sidebar state; saved per browser), `LiveContext` (shared live poll, today's trades, alerts, status events, unread count) |
| `hooks/` | `useDashboard` (polling with backoff), `useAlerts` (new-alert detection, sound, notifications, `describe`), `useApi` (load/reload with loading and error) + `waitForJob` |
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
- **Build:** `npm run build` (TypeScript strict type check + production build) passes. Each page loads only when first opened (largest page chunk 16 kB).
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

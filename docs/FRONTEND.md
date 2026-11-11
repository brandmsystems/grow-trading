# Frontend

## React app (`frontend/`)
**Stack:** React 19, TypeScript 5, Vite 8, Tailwind CSS 4, Lucide React, TradingView Lightweight Charts 4.2, React Router 7.

**Address:** the app runs under **`/app`**:
- **Production:** http://127.0.0.1:5000/app, served by Flask from `frontend/dist`.
- **Development:** http://127.0.0.1:5173/app, via Vite, which proxies `/api` and `/socket.io` to Flask.

| Page | Route | Status |
|---|---|---|
| Live dashboard | `/app/` | **Done** (Phase 5) |
| Backtest, Compare, Signals, Data, History, Account | — | Still the Flask pages at `/`, `/compare`, `/signals`, `/data`, `/history`, `/account`. The header links to them. They will be ported one by one, and each legacy page is removed only after its React version works |

### Live dashboard: what it shows
1. **NIFTY 50:** price, change, OHLC and quote time. Marked live, delayed or closed.
2. **5-minute candles with EMA 9 (blue) and EMA 21 (orange)** and crossover markers. Bars come from Groww; the forming bar is shown separately.
3. **Trend:** up, down or flat from EMA 9 vs 21, with the gap and the last closed bar.
4. **Recommendation:** BUY CE / BUY PE / HOLD with the strategy's reason. For BUY signals:
   - the verified contract: strike, expiry, Groww symbol
   - live premium, entry price, stop and target (option price and NIFTY level)
   - lots and quantity, investment, max risk and profit at target, from your capital and risk % (or Groww's available margin)
5. **Today's P&L after costs:** open plus realised.
6. **Notifications:** the last 20 alerts from the strategy and the engine. Each new one plays a sound (toggle in the header), shows a browser notification if allowed, and flashes the recommendation. Each signal alerts once, because the server stores it with a unique key.
7. **Trading engine:**
   - **Modes:** Paper, Live or Replay.
   - **Settings:** option type, timeframe, signal source (every crossover or prediction score), lots, loss and trade limits.
   - **Controls:** start, stop, square-off; the open position with live P&L.
8. **Status:** connection (connected, delayed, disconnected) and market status in the header.

### Live order safety
- **Starting Live** requires typing `LIVE` and is capped by `LIVE_MAX_LOTS`.
- **Manual confirmation is the default:** each entry order appears as **Confirm live order** with a countdown. Nothing is sent unless you click *Place order*. If the signal expires, nothing is placed.
- **Automatic entries** need ticking a box before each start. The setting is never restored from a previous session.
- **Protective exits** (stop, square-off, 15:00, loss limit) run automatically once a position exists.

### Source layout
| Folder | Contents |
|---|---|
| `src/pages/` | `LiveDashboard.tsx` |
| `src/components/dashboard/` | `Header`, `MarketSummary` (price, trend, P&L), `SignalCard` (recommendation and sizing), `Notifications` |
| `src/components/charts/` | `CandleChart` (candles, EMAs, crossover markers) |
| `src/components/trading/` | `EnginePanel` (settings, controls, position), `PendingOrder` (confirm/skip with countdown) |
| `src/components/common/` | `Card`, `Stat`, `Pill`, `Dot` |
| `src/hooks/` | `useDashboard` (polling with backoff and reconnect), `useAlerts` (new-alert detection, sound, notifications) |
| `src/services/api.ts` | Typed API client |
| `src/context/SettingsContext.tsx` | Per-browser preferences: theme, sound, timeframe, capital, risk %, engine form |
| `src/types/api.ts` | Response types matching [API.md](API.md) |
| `src/utils/format.ts` | ₹ and number formatting, IST times |

### Data flow
- **Endpoint:** `useDashboard` calls `GET /api/live/dashboard` (engine state + Groww feed + alerts).
- **Polling rate:**
  - every 2 s while the market is open or the engine runs
  - every 10 s otherwise
  - after failures, backs off up to 30 s and recovers by itself
- **Phase 6:** Socket.IO push will replace polling, with polling kept as the fallback.

**Themes:** dark (default) and light, responsive down to phone width.

## Build and run
```powershell
cd frontend
npm install
npm run build      # type-check + production build to frontend/dist (served at /app)
npm run dev        # development server at http://127.0.0.1:5173/app
```

## Legacy pages (`backend/legacy/`)
The server-rendered pages (Jinja templates + plain JS) stay in service until React replaces them. Their Live page (`/live`) is superseded by `/app` and will be removed once you've confirmed the React dashboard.

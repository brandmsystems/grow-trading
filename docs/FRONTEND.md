# Frontend

## Current state (after Phase 4)
The React frontend is **not built yet** (Phase 5). The app is served by the legacy server-rendered pages in `backend/legacy/`.

| Page | Template + script | Status |
|---|---|---|
| Backtest `/` | dashboard.html, dashboard.js | Working |
| Compare `/compare` | compare.html, compare.js | Working |
| Signals `/signals` | signals.html, signals.js | Working |
| Data `/data` | data.html, data.js | Working |
| History `/history` | history.html, history.js | Working |
| Account `/account` | account.html | Working |
| Live `/live` | live.html, live.js, live.css | **Mixed:** two sessions edited it at once, and the HTML, JS and CSS may not match. It will be replaced by React first |

Shared styles are in `legacy/static/app.css` (light/dark colour tokens). Charts use TradingView Lightweight Charts 4.2.0.

## Plan (Phases 5–6)
- **Stack:** React 19, TypeScript, Vite, Tailwind CSS, Lucide React, Lightweight Charts, in `frontend/`.
- **Development:** Vite at port 5173 proxies `/api` and `/socket.io` to Flask at 5000.
- **Production:** `npm run build` → `frontend/dist`, served by Flask.
- **Order of work:**
  1. Live dashboard: NIFTY price, 5-minute candles with EMA 9/21, trend, recommended CE/PE with strike, expiry and live premium, entry/stop/target, lots and quantity, investment and risk, daily P&L, notifications.
  2. Then Backtest, Compare, Signals, Data, History and Account.

  Each legacy page is removed only after its React version works.
- **Live updates:** Socket.IO with automatic reconnection; REST is the fallback.
- **Live orders:** each order needs a manual confirmation click by default.

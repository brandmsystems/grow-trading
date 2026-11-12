# Grow Trading

A NIFTY options trading system built on the Groww Trade API. It covers:
- five years of historical data and data-quality reports
- a 9/21 EMA crossover strategy and six variants, with backtests on real option prices and all Indian charges
- a strategy comparison with walk-forward testing
- a signal engine scored only on unseen data
- paper, live and replay trading engines with safety limits and alerts

**Status (11 Nov 2026):**
- The Python backend has been restructured into `backend/app` (Phases 1–4).
- **The React app is at http://127.0.0.1:5000/app**: 9 pages with a sidebar layout that works on desktop, tablet and phone (Overview, Live Trading, Trading Signals, Options Analysis, Backtesting, Strategy Comparison, Market Data, Historical Charts, Account & Settings). This is the only interface; the old server-rendered pages were removed on 12 Nov. WebSocket push (Phase 6) isn't built yet.
- All 140 tests pass.

[GROWTRADING.md](GROWTRADING.md) has the full record and [docs/TODO.md](docs/TODO.md) the pending work.

## Quick start
```powershell
cd C:\Amruthesh\grow-trading
.venv\Scripts\python -m pip install -r backend\requirements.txt
copy .env.example .env      # set PG_PASSWORD; Groww credentials here or in keys.txt
cd frontend; npm install; npm run build; cd ..   # builds the React app
python start.py             # http://127.0.0.1:5000  (React dashboard at /app)
```

| Page | URL |
|---|---|
| **Grow Trading app (React, all pages)** | http://127.0.0.1:5000/app |
| Overview | http://127.0.0.1:5000/app/ |
| Live Trading | http://127.0.0.1:5000/app/live |
| Trading Signals | http://127.0.0.1:5000/app/signals |
| Options Analysis | http://127.0.0.1:5000/app/options |
| Backtesting | http://127.0.0.1:5000/app/backtest |
| Strategy Comparison | http://127.0.0.1:5000/app/compare |
| Market Data | http://127.0.0.1:5000/app/data |
| Historical Charts | http://127.0.0.1:5000/app/history |
| Account & Settings | http://127.0.0.1:5000/app/account |

http://127.0.0.1:5000 opens the app. Old addresses like `/live` or `/compare` redirect to the matching page.

**Requirements:**
- A Groww account with the **paid Trading API plan**. The free plan has no market data.
- PostgreSQL 17.
- Python 3.14.

## Tests
```powershell
cd backend
..\.venv\Scripts\python -m pytest
```

## Documentation
| File | Contents |
|---|---|
| [GROWTRADING.md](GROWTRADING.md) | Master documentation: status, features, results, history |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Backend layers, data flow, frontend/backend communication |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | Every folder and file |
| [docs/API.md](docs/API.md) | REST endpoints |
| [docs/DATABASE.md](docs/DATABASE.md) | Tables and migrations |
| [docs/GROWW_API.md](docs/GROWW_API.md) | Groww login, calls and quirks |
| [docs/STRATEGY.md](docs/STRATEGY.md) | Trading rules, indicators, signals, charges, sizing |
| [docs/BACKTESTING.md](docs/BACKTESTING.md) | Historical data, backtests, comparison results |
| [docs/FRONTEND.md](docs/FRONTEND.md) | React pages, layout, colour system, components, API used per page |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Install, configuration, run |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Dated changes |
| [docs/TODO.md](docs/TODO.md) | Pending work and known issues |

**Safety:** Live mode places real orders. It needs the `LIVE` confirmation, is capped by `LIVE_MAX_LOTS`, and by default asks you to confirm every entry order. Past backtest results don't predict future returns, and none of the tested strategies was clearly profitable after costs.

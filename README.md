# Grow Trading

A NIFTY options trading system built on the Groww Trade API. It covers:
- five years of historical data and data-quality reports
- a 9/21 EMA crossover strategy and six variants, with backtests on real option prices and all Indian charges
- a strategy comparison with walk-forward testing
- a signal engine scored only on unseen data
- paper, live and replay trading engines with safety limits and alerts

**Status (11 Nov 2026):**
- The Python backend has been restructured into `backend/app` (Phases 1–4), and all 135 tests pass.
- The React frontend (Phase 5) and WebSocket updates (Phase 6) are not built yet. Until then the existing server-rendered pages are served.

[GROWTRADING.md](GROWTRADING.md) has the full record and [docs/TODO.md](docs/TODO.md) the pending work.

## Quick start
```powershell
cd C:\Amruthesh\grow-trading
.venv\Scripts\python -m pip install -r backend\requirements.txt
copy .env.example .env      # set PG_PASSWORD; Groww credentials here or in keys.txt
python start.py             # http://127.0.0.1:5000
```

| Page | URL |
|---|---|
| Backtest | http://127.0.0.1:5000/ |
| Compare | http://127.0.0.1:5000/compare |
| Signals | http://127.0.0.1:5000/signals |
| Live / Paper | http://127.0.0.1:5000/live |
| Data | http://127.0.0.1:5000/data |
| History | http://127.0.0.1:5000/history |
| Account | http://127.0.0.1:5000/account |

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
| [docs/FRONTEND.md](docs/FRONTEND.md) | Pages and the React plan |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Install, configuration, run |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Dated changes |
| [docs/TODO.md](docs/TODO.md) | Pending work and known issues |

**Safety:** Live mode places real orders. It needs the `LIVE` confirmation and is capped by `LIVE_MAX_LOTS`. Past backtest results don't predict future returns, and none of the tested strategies was clearly profitable after costs.

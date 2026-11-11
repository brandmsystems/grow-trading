# Project structure

What every folder and file in Grow Trading is responsible for. Updated 11 Nov 2026 (after Phase 4).

```
grow-trading/
├── backend/                  Python: Flask API, services, tests
│   ├── app.py                Entry point: python app.py (port 5000)
│   ├── app/
│   │   ├── __init__.py       create_app(): Flask app, DB migrations, blueprints
│   │   ├── main.py           The app instance used by app.py and tests
│   │   ├── api/              HTTP routes, one blueprint per area
│   │   ├── config/           Settings, .env, credentials
│   │   ├── database/         PostgreSQL engine, migration runner, queries, migrations/*.sql
│   │   ├── models/           (reserved; tables are defined by SQL migrations)
│   │   ├── services/         All business logic (see below)
│   │   ├── workers/          Background jobs
│   │   └── utils/            Small shared helpers
│   ├── legacy/               Server-rendered pages, served until React replaces each one
│   ├── tests/                pytest suite
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/                 React 19 + TypeScript + Vite + Tailwind app (served at /app)
│   ├── src/pages/            LiveDashboard
│   ├── src/components/       dashboard/, charts/, trading/, common/
│   ├── src/hooks/            useDashboard (polling, reconnect), useAlerts (sound, notifications)
│   ├── src/services/api.ts   typed API client
│   ├── src/context/          SettingsContext (theme, sound, timeframe, capital, risk %, engine form)
│   ├── src/types/, src/utils/
│   ├── index.html, vite.config.ts, tsconfig.json, package.json
│   └── dist/                 production build (git-ignored)
├── data/                     Runtime data (git-ignored): historical/, exports/, logs/
├── scripts/                  One-off maintenance scripts
├── docs/                     This documentation
├── GROWTRADING.md            Master project documentation
├── README.md                 Overview and quick start
├── start.py                  Starts the backend (and the frontend dev server with --dev)
├── .env.example              Configuration template
├── keys.txt                  Groww credentials (git-ignored; optional if env vars are set)
└── .env                      Local configuration (git-ignored)
```

## backend/app/api: routes
| File | Routes |
|---|---|
| `common.py` | Shared helpers: `api_error`, result cache, `real_only`, `date_arg`, `active_job` |
| `pages.py` | Legacy pages: `/`, `/account`, `/data`, `/history`, `/compare`, `/signals` |
| `account.py` | `/api/status`, `/api/login`, `/api/logout`, `/api/profile`, `/api/funds` |
| `backtest.py` | `/api/bt/*`, `/api/jobs/<id>` |
| `data.py` | `/api/data/*` |
| `research.py` | `/api/research*`, `/api/signals*` |
| `live.py` | `/live`, `/api/live/*` (incl. `confirm`, `reject`) |
| `frontend.py` | `/app`, `/app/<path>`: the built React app |

Details: [API.md](API.md).

## backend/app/services: business logic
| Folder / file | Responsibility | Previously |
|---|---|---|
| `groww/client.py` | Groww login (TOTP or key+secret), token cache, one re-login on auth errors | `groww_client.py` |
| `market_data/history.py` | Historical download (spot + futures), validation, coverage report, chart candles | `data_manager.py` |
| `market_data/providers.py` | Groww candles, expiries, option contracts; synthetic provider (tests only) | `providers.py` |
| `market_data/live.py` | Live market for the engine: clock, completed candles, LTPs, contracts; replay market | `live_market.py` (minus brokers) |
| `market_data/feed.py` | Live dashboard feed: quote, bars, signal state, verified option recommendation | `live_feed.py` (minus sizing, contracts, alert storage) |
| `options/contracts.py` | Find a strike's CE/PE in a Groww option chain | from `live_feed.py` |
| `options/sizing.py` | Lots from risk budget and available cash, with charges | from `live_feed.py` |
| `strategy/rules.py` | Core 9/21 rules: resampling, crosses, legs, strikes, expiry rules, fill prices | `strategy.py` |
| `strategy/indicators.py` | EMA, Wilder RSI/ATR, MACD, session VWAP | `indicators.py` |
| `strategy/strategies.py` | The seven compared strategies | `strategies.py` |
| `strategy/signals.py` | Signal engine: features, outcomes, walk-forward model, scorer | `signals.py` |
| `trading/charges.py` | Slippage and Indian options charges | `costs.py` |
| `trading/brokers.py` | Order execution: PaperBroker, LiveBroker, OrderError, OrderUnknown | from `live_market.py` |
| `trading/engine.py` | Live / paper / replay engine: crossover and prediction modes, risk rails | `live_engine.py` |
| `trading/manager.py` | One engine instance, start/stop safety checks, dashboard status | `live_manager.py` |
| `backtest/engine.py` | Backtest with real option prices; chart payloads | `backtest.py` |
| `backtest/metrics.py` | Win rate, profit factor, payoff, expectancy, drawdown | `metrics.py` |
| `backtest/research.py` | Strategy × timeframe comparison and walk-forward | `research.py` |
| `notifications/alerts.py` | Store each alert once; read recent alerts | from engine, feed and manager |

## Other backend folders
| Path | Responsibility | Previously |
|---|---|---|
| `config/settings.py` | Paths (project root), PostgreSQL settings, credentials from env or `keys.txt` | `config.py` |
| `database/db.py` | Engine (Asia/Kolkata session), migration runner, candles/contracts/runs queries | `db.py` |
| `database/migrations/` | `0001`–`0007` SQL migrations | `migrations/` |
| `workers/jobs.py` | Background jobs with progress; separate lane for long research runs | `jobs.py` |
| `utils/timeutil.py` | `parse_hm("09:30")`, shared by three modules | three copies of `_hm` |
| `utils/numbers.py` | `to_float` | from `live_feed.py` |
| `legacy/templates`, `legacy/static` | Old pages and their JS/CSS | `templates/`, `static/` |

## Tests (`backend/tests`)
| File | Covers |
|---|---|
| test_setup.py | Credentials (file and env), routes without keys |
| test_strategy.py | Core trade rules |
| test_costs_metrics.py | Charges and metrics |
| test_providers.py | Candle parsing, option symbols |
| test_backtest_integration.py | End-to-end backtest, unfinished sessions |
| test_data_manager.py | Migrations, time zones, downloads, validation, data API |
| test_research.py | Indicators, strategies, signals, walk-forward |
| test_live_engine.py | Engine = backtest, safety rails, prediction mode, alerts |
| test_live_feed.py | Live feed, contract checks, sizing |
| test_frontend.py | React build served at /app, client-route fallback, no files outside dist |

The files under `services/` keep the names other modules and tests import. For example, `feed.py` still exposes `size_position`, and `manager.py` still exposes `recent_alerts`.

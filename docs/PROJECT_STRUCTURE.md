# Project structure

What every folder and file in Grow Trading is responsible for. Updated 18 Nov 2026 (audit, engine/feed/scalping splits, frontend and browser tests).

```
grow-trading/
├── backend/                  Python: Flask API, services, tests
│   ├── app.py                Entry point: python app.py (port 5000, or PORT env)
│   ├── app/
│   │   ├── __init__.py       create_app(): Flask app, DB migrations, blueprints
│   │   ├── main.py           The app instance used by app.py and tests
│   │   ├── api/              HTTP routes, one blueprint per area
│   │   ├── config/           Settings, .env, credentials
│   │   ├── database/         PostgreSQL engine, migration runner, queries, migrations/*.sql
│   │   ├── services/         All business logic (see below)
│   │   ├── workers/          Background jobs
│   │   └── utils/            Small shared helpers
│   ├── tests/                pytest suite
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/                 React 19 + TypeScript + Vite + Tailwind app (served at /app)
│   ├── src/pages/            Overview, LiveTrading, Signals, Options, Backtest, Compare, Scalping, MarketData, HistoryCharts, Account
│   ├── src/components/       layout/ (sidebar, header, mobile nav, notifications), market/, trading/, charts/, common/
│   ├── src/context/          SettingsContext (preferences), LiveContext (one shared live poll, alerts, trades)
│   ├── src/hooks/            useDashboard, useAlerts, useApi (+ waitForJob)
│   ├── src/services/api.ts   typed client for every API call
│   ├── src/types/, src/utils/
│   ├── src/__tests__/        Vitest + React Testing Library: 346 tests (hooks, components, pages, whole app)
│   ├── src/test/             Shared test utilities: mock API, fixtures, fake WebSocket and charts, render helpers
│   ├── e2e/                  Playwright browser tests (all pages × 8 widths, navigation, indicators, paper controls)
│   ├── index.html, vite.config.ts (build, chunk split), vitest.config.ts, playwright.config.ts, tsconfig.json, package.json
│   └── dist/                 production build (git-ignored)
├── data/                     Runtime data (git-ignored): historical/, exports/, logs/ (server.log), backups/
├── docs/                     This documentation
├── GROWTRADING.md            Master project documentation
├── README.md                 Overview and quick start
├── CLAUDE.md                 Commands, rules and layout for Claude Code sessions
├── start.py                  Starts the backend (and the frontend dev server with --dev)
├── .env.example              Configuration template
├── keys.txt                  Groww credentials (git-ignored; optional if env vars are set)
└── .env                      Local configuration (git-ignored)
```

## backend/app/api: routes
| File | Routes |
|---|---|
| `common.py` | Shared helpers: `api_error`, `json_body`, `date_range`, `date_arg`, `reject_foreign_requests` (Host/Origin guard), `json_error` (JSON for HTTP errors), result cache, `real_only`, `active_job` |
| `pages.py` | Redirects `/` and old page addresses to the React app (`/app/...`) |
| `paper.py` | Paper risk: virtual account, risk calculator, stop-loss edits and history |
| `account.py` | `/api/status`, `/api/login`, `/api/logout` (no profile or funds) |
| `backtest.py` | `/api/bt/*`, `/api/jobs/<id>` |
| `data.py` | `/api/data/*` |
| `research.py` | `/api/research*`, `/api/signals*` |
| `live.py` | `/api/live/*` (incl. `confirm`, `reject`) |
| `frontend.py` | `/app`, `/app/<path>`: the built React app |

Details: [API.md](API.md).

## backend/app/services: business logic
| Folder / file | Responsibility | Previously |
|---|---|---|
| `groww/client.py` | Groww login (TOTP or key+secret), token cache, one re-login on auth errors | `groww_client.py` |
| `market_data/history.py` | Historical download (spot + futures), validation, coverage report, chart candles | `data_manager.py` |
| `market_data/providers.py` | Groww candles, expiries, option contracts; synthetic provider (tests only) | `providers.py` |
| `market_data/options_history.py` | Option history scope (ATM ±10, CE/PE, all expiry rules), resumable download, coverage | new |
| `options/lot_sizes.py` | NIFTY lot size of a contract from the NSE `lot_sizes` table | new |
| `strategy/insight.py` | Signal explanations (actual indicator values, confidence) and today's trading plan | new |
| `strategy/patterns.py` | Candlestick patterns on closed bars (no repainting) | new |
| `trading/paper_account.py` | Virtual paper account and daily risk monitor | new |
| `market_data/live.py` | Live market for the engine: clock, completed candles, LTPs, contracts; replay market | `live_market.py` (minus brokers) |
| `market_data/feed.py` | Live dashboard feed: quote, bars, verified option recommendation (re-exports the signal_state names) | `live_feed.py` (minus sizing, contracts, alert storage) |
| `market_data/signal_state.py` | Pure: market hours, the strategy's current call from closed bars, chart markers, data-trust checks | inside `feed.py` |
| `options/contracts.py` | Find a strike's CE/PE in a Groww option chain | from `live_feed.py` |
| `options/sizing.py` | Lots from risk budget and available cash, with charges | from `live_feed.py` |
| `strategy/rules.py` | Core 9/21 rules: resampling, crosses, legs, strikes, expiry rules, fill prices | `strategy.py` |
| `strategy/indicators.py` | EMA, Wilder RSI/ATR, MACD, session VWAP | `indicators.py` |
| `strategy/strategies.py` | The seven compared strategies | `strategies.py` |
| `strategy/signals.py` | Signal engine: features, outcomes, walk-forward model, scorer | `signals.py` |
| `trading/charges.py` | Slippage and Indian options charges | `costs.py` |
| `trading/brokers.py` | Order execution: PaperBroker, LiveBroker, OrderError, OrderUnknown | from `live_market.py` |
| `trading/engine.py` | Live / paper / replay engine: crossover, trend, prediction and scalp modes, risk rails (re-exports `EngineConfig`) | `live_engine.py` |
| `trading/engine_config.py` | `EngineConfig` and its validation | inside `engine.py` |
| `trading/stops.py` | Pure stop-loss/target rules (`stop_levels`) and the NIFTY levels of an open position (`position_levels`) | inside `engine.py` |
| `trading/manager.py` | One engine instance, start/stop safety checks, dashboard status | `live_manager.py` |
| `backtest/engine.py` | Backtest with real option prices; chart payloads | `backtest.py` |
| `backtest/metrics.py` | Win rate, profit factor, payoff, expectancy, drawdown | `metrics.py` |
| `backtest/research.py` | Strategy × timeframe comparison and walk-forward | `research.py` |
| `backtest/scalping.py` | 5-minute scalping analyzer run, summary, storage and the scalp-mode engine settings for paper trading | `research.py` |
| `backtest/scalping_stats.py` | Pure: per-configuration statistics, year/month/regime grouping, verdict, walk-forward | inside `scalping.py` |
| `notifications/alerts.py` | Store each alert once; read recent alerts (live-mode alerts lose fill details) | from engine, feed and manager |
| `privacy.py` | Keeps real-money details out of everything sent to the browser: live status, live alerts, order ids | new |

## Other backend folders
| Path | Responsibility | Previously |
|---|---|---|
| `config/settings.py` | Paths (project root), PostgreSQL settings, credentials from env or `keys.txt` | `config.py` |
| `database/db.py` | Engine (Asia/Kolkata session), migration runner, candles/contracts/runs queries | `db.py` |
| `database/migrations/` | `0001`–`0012` SQL migrations (the runner applies only this folder) | `migrations/` |
| `database/pending/` | Reviewed but **not applied** migrations: `0018_drop_orphan_tables` (up and down) awaiting approval | new |
| `workers/jobs.py` | Background jobs with progress; separate lane for long research runs | `jobs.py` |
| `utils/timeutil.py` | `IST` timezone, `now_naive()` (the clock every `_now` alias points to) and `parse_hm("09:30")` | three copies of `_hm`, four `IST` definitions, four `_now()` bodies |
| `utils/numbers.py` | `to_float` | from `live_feed.py` |

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
| test_scalping.py | Scalping analyzer: exits, no repainting, one position at a time, sizing, verdict, walk-forward, end-to-end run, scalp engine mode |
| test_live_engine.py | Engine = backtest, safety rails, prediction mode, alerts |
| test_live_feed.py | Live feed, contract checks, sizing |
| test_frontend.py | React build served at /app, client-route fallback, no files outside dist |
| test_api_smoke.py | Account endpoints (Groww mocked), live-control guard rails, Host/Origin guard, JSON errors, download validation, not-found cases, read endpoints |
| test_stops.py | `stops.py` rules and `EngineConfig` validation messages |
| test_privacy.py | What live mode may show: redacted status, events and alerts, kept safety information, order ids |

The files under `services/` keep the names other modules and tests import. For example, `feed.py` still exposes `size_position`, and `manager.py` still exposes `recent_alerts`.

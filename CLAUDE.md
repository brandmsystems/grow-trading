# Grow Trading: notes for Claude Code

NIFTY options research and paper-trading app on Groww. Flask + PostgreSQL backend, React 19 + Vite frontend.
Master documentation: [GROWTRADING.md](GROWTRADING.md); details in [docs/](docs/).

## Commands (Windows, PowerShell)
```powershell
python start.py                      # backend on http://127.0.0.1:5000 (serves the built React app at /app)
python start.py --dev                # + Vite dev server on 5173
cd frontend; npm run build           # tsc -b && vite build -> frontend/dist
cd frontend; npm test                # Vitest + React Testing Library
cd backend; ..\.venv\Scripts\python -m pytest     # ~9 min; replays real days
$env:PORT=5001; ..\.venv\Scripts\python app.py    # a second server on another port
```
- **Run Vitest and npm from a path with an upper-case drive letter** (`C:\Amruthesh\...`). From `c:\...` Vitest loads itself twice and every suite fails with "failed to find the current suite".
- **Never run two pytest sessions at once.** They share the `groww_trading_test*` databases and fail with `OperationalError`.
- pytest and Python tooling live in `.venv` (project root), not on the system Python.

## Rules that matter
- **No real-money orders while developing or testing.** Only `trading/brokers.LiveBroker` places orders; it needs the `LIVE` phrase, the `LIVE_MAX_LOTS` cap and (by default) a manual confirmation per entry. Tests mock Groww; `tests/test_api_smoke.py` fails any test that reaches the real client.
- **Never delete or rewrite market data, option candles, paper/live trades or other history.** Schema changes need a verified `pg_dump` and a migration. Pending, unapplied migrations live in `backend/app/database/pending/` (the runner only reads `migrations/`).
- **Do not change trading rules or calculations without being asked.** One source of rules: `strategy/rules.generate_legs` is used by the backtester, the engine and the live feed. Compare before/after with a replay when refactoring.
- The API has no login (local only). `api/common.reject_foreign_requests` refuses foreign `Host` and cross-site `Origin`. New POST routes read bodies with `json_body()`, not `request.get_json(force=True)`.
- Keep `_now` as a module-level name in modules that have it (tests patch it per module); it aliases `utils/timeutil.now_naive`.

## Layout
- `backend/app/api/` thin Flask blueprints; `services/` all logic (no Flask imports); `database/migrations/` SQL; `workers/jobs.py` background jobs.
- `backend/app/services/trading/`: `engine.py` (loop, entries, exits), `engine_config.py`, `stops.py` (pure stop/target rules), `brokers.py`, `charges.py`, `paper_account.py`, `manager.py`.
- `frontend/src/`: `pages/`, `components/`, `context/` (Settings, Live), `hooks/`, `services/api.ts` (the only place that calls `fetch`), `utils/format.ts`, `test/` (shared test utilities).
- Full file map: [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md). Database: [docs/DATABASE.md](docs/DATABASE.md). Testing: [docs/TESTING.md](docs/TESTING.md).

## Secrets
`.env`, `keys.txt` and `.token_cache.json` are git-ignored. Never print or log their contents or send them anywhere.

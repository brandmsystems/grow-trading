# Installation and deployment

## Requirements
- **Windows 10/11** (developed on Windows 11). Linux/macOS work with the usual path changes.
- **Python 3.14** with a virtual environment in `.venv`.
- **PostgreSQL 17**, database `groww_trading`.
- **Node.js 24 / npm 11**, for the frontend (Phase 5).
- **A Groww account with the paid Trading API plan** (market data needs it).

## Install
```powershell
cd C:\Amruthesh\grow-trading
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
copy .env.example .env          # fill in PG_PASSWORD (and optionally GROWW_* credentials)
```

**Credentials:** either set `GROWW_API_KEY` and `GROWW_TOTP_SECRET` in `.env`, or create `keys.txt` (see `keys.example.txt`):
```
API_KEY=<TOTP token from Groww>
TOTP_SECRET=<code shown with the QR>
```

**Database:** created automatically on first start. All migrations run, and existing data is never removed.

## Run
```powershell
python start.py                 # backend at http://127.0.0.1:5000, log in data\logs\server.log
# or
cd backend; ..\.venv\Scripts\python app.py
```

## Environment variables
| Variable | Purpose |
|---|---|
| `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DB` | PostgreSQL connection |
| `LIVE_MAX_LOTS` | Hard cap on lots in Live (real-money) mode, default 1 |
| `GROWW_API_KEY`, `GROWW_TOTP_SECRET` / `GROWW_API_SECRET` | Groww credentials (optional; `keys.txt` is the fallback) |

## Tests
```powershell
cd backend
..\.venv\Scripts\python -m pytest
```
The tests create and drop their own `groww_trading_test*` databases and never touch `groww_trading`. **Don't run two test sessions at once**, because they share those test databases.

## Notes
- **The app is local-only:** it binds to 127.0.0.1. Don't expose it to the internet, because it can place orders.
- **Keep it running until 15:00 on trading days** if the engine holds positions. Groww auto-squares MIS positions later, with a charge.

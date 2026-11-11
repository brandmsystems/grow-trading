# Pending work and known issues

*Updated 11 Nov 2026, after Phase 5 (live dashboard).*

## Restructure phases
| Phase | Status |
|---|---|
| 1. Inspect and plan | Done |
| 2. Dependencies and duplicates | Done |
| 3. New folder structure | Done |
| 4. Backend migration (no logic changes) | Done |
| 5. React frontend connected to Flask | **Live dashboard done** (`/app`). Other pages still legacy |
| 6. WebSocket live updates (Flask-SocketIO, auto-reconnect) | **Not started**; `flask-socketio` not installed yet |
| 7. Full verification (tests, Groww connectivity, live data, React build) | Pending |
| 8. Documentation per phase | Ongoing |

## Agreed decisions
- **Port every page to React.** Each legacy page is removed only after its React version works.
- **Live orders need a manual confirmation click per order by default.** Automatic execution needs an explicit opt-in. **Implemented in Phase 5:** protective exits stay automatic.
- **Commit at the end of each phase.**

## Next
- Port Backtest, Compare, Signals, Data, History and Account to React; then remove `backend/legacy/`.
- Remove the legacy `/live` page once you've confirmed the React dashboard.
- Phase 6: Flask-SocketIO push for quotes, signals and alerts.

## Known issues
- **Legacy `/live` page:** mixed from two sessions' edits; superseded by `/app`.
- **First live order not yet seen:** manual confirmation is tested on replayed days with a counting broker, but no real Groww order has been placed through it yet.
- **`_now()` exists in three modules** (backtest engine, history, providers). Tests patch each one separately, so they were left as they are.
- **Market status:** no holiday calendar, so it shows "open" on NSE holidays.
- **Lot size:** fixed (65) for all backtest years.
- **Prediction rule:** its option P&L hasn't been backtested yet; a "Prediction score ≥ X" Backtest filter is proposed.
- **No strategy profitable after costs:** none of the 28 configurations was profitable over five years except EMA 20/50 30m (about break-even). See [BACKTESTING.md](BACKTESTING.md).

## Future
- Level 3: Telegram notifications, trading terminal improvements.
- Revoke the old Groww keys that were pasted into chat.

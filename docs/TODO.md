# Pending work and known issues

*Updated 12 Nov 2026, Phase 1 (historical data).*

## Restructure phases
| Phase | Status |
|---|---|
| 1. Inspect and plan | Done |
| 2. Dependencies and duplicates | Done |
| 3. New folder structure | Done |
| 4. Backend migration (no logic changes) | Done |
| 5. React frontend connected to Flask | **Done:** all 9 pages in React (redesign, 11 Nov). Old server-rendered pages removed 12 Nov |
| 6. WebSocket live updates (Flask-SocketIO, auto-reconnect) | **Not started**; `flask-socketio` not installed yet |
| 7. Full verification (tests, Groww connectivity, live data, React build) | Pending |
| 8. Documentation per phase | Ongoing |

## Agreed decisions
- **Port every page to React.** Done; the old server-rendered pages were removed on 12 Nov at your request.
- **Live orders need a manual confirmation click per order by default.** Automatic execution needs an explicit opt-in. **Implemented in Phase 5:** protective exits stay automatic.
- **Commit at the end of each phase.**

## Next
- Backend endpoints the redesigned frontend would use (frontend-only work couldn't add them):
  - option chain and expiry list for Options Analysis
  - CE and PE premiums together, with premium change and volume
  - EMA values from `/api/data/candles`, so historical EMAs match the strategy exactly
- Phase 6: Flask-SocketIO push for quotes, signals and alerts.

## Known issues
- **Polling delay:** with the engine stopped, the app polls every 10 s, so an engine started from elsewhere appears up to 10 s later. Phase 6 (Socket.IO) removes this.
- **Live premiums not seen during market hours yet:** the redesign was checked after the close. The CE/PE premium panel was checked with HOLD and replay data, not with a live BUY signal.
- **First live order not yet seen:** manual confirmation is tested on replayed days with a counting broker, but no real Groww order has been placed through it yet.
- **`_now()` exists in three modules** (backtest engine, history, providers). Tests patch each one separately, so they were left as they are.
- **Market status:** no holiday calendar, so it shows "open" on NSE holidays.
- **Option history download:** runs about 110 requests a minute (Groww rate limit). Until it finishes, the Market Data page shows partial option coverage.
- **Download status after a restart:** starting the app marks any download still `running` as `interrupted`. A download run in a separate process keeps going and records its real final status when it ends.
- **No historical IV/Greeks:** Groww has no option-chain history; OI is stored with each option candle.
- **Prediction rule:** its option P&L hasn't been backtested yet; a "Prediction score ≥ X" Backtest filter is proposed.
- **No strategy profitable after costs:** none of the 28 configurations was profitable over five years except EMA 20/50 30m (about break-even). See [BACKTESTING.md](BACKTESTING.md).

## Future
- Level 3: Telegram notifications, trading terminal improvements.
- Revoke the old Groww keys that were pasted into chat.

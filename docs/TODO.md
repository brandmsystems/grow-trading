# Pending work and known issues

*Updated 12 Nov 2026, Phase 2 (strategy and backtesting).*

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
- EMA values from `/api/data/candles`, so historical EMAs match the strategy exactly. (Option chain, expiry list and CE+PE premiums were done in Phase 2.)
- **Proposals needing your approval (would change trading or results):**
  - stronger regularisation chosen by walk-forward validation for the signal model (changes scores, so prediction-mode trades)
  - a "require N confirmations" or "score ≥ X" entry filter, backtested first
  - custom EMA periods as new strategy settings (existing defaults unchanged)
- Phase 6: Flask-SocketIO push for quotes, signals and alerts.

## Known issues
- **Polling delay:** with the engine stopped, the app polls every 10 s, so an engine started from elsewhere appears up to 10 s later. Phase 6 (Socket.IO) removes this.
- **Live premiums not seen during market hours yet:** the redesign was checked after the close. The CE/PE premium panel was checked with HOLD and replay data, not with a live BUY signal.
- **First live order not yet seen:** manual confirmation is tested on replayed days with a counting broker, but no real Groww order has been placed through it yet.
- **`_now()` exists in three modules** (backtest engine, history, providers). Tests patch each one separately, so they were left as they are.
- **Market status:** no holiday calendar, so it shows "open" on NSE holidays.
- **165 option candles at 15:30** (Aug–Nov 2026) from an older fetch version; real but outside the stored 09:15–15:29 window. Unused; awaiting your decision to delete or keep.
- **Option history refresh:** new sessions are not downloaded automatically; press *Download or resume options* on the Market Data page (only new days are fetched).
- **Download status after a restart:** starting the app marks any download still `running` as `interrupted`. A download run in a separate process keeps going and records its real final status when it ends.
- **No historical IV/Greeks:** Groww has no option-chain history; OI is stored with each option candle.
- **Paper risk:** the engine holds one position at a time, so `max_open_positions` above 1 has no effect yet. Option-selling margin isn't modelled (sells are sized by risk and max lots only). The target premium is shown for risk/reward but not enforced.
- **Paper stop vs backtest:** paper trades now exit at a premium stop-loss; backtests and replay have no such stop, so paper results will differ from them.
- **Weak-confirmation signals are not filtered:** the explanation flags them, but the strategy still trades every crossover. A "require N confirmations" option would change the trading rules, so it needs your approval and a backtest first.
- **Chart stop/target for paper positions** are NIFTY levels converted with the option's delta at entry, so they're approximate. The premium stop itself is exact.
- **Plan history** is stored per timeframe; switching the chart timeframe shows that timeframe's plan.
- **Prediction rule:** its option P&L hasn't been backtested yet; a "Prediction score ≥ X" Backtest filter is proposed.
- **No strategy profitable after costs:** none of the 28 configurations was profitable over five years except EMA 20/50 30m (about break-even). See [BACKTESTING.md](BACKTESTING.md).

- **Today's option candles have OI = 0:** Groww's historical candles return OI 0 for the current session (seen 12 Nov: all 32,982 option candles stored that day). The day is marked fetched, so it won't be re-downloaded. Fix proposed: re-request days whose candles all have OI 0 and update only the OI column. Awaiting your approval (it updates stored rows).
- **Signal score has little edge:** out of sample, EMA 9/21 5-min has no proven edge (AUC 0.49–0.55), 15-min a modest one (+2.3% Brier skill), 30-min can't be tested yet. Scores rarely reach 70+. Shown on the Signals page.
- **Option chain speed:** Groww takes 1–4 s per call, so the first chain load takes about 5–8 s; later loads are cached.
- **Groww `oi_day_change`** is scaled (×0.65 of OI minus previous OI); the app computes the change itself.

## Future
- Level 3: Telegram notifications, trading terminal improvements.
- Revoke the old Groww keys that were pasted into chat.

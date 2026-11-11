# Groww 9/21 EMA Trading System

A Flask app for a NIFTY options 9/21 EMA crossover strategy. It has a backtester, a trade viewer, and a Groww account page that signs in with TOTP.

## Run

```powershell
.venv\Scripts\python app.py
```

Then open:
- http://127.0.0.1:5000: backtest dashboard
- http://127.0.0.1:5000/live: live / paper trading engine
- http://127.0.0.1:5000/account: Groww profile and funds

## Setup

- **`keys.txt`** holds your Groww credentials. Copy it from `keys.example.txt` and fill in both lines:
  ```
  API_KEY=...
  TOTP_SECRET=...
  ```
  With an approval-type Groww key, use `API_SECRET=...` instead of `TOTP_SECRET`. The app detects which one it has.
- **`.env`** holds the PostgreSQL connection details. The database is PostgreSQL 17 on localhost, in the `groww_trading` database.
- **Tests:** run `.venv\Scripts\python -m pytest`. The end-to-end test creates a throwaway `groww_trading_test` database and drops it afterwards.

## Datasets

| Dataset | What it is |
|---|---|
| **Groww** | Real NIFTY 1-minute spot data. Option 1-minute candles for the exact contracts a trade needs are downloaded on demand and cached in Postgres. |
| **Synthetic** | A deterministic random walk with Black-Scholes option prices, for exploring the UI. The UI labels it as synthetic, and its results mean nothing. It is stored under `SYNTH:` symbols, so it never mixes with real data. |

## Strategy conventions

[strategy.py](strategy.py) documents every convention, and the tests cover each one.

**Bars and signals**
- **Candle timestamps:** 1-minute candles are stamped with their start time.
- **Resampling:** 1-minute bars are resampled to 5, 15 or 30 minutes, aligned to 09:15. Each bar is identified by its close time. The last 30-minute bar of the day is capped at 15:30.
- **EMA:** standard `ewm(span, adjust=False)`, carried across days. The first 3 sessions are warm-up and are never traded.
- **What counts as a cross:** a change in the sign of (EMA9 − EMA21) on a closed bar.
  - **Ties:** exactly-equal EMAs are not a cross; the previous sign is kept.

**Fills and exits**
- **Fill price:** the open of the 1-minute candle that starts when the signal bar closes. This avoids look-ahead.
  - **Missing candle:** if there's no candle at that minute, the next candle within 3 minutes is used. If there's none, the trade is skipped and the reason is logged.
- **Entry window:** a signal can open a trade if its bar closes at or after the start time and at or before the cutoff, both edges included.
- **Exits:**
  - **Opposite cross:** exits the trade, even after the cutoff.
  - **Reversal:** inside the window, an opposite cross also opens the reverse trade at the same fill.
  - **Square-off:** any open trade is closed at the 15:00 1-minute open.
- **Cross #:** the 1-based rank of the cross among that day's in-window crosses.
- **Whipsaw:** an exit on the opposite cross within 2 signal bars.

**Contracts**
- **ATM strike:** spot at the signal close, rounded to the nearest 50. Exact halves round up.
- **ITM 5:** five strikes in the money: CE at ATM − 250, PE at ATM + 250.
- **Direction:**
  - **Bullish:** buy CE, or sell PE in sell mode.
  - **Bearish:** buy PE, or sell CE in sell mode.
- **Expiry:** the nearest expiry. On expiry day it rolls to the next one; a setting turns this off.

**Friction**
- **Slippage:** 0.5% of premium plus 0.5 points per fill.
  - **Buy fills:** rounded up to the 0.05 tick.
  - **Sell fills:** rounded down to the tick, with a 0.05 minimum.
- **Charges:** all editable in Settings.

| Charge | Rate |
|---|---|
| Brokerage | ₹20 per order |
| STT | 0.15% of sell premium |
| Exchange transaction | 0.03503% of turnover |
| SEBI fee | ₹10 per crore |
| Stamp duty | 0.003% of buy value |
| GST | 18% of (brokerage + exchange + SEBI) |

**Metrics**
- **Max drawdown %:** measured against the configurable starting capital.
- **Profit factor:** shown as "∞" when there are no losing trades.

## Live / paper engine (`/live`)

**How it works**
- **Same rules as the backtest:** on every signal-bar close (plus 5 seconds) the engine rebuilds today's trade sequence from closed bars using the backtester's own code, and acts only on events it hasn't handled yet. A replay test checks that the engine reproduces the backtest's trades exactly in all three execution modes.
- **Data:** NIFTY 1-minute candles come from the Groww historical API, the same source the backtest uses. Prices come from the LTP endpoint. Contracts are looked up in Groww's instrument master, which is cached daily in `data/instruments.csv`.

| Mode | Behaviour |
|---|---|
| **Paper** | Real-time Groww prices. Fills are simulated at the option's LTP, with the same slippage and charge model as the backtest. No orders are sent. |
| **Live** | Real MIS market orders on your Groww account. Each order is confirmed through its order status, and the actual average fill price is recorded. |
| **Replay demo** | Replays a stored synthetic day on a fast simulated clock, so you can watch the engine work. |

**Safety rails**
- **Starting live:** you must type `LIVE` to confirm. Lots are capped by `LIVE_MAX_LOTS` in `.env` (default 1).
- **Pre-start checks:** Groww login, a live quote, and an expiry lookup must all succeed before the engine starts.
- **Limits:**
  - **Daily loss limit:** realised PnL plus open MTM, after costs. Hitting it squares off and halts entries for the day.
  - **Maximum trades per day.**
- **Late starts:** a signal more than 3 minutes old is never entered.
- **Restarts:** an open position is resumed from Postgres after an app restart, and a bar that has already been filled is never processed twice.
- **Failed exits:** retried up to 5 times; after that the engine halts.
- **Unconfirmed orders:** if an order times out without a confirmation, the engine switches to an ERROR state and sends no further automatic orders. Only manual square-off and stop still work. Check the Groww app before doing anything else.
- **Buttons:** **Square off now** exits the position and keeps the engine running. **Stop & square off** exits and stops.

**Keep the app running during market hours.** If it stops, open positions are not managed. Groww auto-squares MIS positions near the close, with a charge. Use **Check Groww positions** to compare the broker's view with the engine's.

**Database tables:** trades and events are stored in `live_trades`, `live_events` and `live_sessions`.

## Files

| File | Role |
|---|---|
| `app.py` | Flask routes (pages and JSON API) |
| `groww_client.py` | TOTP login, token cache, and re-login once on an auth error |
| `providers.py` | Groww and synthetic data providers |
| `db.py` | Postgres schema and queries; backtest runs are cached in `bt_runs` |
| `strategy.py` | Pure signal and trade-sequencing logic |
| `costs.py`, `metrics.py` | Friction and performance metrics |
| `backtest.py` | Orchestration and chart payloads |
| `jobs.py` | Background jobs with progress for downloads and runs |
| `live_engine.py` | Live/paper engine: signal replay, entries, exits, risk |
| `live_market.py` | Groww market data, paper and live brokers, replay market |
| `live_manager.py` | Single engine instance and start/stop safety checks |
| `templates/`, `static/` | UI |

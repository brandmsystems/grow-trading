# Groww 9/21 EMA Trading System

A Flask app for a NIFTY options 9/21 EMA crossover strategy. It has a historical data manager, a backtester, a trade viewer, a live/paper engine, and a Groww account page.

## Run

```powershell
.venv\Scripts\python app.py
```

Then open:
- http://127.0.0.1:5000: backtest dashboard
- http://127.0.0.1:5000/compare: all strategies × timeframes compared over the full history
- http://127.0.0.1:5000/signals: signal engine with out-of-sample confidence scores
- http://127.0.0.1:5000/live: live / paper trading engine
- http://127.0.0.1:5000/data: download historical data and check its coverage and quality
- http://127.0.0.1:5000/history: historical candlestick chart
- http://127.0.0.1:5000/account: Groww profile and funds

## Setup

- **`keys.txt`** holds your Groww credentials. Copy it from `keys.example.txt` and fill in both lines:
  ```
  API_KEY=...
  TOTP_SECRET=...
  ```
  With an approval-type Groww key, use `API_SECRET=...` instead of `TOTP_SECRET`. The app detects which one it has.
- **`.env`** holds the PostgreSQL connection details. The database is PostgreSQL 17 on localhost, in the `groww_trading` database.
- **Tests:** run `.venv\Scripts\python -m pytest`. The database tests create throwaway `groww_trading_test*` databases and drop them afterwards.
- **Migrations:** SQL files in `migrations/` are applied in order when the app starts, and recorded in `schema_migrations`. To change the schema, add the next numbered file; never edit one that has been applied.
- **Timestamps:** stored as `TIMESTAMPTZ`. Database connections use Asia/Kolkata, and the app works in IST wall-clock datetimes.

## Datasets

| Dataset | What it is |
|---|---|
| **Groww** | Real NIFTY 1-minute spot data. Option 1-minute candles for the exact contracts a trade needs are downloaded on demand and cached in Postgres. |
| **Synthetic** | A deterministic random walk used only by automated tests. The web app refuses it. It is stored under `SYNTH:` symbols, so it never mixes with real data. |

## Historical data (`/data`, `/history`)

- **Requires** an active Groww Trading API subscription. Without it, Groww answers 403 and the download stops with an explanation.
- **Requests:** up to 30 days of 1-minute candles each, and only for days not already stored.
- **Recovery:** finished days are recorded as they complete, so re-running after a failure, a stop or an app restart carries on where it left off. Each attempt is listed in Download history.
- **Validation:** repeated candles are counted and stored once. Candles with bad prices, inconsistent OHLC or misaligned times are rejected as invalid. Moves over 5% between adjacent minutes are flagged but kept.
- **Regular session only:** Groww also returns pre-open (09:00–09:14), after-close (15:30–15:59) and evening Muhurat candles. They are counted as "outside hours" and not stored, because the strategy trades 09:15–15:29. A day with only such candles is shown as a special session.
- **Gaps are never filled.** Missing minutes are listed per day. A weekday with no candles is shown as "no candles returned": usually a holiday, but it can't be told apart from a real gap without a holiday calendar.

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

## Strategies and research (`/compare`, `/signals`)

**Strategies** ([strategies.py](strategies.py)): EMA 9/21, 5/20, 8/21, 20/50, and EMA 9/21 confirmed by VWAP, RSI(14) > / < 50, or the MACD(12, 26, 9) histogram. All use the same trade rules as 9/21 (entry window, reversal, 15:00 square-off) on 1, 5, 15 or 30-minute bars.
- **Confirmation:** an unconfirmed cross doesn't open a trade, but still exits an opposite one.
- **VWAP and volume** come from near-month NIFTY futures, because the index has no volume. The contract rolls on its expiry day.
- **Warm-up:** enough sessions are skipped at the start of the data for the slowest indicator to settle.
- **Expiry rule:** nearest weekly (default), next weekly, or nearest monthly; set in Backtest settings.

**Option pricing**
- Every trade uses real 1-minute candles of the actual contract.
- Groww's contract list for an old expiry can miss strikes that did trade, so the standard symbol is used instead, and Groww's candles for it decide.
- An entry or exit with no option candle within 3 minutes is skipped and listed. No earlier price is used.
- Lot size is the configured value for all years.

**Compare** runs every strategy × timeframe over all stored data and keeps a compact summary in `strategy_results`. It shows:
- net P&L, win rate, profit factor and drawdown
- equity curves and monthly P&L
- year-by-year returns
- a walk-forward table, where each year uses the configuration that did best on earlier years only

The first run downloads every option contract it needs, a few in parallel. Later runs reuse them.

**Signals** ([signals.py](signals.py))
- **References:** each in-window cross gets an entry reference (signal close), a stop (1 × ATR) and a target (2 × ATR).
- **Indicators:** trend, VWAP, RSI, MACD, volume, volatility and daily regime, each marked as supporting or against.
- **Outcome:** a hit if the target is reached before the stop by 15:00.
- **Score:** a logistic model trained walk-forward, so every scored year was unseen by its model. The page shows the hit rate each score band actually achieved.
- **Bands:** <50 none, 50–69 moderate, 70–84 strong, 85+ very strong.
- **Strong alert:** needs a score of at least 70, 3 supporting indicators and 30 comparable past signals.
- **Not used:** option-chain OI, IV and Greeks, because Groww has no historical snapshots to validate them against.

## Live / paper engine (`/live`)

**How it works**
- **Same rules as the backtest:** on every signal-bar close (plus 5 seconds) the engine rebuilds today's trade sequence from closed bars using the backtester's own code, and acts only on events it hasn't handled yet. A replay test checks that the engine reproduces the backtest's trades exactly in all three execution modes.
- **Data:** NIFTY 1-minute candles come from the Groww historical API, the same source the backtest uses. Prices come from the LTP endpoint. Contracts are looked up in Groww's instrument master, which is cached daily in `data/instruments.csv`.

| Mode | Behaviour |
|---|---|
| **Paper** | Real-time Groww prices. Fills are simulated at the option's LTP, with the same slippage and charge model as the backtest. No orders are sent. |
| **Live** | Real MIS market orders on your Groww account. Each order is confirmed through its order status, and the actual average fill price is recorded. |
| **Replay** | Replays a stored real trading day on a fast simulated clock, using paper fills. |

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
| `providers.py` | Groww data provider, and the synthetic provider used by tests |
| `data_manager.py` | Historical download (spot and near-month futures), validation, coverage reports and chart candles |
| `indicators.py` | EMA, Wilder RSI and ATR, MACD, session VWAP |
| `strategies.py` | The seven compared strategies and their confirmation rules |
| `research.py` | Full-history comparison grid and walk-forward selection |
| `signals.py` | Signal engine: references, indicators, outcomes and out-of-sample scores |
| `migrations/` | Numbered SQL schema migrations |
| `db.py` | Postgres schema and queries; backtest runs are cached in `bt_runs` |
| `strategy.py` | Pure signal and trade-sequencing logic |
| `costs.py`, `metrics.py` | Friction and performance metrics |
| `backtest.py` | Orchestration and chart payloads |
| `jobs.py` | Background jobs with progress for downloads and runs |
| `live_engine.py` | Live/paper engine: signal replay, entries, exits, risk |
| `live_market.py` | Groww market data, paper and live brokers, replay market |
| `live_manager.py` | Single engine instance and start/stop safety checks |
| `templates/`, `static/` | UI |

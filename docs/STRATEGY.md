# Strategy and calculations

**Code:** `backend/app/services/strategy/` (`rules.py`, `indicators.py`, `strategies.py`, `signals.py`) and `trading/charges.py`.

## 9/21 EMA crossover rules (`rules.py`)
- **Bars:** 1-minute candles (stamped with their start time) are resampled to 1, 5, 15 or 30 minutes, aligned to 09:15. A bar is identified by its close time; the last bar is capped at 15:30.
- **EMA:** `ewm(span, adjust=False)`, carried across days. Enough sessions are skipped at the start of the data for the slowest indicator to settle (at least 3).
- **Cross:** a change in the sign of fast − slow on a closed bar. Equal EMAs keep the previous sign, so ties are never a cross.
- **Fill:** the open of the 1-minute candle starting at the signal bar's close. That's the first moment the signal is known, so there's no look-ahead. With no candle there, the next one within 3 minutes is used; otherwise the trade is skipped.
- **Entry window:** the signal bar's close must fall within [entry start, cutoff], both ends included. The default is 09:30–14:30.
- **Exits:**
  - **Opposite cross:** exits the trade, at any time before 15:00. Inside the window, the same cross also opens the reverse trade.
  - **Square-off:** anything still open is closed at the 15:00 1-minute open. Signals from bars closing at or after 15:00 are ignored.
- **Cross #:** the trade's rank among that day's in-window crosses.

## Option selection
| Mode | Bullish | Bearish |
|---|---|---|
| ATM buy | Buy CE at ATM | Buy PE at ATM |
| ITM 5 buy | Buy CE at ATM − 250 | Buy PE at ATM + 250 |
| ATM sell | Sell PE at ATM | Sell CE at ATM |

- **ATM:** the spot at the signal close, rounded to the nearest 50 (halves round up).
- **Expiry:** nearest weekly (default), next weekly, or nearest monthly. On expiry day it rolls to the next expiry (configurable).

## Strategies compared (`strategies.py`)
EMA 9/21, 5/20, 8/21, 20/50, and EMA 9/21 confirmed by:
- **VWAP:** near-month futures close vs futures session VWAP. The index has no volume, so futures are used.
- **RSI(14):** above or below 50.
- **MACD(12, 26, 9):** histogram above or below 0.

An unconfirmed cross doesn't open a trade, but still exits an opposite one.

## Indicators (`indicators.py`)
- **EMA**
- **Wilder RSI and ATR:** seeded with the simple mean of the first n values. Checked against Wilder's published example (70.46).
- **MACD**
- **Session VWAP:** cumulative from the first candle of each day.

## Signal engine (`signals.py`)
- **Levels:** entry reference = signal close; stop = 1 × ATR(14); target = 2 × ATR, so risk/reward is 2.
- **Outcome:**
  - **Hit:** the target is reached before the stop, on 1-minute highs/lows, by 15:00.
  - **Miss:** the stop is reached first, or neither by 15:00. A minute that touches both counts as the stop.
- **Features:** trend slope, price vs slow EMA, VWAP position, RSI, MACD, volume ratio, ATR %, daily regime (previous days only), high-volatility flag, time of day.
- **Model:** ridge logistic regression, trained walk-forward (each year scored by a model trained only on earlier years).
- **Bands:** <50 none, 50–69 moderate, 70–84 strong, 85+ very strong. They are always shown next to the hit rate achieved on unseen data.
- **Strong alert:** score ≥ 70, at least 3 supporting indicators, and at least 30 comparable past signals.
- **Not used:** option-chain OI/IV/Greeks, because Groww has no historical snapshots.

## Charges (`trading/charges.py`)
| Item | Rate |
|---|---|
| Slippage | 0.5% of premium + 0.5 points per fill. Buy fills round up to the 0.05 tick; sell fills round down, minimum 0.05 |
| Brokerage | ₹20 per order |
| STT | 0.15% of sell premium |
| Exchange fee | 0.03503% of turnover |
| SEBI fee | ₹10 per crore |
| Stamp duty | 0.003% of buy value |
| GST | 18% of (brokerage + exchange + SEBI) |

All rates are editable in Backtest settings.

## Position sizing (`options/sizing.py`)
`lots = min(floor(risk budget ÷ risk per lot), floor(available cash ÷ cost per lot))`.
- **Risk budget:** capital × risk %.
- **Risk per lot:** (entry − stop) × lot size, plus charges. Live and paper use the contract's current lot size from Groww's instrument list; backtests use the NSE lot size of each historical contract.
- **Cost per lot:** premium × lot size, plus charges.

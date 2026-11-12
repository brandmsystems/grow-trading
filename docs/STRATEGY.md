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

### Calibration (Phase 2, 12 Nov 2026, analysis version 3)
The raw score and its model are unchanged (prediction mode compares that score with `min_score`, so changing it would change trading). Calibration is measured and shown next to it:
- **Band hit rates with 95% ranges:** Wilson intervals on the out-of-sample signals in each band and in ten equal-sized score groups.
- **AUC range:** 95% bootstrap interval (400 resamples, fixed seed).
- **Walk-forward calibration:** each out-of-sample year is calibrated (Platt scaling on logit(score)) using only earlier out-of-sample years, then compared with the simplest honest forecast, the earlier years' average hit rate (Brier skill). A test proves that changing a later year's outcomes never changes an earlier year's result.
- **Calibrated estimate:** each historical signal gets its walk-forward estimate; live signals use a calibrator fitted on all out-of-sample signals.
- **Verdict:** "No proven edge" when the AUC range includes 0.50; "Weak" when the calibrated rates don't beat the average; "Modest edge" when both tests pass.

**EMA 9/21 results (built 12 Nov 2026):**
| Timeframe | Out-of-sample signals | AUC (95% range) | Calibrated vs average (Brier skill) | Verdict |
|---|---|---|---|---|
| 5 min | 2,124 | 0.52 (0.49–0.55) | −0.1% | No proven edge |
| 15 min | 570 | 0.59 (0.53–0.63) | +2.3% | Modest edge |
| 30 min | 90 | 0.72 (0.61–0.83) | not testable yet (one out-of-sample year) | Not enough later years |

Scores almost never reach the 70+ bands (15 min: 1 signal of 570). The bands describe the score, not a likelihood: in the 15-minute "No strong signal" band, 25.2% (21.7–29.0%) of signals hit their target.

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

## Paper trading risk management (12 Nov 2026)
Paper trading only. Live and replay keep fixed lots and are unchanged; nothing here can place a Groww order.

**Your decisions:** premium stop-loss enforced on paper trades; default stop ATR × delta; after a daily-limit halt, trading resumes at the next session; the virtual account carries a running balance.

**Before every paper entry** (`Engine._paper_risk`, using `options/sizing.risk_size`):
1. Available virtual capital = account balance − open investment (`paper_account.state`).
2. Risk % from the session settings (presets: Conservative 0.5%, Low 1%, Moderate 1.5%, High 2%, or custom). These are settings, not safe levels.
3. Actual option premium: the contract's Groww LTP. If it's unavailable: **NO TRADE**.
4. Stop-loss premium:
   - **ATR (default):** premium − |delta| × ATR multiple (1) × NIFTY ATR(14) of the signal timeframe; delta from Groww's option chain.
   - **%:** premium × (1 − stop %).
   - Sells mirror this above the premium. If ATR or delta is unavailable: **NO TRADE**.
   - Target (shown for risk/reward only, not enforced) = premium ± |delta| × 2 × ATR, or 2× the % distance.
5. Risk amount = available capital × risk % ÷ 100.
6. Risk per lot = (entry − stop) × lot size + slippage allowance + charges, i.e. the full loss of one lot closed at the stop (`charges.round_trip`). Lot size is the contract's own.
7. Lots = floor(risk amount ÷ risk per lot), capped by the cash available after the minimum balance (buys) and by max lots. Quantity = lots × lot size.
8. **Checks:**
   - the daily loss limit isn't already reached
   - the trade's maximum loss fits in what's left of today's limit
   - balance and maximum lots
   - open positions < maximum
9. **NO TRADE** if one lot exceeds the risk budget, the capital is insufficient, or any check fails. The exact reasons (every failed check) and the full calculation are stored in a HOLD alert.
10. Otherwise the simulated fill happens, and the full calculation is saved in `live_trades.risk`, with `stop_premium`, `target_premium` and `paper_account_id`.

**While a paper position is open:** it exits when the option premium reaches `stop_premium` (`stop_loss`), as well as on the opposite crossover and the 15:00 square-off.

**Daily limit:** the smaller of `max_daily_loss` (₹) and `daily_risk_pct` of the day's starting capital. Realised + open P&L reaching it squares off and halts new entries until the next session.

**Selling (ATM sell):** option-selling margin isn't modelled, so sells are sized by the risk budget and max lots only.

## Live dashboard insight (12 Nov 2026)
Everything below reads the strategy's own closed bars (`strategies.prepare` via `signals.signal_bars`). **None of it changes a signal:** the 9/21 strategy still enters on every crossover inside the window. A crossover with weak confirmation stays BUY CE / BUY PE, with a caution. Turning it into HOLD would change the trading rules.

**Explanation (`strategy/insight.explain`):** for the signal bar (or the latest closed bar on HOLD), with actual values:

| Check | Rule (same conventions as the strategies and signal engine) |
|---|---|
| EMA 9 / EMA 21 | the crossover, the values and the bar time |
| VWAP | NIFTY futures close vs the futures session VWAP |
| RSI(14) | above 50 bullish, below 50 bearish, 45–55 neutral |
| MACD(12,26,9) | histogram sign |
| Volume | futures bar volume vs the 20-bar average: ≥ 1.2× strong, < 0.8× weak |
| Trend | daily regime from previous days |

- **Confidence:** the signal engine's model score (`signals.Scorer`, from the latest Signals analysis for that timeframe), with its band's out-of-sample hit rate. It's a model score, not a probability.
- **"Why X and not HOLD":** the crossover was inside the entry window.
- **On HOLD:** the exact reason, plus what a new entry needs (the EMA gap now).
- **Caution:** shown when 2 or more confirmations disagree.

**Today's plan (`insight.trading_plan`):**
- **From Groww's quote:** previous close, open, high, low.
- **Calculated from candles (labelled as such; the exchange publishes no support/resistance):** classic pivots (P, R1/R2, S1/S2) from the previous session, previous day high/low, and today's 09:15–09:30 opening range.
- **Bullish / bearish level:** the opening range high / low once formed, otherwise the previous day high / low.
- **Preferred direction:** bullish if at least 3 of {EMA 9 > 21, futures above VWAP, price above pivot, daily regime bullish} agree and at most 1 disagrees. Bearish is the mirror; otherwise none.
- **Scenarios:** bullish (BUY CE), bearish (BUY PE) and sideways (HOLD), each with conditions built from these levels.
- **Updates:** the plan is judged on closed bars. Each change (direction or levels) is stored in `trading_plans` with its reason.

**Candle patterns (`strategy/patterns.py`):**
- **Patterns:** doji, hammer, shooting star, bullish/bearish engulfing, morning/evening star, strong bullish/bearish candle, and breakout/breakdown (close beyond the 20-bar high/low). Thresholds are in the module docstring.
- **Closed bars only:** a pattern is fixed at the bar that completes it.
- **Status:** "confirmed" when the next closed bar closes beyond the pattern bar in its direction, "awaiting confirmation" while the pattern bar is the latest closed bar, "neutral" for doji. Patterns never repaint (tested).
- **Effect:** each pattern states whether it agrees or conflicts with the current call; it never changes the call.

**Chart data:**
- **Per bar:** EMA 9/21, VWAP (futures VWAP shifted by the futures–spot basis), futures volume, RSI and MACD line/signal/histogram.
- **Markers:** BUY CE / BUY PE / EXIT / HOLD from the strategy's events (HOLD = a crossover outside the window).
- **Timeframes:** 1, 5, 15 and 30 minutes on the chart. The engine still trades 5, 15 or 30.

## Paper stop-loss management (12 Nov 2026)
- **Methods:** ATR × delta (default), % of premium, or fixed premium points (`stop_points`).
- **Calculated before every entry:** the entry premium, stop, target, risk/reward and maximum loss (₹ and % of capital) are stored with the trade. The first stop is logged in `paper_stop_changes` (`source=entry`).
- **Editing the stop on an open paper position (`Engine.set_paper_stop`, `POST /api/paper/position/stop`):** the stop must sit on the safe side of the current premium. The new maximum loss (with slippage and charges) is recalculated, and a looser stop is refused if it exceeds the trade's risk amount or what's left of today's loss limit. Each change is logged with the time, old and new stop, and old and new maximum loss.
- **Exits:** automatic at the stop, on a fresh premium only (older than 15 s is never acted on; a warning is logged). One exit per position; a failed exit goes through the existing retry path. Net P&L includes slippage and charges.
- **Chart:** the stop and target are drawn as NIFTY levels converted with the option's delta at entry (approximate).
- **Scope:** paper only; live and replay are unchanged.

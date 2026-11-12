# Historical data and backtesting

## Historical data (`services/market_data/history.py`)
- **Coverage:** NIFTY spot 1-minute candles from 11 Nov 2021 (five years), plus the near-month NIFTY future for every day (for VWAP and volume).
- **Downloads:**
  - up to 30 days per request, only for days not yet stored
  - resumes after failures, stops and restarts
  - each attempt is recorded in `data_downloads`
- **Validation:**
  - repeated candles are counted and stored once
  - bad prices, inconsistent OHLC or misaligned times are rejected
  - pre-open, after-close and Muhurat candles are counted but not stored
  - moves over 5% between adjacent minutes are flagged
- **Gaps are never filled.** Missing minutes are listed per day on the Data page.
- **Coverage report:**
  - 1,237 sessions, 0 left to download, 0 invalid candles
  - 72 weekday holidays, 2 Muhurat sessions, 4 short special sessions
  - 4 real gaps in Groww's data: 7 Mar 2022, 28 Mar 2023, 26 Sep 2025, 29 Sep 2026
- **Cross-check:** including pre-open/after-close candles, the 1-minute data rebuilds Groww's official daily OHLC on 19 of 19 days checked.

## Backtest (`services/backtest/engine.py`)
1. Load spot candles for the range plus 40 days of indicator history (and futures for VWAP strategies).
2. Build bars and indicators; generate legs with the strategy rules.
3. For each leg and execution mode, choose the expiry and strike. Download the contract's 1-minute candles from Groww (4 at a time, one request per contract, cached) and price the entry and exit.
4. Apply slippage and charges, then compute metrics.

**Rules that keep results honest:**
- **No look-ahead.**
- **No invented prices:** a missing option candle skips the trade with a reason.
- **Today's unfinished session:** valued at the latest completed minute and marked "open".

**Results:** each mode gets trades, win rate, gross/net P&L, friction, profit factor, payoff, expectancy and max drawdown (₹ and %). The Backtest page also shows monthly, yearly, best and worst days, no-trade days and skipped trades.

## Comparison (`services/backtest/research.py`, Compare page)
Every strategy × timeframe (7 × 4 = 28) runs over all stored data, and a compact summary is kept in `strategy_results`. **Walk-forward:** each year uses the setup with the best net P&L on earlier years only.

### Results (11 Nov 2021 → 11 Nov 2026, 1 lot of 65, after all costs)
- **All 28 configurations are complete.** Only two of 84 strategy × mode results were positive:
  - EMA 20/50 30m ATM sell: +₹8,807
  - EMA 20/50 30m ATM buy: +₹2,048 (profit factor ≈ 1.0)
- **EMA 9/21 15m ATM buy:** −₹1,80,326 over 982 trades. It lost every year from 2021 to 2025.
- **5-minute ATM buy:** −₹3.3 to −₹7.7 lakh.
- **1-minute ATM buy:** −₹12.7 to −₹49.2 lakh, because there are far more trades and so far more costs.
- **Walk-forward totals:** ATM buy −₹52,537; ITM 5 buy −₹82,819; ATM sell −₹52,684.

Signal engine at 15m: base hit rate 26%; scores of 50+ hit 38% (29 signals); AUC 0.587.

**These are past results and don't predict future returns.**

## Limitations
- **Lot size:** by default each contract's NSE lot size (`lot_sizes`): 50 until Apr 2024, then 25, then 75 (weeklies from 2 Jan 2025, monthlies from 27 Feb 2025), then 65 (weeklies from 6 Jan 2026, monthlies from 27 Jan 2026). A fixed lot size can still be chosen. Each trade records `lot_size` and `lot_source`.
- **Holidays:** no holiday calendar.
- **Option-chain data:** IV, OI and Greeks have no history.

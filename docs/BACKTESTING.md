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

**Results:** each mode gets trades, win rate, gross/net P&L, friction, profit factor, payoff, expectancy and max drawdown (₹ and %). The Backtest page also shows monthly, yearly, best and worst days, no-trade days and skipped trades. Phase 2 (12 Nov 2026) added the payoff ratio and average win/loss, costs split into brokerage & taxes and slippage, and filters for direction, crossover number of the day (#1, #2, #3, #4+) and entry time range; every KPI, chart and table follows the filters. The page's figures use the same definitions as `metrics.compute` (break-even counts as a loss). Engine and results unchanged.

## Comparison (`services/backtest/research.py`, Compare page)
Every strategy × timeframe (7 × 4 = 28) runs over all stored data, and a compact summary is kept in `strategy_results`. **Walk-forward:** each year uses the setup with the best net P&L on earlier years only.

### Results with NSE lot sizes (11 Nov 2021 → 11 Nov 2026, 1 lot, after all costs; re-run 12 Nov 2026)
Each trade uses its contract's NSE lot size (50, 25, 75 or 65; see `lot_sizes`). The earlier fixed-65 results are kept in `strategy_results` for comparison.

| Result | NSE lot sizes | Fixed lot of 65 |
|---|---|---|
| Positive strategy × mode results (of 84) | 2 | 2 |
| EMA 20/50 30m ATM sell | +₹1,674 (PF 1.008) | +₹8,807 |
| EMA 20/50 30m ATM buy | +₹571 (PF 1.003) | +₹2,048 |
| EMA 9/21 15m ATM buy (984 trades) | −₹1,58,676 (PF 0.84) | −₹1,85,783 |
| 5-minute ATM buy, range across strategies | −₹2.6 to −₹6.3 lakh | −₹3.3 to −₹7.7 lakh |
| 1-minute ATM buy, range across strategies | −₹11.5 to −₹43.0 lakh | −₹12.7 to −₹49.2 lakh |
| Walk-forward (out-of-sample) ATM buy / ITM 5 buy / ATM sell | −₹37,883 / −₹45,012 / −₹44,519 | −₹52,537 / −₹82,819 / −₹52,684 |

- **EMA 9/21 15m ATM buy by year (NSE lots):** 2021 −₹27,074; 2022 −₹29,580; 2023 −₹27,181; 2024 −₹29,037; 2025 −₹50,946; 2026 +₹5,142.
- **Why losses shrank:** from May 2024 to Dec 2024 the real lot was 25 (not 65), and before that 50, so those years carried smaller positions. 2025 used 75. The conclusion doesn't change: the two EMA 20/50 30m results are break-even, and everything else lost money after costs.

Signal engine at 15m: base hit rate 26%; scores of 50+ hit 38% (29 signals); AUC 0.587.

**These are past results and don't predict future returns.**

## Limitations
- **Lot size:** by default each contract's NSE lot size (`lot_sizes`): 50 until Apr 2024, then 25, then 75 (weeklies from 2 Jan 2025, monthlies from 27 Feb 2025), then 65 (weeklies from 6 Jan 2026, monthlies from 27 Jan 2026). A fixed lot size can still be chosen. Each trade records `lot_size` and `lot_source`.
- **Holidays:** no holiday calendar.
- **Option-chain data:** IV, OI and Greeks have no history.

# 5-minute NIFTY options scalping (13 Nov 2026)

This is a separate analyzer that sits next to the existing backtester. It does not change any existing strategy, backtest or Compare result.

| Part | Where it lives |
|---|---|
| Analyzer | `backend/app/services/backtest/scalping.py` |
| API | `backend/app/api/research.py` (`/api/scalping*`) |
| Engine mode | `signal_mode="scalp"` in `backend/app/services/trading/engine.py` |
| Page | `/app/scalping`, built from `frontend/src/pages/Scalping.tsx` |
| Tables | `scalp_runs` and `scalp_trades` (migration 0011); `live_trades.strategy` and `live_trades.scalp_config` (migration 0012) |
| Tests | `backend/tests/test_scalping.py` (14 tests) |

## What is tested

The analyzer tests 6 strategies × 2 contracts × 10 exit rules, which gives **120 configurations**.

- **Strategies.** These are the definitions already in `strategies.py`:
  - EMA 9/21
  - EMA 5/20
  - EMA 20/50
  - EMA 9/21 + VWAP (near-month futures VWAP)
  - EMA 9/21 + RSI (above or below 50)
  - EMA 9/21 + MACD histogram (above or below 0)
- **Contracts.** Each contract type is tested on its own:
  - ATM
  - ITM 5 (5 strikes in the money)

  Bullish signals buy CE and bearish signals buy PE. The analyzer uses the nearest weekly expiry and rolls to the next one on expiry day.
- **Exit rules.**
  - Fixed 5-minute hold.
  - Stop-loss and target, with a maximum hold of 5 minutes. Stops tested: 5, 10 and 15% of the premium. Targets tested: 5, 10 and 20%.
- **Risk sizing.** Every stop/target configuration is also sized at 0.5%, 1% and 2% risk of ₹1,00,000. The number of lots is chosen so that the loss at the stop, including slippage and charges, fits inside the risk amount. Capital also caps the lots.

## How a trade is simulated

**Signal.** A signal is a crossover of the strategy's fast and slow EMA on a **completed** 5-minute NIFTY spot bar. The strategy's filter must confirm it on the same bar. A bar that starts at 09:30 closes at 09:35, so its signal is known at 09:35. Signals count only between 09:30 and 14:30.

**Entry.** The entry price is the open of the option's first 1-minute candle at or after the bar close. This is the first price you could actually trade at. If the option has no candle within 2 minutes, the analyzer skips the signal and records the reason. It never fills in a missing price.

**Exit.**
- **Fixed hold:** the open of the option candle 5 minutes after the fill. That candle must appear within 3 minutes of the exit time; otherwise the trade is skipped.
- **Stop/target:** the analyzer checks the levels on every 1-minute option candle, starting with the entry candle. Levels are rounded to the 0.05 tick, against the trade.
  - If one candle touches both levels, the stop counts first.
  - If a candle opens beyond a level, the trade fills at that open, which is the worse price.
  - If neither level is hit, the 5-minute time exit applies.

**No duplicate entries.** Each configuration holds one position at a time. A signal that arrives while a trade is still open is skipped and counted.

**No look-ahead and no repainting.**
- The analyzer uses only completed bars.
- Today's unfinished session is excluded.
- Tests show that adding later candles never changes an earlier signal.

**Costs.** Every trade pays:
- slippage of 0.5% plus 0.5 point on each fill
- brokerage
- STT, exchange charges, SEBI fees, stamp duty and GST (`trading/charges.py`)

Lot sizes come from the stored NSE lot-size history for each contract.

## Choosing a configuration (win rate is not used)

1. **In-sample ranking.** The analyzer ranks configurations on the first 60% of trading days by net P&L divided by maximum drawdown. Only configurations with enough trades are ranked.
2. **Best configuration.** This is the highest-ranked configuration that is also net positive on the remaining 40% of days (out-of-sample). If no configuration qualifies, there is no best configuration.
3. **Walk-forward test.** For each year, the analyzer picks the configuration that scored best on all earlier years. The pick needs at least 200 earlier trades and a positive earlier net. It then records that pick's result in the year being tested. Years with no qualifying pick are not traded.
4. **"Consistently profitable".** A configuration must pass every check below:
   - net positive
   - at least 200 trades
   - profit factor of at least 1.1
   - positive in at least 75% of its years
   - positive out of sample

## Results (run 2: 11 Nov 2021 → 12 Nov 2026, 296,170 simulated trades)

**No configuration was consistently profitable after costs.**

| Measure | Result |
|---|---|
| Net positive after all costs | **0 of 120** |
| Positive before costs (gross) | 88 of 120 |
| Positive out of sample | 0 of 120 |
| "Best" under the selection rule | none |
| Walk-forward | no qualifying pick in any year (2022–2026) |
| Average cost per trade (slippage + brokerage + taxes) | about ₹244 |
| Best gross result per trade | about ₹27 |

**The edge is smaller than the costs.** The best configuration was EMA 20/50 · ATM · fixed 5-minute hold:
- 1,156 trades
- gross +₹5,580
- brokerage ₹46,240, taxes ₹27,170 and slippage ₹1,45,509
- **net −₹2,13,339**, with a profit factor of 0.36
- negative in every year and in every market regime

**Slippage is not the cause.** With slippage set to zero, no configuration turns positive. The best would still be −₹67,830, because brokerage and taxes alone are larger than any gross edge.

**CE and PE are both negative for every strategy.** Before costs, CE did a little better than PE for EMA 9/21, 9/21 + RSI and 9/21 + MACD.

**Win rate would have misled.** The highest win rate was 41% (EMA 20/50 · ATM · SL 15% / TP 5%), and that configuration lost ₹2.17 lakh.

**Comparison with the existing strategies.** On the Compare page, which holds each trade until the opposite cross, 1 of 56 strategy × timeframe × contract results is net positive: EMA 20/50 30m ATM buy, +₹571 with a profit factor of 1.003. That is break-even. Every 5-minute scalping configuration did worse, because a 5-minute hold pays the full round-trip cost on a much smaller price move.

Run 1, made before stop and target levels were rounded to the tick, gave the same conclusion.

## Paper trading a tested configuration

The page's **Automatic paper trading** card starts the engine with `signal_mode="scalp"` on the configuration you pick from the table.

**What you choose.** You pick a configuration, paper or replay mode, risk %, daily risk %, the maximum trades per day and the maximum lots. The strategy, contract and exit rule always come from the tested configuration.

**What the engine does.**
- It looks for confirmed crossovers on completed 5-minute bars, the same way the analyzer does.
- It buys the ATM or ITM 5 option.
- It exits on the 5-minute time limit, or earlier at the premium stop or target.
- The paper risk rules require a stop-loss, so fixed-hold configurations also get a protective 30% premium stop. The backtest has no such stop.
- Stop and target levels are rounded to the tick against you, the same way the analyzer rounds them.
  - In paper mode, the risk calculation sets the levels from the premium at signal time.
  - Replay has no paper risk sizing, so it trades the configured lots and sets the levels from the entry fill.

**What still applies.** The daily loss limit, the trades-per-day limit and the 15:00 square-off.

**Records.** Every trade is stored in `live_trades` with `signal_mode='scalp'`, `strategy` and `scalp_config`. The card's transaction table lists each BUY and SELL. Click a row to see times, prices, quantity and lots, stop and target, gross P&L, slippage, brokerage, taxes and net P&L.

**Limits.**
- **Paper and replay only.** `EngineConfig.validate` refuses scalp mode with `trade_mode="live"`, and `/api/scalping/paper/start` accepts only `paper` or `replay`. Real-money scalping is not enabled.
- **Nothing is picked for you.** You must choose a configuration. If it did not pass the checks, the page asks you to confirm that you are only observing it.

**Checked on a real session.** A replay of 12 Nov 2026 with EMA 9/21 · ATM · SL 10% / TP 20% ran through the same API the page uses. It took 4 trades, at 11:30, 13:55, 14:05 and 14:10. Each entered at the bar close, plus the engine's 10-second tick, and left by the 5-minute time exit. None reached its stop or target. Net after costs: −₹3,079 for 1 lot (65).

**Not yet checked:** paper mode on live Groww data during market hours.

## Re-running

- **From the page:** use **Run analysis** on the Scalping page.
- **From the API:** `POST /api/scalping/run`. This runs as a background job (`kind="scalping"`) and takes about 2 minutes on the stored history.
- **Data:** the analyzer reads only stored candles. To extend the history, download it on the Data page first.

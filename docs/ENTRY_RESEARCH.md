# Five-year entry-method research (19 Nov 2026)

Question: do more entry methods find more *qualified* NIFTY option opportunities than the single EMA crossover? Answer from real data: **no method survives costs, in any period.** Nothing was promoted.

## Method
- Data: NIFTY 1-minute candles and futures (VWAP, volume) 2021-11 to 2026-11-18, **real 1-minute option candles** (ATM CE/PE, nearest weekly expiry, rolled on expiry day), NSE lot size per contract. Option candles missing at entry or exit skip the trade (counted); nothing is filled in. Spot prices are never used as premiums. Bids, asks and Greeks are not stored historically, so spread and Greek filters could not be tested.
- Signals: 22 methods in `services/strategy/entries.py` on closed 5-minute bars with the closed 15-minute trend (EMA 20/50): fresh crossovers (9/21, 5/20, 8/21, 9/21+VWAP), 9/21 continuation and pullback, 20/50/200 alignment, RSI divergence with price confirmation, MACD cross and histogram, Bollinger breakout and reversal, VWAP breakout and retest, previous-day high/low breakout, retest and rejection, volume momentum, ATR breakout, opening range breakout, consolidation breakout, 15m trend reversal. The automated bias engine is included for comparison. Causality is tested (`tests/test_entries.py`). Parameters are textbook values fixed beforehand.
- Fills: next option candle after the signal bar closes; slippage and the full charge stack (`trading/charges.py`); 1 lot; one position at a time per method and exit rule; nothing held past 15:15.
- Four exit rules, fixed beforehand and not tuned: SL 20% / TP 40% / 30 min; SL 25% / TP 50% / 60 min; 20% stop with 12% trail after +15% / 60 min; 15-minute time exit.
- Chronological split: train 2022-23, validation 2024, out-of-sample 2025 to Nov 2026. A pair counts as robust only if net positive in all three with at least 30 trades each.
- Reproduce: `scripts/research_entries.py run` then `report` (read-only on the database; output in `data/exports/`).

## Result (234,576 trades, 92 method x exit pairs)
| | |
|---|---|
| Pairs robust (positive in train, validation and out-of-sample) | **0 of 92** |
| Pairs with positive net over all five years | **0 of 92** |
| Pairs with positive gross (before costs) | 44 of 92, all tiny |
| Mean gross per trade | **-₹4** |
| Mean costs + slippage per trade | **₹189** |
| Net, all trades | about **-₹4.5 crore** (summed over all pairs; overlapping streams, not a portfolio) |

- By year the pooled net is negative every year (2022 -₹84 lakh, 2023 -₹75 lakh, 2024 -₹78 lakh, 2025 -₹1.2 crore, 2026 to Nov -₹89 lakh); 2025 is the worst.
- **By time window (net):** every one of the seven windows loses in train, validation and out-of-sample. The two least bad before costs are 09:15-09:30 and 11:30-12:30 (small positive gross, still net negative). No window is "the good one".
- **CE versus PE:** both lose (CE -₹2.25 crore, PE -₹2.27 crore net). **By regime and days to expiry:** all lose.
- **Exit reasons:** stops lost ₹3.4 crore gross, targets earned ₹1.7 crore, time exits ₹1.6 crore gross. Time exits end net negative after costs.
- **Old versus new:** EMA 9/21 crossover -₹18 lakh, automated bias engine -₹19 lakh (all four exit rules, ~10,800 trades each). The new methods are no better than the old ones. The best pair is `trend_reversal` with a 15-minute exit: gross +₹5.7k over 449 trades, net -₹83k.
- Why: the average gross trade is about zero, so the fixed cost of about ₹189 per round trip decides the result. More opportunities means more losing round trips, not more profit.

## Decisions
- **No entry method is added to the engine, and no strategy was removed.** Promoting any of them would contradict this evidence. The existing cross, trend, prediction, scalp and bias modes are unchanged.
- Option selling was not validated (not tested here), so it stays off by default (`bias_allow`).
- The 20-trades-a-day cap remains a cap, never a target.
- `entries.py` is kept as research infrastructure (used by the script and tests), not wired to any trading mode.

## Limits
- ATM options only; the stop/target grid is small on purpose. A different contract or exit design could behave differently, but searching for one on this data would mean fitting noise.
- 1-minute candle fills: stop and target on the same candle assume the stop first; gaps fill at the open.
- No historical spread or Greeks; the live engine checks them when Groww provides them.
- Out-of-sample here means data not used to choose anything (nothing was chosen), so it is a plain hold-out.

## Confluence, FVG retest and VWAP rejection (21 Nov 2026)
Question: does a strategy built from fair value gaps, VWAP, ADR, EMA and market structure find qualified NIFTY option trades that survive costs? Answer from real data: **no.**

- Same method as above (`scripts/research_entries.py confluence`, then `report confluence`; the earlier result file is not touched, output goes to `data/exports/entry_research_confluence_trades.csv.gz`): real 1-minute option premiums, slippage and the full charge stack, four fixed exit rules, chronological split. Signals are the live strategy's own (`strategy/confluence.py`, default settings, never tuned): `confluence` (the four factors, 75% score, 15-minute trend, ADR filter), `fvg_retest` (a confirmed retest of a gap with the 15-minute trend agreeing) and `vwap_rejection` (a rejection of VWAP with the 15-minute trend agreeing).
- **26,733 trades, 12 method x exit pairs. 0 of 12 positive in train, validation and out-of-sample; none positive in any single period.**
- Net after costs per exit rule (1 lot, overlapping streams): confluence -₹4.8 to -6.1 lakh, FVG retest -₹3.9 to -4.2 lakh, VWAP rejection -₹3.6 to -3.9 lakh. Best pair out of sample: VWAP rejection with a 15-minute exit, -₹1.52 lakh over 759 trades.
- Pooled: win rate 33-42% with a payoff near 1.0, mean gross per trade about -₹10, costs about ₹188 per round trip. Every year, every entry window and every exit rule loses; stops lose ₹37.9 lakh gross and targets earn ₹14.5 lakh.
- Not done on purpose: no filter, factor or threshold was adjusted after seeing these numbers (that would fit noise); the ADR filter and each factor were not tested one by one.

## Decisions (21 Nov addendum)
- The confluence strategy was built at the user's request as an **opt-in** entry strategy of the bias engine (default unchanged). The 22 methods above remain research only and are not wired to any trading mode.

## Scored strategy against the seven existing strategies (21 Nov 2026)
Question: does a strategy of market structure, EMA 20/50/200, VWAP, an unmitigated FVG retest, momentum, volume and ADR (points out of 100, minimum 80) do better than the seven existing strategies once all costs are paid, on 5-minute and on 15-minute entries? Answer from real data: **no strategy, new or old, is profitable, and the new one is not better.**

- **Method** (`scripts/research_entries.py compare`, then `report scored`; output `data/exports/entry_research_scored_trades.csv.gz`, report text `entry_research_scored_report.txt`): the seven strategies' entries come from the same `strategies.prepare` / `legs` rules the backtester and the engine use, the scored strategy's from `confluence.sc_decide` (the live rules, defaults); both at a 5-minute entry (15-minute trend) and a 15-minute entry (30-minute trend). Real 1-minute CE/PE premiums (ATM, nearest weekly expiry, rolled on expiry day), the NSE lot size of each expiry, slippage and the full charge stack, 1 lot, one position at a time per strategy and exit, fill at the next option candle. Five exit rules for every strategy: the four fixed ones above and **atr_rr2**, the scored strategy's own risk (stop = 0.5 delta x 1.0 x ATR, validated to 5-50% of the premium, 2R target, held to 15:15 at most). Chronological split: train 2022-23, validation 2024, out-of-sample 2025 to Nov 2026.
- **Result** (125,046 trades, 80 strategy x exit pairs): **0 of 80 positive in train, validation and out-of-sample.** With atr_rr2: scored 5m 379 trades, win 27.2%, net -₹97,628, expectancy -₹258, profit factor 0.51, drawdown ₹99,500 (train -₹26,580, validation -₹14,457, out-of-sample -₹56,591); scored 15m 108 trades, win 31.5%, net -₹28,503, expectancy -₹264, profit factor 0.61 (train -₹7,144, validation +₹470 over 20 trades, out-of-sample -₹21,830). The seven existing strategies pooled: 5m expectancy -₹185 (profit factor 0.64), 15m -₹168 (0.78); single strategies range from -₹130 (EMA 9/21 + VWAP, 15m) to -₹252 (EMA 20/50, 15m).
- **By year** (scored 5m, walk-forward, nothing fitted): 2022 -₹9,161, 2023 -₹17,826, 2024 -₹14,457, 2025 -₹29,040, 2026 -₹27,551. Scored 15m: +₹4,540 (2022), then -₹8,509, +₹470, -₹13,227, -₹8,602. **By market** (5m): trending -₹229 a trade, sideways -₹310, high volatility -₹328. **By month:** positive in 11 of 60 months (5m) and 19 of 50 (15m); worst month -₹7,979. The full tables are in the report file.
- **Exits** (scored 5m): 264 stops lost ₹1.95 lakh, 102 targets earned ₹1.01 lakh, 13 time exits; average -0.52 R per trade (median -1.29 R). A 2R target needs about a one-in-three hit rate before costs; costs raise that to roughly 40%, and the strategy hit 27%.
- **Optimization on the training period only** (`research_entries.py optimize`): minimum score 70/80/90 x stop 0.75/1.0/1.5 ATR, grid fixed beforehand, 18 cells per timeframe pair. **None had positive expectancy in the training period itself.** The least-bad cell per timeframe (5m: score 80, 1.5 ATR; 15m: score 70, 1.0 ATR) was then priced on validation and out-of-sample: 5m -₹30,868 and -₹29,029, 15m +₹3,069 (25 trades) and -₹30,841. Validation and out-of-sample data were never used to choose; the specified defaults were kept.
- **Limits.** ATM delta assumed 0.5 for the research ATR stop (Greeks are not stored historically); no opposite-signal exit and no 15:00 square-off in the simulator (positions end at the stop, target or 15:15); 1-minute candle fills (stop first when both are in one candle); 1 lot per trade, so drawdown is rupees at one lot. The scored strategy's sample is small (the FVG first-return condition is rare: about 3% of candles pass it), so its year and month rows are indicative only. The earlier harness runs (`run`, `confluence`) were re-run through the refactored code and reproduce the same trades exactly.

## Decisions (21 Nov, scored strategy)
- Built as an **opt-in** entry strategy of the bias engine at the user's request; the seven strategies, the bias engine and the confluence strategy are unchanged and remain the defaults. No result here supports using it with real money, and the engine cannot.

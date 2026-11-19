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

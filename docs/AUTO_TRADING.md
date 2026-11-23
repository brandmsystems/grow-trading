# Automated multi-timeframe paper trading

*Built 19 Nov 2026 at the user's request. Paper and replay only: the engine refuses `trade_mode=live` and has no way to place a Groww order.*

Page: **Automated Paper Trading** (`/app/auto`). Engine mode: `signal_mode="bias"` in `services/trading/engine.py`. Analysis: `services/strategy/bias.py` (pure, no I/O). Reports: `services/trading/bias_report.py`. API: `api/bias.py`. Table: `candle_bias` (migration `0019_bias_engine.sql`).

> **Read this first.** The analysis was validated on stored real candles before this page was written up, and **it shows no tradable edge** (numbers below). The page does what the brief asks: it analyses every closed candle, takes qualified paper trades, logs every prediction and scores it against what happened. It does not claim the result is profitable, and neither should you.

## How it works
1. **Every closed analysis candle** (5 minutes by default; setting: 5 or 15) is analysed once its last 1-minute candle is in. The 15-minute candles (setting: 15, 30 or 60) confirm the direction. Only closed candles are used; a confirmation candle is visible to an analysis candle only after it closed.
2. **Twelve indicators vote** on each timeframe, from -1 (fully bearish) to +1 (fully bullish):

| Indicator | Weight | Vote |
|---|---|---|
| EMA 9/21 | 1.0 | (fast - slow) / (0.35 x ATR), after 3 x slow bars |
| EMA 5/20, EMA 8/21 | 0.5 each | same |
| EMA 20/50 | 1.0 | same |
| 200 EMA | 1.0 | (close - EMA200) / (1.5 x ATR), after 200 bars |
| VWAP | 1.0 | (futures close - session VWAP) / (0.5 x ATR); abstains without futures candles |
| RSI(14) | 0.75 | (RSI - 50) / 15 |
| RSI divergence | 0.5 | regular +-1.0, hidden +-0.6, from swing pivots that are only known 3 candles after they form; kept 6 candles; abstains when none |
| MACD(12,26,9) | 1.0 | 0.6 histogram + 0.2 line side + 0.2 fresh crossover |
| Bollinger(20,2) | 0.75 | breakout beyond a band +-1, inside 0.5 x %b |
| Volume expansion | 0.5 | futures volume vs the previous 20 candles, signed by the candle's direction (0 below 1.2x, full at 1.8x); abstains without futures |
| Support / resistance | 1.0 | previous-day high/low breakout +-1; inside the range a lean toward the nearer side, headwind just under the high, floor just above the low |

   ATR is not a direction: it only blocks entries when volatility is too low (`bias_min_atr_pct`). A vote that cannot be computed (not enough candles, no futures) is left out of the average, not counted as neutral. **The weights and thresholds are fixed starting values; none was fitted to any result.**
3. **Scores and bias.** A timeframe's score is the weighted mean of its votes. Bias = 0.6 x confirmation score + 0.4 x analysis score; STRONG BULLISH / BULLISH / NEUTRAL / BEARISH / STRONG BEARISH at +-0.5 and +-0.2. If the two timeframes point in opposite directions (both beyond 0.15) the bias is NEUTRAL ("conflicting timeframes = wait").
4. **Confidence** is the weighted share of votes pointing the same way as the bias (minus half of those pointing the other way), 0-100, and 0 for a NEUTRAL bias. **It measures agreement between indicators. It is not a probability of winning.**
5. **Entry candidate** (BUY CE / BUY PE): the confirmation score reaches +-`bias_trend_thr` (0.25), the analysis score reaches +-`bias_confirm_thr` (0.20) with the same sign, confidence >= `bias_min_confidence` (55) and 5m ATR >= 0.04% of price. Otherwise HOLD, with the reasons listed.
6. **Prediction for the next candle:** UP/DOWN when |bias| >= 0.15, else NEUTRAL. It is stored (with the bias, scores, votes, reasons, raw indicator values) in `candle_bias`. When the next candle closes, the actual move is stored: FLAT if smaller than 0.1 x ATR, and the outcome is CORRECT, INCORRECT or NEUTRAL (no call, or flat candle). Accuracy counts CORRECT and INCORRECT only.

## When a trade is taken
All of these on a closed candle, otherwise nothing happens (the daily limit is a cap, never a target):
- an entry candidate exists, inside the entry window (09:30-14:30 by default), before 15:00;
- no position is open (one at a time) and `max_trades_per_day` (default **20**) is not reached;
- **one entry per signal episode:** a run of consecutive candles with the same candidate direction is traded once; after a stop, target or time exit the same unchanged signal does not re-enter, it has to lapse and form again (this stops stacking and repeated entries; before the rule the filter produced about 49 candidate candles a day);
- after an *opposite-signal exit* there is a cool-down (`bias_cooldown_bars`, default 2 candles) and **never a reversal trade on the same candle**: the next candle gets a fresh analysis ("strong reversal signals trigger fresh analysis, not automatic reversal trades");
- an enabled instrument exists for the direction. Bullish: Buy CE, else Sell PE. Bearish: Buy PE, else Sell CE. **Default: buying only**; writing is a checkbox with its own, smaller risk % (`sell_risk_pct`, 0.5) and a stop above the premium;
- the contract passes the checks: premium >= minimum (5), open interest >= minimum, bid-ask spread <= maximum (5%) when Groww gives bid/ask, |delta| >= 0.25 when buying (<= 0.6 when writing) when Groww gives a delta. **A value that is not available is recorded as "not available" and skipped, never guessed.** Replay has stored open interest and volume but no bids, asks or Greeks.
- the paper risk calculation says TRADE (risk %, capital, daily loss limit, balance, lots).

## Managing the position
Stop-loss and target (target = `target_rr` x the stop distance, default 2), optional **trailing stop** (`trail_pct` from the best premium once the premium is `trail_activate_pct` in profit; it only ever tightens), **time exit** (`bias_max_hold_min`), **opposite-signal exit**, 15:00 square-off, daily loss limit, brokerage, taxes, STT, stamp duty, GST and slippage (`trading/charges.py`), gross and net P&L. Paper positions can be closed by hand, and the stop and target changed (stop changes are refused beyond the trade's risk amount; the target must stay on the profit side of the premium). Every stop change, trailing moves included, is recorded in `paper_stop_changes`.

## Continuous automation: 70% bias, ₹1,500 net profit per trade (20 Nov 2026)
Added to the same engine (no second engine). Paper and replay only; `trade_mode=live` is still refused. The page defaults are a **Market Bias threshold of 70%** and a **net profit target of ₹1,500 per trade** (`bias_min_confidence`, `profit_target_net`; the engine's own defaults stay 55 and 0 = off, only the Automated Paper Trading page and `GET /api/bias/config` carry 70 and 1,500).

**The loop** (each step is an existing rule unless marked new):
1. A completed 5-minute candle is analysed; the 15-minute trend must confirm (`bias_trend_thr`). Entry needs the bias confidence **at least** the threshold (inclusive: 70% qualifies, 69.99% does not; the log says "confidence X% is below your minimum 70%"). Bullish = BUY CE, bearish = BUY PE.
2. One position at a time, one entry per candle, inside the entry window, before 15:00, below the daily trade cap, passing the contract and paper risk checks (sizing, daily loss limit, minimum balance).
3. **New: the net profit target.** Every second the engine values the open position at the current premium **after slippage, brokerage, STT, exchange fees, SEBI fee, stamp duty and GST** (the same `charges.round_trip` that writes the trade). When that net reaches `profit_target_net` it exits with reason `profit_target`. A price older than 15 seconds never triggers it (the same stale-price rule as the stop). It is per trade, not a daily target, and the stop-loss, risk-reward target, trailing stop, opposite-signal exit, time exit, daily loss limit and 15:00 square-off all stay in force; whichever comes first ends the trade.
4. **New: after any exit the candle that contained the exit is closed to entries** (`_no_entry_through`): the next entry needs a candle that opened after the exit. Example: exit at 11:47 (inside the 11:45-11:50 candle) means the earliest next entry is the 11:55 candle (11:50 is skipped, with a log line saying so). The existing 2-candle cool-down after an opposite-signal exit still applies on top.
5. The candle after that is analysed again from scratch (nothing is carried over).
6. **New: re-entry after a profit-target exit.** A profit-target exit releases its signal, so an unchanged bullish signal that is still at or above the threshold may open the next trade on that fresh candle. After a stop-loss, time or opposite-signal exit the earlier rule still holds: the same unchanged signal does not re-enter until it lapses and forms again (this stops stacking after a loss).
7. Repeat until `max_trades_per_day` (default 20, a cap and never a target), the daily loss limit (state `halted`, no new entries) or 15:00.

**Pause / Resume / Stop** (`POST /api/bias/pause`, `/api/bias/resume`, `POST /api/live/stop`): Pause stops new entries only. The analysis, predictions and the management of an open position (stop, profit target, square-off) continue; nothing is closed. Resume allows entries from the next closed candle. Stop squares off and ends the session as before. Pause is held in memory: a restart starts a new session.

**What the page shows** (`bias.automation` in `GET /api/bias/status`): a phase and a plain sentence. `Ready for entry / Ready for re-entry`, `Holding a position`, `Exiting` (an exit is being retried or confirmed), `Waiting` (the exit candle, a cool-down, market closed or outside the entry window), `Paused`, `Daily limit reached`, `Halted`. Also the current bias against the threshold ("eligible for BUY CE" or "no entry"), the two editable numbers (applied to the running engine without a restart through `POST /api/bias/settings`), completed trades, profit-target hits, total trades and net paper P&L, the last exit with its reason, and on the open position the entry reason (the analysis summary), CE/PE, entry premium, live net P&L and how much of the target has been reached.

**Safeguards and recovery**
- The engine has no path to `LiveBroker`; `profit_target_net` only exists in the bias configuration, which refuses live mode.
- Stale or missing premium: an entry without a premium is refused ("the option premium is unavailable"); an exit rule never fires on a stale price; a failed exit is retried and halts the engine after five failures, as before.
- Restart: today's trades are read back from the database. The open position resumes with the same stop, risk-reward target and net profit target (the setting is in the new session's configuration). The candle of the latest exit stays closed to entries, the profit-target hit count is restored, and a profit-target exit still releases its signal. If the engine restarts after 15:00 the position was already squared off.
- Market close: the 15:00 square-off closes any position (reason `square_off`); candles after 15:00 are analysed and predicted only.

**Limits.** The net target is checked every second against the latest premium Groww gives; the paper fill is at the premium when the exit is sent, so the realised net can differ from the target by a tick or two (it was at or above the target when the decision was made). The target does not change the analysis, which shows no edge (validation above): a ₹1,500 target caps the winners and the stop-loss still takes the losers, and **nothing here makes the strategy profitable or guarantees any result**. The confidence figure is indicator agreement, not a probability of winning. Verified on stored and synthetic candles and in unit tests; **not verified in a live market session**.

## Confluence strategy: FVG + VWAP + ADR + EMA + market structure (21 Nov 2026)
An **opt-in entry strategy of the same engine** (`entry_strategy="confluence"`; the default stays `bias`). Module `services/strategy/confluence.py` (pure, closed candles only), studies in `services/strategy/indicators.py` (`fvg_zones`, `adr`, `swing_structure`). Paper and replay only: it lives inside bias mode, which refuses `trade_mode=live`. Only the **entry decision** differs; position sizing, stop-loss, risk-reward target, the net profit target, the exit-candle rule, cool-down, pause, the daily loss limit, charges and the 15:00 square-off are the existing code, not a copy. The bias analysis keeps running beside it, so predictions and their accuracy are unchanged.

**Factors.** Four factors vote from -1 (bearish) to +1 (bullish) on each closed 5-minute candle; a vote is the full value only when the condition is confirmed (a half vote means "leaning this way"). Weights are all 1.0, fixed before any result was seen.
| Factor | +-1 (confirmed) | +-0.5 (leaning) |
|---|---|---|
| EMA trend | EMA 9 > 21 > 50 and the close beyond EMA 21 | EMA 9 vs 21 and the close beyond EMA 21 only |
| VWAP (futures, on the index's scale) | a retest or a rejection of VWAP held in that direction | the close is on that side, 0.1 ATR away or more |
| Fair value gap | a retest of an unfilled or mitigated gap confirmed on this candle | the newest active gap is in that direction and waits for a retest |
| Market structure | higher highs and higher lows (or lower / lower) from confirmed swings | a recent break of structure while the swings are mixed |

**Fair value gap** (`indicators.fvg_zones`). Bullish: candle 3's low is above candle 1's high; bearish: candle 3's high is below candle 1's low. The gap is known when candle 3 closes, only gaps of at least `cf_fvg_min_atr` x ATR (default 0.1) count, and a gap lives for the session and `cf_fvg_max_age` candles (default 24). Status after each later candle: **unfilled** (price has not traded back into it), **mitigated** (price traded into it but not through it), **filled** (traded through the far edge: finished). A **retest** is a candle that enters an unfilled or mitigated gap, holds it (does not trade through it) and closes back out of it in the gap's direction on a candle of that colour.

**VWAP** (`confluence.frame`; the retest geometry is the one `entries.py` already used, moved into `entries.vwap_geometry` with identical output, checked before and after). *Retest*: the close was far (0.75 ATR) on one side in the last six candles, is now within 0.25 ATR and the candle closes back in the trend's colour. *Rejection*: the previous close was on that side, this candle's wick touched VWAP (within 0.1 ATR), the close is back on that side and the candle has that colour.

**ADR** (`indicators.adr`). Average Daily Range (high - low) of the previous 5, 10 and 20 completed sessions, today never in its own average, and today's range so far as a percentage of each. It is a filter, not a direction: with the ADR filter on, an entry is refused once today's range has used more than `cf_adr_max_used` % (default 100) of the chosen ADR (default 10 sessions). Too few sessions: "not checked", never guessed.

**Market structure** (`indicators.swing_structure`). A swing high/low has the highest high / lowest low of the 2k+1 candles around it (k = 3), so it is only known 3 candles after it formed and is recorded then (the rule the RSI divergence already used). Higher highs and higher lows give +1, lower and lower -1, otherwise 0; a close through the latest swing is a break of structure, remembered for six candles.

**Decision.** The factors point to a direction (the sign of the weighted vote). The **confirmation score** is the weighted share of the enabled factors that agree with it (a half vote counts half). An entry needs **all** of: score at least `cf_min_score` (default 75%); every factor in `cf_require` fully confirmed; the closed 15-minute trend (EMA 20/50) not against the trade (`cf_htf`); the ADR not used up (`cf_adr_filter`); and the same minimum volatility (`bias_min_atr_pct`) as the bias engine. A factor with missing data (no futures candles for VWAP, too few swings) is left out of the score and shown as n/a. When no entry is taken the reasons are listed in the log, on the page and in the stored analysis. The confirmation score is stored as the trade's `confidence`; the trade's `analysis.confluence` holds every factor, value, condition and gate as they were when it was taken. After an entry the usual rules apply: one position at a time, one entry per signal run, an opposite confluence signal exits, and a profit-target exit releases its signal.

**Settings** (page and `POST /api/bias/settings`, applied to a running engine without a restart): `entry_strategy`, `cf_factors` (which factors are on), `cf_require`, `cf_min_score`, `cf_adr_filter`, `cf_adr_period` (5, 10 or 20), `cf_adr_max_used`, `cf_fvg_min_atr`, `cf_fvg_max_age`, `cf_htf`. Invalid values are a 400 and change nothing.

**Page** (`/app/auto`, "Confluence strategy"): the strategy switch and filters; for each factor an On and a Required box, its vote, its status and the condition on the latest candle; the confirmation score against the minimum; the bullish and bearish gap (levels, status, age, retest); the 5/10/20-day ADR and today's range used; and "Why no entry" or "All conditions met". A trade's reasoning dialog shows the factors, score and ADR it was entered on. Before the engine starts it previews the latest candle with the settings you have chosen (`GET /api/bias/analysis` with the `cf_*` query parameters); the top automation panel shows the score threshold instead of the bias threshold while the strategy is on.

**Validation (21 Nov 2026, `scripts/research_entries.py confluence`): no edge.** Five years of NIFTY candles, real 1-minute option premiums, slippage and the full charge stack, four fixed exit rules, train 2022-23 / validation 2024 / out-of-sample 2025-Nov 2026, nothing tuned after seeing a result. **0 of 12** method and exit pairs (confluence, FVG retest, VWAP rejection) were positive in all three periods; none was positive in any of them. Confluence: 2,360-3,191 trades per exit rule, win rate 33-40%, net -₹4.8 to -6.1 lakh per exit rule (1 lot, overlapping streams), out-of-sample -₹1.9 to -2.5 lakh. Mean gross per trade about -₹10 against about ₹188 of costs per round trip, the same finding as the earlier 22 methods ([ENTRY_RESEARCH.md](ENTRY_RESEARCH.md)). The strategy is built and tested as asked; **it should be treated as a way to watch FVG, VWAP, ADR, EMA and structure agree, not as something that makes money.** Not verified in a live market session.

## Entry strategy `configured` (Trading Settings, 21 Nov 2026)
A fourth entry strategy of the same engine (`entry_strategy="configured"`, paper and replay only): the signals come from every strategy that is ON in [Trading Settings](TRADING_SETTINGS.md) and the timeframes, indicator parameters, risk, stop, target, trailing, trading window, re-entry and limits are read from the saved settings on every tick (a change applies to the next candle, no restart). Every order records the settings version, the strategies that fired, the timeframes and the enabled indicators. The other entry strategies are unchanged but are also gated by the ON/OFF switches, the timeframes and the indicators.

## Scored strategy: market structure + EMA + VWAP + FVG + ADR, points out of 100 (21 Nov 2026)
A second opt-in entry strategy of the **same engine** (`entry_strategy="scored"`; default `bias`), next to the equal-weight confluence strategy above. Module `services/strategy/confluence.py` (`ScoredParams`, `sc_decide`, `sc_explain`), same studies and closed-candle rule. Paper and replay only (it lives inside bias mode, which refuses `trade_mode=live`). Only the entry decision differs: sizing, stops, the net profit target, the exit-candle rule, pause, the daily loss limit, charges and the 15:00 square-off are the existing code.

**Timeframes.** Entry candle 5 minutes (`timeframe`), trend confirmed by the closed 15-minute candle (`bias_confirm_tf`); the engine also runs 15-minute entries confirmed by 30 minutes, and the backtest tests the two configurations separately. Optional higher-timeframe context (`sc_ctx_tf` = 30 or 60, off by default): that trend must not be against the trade. **A 1-minute entry refinement is not implemented** (the engine decides on closed 5/15-minute candles and fills at the next price).

**Indicators.** EMA 20/50/200, session VWAP (futures, on the index's scale), RSI 14, MACD 12/26/9 (histogram), ATR 14, volume against its 20-bar average (futures volume), 3-candle FVG, ADR over the last 10 sessions (`sc_adr_period` 5, 10 or 20).

**Points (a candle is scored for each side; the leading side is the candidate).**
| Component | Max | Earned when |
|---|---|---|
| Market trend | 25 | 15 for the confirmation-timeframe trend agreeing (EMA 20/50 on its closed candles) + 10 for the 5-minute structure (higher highs and lows, or lower and lower; 5 for a recent break of structure while the swings are mixed) |
| EMA 20/50/200 | 15 | 15 stacked in order with the close beyond EMA 20; 8 for EMA 20 beyond 50 and the close beyond EMA 20 |
| VWAP | 20 | 20 for a retest or rejection of VWAP held on that side; 12 for the close on that side by 0.1 ATR or more |
| Unmitigated FVG retest | 20 | a gap in that direction, not touched since it formed, whose **first return** enters it, holds it and closes back out in its direction on a candle of that colour |
| Momentum | 10 | 5 for RSI on that side of 50 (and not beyond 75 / 25) + 5 for the MACD histogram on that side |
| Volume | 5 | volume at least its 20-bar average |
| ADR | 5 | today's range has used no more than `sc_adr_max_used` % (default 100) of the ADR |

**Entry.** Every gate AND a total of at least `sc_min_score` (**80**, experimental): the confirmation trend agrees; EMA aligned; VWAP aligned (it needs futures candles: without them the strategy cannot trade); an unmitigated FVG retested and closed out; momentum agrees (at least one of RSI, MACD); the ADR not used up (not checked when fewer than N sessions exist); enough volatility (`bias_min_atr_pct`); **no conflicting signal** (opposite structure, both RSI and MACD against, or an opposite gap retest on the same candle); the optional context not against. A candle that fails any of them is a HOLD with every reason listed. Missing data scores 0 and is flagged, never guessed. No trade is forced to reach a count; the daily cap is a limit.

**Risk (the specified preset, one click on the page, never forced; `GET /api/bias/config` -> `presets.scored`).** 0.5% of virtual capital per trade, ATR stop (delta x 1.0 x NIFTY ATR), **2R target** (`target_rr`), daily loss limit 1.5%, at most 5 trades a day, one open position, paper only. **Option premium validation:** before anything is opened (paper and replay) the stop the engine will use must be 5% to 50% of the premium (`sc_stop_min_pct`, `sc_stop_max_pct`); otherwise the trade is refused with the reason and the check is part of the trade's record. Without a known delta the percentage stop is used and is validated the same way.

**Dashboard (`/app/auto`).** The Entry strategy switch; a Scored strategy panel with its settings and the risk preset button, the score out of 100 (and the long and short scores), each component's points and what the candle shows, every gate with the reason it failed, the near-miss **rejected signals** (a candidate scoring at least 80% of the minimum that was refused, with its reasons; `bias.rejected` in the status), and the score of every trade in its reasoning dialog with entry and exit reasons. Performance is reported **per entry strategy** (`by_strategy` in `GET /api/bias/summary`: trades, win rate, net expectancy per trade, profit factor, maximum drawdown, net), never pooled with another strategy's. Before the engine starts the panel previews the latest candle (`GET /api/bias/analysis?entry_strategy=scored&sc_...`).

**Settings** (`POST /api/bias/settings`, live): `entry_strategy`, `sc_min_score`, `sc_adr_period`, `sc_adr_max_used`, `sc_fvg_min_atr`, `sc_fvg_max_age`, `sc_ctx_tf`, `sc_stop_min_pct`, `sc_stop_max_pct`. Invalid values are a 400 and change nothing.

**Validation (21 Nov 2026): no edge.** Real 1-minute CE/PE premiums, NSE lot size per expiry, slippage, brokerage and the full charge stack, 1 lot, ATR stop validated against the premium, 2R target, held to 15:15 at most; the **same simulator, window and exit** for the seven existing strategies and the scored one, 5-minute and 15-minute entries separately; train 2022-23, validation 2024, out-of-sample 2025 to Nov 2026 (125,046 trades, 80 strategy x exit pairs; [ENTRY_RESEARCH.md](ENTRY_RESEARCH.md)).
| ATR / 2R exit | Trades | Win | Net | Expectancy per trade | Profit factor | Max drawdown | Train / validation / out-of-sample net |
|---|---|---|---|---|---|---|---|
| Scored, 5m entries | 379 | 27.2% | -₹97,628 | -₹258 | 0.51 | ₹99,500 | -₹26,580 / -₹14,457 / -₹56,591 |
| Scored, 15m entries | 108 | 31.5% | -₹28,503 | -₹264 | 0.61 | ₹32,199 | -₹7,144 / +₹470 (20 trades) / -₹21,830 |
| Seven existing, 5m (pooled) | 18,710 | 33.1% | -₹34.6 lakh | -₹185 | 0.64 | | all negative |
| Seven existing, 15m (pooled) | 6,395 | 36.5% | -₹10.8 lakh | -₹168 | 0.78 | | all negative |
**0 of 80** pairs were positive in all three periods. The scored strategy was negative in every calendar year from 2023 on (5m: -₹9k, -₹18k, -₹14k, -₹29k, -₹28k for 2022-26), in trending (-₹229 a trade), sideways (-₹310) and high-volatility (-₹328) markets, and in 49 of 60 months (5m). Its 2R target was reached by 102 of 379 trades and its stops by 264; the average trade lost 0.52 R. A **train-only** search over a grid fixed beforehand (minimum score 70/80/90 x stop 0.75/1.0/1.5 ATR, 18 cells) found **no cell with positive expectancy even in the training period**; the least-bad cell, tested afterwards, was also negative out of sample (5m -₹29,029, 15m -₹30,841). Nothing was tuned on validation or out-of-sample data and the specified defaults were kept. The one positive cell anywhere (15m validation, +₹470 over 20 trades) is noise. **The strategy is built, configured and tested as asked; it has not shown any edge, and a score of 80 is a count of conditions met, not a probability of winning.** Prediction accuracy is not a profitability claim. Not verified in a live market session.

**Limits.** Research assumes an ATM delta of 0.5 for the ATR stop (Greeks are not stored historically; the live engine uses the real delta); the research exit has no opposite-signal exit and uses 1-minute candle fills (a stop and a target on the same candle assume the stop first); sizing in the backtest is 1 lot, so drawdown is in rupees at one lot, not at 0.5% risk. In the live engine the 15:00 square-off, the opposite-signal exit and the daily limits apply as for the other strategies.

## Settings (page and API)
Everything above is a setting. While the engine runs, **Apply** changes it at once, without a restart (`POST /api/bias/settings`; the whole new configuration is validated first, a bad value changes nothing). Not changeable while running: the analysis interval (applies from the next start), trade mode. The page remembers its settings in the browser (`gt.auto.settings`).

## Dashboard
Directional bias and confidence, 15m and 5m trend, next-candle prediction, signal, every indicator's vote on both timeframes, daily trade count and remaining limit, wins, losses, win rate and net P&L, the active position (entry, stop, target, quantity, open P&L), the day's orders (click one for its **complete reasoning**: why it was entered, supporting and opposing indicators, contract checks, every strategy's vote at entry, the risk calculation, every stop change, why and how it ended), predictions versus actual candle results, accuracy per strategy and per timeframe, a performance breakdown (instrument, exit reason, confidence band, supporting indicator) and the engine log.

## API (`api/bias.py`)
| Route | Purpose |
|---|---|
| GET `/api/bias/config` | Defaults, indicator list, running settings |
| GET `/api/bias/status` | Engine state, latest analysis, history, position, counters, events |
| GET `/api/bias/analysis` | The bias now (or at the last close) from stored and live candles, engine running or not |
| POST `/api/bias/start` | `{trade_mode: "paper" or "replay", config, replay_day}`; anything else is a 400 |
| POST `/api/bias/pause`, `/api/bias/resume` | Stop / allow new entries (an open position is still managed) |
| GET `/api/bias/analysis?entry_strategy=scored&sc_min_score=80&sc_adr_period=10...` | The latest candle with the scored strategy previewed under the given settings (`analysis.scored`); `bias.rejected` in `/api/bias/status` lists its refused near misses |
| GET `/api/bias/analysis?cf_factors=ema,vwap&cf_min_score=80...` | The latest candle with the confluence factors previewed under the given settings (a running engine uses its own) |
| POST `/api/bias/settings` | Change the running engine's settings |
| POST `/api/paper/position/target` | Change the open position's target |
| GET `/api/bias/predictions`, `/accuracy`, `/history-accuracy`, `/trades`, `/summary`, `/trade/<id>` | Reports (paper and replay rows only) |

Stop, square-off and the stop-loss edit reuse `/api/live/stop`, `/api/live/squareoff` and `/api/paper/position/stop`.

## Validation (19 Nov 2026, real stored candles, nothing fitted)
Defaults were fixed before any result was looked at. Scripts: `scripts/validate_bias_accuracy.py` (read-only) and `scripts/validate_bias_trades.py` (replays into a scratch database that is dropped afterwards).

**Next-candle prediction, 1,206 sessions (3 Jan 2022 - 18 Nov 2026), 65,270 calls out of 88,998 candles:** combined hit rate **50.9%** (95% interval +-0.4); by year 50.9, 50.9, 50.7, 51.0, 50.9. The market closed up on 50.5% of candles. Each indicator alone is between 49.1% (MACD, 5m) and 51.0% (EMA 9/21, 15m). This is a coin flip, in line with the earlier next-candle forecast (51.4%). The 15-minute votes are about half a point better than the 5-minute ones.

**Entry candidates (before the one-position rule):** 48.8 a day; after 15 minutes the spot price had moved in the signal's direction by a mean of 0.53 points (ATR is 21), positive 51.6% of the time (2022-2026: 52.3, 52.2, 51.0, 51.3, 51.1%). Higher confidence did not help (51.0% in the lowest band, 51.7% in the highest).

**Trades with real option premiums, replayed through the engine (1 lot, paper broker with slippage and the full charge stack, ATM buy, 30% premium stop, target 2x, opposite-signal and 15:00 exits, buying only):**

| Window | Sessions | Trades | Win rate | Gross | Slippage | Charges | **Net** | Max drawdown |
|---|---|---|---|---|---|---|---|---|
| 1 Oct - 12 Nov 2026 | 28 | 43 (1.5 a session) | 48.8% | +₹13,185 | ₹7,326 | ₹3,071 | **+₹2,789** | ₹26,620 |
| 1 Jul - 30 Sep 2026 | 65 | 95 (1.5 a session) | 34.7% | −₹16,302 | ₹13,562 | ₹6,140 | **−₹36,004** | ₹52,052 |

Reading it honestly: the longer window **lost ₹36,004 net (−₹379 a trade) and was already negative before costs (−₹16,302 gross)**; its stop-loss exits (25 trades) cost ₹63,942 and its targets (12 trades) earned ₹51,988. The shorter window made a small net gain, but costs took about ₹10,400 of its ₹13,185 gross and 43 trades cannot tell that apart from zero. Together: 93 sessions, 138 trades, **net −₹33,215**. The next-candle hit rates in the two windows were 54.3% and 50.5% (the first is noise-sized: 1,481 calls, ±2.5 points). **No result here supports calling the system profitable; the larger sample says it loses after costs.** Walk-forward threshold tuning was not done on purpose: with no edge in the unconditional hit rate, tuning thresholds on these candles would only fit noise.

## Limits and known gaps
- Replay has no bids, asks or Greeks and no capital-based sizing (fixed lots); paper mode with Groww connected checks them when Groww provides them.
- Open interest, spread and Greeks checks and the 1-second premium stop were verified in tests and replay, **not in a live market session** (the market was closed during the build; see [TODO.md](TODO.md)).
- The 5-minute and 15-minute votes are slot names in the data (`v5`, `v15`, `score_5m`, `score_15m`); they hold the analysis and confirmation timeframes whatever you choose, and the page labels them with the real minutes (`tf_primary`, `tf_confirm`).
- "Strategy-wise performance" attributes a trade to every indicator that supported it at entry. Several indicators share each trade, so those rows describe, they do not prove.
- Prediction accuracy mixes sessions run with different settings when settings change between runs.

## Tests
`backend/tests/test_bias.py` (look-ahead and repainting checks, 5m/15m synchronisation, every indicator alone and combined, every timeframe pair, labels, confidence, accuracy), `test_bias_engine.py` (replay: every candle stored and settled once, daily cap, one entry per signal, enabled instruments, writing, time exit, trailing stop, target and stop for buy and sell, stale price, settings without restart, contract checks), `test_bias_api.py` (paper/replay only, settings, reports, the 70% / ₹1,500 defaults, pause and resume), the continuous-automation tests at the end of `test_bias_engine.py` (net profit target on the sell and buy side, net not gross, stale price, exit candle blocked, release after a target hit, pause, phases, restart recovery, daily loss limit, 70% threshold on replayed days, sequential trades) and `test_bias.py` (the inclusive threshold), `test_confluence.py` (FVG incl. the first-return rule, ADR, structure, VWAP events, both strategies: hand-built bars and one-row frames for every point and gate, causality and repainting on 5m and 15m, rejections, missing data, the premium stop validation, per-strategy statistics), the confluence tests at the end of `test_bias_engine.py` (replay, validation, live settings, status) and `test_bias_api.py`; `frontend/src/__tests__/pages/auto-trading.test.tsx`; Playwright (`/auto` at eight widths, navigation, privacy). Counts are in [TESTING.md](TESTING.md).

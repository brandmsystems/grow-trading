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
`backend/tests/test_bias.py` (look-ahead and repainting checks, 5m/15m synchronisation, every indicator alone and combined, every timeframe pair, labels, confidence, accuracy), `test_bias_engine.py` (replay: every candle stored and settled once, daily cap, one entry per signal, enabled instruments, writing, time exit, trailing stop, target and stop for buy and sell, stale price, settings without restart, contract checks), `test_bias_api.py` (paper/replay only, settings, reports, the 70% / ₹1,500 defaults, pause and resume), the continuous-automation tests at the end of `test_bias_engine.py` (net profit target on the sell and buy side, net not gross, stale price, exit candle blocked, release after a target hit, pause, phases, restart recovery, daily loss limit, 70% threshold on replayed days, sequential trades) and `test_bias.py` (the inclusive threshold); `frontend/src/__tests__/pages/auto-trading.test.tsx`; Playwright (`/auto` at eight widths, navigation, privacy). Counts are in [TESTING.md](TESTING.md).

# Continuous opportunity scanner and concurrent paper positions (26 Nov 2026)

*Built at the user's request. Paper and replay only: the scanner is an entry strategy (`entry_strategy="scanner"`) of the existing bias engine, which refuses `trade_mode=live`. It has no path to `LiveBroker`. The default entry strategy stays `bias`.*

> **Read this first.** Every strategy tested on five years of real option premiums, with full costs and a train / validation / out-of-sample split, lost money after costs ([ENTRY_RESEARCH.md](ENTRY_RESEARCH.md): 0 of 92, 0 of 12 and 0 of 80 strategy x exit pairs were positive in all three periods; mean gross per trade about -₹4 to -₹10 against about ₹189 of costs per round trip). More trades means more round trips, not more profit. So the scanner is built to be **safe and honest, not to promise profit**: strategies with a negative or missing validated result are labelled so and **trade only if you allow them**.

## What it does
1. **Scans every closed candle** (5 minutes by default; 15 is allowed) with the closed 15-minute trend confirming the direction. Closed candles only.
2. **Evaluates every strategy that is ON in [Trading Settings](TRADING_SETTINGS.md) on its own.** Strategy signals come from `strategy/configured.py` (the same code the `configured` entry strategy uses: the seven EMA crossovers incl. 9/21, 5/20, 8/21, 9/21 + VWAP, bias votes, confluence, scored, and the research methods: MACD, Bollinger, VWAP, support/resistance breakout, volume momentum, ORB, RSI divergence, trend reversal, ...). Nothing is recomputed in the scanner.
3. **Scores each signalling strategy 0-100** (below) and ranks them by score, then by validated record.
4. **Takes every opportunity that every rule allows**, in rank order, each as its own paper position with its own stop, target, trailing stop, time exit and charges.
5. **Does not force trades:** no signal, no trade. Rejected signals are listed with the exact reason.

## Quality score (0-100, transparent)
A count of sound conditions met. **It is not a probability of winning.** A missing value earns 0 points and is flagged, never guessed. The score and all ten components are stored with every trade (`analysis.quality`) and shown on the page.

| Component | Max | Earned when |
|---|---|---|
| Trend confirmation | 15 | the closed 15-minute score points the trade's way (full at +-0.5) |
| Entry signal quality | 15 | 8 for the strategy's own signal + up to 7 for the share of enabled indicator votes that agree |
| VWAP / EMA alignment | 10 | VWAP vote 5 + EMA 9/21 and 20/50 votes 5, aligned |
| RSI / MACD confirmation | 10 | RSI vote 5 + MACD vote 5, aligned |
| Volume confirmation | 5 | futures volume expansion in the trade's direction |
| Market structure / support-resistance | 10 | the support/resistance and structure vote aligned (FVG scores inside the Confluence and Scored strategies, not here) |
| Option liquidity and spread | 10 | premium 3 + open interest 4 + bid-ask spread 3, each against your limits (unknown = 0, flagged) |
| IV and Greeks validation | 5 | delta available and inside the allowed range (the data source gives no IV: noted) |
| Historical out-of-sample result | 10 | the strategy's validated record (`strategy/evidence.py`): negative 0, insufficient 3, positive 10 |
| Risk/reward after costs | 10 | net reward at the target against net loss at the stop, both after brokerage, taxes and slippage: 2.0 or better earns 10 |

The candle part (65) plus the validated record (10) is known when the candle closes and ranks the opportunities; the contract-dependent part (25: liquidity, Greeks, reward/risk) is added when the contract is looked up, and the entry needs the **final** score to reach `scan_min_quality` (default 55, a fixed starting value, never tuned to results). A perfect setup with unknown spread and Greeks therefore cannot reach 100.

## Validated record (`strategy/evidence.py`)
Every registered strategy is **negative** today, with the reason and numbers shown on the page: bias -₹33,215 over 138 replayed trades; confluence 0 of 12 pairs positive, out-of-sample -₹1.9 to -2.5 lakh; scored -₹97,628 over 379 trades, out-of-sample -₹56,591; every other method is covered by the 92-pair research. By default only a validated-positive strategy trades, **which means the scanner takes no trade until you tick "Also trade strategies without a validated positive result"** (`scan_allow_unvalidated`, paper research use). That is a deliberate safety default, not a fault.

## Concurrent positions and risk (all configurable; Trading Settings and the page)
| Setting | Default (scanner preset) | Meaning |
|---|---|---|
| `max_open_positions` | 3 (1 elsewhere) | positions open at once across all strategies (1-20) |
| `max_strategy_positions` | 1 | positions one strategy may hold at once |
| `max_open_risk_pct` | 3.0 | sum of every open position's maximum loss, % of virtual capital (0 = off) |
| `max_strategy_risk_pct` | 1.5 | open risk one strategy may hold, % of capital (0 = off) |
| `risk_pct` | 0.5 on the preset | maximum loss of one trade, % of capital (sizes the lots) |
| `daily_risk_pct`, `max_daily_loss` | **0, 0 = off** (26 Nov, at the user's request) | an optional daily loss limit (realised + open): when set and hit, every position is squared off and entries stop. Off by default: a good entry is taken whenever it comes, so a bad day is bounded only by the per-trade risk, the open-risk limits and the 15:00 square-off |
| `scan_min_quality` | 55 | final quality score needed |
| `max_trades_per_day` | **0 = no count cap** | optional; the risk limits bound the day, not a trade count |

Virtual capital is the paper account (reset on the Account page). Each entry is sized by `sizing.risk_size` against the **capital left after every open position** (`paper_account.state(positions=...)`), then must also pass the daily-loss room, the total and per-strategy open-risk limits and the position counts. **No limit was removed to increase trade frequency:** the stop-loss, the risk-per-trade sizing, the daily loss limit, the minimum premium / open interest / spread / delta checks, the 15:00 square-off and the stale-price rule are all unchanged.

**No hedging against yourself:** a signal opposite to any open position is refused ("opposite to the open position of ..."); strategies that disagree on one candle are all refused as a conflict.

## Unlimited daily trade count, safely
`max_trades_per_day = 0` removes only the count cap (the page default is now 0; it was 20; Trading Settings still defaults to 6 for the `configured` strategy and accepts 0 to 1,000). What bounds the day instead: the position and risk limits above, the daily loss limit if you set one, one entry per strategy per signal episode, the exit candle being closed to that strategy, a cool-down after an opposite-signal exit, the entry window and the 15:00 square-off. A count cap still works when you set one.

## Duplicates and re-entry
- An order is keyed by (signal candle, direction, strategy): one signal never orders twice (`Engine._ordered`), and a broker order id is unique per contract and side.
- **One entry per strategy per signal episode** (the unbroken run of candles with that strategy's signal). A new qualified signal is a new episode, so the strategy may enter again once it has lapsed and re-formed. Strategies are independent: one exiting does not close the candle to the others (`strat_block`, per strategy).

## Option contracts
Direction maps to an instrument with the existing `_bias_pick`: bullish = BUY CE, bearish = BUY PE (ATM or ITM5 by `exec_mode`); writing (SELL PE for bullish, SELL CE for bearish) only when buying that side is switched off in `bias_allow`, with its own smaller `sell_risk_pct` and a stop above the premium. The page marks buying (loss limited to the premium) and writing (margin and a stop apply) separately. Premium, open interest, spread and delta checks use real quotes; a value the source does not give is recorded "not available" and skipped. The simulated fill is the **real option premium**; the NIFTY spot is never used as a premium. Option writing was not validated by the research and stays off by default.

## Safety and recovery
- Paper and replay only; `EngineConfig._validate_bias` refuses `live`; the scanner adds no order path.
- **Restart:** every open position of today is restored from `live_trades` (each with its own stop, target and strategy), each strategy's latest entry (no signal traded twice) and each strategy's exit candle are rebuilt; the 15:00 square-off and daily loss limit continue to apply. Stale open trades from an earlier day are marked closed as before.
- Exits are per position: a failed exit retries and halts after five failures **for that position**; an unconfirmed order halts the engine (no automatic orders while the outcome is unknown); the daily loss check squares off every position.
- Missing candles, a disconnected feed and a stale option price never trigger an exit or an entry (unchanged rules).
- Replay keeps working (the scanner runs in replay with fixed lots; the money-based open-risk limits apply to paper only, since replay has no capital sizing).

## Page (`/app/auto`, entry strategy "Scanner")
Start / Pause / Resume / Stop (existing), scanning status (candles scanned, open positions of the maximum, open risk, trades today without a cap), active strategies with their validated-result label, the latest candle's opportunities (BUY / HOLD / REJECTED, action, expandable score components with reasons, validated result, reason), all open positions across strategies (strategy, CE/PE, buying or writing, quantity, entry, stop, target, risk, open P&L), rejected signals with the exact reason, filters (strategy, CE/PE, BUY/SELL, timeframe), the risk limits, and the existing completed trades and the per-strategy table (trades, win rate, expectancy, profit factor, max drawdown, net).

## Backtesting and validation
The scanner adds no new alpha, so its validation is the validation of its strategies, which already exists and is reproducible: `scripts/research_entries.py` (22 methods, confluence, scored and the seven crossovers; real 1-minute option candles, historical NSE lot sizes per contract, slippage and the full charge stack, four fixed exit rules, train 2022-23 / validation 2024 / out-of-sample 2025-Nov 2026, net, win rate, profit factor, expectancy and maximum drawdown per pair; nothing tuned after seeing a result). Results: [ENTRY_RESEARCH.md](ENTRY_RESEARCH.md) and [AUTO_TRADING.md](AUTO_TRADING.md). **None is positive; the scanner labels them so and does not trade them unless you opt in.** Multi-position portfolio behaviour (several strategies at once) was not backtested on five years: the research simulates one stream per strategy and exit rule, and combining them adds correlated losing streams, not an edge. Walk-forward re-fitting was not done on purpose: with no edge in any period it would only fit noise.

## Limits
- Not verified in a live market session.
- FVG scores only inside the Confluence and Scored strategies; ADR is a filter there, not a score component here.
- The data source gives no implied volatility; Greeks (delta) exist only in paper mode with Groww connected, not in replay.
- Replay has no bids, asks or Greeks, so liquidity and Greeks components earn fewer points there (flagged).
- Per-strategy sell/write is governed by the global `bias_allow` list (buying is preferred), not by a per-strategy switch.
- Strategy-wise statistics describe paper trades; a small sample says little.

## Tests
`backend/tests/test_scanner.py` (score adds to 100, missing data = 0 and flagged, reward/risk after costs, evidence labels, signal episodes, configuration, independent strategies with capped concurrency and no duplicate signals, negative strategies not traded by default, quality floor with exact reasons, one position behaves as before, no daily count cap, no hedging, restart recovery of every position, total and per-strategy risk limits, paper only), the regression suites for the engine, paper risk, Trading Settings and the API, and `frontend/src/__tests__/pages/scanner-panel.test.tsx`.

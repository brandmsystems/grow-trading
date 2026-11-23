# Trading Settings (21 Nov 2026)

One centrally managed, persisted configuration for the paper-trading engine: **which strategies may signal, which timeframes and indicators take part, and the paper-trading rules.** Page: **Trading Settings** (`/app/trading-settings`). Service: `services/trading/trading_settings.py`. API: `api/trading_settings.py`. Signals: `services/strategy/configured.py`. Table: `trading_settings` (migration `0021_trading_settings.sql`).

**Paper and replay only.** Nothing here places an order, nothing here can reach `LiveBroker`, and the API returns no balance, funds, positions, order ids or real trades.

## What is controllable
**Strategies (32, each with an ON/OFF switch and editable parameters).**
| Group | Strategies | Parameters | Needs (indicators that must be ON) |
|---|---|---|---|
| EMA crossovers (7) | EMA 9/21, 5/20, 8/21, 20/50, 9/21 + VWAP, 9/21 + RSI, 9/21 + MACD | fast and slow EMA | EMA (+ VWAP / RSI / MACD for the confirmed ones) |
| Bias votes | the 12-indicator weighted vote | minimum confidence, trend and entry-candle thresholds | at least one indicator that owns a vote; a disabled indicator's votes are removed |
| Confluence | FVG + VWAP + ADR + EMA + structure | minimum score, trend timeframe must not be against | at least one of EMA, VWAP, FVG, structure; each is a factor only while ON; the ADR filter only while ADR is ON |
| Scored | structure + EMA + VWAP + FVG + ADR, points out of 100 | minimum score, context timeframe, stop range | all of EMA, VWAP, RSI, MACD, volume, FVG, ADR, ATR, structure (every one is scored) |
| Research methods (22) | the entry methods of `entries.py` | none (fixed rules) | per method (for example Bollinger methods need Bollinger) |
New strategies added to the registry (`trading_settings.STRATEGIES`) appear on the page automatically. Every existing strategy is ON by default; the 22 research methods are OFF (the five-year research found none profitable).

**Timeframes.** 1, 5, 15 and 30 minutes, each ON/OFF. Roles: **trend confirmation** (15 or 30), **entry signal** (5 or 15), **exit confirmation** (the entry timeframe's opposite signal, or the trend timeframe turning against the trade), plus a switch for the trend filter on crossovers and research methods. Only enabled timeframes can be used; a role that points at a disabled timeframe is a validation error.

**Indicators (11, ON/OFF with parameters).**
| Indicator | Parameters | Where it takes effect |
|---|---|---|
| EMA | periods are per strategy (above) | crossover strategies; the bias, confluence and scored strategies use a fixed 20/50/200 set |
| VWAP | none | VWAP vote, confluence and scored VWAP factor, VWAP-confirmed crossover, research methods |
| RSI | period, overbought, oversold | RSI vote, scored momentum (counted inside the limits), RSI-confirmed crossover |
| MACD | fast, slow, signal | MACD vote, scored momentum, MACD-confirmed crossover |
| Bollinger Bands | period, standard deviations | Bollinger vote, Bollinger research methods |
| Volume / Volume SMA | SMA period | volume vote, scored volume points |
| FVG | smallest gap (x ATR), tradable age | confluence and scored |
| ADR | sessions (5/10/20), no entry once used (%) | confluence filter, scored points |
| ATR | period | every ATR use: volatility filter, ATR stop, scored, research methods |
| RSI divergence | pivot bars, valid bars | RSI-divergence vote, research method (needs RSI) |
| Market structure / Support & resistance | swing pivot bars | structure vote and factor, previous-day high / low votes and methods |
A disabled indicator **does not affect any score, filter or entry**: its votes and factors are removed, and a strategy that needs it is **blocked** (shown on the page, never run without it).

**Rules.** Minimum confidence / signal score (a floor on every score threshold), maximum trades a day, maximum open positions (this engine holds one), stop (ATR x delta, percentage of premium, or premium points), target (x the stop distance) and an optional net profit target per trade, risk per trade (% of virtual capital), trailing stop and its activation, trading window start and end, re-entry (allowed or one trade a day, and the cool-down in candles), daily loss limit (% of the day's starting capital and rupees).

## How the settings drive paper orders
1. **Every order of every mode** (crossover, trend, prediction, scalp, bias) passes `Engine._try_entry`, which first calls `Engine._settings_gate`. An order is refused (and logged with the reason) unless: the saved settings are valid and readable; a strategy is behind the signal; **every such strategy is ON**; none of the indicators it needs is OFF; and **the engine's timeframe is enabled**. Everything else (position open, daily cap, contract and risk checks, one order per candle) then applies as before.
2. **Entry strategy `configured`** (Automated Paper Trading page, bias mode): the signals come from the strategies that are ON (`configured.evaluate`), at the entry timeframe, confirmed on the trend timeframe. A strategy that is OFF or blocked is never evaluated. Signals in the same direction on one candle are one order, recorded with every strategy that fired; opposite directions on one candle are a conflict and no order is placed. Closed candles only, causal (a later candle never changes an earlier signal; tests check).
3. **Applied live.** A `configured` engine re-reads the saved settings on every tick (a one-second cache); when the version changes it applies the timeframes, indicator parameters, risk, stop, target, trailing, window, re-entry and limits to its own configuration (validated as a whole) and logs `Trading Settings version N applied`. No restart. An invalid configuration is refused (nothing changes) and blocks entries. The exit confirmation timeframe applies to the next candle.
4. **Every paper order records** `analysis.settings`: the settings **version**, saved time, the strategies that fired, the timeframes (entry, trend, exit, enabled) and the engine's own timeframe, and the **enabled indicators**; plus `analysis.strategy` and the entry reason (`analysis.summary`). The exit reason is the trade's `exit_reason`. Performance is reported per strategy (`by_strategy`).
5. **Fail closed.** Invalid stored settings (a hand-edited row), an unreadable table or a database that is down produce **no orders**; nothing is repaired or guessed.
**Defaults reproduce today's behaviour:** all existing strategies and the 5, 15 and 30-minute timeframes are ON, so engines started the old way keep trading exactly as before until you switch something OFF.

## Validation
Errors (cannot be saved, listed with the field): a value outside its bounds or of the wrong type, an unknown setting, fast EMA not shorter than slow, MACD fast not shorter than slow, an entry or trend timeframe that is disabled or not allowed, a trend timeframe that is not longer than the entry timeframe (and a multiple of it), no timeframe enabled, an ATR stop with the ATR indicator OFF, RSI divergence without RSI, trading end before start, scored stop range inverted. Warnings (can be saved; the engine just does not trade them): a strategy that is ON but blocked by a disabled indicator, no strategy ON, every ON strategy blocked, the 1-minute timeframe enabled (it cannot be used for entry, trend or exit in this engine).

## Persistence and the page
Append-only table `trading_settings(version, config JSONB, saved_at, note)`: every save (and every reset) is a new version, the current one is the highest, and an order's `analysis.settings.version` says which one it was placed under. With no row the code's defaults apply (version 0). Settings survive a page refresh and a server restart. The page shows the active configuration summary and the last saved time; has **Save settings** (validated, with a base-version check so a stale page cannot overwrite a newer save), **Discard changes**, **Reset to defaults** (asks first, saves a new version), **Enable all / Disable all** for strategies, indicators and timeframes, live validation messages next to the fields, blocked-strategy reasons, and an unsaved-changes warning (a banner, the browser's own warning on refresh or close, and a confirmation before an in-app link is followed).

## API
| Method | Path | |
|---|---|---|
| GET | `/api/trading-settings` | configuration, version, saved time, summary, warnings, defaults and the metadata the page draws from |
| POST | `/api/trading-settings/validate` | check a draft without saving: errors, warnings, cleaned configuration, summary |
| PUT | `/api/trading-settings` | `{config, base_version?}`: save as a new version; 400 with every problem, 409 if changed elsewhere |
| POST | `/api/trading-settings/reset` | save the defaults as a new version |

## Limits and what is not supported
- **1-minute timeframe:** can be switched ON, but cannot be the entry, trend or exit timeframe (the engine decides on closed 5- or 15-minute candles); there is no 1-minute entry refinement.
- **EMA periods** are configurable per crossover strategy only; the 20/50/200 set used by the bias, confluence and scored strategies and by the trend filter is fixed.
- **Maximum open positions** is 1 (the engine holds one position).
- **Backtesting** (the Backtest and Compare pages and the research scripts) names its strategies explicitly and is not gated by these switches; it does not read this configuration.
- **Engines started with another entry strategy** (bias, confluence, scored, or the crossover / trend / prediction / scalp modes) keep their own risk and indicator fields; the settings gate them (strategy ON, indicators ON, timeframe enabled, valid settings) and record the version, but only `configured` takes its risk, timeframes and indicator parameters from here.
- Research methods have fixed rules (no parameters). Nothing here changes the finding that no strategy tested has a demonstrated edge.

## Tests
`backend/tests/test_trading_settings.py` (registry coverage, defaults, validation, blockers for every strategy x required indicator, indicator and rule mapping, **every strategy at both entry timeframes**, parameter changes, causality, combination and conflict rules, persistence and restart, fail-closed, API), the Trading Settings tests at the end of `test_bias_engine.py` (an OFF strategy never orders, a disabled timeframe blocks, invalid settings stop everything, a configured engine trades only what is ON and records it, changes while running, exit confirmation) and `frontend/src/__tests__/pages/trading-settings.test.tsx`; Playwright (the page at eight widths, privacy).

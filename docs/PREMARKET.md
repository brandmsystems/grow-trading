# Pre-market analysis (19 Nov 2026)

Page **Pre-Market Analysis** (`/app/premarket`). Code: `services/premarket/` (`sources.py` the only network access, `scoring.py` pure rules, `service.py` build / store / settle / schedule / engine stamp), `api/premarket.py`, tables `premarket_reports` and `premarket_inputs` (migration `0020_premarket.sql`, new tables only). Frontend: `pages/PreMarket.tsx`, `components/premarket/` (`NewsFeed`, `ArticleCard`, ...), `utils/news.ts`. News analysis: `services/premarket/news_analysis.py`.

> **What it is.** Context for the morning, not a trade signal. The page cannot place an order. The engine may *read* the stored result (below); live entries still need a completed 5-minute candle signal and the 15-minute direction. The validation at the end shows the score reads the opening gap partly and says nothing reliable about the rest of the day.

## The five factors (+1 bullish, -1 bearish, 0 neutral; no data = 0 points and a flag)
| # | Factor | Data and source | Rule (fixed starting values, none fitted) |
|---|---|---|---|
| 1 | Global markets | S&P 500, Nasdaq, Dow, Nikkei, Hang Seng; Yahoo Finance (up to 15 min delayed) | average change of the available indices ≥ +0.40% → +1, ≤ -0.40% → -1; needs at least 3 of 5 |
| 2 | FII / DII | **entered by hand** from the NSE FII/DII report (NSE blocks scripts) | FII net cash ≥ ₹500 cr → +1, ≤ -₹500 cr → -1; index futures long share ≥ 55% → +1, ≤ 40% → -1; the two are added and limited to one point |
| 3 | Crude oil | Brent (WTI shown); Yahoo Finance | read inversely for India: Brent +1.0% or more (or +0.3% with a 5-day rise of 4%+) → -1; the mirror fall → +1 |
| 4 | India VIX | Yahoo Finance | change ≥ +5% → -1, ≤ -5% → +1; a fall from a level ≥ 22 scores 0 (still a high-risk market) |
| 5 | NIFTY structure | stored NIFTY 1-minute and futures candles, closed candles only | weighted vote: daily trend and indicators 35% (EMA 9/21/50/200, VWAP, RSI, MACD, Bollinger, volume, previous-day high/low via `strategy/bias.py`), 15-minute trend 35%, 3-session higher-high/low sequence 15%, opening gap 15% (only once today's first candle exists); score ≥ +0.20 → +1, ≤ -0.20 → -1 |

Total -5..+5: +4/+5 Strong Bullish, +2/+3 Bullish, -1..+1 Neutral / Mixed, -2/-3 Bearish, -4/-5 Strong Bearish. Preference: BUY CE at +2 or more, BUY PE at -2 or less, otherwise HOLD. "Factor agreement" is |total| / 5 (0 below ±2) and **is not a probability**.

## Conclusion contents
Direction, expected opening (from the global factor), CE/PE/HOLD lean, support and resistance (previous-day high/low, classic pivot with R1/S1, 20-day high/low, daily EMA 21/50/200), breakout and breakdown levels (previous-day high/low), risks (missing factors, disagreement, high VIX, expiry day, today's events) and an explicit reminder that live confirmation is required.

## News headlines in the report
Google News RSS searches (US markets, Asian markets, RBI, inflation, Fed, crude, FII/Nifty, geopolitics, the economy). Kept: headlines from a list of trusted outlets (`sources.TRUSTED`), relevant to markets, from the last 40 hours, never future-dated; near-duplicates (60% shared words) removed, newest first. Tone (positive / negative / neutral) is a word-list read of the headline only. Today's events: the weekly expiry (from the stored expiry list), events you type in, and headlines that mention something happening today, which are labelled "schedule unverified".

## News (live feed on the page, `GET /api/premarket/news`)
Real articles, readable on the page without leaving it: headline, the publisher's own summary, thumbnail, publisher, publication time, sentiment, expected NIFTY direction, impact level, why it matters, sectors and indices, and a "Read full news" link to the original.
- **Sources** (`sources.py`, the only network access): publisher RSS feeds of The Economic Times (markets, stocks, economy, commodities), Mint (markets, economy), Business Standard (markets, economy), The Hindu BusinessLine (markets, economy), BBC News (business) and CNBC (markets, economy, top news), plus Google News RSS searches (headline, outlet, time and link only; no summary or picture). Google items are kept only from the trusted-outlet list. Feeds are read in parallel (searches two at a time: Google answers 429 to a burst), cached for two minutes (`?refresh=1` skips the cache).
- **Never invented:** a missing summary or picture is shown as missing (a letter tile, "this publisher's feed gives no summary"); future-dated items are dropped; a feed that is dead or old simply contributes nothing. If every source fails the page says so (`status: unavailable`); if a refresh fails after an earlier success the old articles are labelled `stale` with their own fetch time and "not live". Old news is never shown as live.
- **Periods** (relative to now, IST): today during market hours, today pre-market (00:00 to 09:15), overnight (since the previous trading day's 15:30 close), previous trading day, earlier. Articles from the last two hours are marked New. Today's events are the weekly expiry, events typed in, and headlines that mention something today (marked unverified); there is no verified economic calendar.
- **Tabs:** All News, Indian Stock Market, Global Markets, US Market, Asian Markets, FII / DII, RBI / Federal Reserve, Crude Oil, Economic News, NIFTY / Bank NIFTY, Important Breaking News. Search (headline, summary, source, sector), date filter (today, previous trading day, last 24 hours, a picked day), refresh, breaking highlight, loading and error states, show more in steps of 30.
- **Analysis (`news_analysis.py`, pure, fixed keyword rules on the publisher's headline and summary; a rough first read, not a forecast and not validated):**
  - Related coverage: headlines sharing at least half their words are one article; the one with a summary and picture leads and the other outlets are listed under "Also covered by".
  - NIFTY direction: crude is read inversely for India (rising oil bearish; stories about production or demand volumes neutral), FII/DII by the first flow word (buy, inflow vs sell, outflow), rate news by easing or tightening words, inflation up bearish, down bullish; a company-only story is neutral for the index. Sentiment follows that direction when there is one, else the headline's word tone.
  - Impact level (High / Medium / Low): points for breaking words, a high-weight topic (RBI/Fed, FII/DII, NIFTY), how many outlets cover it and having a direction; minus one for company-only. Breaking = High, published within 12 hours, with a breaking word or three or more outlets.
  - Why it matters: a general explanation of how that kind of news usually reaches Indian markets (per topic and direction), not a claim about the article. Sectors and indices come from keywords.
- **Factor evidence:** each article backs one factor only (FII/DII, crude, volatility, NIFTY structure, then global, in that priority), so no event is counted twice. The factor card lists its articles as supports / conflicts / context against the factor's own result. **Evidence only: news never changes a score or the total** (the scores come from market data; the word-list reading is not validated, and this app does not change trading rules without being asked).

## Daily workflow
`premarket.start_scheduler()` runs when the server starts (disable with `PREMARKET_SCHEDULER=0`): a report at 08:30 IST on weekdays (immediately if the server starts later), refreshes at 08:55, 09:10 and 09:30, then every 30 minutes until 15:30; at 15:45 each unsettled day is settled with what NIFTY actually did (stored candles, else Yahoo daily bars) and scored CORRECT / INCORRECT (|total| ≥ 2 and a day that moved at least 0.15%) or NEUTRAL. A new snapshot is stored only when the total or a factor changed. Entering FII/DII figures or an event recalculates at once. Weekday holidays are not known, so a report may be generated on an exchange holiday; it is harmless and settles as no data.

## Engine integration (paper and replay; never live)
New setting `premarket_mode` (Automated Paper Trading settings, changeable while running): `log` (default) stores `analysis.premarket` {bias, total, preference, agrees: true / false / null} with every paper or replay trade; `block_opposed` also skips a trade that goes against a Bullish/Bearish pre-market bias (neutral or missing never blocks); `off` records nothing. It is a confirmation factor, never a mandatory signal, and never creates an entry. The History panel shows how agreed and opposed trades performed. Live mode gets no stamp.

## Data that is not available
- **Gift Nifty:** no free source this app can read; scored as unavailable, and the opening gap is not estimated from it.
- **NSE FII/DII and FII index-futures positions:** NSE refuses script access; enter the figures from the NSE report (about 18:00 IST). Until then the factor scores 0.
- **Economic calendar (RBI/Fed dates, CPI releases):** no reliable free API, so there is no verified calendar beyond the expiry day and what you type in.
- Yahoo Finance and Google News are unofficial, can fail or change, and quotes can be 15 minutes late. Failures are shown as warnings, never filled in.

## Validation (`scripts/validate_premarket.py`, 1,032 sessions, Sep 2022 - 18 Nov 2026)
Rebuilt from data known before 09:15 with the page's rules: US half of the global factor, Brent, India VIX, daily structure (no 15-minute or gap part); FII/DII, Asia and Gift Nifty have no usable history. Target: close against the previous close, flat days (|move| < 0.15%, 18%) not scored.
- Total score |total| ≥ 2: **56.9%** right over 269 calls (95% range 50.9-62.7%); by period 65.8% (2022-23), 58.7% (2024), **51.1%** (2025-26). |total| ≥ 3: 60.6% over 94 calls.
- Single factors: global (US) 61.0%, structure 54.1%, **crude 48.3%, VIX 48.1%** (no better than a coin flip; not changed, to avoid fitting to this result).
- **Open to close** (what a trade after 09:15 could capture) shows no relation to the score: mean open-to-close move is slightly negative at positive scores.
- Reading: the score mostly tells you about the opening gap through the US close, and that edge faded in 2025-26. It does not predict the intraday move the paper engine trades. No profitability claim is made. Live history now accumulates in `premarket_reports` and the History panel.

## Tests
`backend/tests/test_premarket.py` (scoring rules, bands, news filtering and tone, schedule, outcome scoring, storage and snapshots, manual input validation, settling, API, engine stamp and block mode), `backend/tests/test_premarket_news.py` (feed parsing, cache and failure handling, grouping, categories, direction rules, periods, evidence), `frontend/src/__tests__/pages/pre-market.test.tsx` and `pre-market-news.test.tsx`, Playwright route list (`/premarket`) and the news block at 1280/768/390 px.

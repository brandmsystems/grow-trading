# Groww API integration

**SDK:** `growwapi` (Python). All calls go through `backend/app/services/groww/client.py`.

## Credentials and login
- **Source:** credentials come from the environment (`GROWW_API_KEY` plus `GROWW_TOTP_SECRET` or `GROWW_API_SECRET`). Otherwise `keys.txt` in the project root is read (`API_KEY=`, `TOTP_SECRET=` or `API_SECRET=`). Both are git-ignored, and the app never logs them.
- **Login method:** detected from the secret.
  - A base32 secret means TOTP: `get_access_token(api_key, totp=pyotp.TOTP(secret).now())`. It has no daily approval.
  - Otherwise it's an approval key: `get_access_token(api_key, secret=...)`. Groww requires daily approval for these.
- **Token cache:** the access token is cached in `.token_cache.json` until 06:00 IST.
- **Retry:** `client.call(fn, ...)` re-logs in once on an authentication error.
- **Plan:** the **paid Trading API plan** is required for market data. The free plan returns 403 "Access forbidden" for quotes, candles and expiries. The token's roles must include `live_data` and `back_test`.
- **IP whitelist:** keys may be tied to whitelisted IPs, which are set when the key is generated on Groww.

## Calls used
| Purpose | Call | Where |
|---|---|---|
| NIFTY spot candles | `get_historical_candles(NSE, CASH, NSE-NIFTY, …, 1minute)`, up to 30 days per request | market_data/history, providers |
| Futures / option candles | `get_historical_candles(NSE, FNO, <symbol>, …)` | providers |
| Expiries | `get_expiries(NSE, NIFTY, year, month)` (current year only) | providers, live |
| Contracts of an expiry | `get_contracts(NSE, NIFTY, expiry_date)` | providers, history (futures) |
| Quotes | `get_ltp`, `get_quote` | live, feed |
| Option chain | `get_option_chain` | feed, options/contracts |
| Funds | `get_available_margin_details` | account, feed (sizing) |
| Orders | `place_order` (MIS, MARKET, DAY), `get_order_status`, `get_order_status_by_reference`, `get_order_detail` | trading/brokers (Live mode only) |
| Positions | `get_positions_for_user(FNO)` | live (Check Groww positions) |

## Known behaviour
- **History:** 1-minute history is available from 2020 for spot, futures and expired options.
- **Pre-open and after-close candles:** Groww returns them (09:00–09:14, 15:30–15:59). They are counted but not stored.
- **Incomplete contract lists:** the list for an old expiry can miss strikes that traded. The standard symbol (`NSE-NIFTY-06Oct26-22550-CE`) still returns candles, so it is used.
- **Moved expiries:** holidays move monthly expiries (e.g. 29 Mar 2023, 24 Apr 2025). The futures contract for each month is confirmed against Groww's contract list.
- **Rate limits:** live data 10/s, non-trading 20/s, orders 10/s, token endpoint 150 per day. Backtest option prefetch uses 4 parallel requests and the option history download 3; the provider retries transient errors (including "Rate limit has breached") with backoff and never retries 403/400. The history download runs at about 110 contract requests a minute.
- **Holidays:** a contract requested over a holiday returns no candles for that day (e.g. 10 Nov 2026, Balipratipada). It is recorded with 0 rows; spot has no session that day either.
- **Lot sizes:** the instrument master (`instrument.csv`) lists only current contracts. Their lot sizes (65 for every listed NIFTY expiry on 12 Nov 2026) match the `lot_sizes` table. Past lot sizes come from NSE circulars, not Groww.

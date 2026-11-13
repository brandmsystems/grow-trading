"""Live NIFTY feed and option recommendation for the Live dashboard.

Everything shown comes from Groww: nothing is sampled or simulated here.

* Quote: get_quote(NIFTY, CASH). Cached for QUOTE_TTL seconds; on a failure the last good
  quote is kept and marked "delayed" (never presented as live), and retries back off.
* Bars: the same 1m candles the engine uses (GrowwMarket.spot_1m: warm-up history + today's
  completed candles), resampled and given EMAs by strategy.resample/add_emas, unchanged.
* Signal: strategy.generate_legs, exactly as the engine and backtest use it. An open leg
  means BUY CE (bullish) or BUY PE (bearish); otherwise HOLD.
* Contract: expiry from Groww's expiry list (strategy.pick_expiry), strike from
  strategy.option_for on the live spot, trading symbol from the Groww option chain,
  cross-checked against the instrument master (which also gives the lot size). The premium
  is the option's own verified quote, never the index price.
* Stop / target: the option has no stop in the crossover rules (exit = opposite cross or
  15:00), so the dashboard estimates one: NIFTY 1 x ATR against the trade (2 x ATR for the
  target, as on the Signals page) translated to premium with the option's delta.
* Size: lots limited by both the risk budget (capital x risk %) and the available option-buy
  margin, in whole contract lots.
* Alerts: each new BUY CE / BUY PE / HOLD signal is stored once in live_alerts (unique key).
"""
from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd

from app.utils.timeutil import parse_hm
from app.utils.numbers import to_float as _f
from app.services.notifications import alerts
from app.services.options.contracts import chain_row
from app.services.options.sizing import size_position
from app.services.trading import charges as costs
from app.services.strategy import indicators as ind
from app.services.strategy import rules as st
from app.services.strategy import insight, patterns, signals
from app.services.strategy.signals import STOP_ATR, TARGET_ATR

log = logging.getLogger("live.feed")

QUOTE_TTL = 3            # seconds, market open
CLOSED_TTL = 60          # seconds, market closed (the price doesn't move)
SPOT_TTL = 15            # 1m candles
CHAIN_TTL = 10
CHAIN_WIDTH = 10               # option chain page: strikes each side of ATM
CHAIN_QUOTE_WIDTH = 5          # strikes each side of ATM that also get a per-contract quote (change, OI change)
CHAIN_QUOTES_TTL = 60          # those quotes: refreshed at most once a minute while open
CLOSED_CHAIN_QUOTES_TTL = 600
OPT_QUOTE_TTL = 3
MARGIN_TTL = 30
LIVE_MAX_AGE = 15        # a quote older than this is "delayed"
STALE_SIGNAL_SEC = 180   # same as the engine: later entries differ from the backtest
FROZEN_N = 4             # identical completed 1m candles in a row = frozen candle feed
QUOTE_GAP_PCT = 0.5      # quote vs latest 1m close; NIFTY rarely moves this much in a few minutes
SIGNAL_MODE = "signal"   # live_alerts.trade_mode for dashboard signals


def market_status(now: datetime) -> dict:
    """NSE hours from the clock. Holidays aren't known here; the feed detects them from candles."""
    t = now.time()
    if now.weekday() >= 5:
        return {"state": "closed", "label": "Closed (weekend)"}
    if t < time(9, 0):
        return {"state": "closed", "label": "Closed · opens 09:15"}
    if t < time(9, 15):
        return {"state": "preopen", "label": "Pre-open"}
    if t < time(15, 30):
        return {"state": "open", "label": "Open"}
    return {"state": "closed", "label": "Closed for the day"}


_hm = parse_hm   # kept as a module name: other modules and tests call it here


def _tick_down(p: float) -> float:
    return max(costs.TICK, costs._round_tick_down(p))


# ====================================================================== pure logic (tested)


def signal_state(bars: pd.DataFrame, day: date, now: datetime, entry_start: str, cutoff: str) -> dict:
    """Current 9/21 EMA position from completed bars, with the event that set it.

    Returns {action, direction, since, nifty, reason, alert} where `alert` is False only
    for the "no crossover yet" state (nothing new happened, so nothing to notify).
    """
    done = bars[bars["close_ts"] <= pd.Timestamp(now)]
    today = done[done["day"] == day]
    if today.empty:
        return {"action": "HOLD", "direction": None, "since": None, "nifty": None, "alert": False,
                "reason": "No completed bars today yet."}
    start_t = _hm(entry_start)
    events = signal_events(bars, day, now, entry_start, cutoff)
    if not events:
        return {"action": "HOLD", "direction": None, "since": None, "nifty": None, "alert": False,
                "reason": f"No crossover in the {entry_start}–{cutoff} entry window yet today."}
    ts, _, kind, obj = max(events, key=lambda e: (e[0], e[1]))
    hhmm = ts.strftime("%H:%M")
    if kind == "entry":
        d = obj.direction
        word, rel = ("Bullish", "above") if d > 0 else ("Bearish", "below")
        return {"action": "BUY CE" if d > 0 else "BUY PE", "direction": word, "since": ts.isoformat(),
                "nifty": round(obj.signal_close, 2), "alert": True,
                "reason": f"{word} crossover: EMA 9 crossed {rel} EMA 21 on the bar closing {hhmm} "
                          f"(NIFTY {obj.signal_close:,.2f}). The strategy stays in this trade until an "
                          f"opposite crossover or the 15:00 square-off."}
    if kind == "exit":
        word = "Bearish" if obj.direction > 0 else "Bullish"
        return {"action": "HOLD", "direction": word, "since": ts.isoformat(), "nifty": None, "alert": True,
                "reason": f"{word} crossover at {hhmm} closed the {'CE' if obj.direction > 0 else 'PE'} trade. "
                          f"It is after the {cutoff} entry cutoff, so no new trade."}
    if kind == "square_off":
        return {"action": "HOLD", "direction": None, "since": ts.isoformat(), "nifty": None, "alert": True,
                "reason": "15:00 square-off: the strategy holds no position after 15:00."}
    d = int(obj["direction"])
    word = "Bullish" if d > 0 else "Bearish"
    t = ts.time()
    why = (f"before the {entry_start} entry window" if t < start_t else
           "at or after 15:00" if t >= st.SQUARE_OFF else f"after the {cutoff} entry cutoff")
    return {"action": "HOLD", "direction": word, "since": ts.isoformat(), "nifty": round(float(obj["close"]), 2),
            "alert": True, "reason": f"{word} crossover at {hhmm} was {why}, so the strategy does not trade it."}


def signal_events(bars: pd.DataFrame, day: date, now: datetime, entry_start: str, cutoff: str) -> list[tuple]:
    """Today's strategy events from closed bars: (ts, order, kind, payload); exits sort before entries.
    kind: entry | exit (opposite cross) | square_off | ignored (a cross outside the entry window)."""
    done = bars[bars["close_ts"] <= pd.Timestamp(now)]
    legs, _ = st.generate_legs(done, {day}, _hm(entry_start), _hm(cutoff))
    events, used = [], set()
    for leg in legs:
        events.append((pd.Timestamp(leg.entry_ts), 1, "entry", leg))
        used.add(pd.Timestamp(leg.entry_ts))
        if leg.exit_reason == "opposite_cross":
            events.append((pd.Timestamp(leg.exit_ts), 0, "exit", leg))
            used.add(pd.Timestamp(leg.exit_ts))
        elif now.time() >= st.SQUARE_OFF:
            events.append((pd.Timestamp(leg.exit_ts), 0, "square_off", leg))
    crosses = st.find_crosses(done)
    for _, c in crosses[crosses["day"] == day].iterrows():
        ts = pd.Timestamp(c["close_ts"])
        if ts not in used:
            events.append((ts, 0, "ignored", c))
    return events


def event_markers(events: list[tuple]) -> list[dict]:
    """Chart markers for the strategy's calls: BUY CE / BUY PE at entries, EXIT, HOLD for ignored crosses."""
    out = []
    for ts, _, kind, obj in sorted(events, key=lambda e: (e[0], e[1])):
        if kind == "entry":
            out.append({"ts": ts.isoformat(), "kind": kind, "action": "BUY CE" if obj.direction > 0 else "BUY PE"})
        elif kind in ("exit", "square_off"):
            out.append({"ts": ts.isoformat(), "kind": kind, "action": "EXIT"})
        else:
            out.append({"ts": ts.isoformat(), "kind": kind, "action": "HOLD"})
    return out


def data_checks(today1m: pd.DataFrame, quote: dict, now: datetime) -> list[str]:
    """Problems that make the live data untrustworthy for a recommendation (empty = OK).

    * candles frozen: the last FROZEN_N completed minutes have identical OHLC
    * quote and candles disagree: LTP more than QUOTE_GAP_PCT away from the latest close
    """
    out = []
    if today1m is None or today1m.empty:
        return out
    tail = today1m.tail(FROZEN_N)
    if len(tail) == FROZEN_N and (tail[["open", "high", "low", "close"]].nunique() == 1).all():
        out.append(f"Groww's NIFTY 1-minute candles have not moved since {tail['ts'].iloc[0]:%H:%M} "
                   f"(all {tail['close'].iloc[-1]:,.2f}). The candle feed looks frozen.")
    last = today1m.iloc[-1]
    price = quote.get("price")
    recent = (pd.Timestamp(now) - last["ts"]).total_seconds() <= 300
    if price and recent and abs(price - last["close"]) / last["close"] * 100 > QUOTE_GAP_PCT:
        out.append(f"Groww's NIFTY quote ({price:,.2f}) and its latest candle close ({last['close']:,.2f} at "
                   f"{last['ts']:%H:%M}) differ by {abs(price - last['close']) / last['close'] * 100:.2f}%.")
    return out


# ====================================================================== feed
@dataclass
class _Entry:
    value: object = None
    error: str | None = None
    fetched: float = 0.0          # monotonic time of the last attempt
    good_at: datetime | None = None   # wall time of the last successful fetch
    fails: int = 0


class Feed:
    def __init__(self, market=None, api=None, clock=None):
        # The database (daily history, signal model, plan history) is used only by the real feed;
        # a feed built around an injected market (tests) never reads or writes it.
        self.use_db = market is None
        if market is None:
            from app.services.market_data.live import GrowwMarket
            market = GrowwMarket()
        if api is None:
            from app.services.groww import client as groww_client
            api = groww_client.call
        self.market, self.api = market, api
        self.now = clock or market.now
        self._lock = threading.Lock()
        self._c: dict[str, _Entry] = {}
        self._derived: dict = {}

    # -------------------------------------------------- cache with backoff
    def _get(self, key: str, ttl: float, fn):
        """Fresh value, else the last good one (with its error). Failures back off up to 30 s."""
        e = self._c.setdefault(key, _Entry())
        wait = ttl if not e.error else min(30.0, ttl * 2 ** min(e.fails, 4))
        if e.fetched and _time.monotonic() - e.fetched < wait:
            return e
        e.fetched = _time.monotonic()
        try:
            e.value, e.error, e.good_at, e.fails = fn(), None, self.now(), 0
        except Exception as exc:
            e.error, e.fails = (str(exc) or type(exc).__name__), e.fails + 1
            log.warning("feed %s failed (%d): %s", key, e.fails, e.error)
        return e

    # -------------------------------------------------- pieces
    def quote(self, open_: bool) -> dict:
        def fetch():
            q = self.api("get_quote", trading_symbol="NIFTY", exchange="NSE", segment="CASH", timeout=5)
            price = _f(q.get("last_price"))
            if not price:
                raise RuntimeError("Groww returned no NIFTY price")
            o = q.get("ohlc") or {}
            return {"price": price, "change": _f(q.get("day_change")), "change_pct": _f(q.get("day_change_perc")),
                    "open": _f(o.get("open")), "high": _f(o.get("high")), "low": _f(o.get("low")),
                    "prev_close": _f(o.get("close"))}
        e = self._get("quote", QUOTE_TTL if open_ else CLOSED_TTL, fetch)
        out = dict(e.value or {})
        age = (self.now() - e.good_at).total_seconds() if e.good_at else None
        if not e.value:
            state = "unavailable"
        elif not open_:
            state = "closed"
        elif e.error or age is None or age > LIVE_MAX_AGE:
            state = "delayed"
        else:
            state = "live"
        out.update({"state": state, "as_of": e.good_at.isoformat() if e.good_at else None,
                    "age_sec": None if age is None else round(age), "error": e.error})
        p, hi, lo = out.get("price"), out.get("high"), out.get("low")
        if p and hi and lo:
            out.update({"from_high": round(p - hi, 2), "from_low": round(p - lo, 2),
                        "range_pct": round((p - lo) / (hi - lo) * 100, 1) if hi > lo else None})
        return out

    def bars(self, day: date, tf: int) -> tuple[pd.DataFrame | None, pd.DataFrame | None, str | None]:
        """(bars with EMAs and ATR, today's completed 1m candles, error).

        The 1m candles (the engine's own source) are refetched every SPOT_TTL seconds, so a bar
        is evaluated within seconds of Groww publishing its last minute. On a failure the last
        good candles are kept and the error is returned alongside them."""
        for k in [k for k in self._c if k.startswith("spot|") and k != f"spot|{day}"]:
            del self._c[k]
        e = self._get(f"spot|{day}", SPOT_TTL, lambda: self.market.spot_1m(day))
        if e.value is None:
            return None, None, e.error
        fut = self.futures(day)
        key = (day, e.good_at, tf, id(fut))
        if self._derived.get("key") != key:
            spot = e.value
            # The strategy's own bars (strategies.prepare): EMA 9/21 identical to rules.add_emas,
            # plus RSI, MACD, ATR and futures VWAP/volume for the explanation, plan and chart.
            b = signals.signal_bars(spot, fut, tf, "ema_9_21")
            b["ema9"], b["ema21"] = b["fast"], b["slow"]
            line, sig_, _ = ind.macd(b["close"])
            b["macd"], b["macd_signal"] = line, sig_
            self._derived = {"key": key, "bars": b, "today": spot[spot["ts"].dt.date == day]}
        return self._derived["bars"], self._derived["today"], e.error

    def futures(self, day: date) -> pd.DataFrame | None:
        """Near-month futures 1m candles (VWAP and volume source). None if unavailable."""
        if not hasattr(self.market, "futures_1m"):
            return None
        e = self._get(f"fut|{day}", SPOT_TTL, lambda: self.market.futures_1m(day))
        return e.value

    def context(self, day: date, tf: int, entry_start: str, cutoff: str) -> dict:
        """Daily regime, previous session and 10-day average range (once a day) and the signal model."""
        def daily():
            from app.database import db
            try:
                if not self.use_db:
                    raise LookupError("no database for an injected market")
                hist = db.load_candles(getattr(self.market, "spot_symbol", "NSE-NIFTY"),
                                       datetime.combine(day - timedelta(days=420), time(0)), datetime.combine(day, time(0)))
            except Exception:
                hist = pd.DataFrame()
            if hist.empty:   # no database: the market's own warm-up history (about 40 days)
                s = self.market.spot_1m(day)
                hist = s[s["ts"].dt.date < day]
            reg = signals.daily_regime(hist) if not hist.empty else None
            dd = hist.groupby(hist["ts"].dt.date).agg(high=("high", "max"), low=("low", "min"), close=("close", "last")) if not hist.empty else None
            prev = dd.iloc[-1].to_dict() if dd is not None and len(dd) else None
            rng = float((dd["high"] - dd["low"]).tail(10).mean()) if dd is not None and len(dd) >= 5 else None
            row = reg.loc[day] if reg is not None and day in reg.index else None
            if reg is not None and row is None:   # today's row: regime from previous days only
                full = signals.daily_regime(pd.concat([hist, pd.DataFrame({"ts": [pd.Timestamp(datetime.combine(day, time(9, 15)))],
                                                                           "open": [prev["close"]], "high": [prev["close"]],
                                                                           "low": [prev["close"]], "close": [prev["close"]]})]))
                row = full.loc[day] if day in full.index else None
            return {"regime": row, "prev": prev, "avg_range": rng}
        d = self._get(f"daily|{day}", 3600, daily)

        def model():
            if not self.use_db:
                return None
            a = signals.latest("ema_9_21", tf, entry_start, cutoff)
            return signals.Scorer(a) if a else None
        m = self._get(f"model|{tf}|{entry_start}|{cutoff}", 600, model)
        return {**(d.value or {"regime": None, "prev": None, "avg_range": None}), "scorer": m.value}

    def margin(self) -> tuple[float | None, str | None]:
        def fetch():
            m = self.api("get_available_margin_details", timeout=10)
            v = _f(((m or {}).get("fno_margin_details") or {}).get("option_buy_balance_available"))
            if v is None:
                raise RuntimeError("Groww returned no option-buy balance")
            return v
        e = self._get("margin", MARGIN_TTL, fetch)
        return e.value, e.error

    def _chain(self, expiry: date) -> _Entry:
        return self._get(f"chain|{expiry}", CHAIN_TTL, lambda: self.api(
            "get_option_chain", exchange="NSE", underlying="NIFTY", expiry_date=expiry.isoformat(), timeout=10))

    def _opt_quote(self, symbol: str, ttl: float = OPT_QUOTE_TTL) -> _Entry:
        return self._get(f"oq|{symbol}", ttl, lambda: self.api(
            "get_quote", trading_symbol=symbol, exchange="NSE", segment="FNO", timeout=5))

    # -------------------------------------------------- CE / PE premium monitor (Phase 3)
    def premiums(self, q: dict, day: date, now: datetime, open_: bool, roll: bool, sig: dict) -> dict:
        """Live CE and PE premiums for one strike: the recommended contract's strike and expiry when
        there is a verified recommendation, otherwise the ATM strike of the expiry the strategy would use.
        Every number is from Groww (chain + the contract's own quote). Never derived from the spot."""
        rec = sig.get("rec") or {}
        spot = q.get("price")
        out = {"strike": None, "expiry": None, "basis": None, "ce": None, "pe": None, "error": None}
        if rec.get("verified") and rec.get("strike") and rec.get("expiry"):
            strike, expiry = float(rec["strike"]), date.fromisoformat(rec["expiry"])
            out["basis"] = "recommended contract's strike"
        else:
            if not spot:
                return {**out, "error": "NIFTY spot unavailable, so no ATM strike can be chosen."}
            strike = float(st.atm_strike(spot))
            try:
                expiry = st.pick_expiry(day, self.market.expiries(day), roll)
            except Exception as exc:
                return {**out, "strike": strike, "error": f"Could not load NIFTY expiries from Groww: {exc}"}
            if not expiry:
                return {**out, "strike": strike, "error": "No usable NIFTY expiry found."}
            out["basis"] = "at the money (nearest strike to spot)"
        out.update(strike=strike, expiry=expiry.isoformat(), days_to_expiry=(expiry - day).days)
        # While open, the chain adds IV, delta and a symbol cross-check. While closed it isn't called
        # (no needless Groww calls after hours); the instrument master gives the symbol instead.
        ch = self._chain(expiry) if open_ else None
        if ch is not None and ch.value is None:
            return {**out, "error": f"Option chain unavailable: {ch.error}"}

        def side(typ: str) -> dict:
            try:
                c = self.market.contract(day, expiry, strike, typ)
            except Exception as exc:
                return {"state": "unavailable", "error": f"Instrument master unavailable: {exc}"}
            if not c:
                return {"state": "unavailable", "error": f"NIFTY {expiry} {strike:.0f} {typ} not found in the instrument master."}
            sym = c.trading_symbol
            r = {"symbol": sym, "chain_ltp": None, "oi": None, "volume": None, "iv": None, "delta": None}
            if ch is not None:
                row = chain_row(ch.value, strike, typ)
                if not row or not row.get("trading_symbol"):
                    return {"state": "unavailable", "error": f"{strike:.0f} {typ} is not in the {expiry} option chain."}
                if row["trading_symbol"] != sym:
                    return {"state": "unavailable", "error": f"Option chain symbol {row['trading_symbol']} does not match the instrument master ({sym})."}
                g = row.get("greeks") or {}
                r.update({"chain_ltp": _f(row.get("ltp")), "oi": _f(row.get("open_interest")),
                          "volume": _f(row.get("volume")), "iv": _f(g.get("iv")), "delta": _f(g.get("delta"))})
            oq = self._opt_quote(sym, OPT_QUOTE_TTL if open_ else CLOSED_TTL)
            v = oq.value or {}
            price = _f(v.get("last_price"))
            age = max(0.0, (now - oq.good_at).total_seconds()) if oq.good_at else None
            if price and spot and (abs(price - spot) < 1 or price > spot * 0.5):
                return {**r, "state": "unavailable", "error": "Groww returned an index-like price for this option; not shown."}
            if not price:
                state = "unavailable"
            elif not open_:
                state = "closed"
            elif oq.error or age is None or age > LIVE_MAX_AGE:
                state = "delayed"
            else:
                state = "live"
            ltt = v.get("last_trade_time")
            r.update({"premium": price, "change": _f(v.get("day_change")), "change_pct": _f(v.get("day_change_perc")),
                      "prev_close": _f((v.get("ohlc") or {}).get("close")),
                      "volume": _f(v.get("volume")) if v.get("volume") is not None else r["volume"],
                      "oi": _f(v.get("open_interest")) if v.get("open_interest") is not None else r["oi"],
                      "last_trade": datetime.fromtimestamp(ltt).isoformat() if isinstance(ltt, (int, float)) and ltt > 0 else None,
                      "state": state, "as_of": oq.good_at.isoformat() if oq.good_at else None,
                      "age_sec": None if age is None else round(age), "error": oq.error})
            return r
        out["ce"], out["pe"] = side("CE"), side("PE")
        try:
            c = self.market.contract(day, expiry, strike, "CE")
            out["lot_size"] = c.lot_size if c else None
        except Exception:
            out["lot_size"] = None
        return out

    # -------------------------------------------------- option chain (Options Analysis page)
    def option_chain(self, expiry: date | None = None, width: int = CHAIN_WIDTH, quote_width: int = CHAIN_QUOTE_WIDTH) -> dict:
        """CE and PE side by side for the strikes around ATM, from Groww only.

        * Groww's option chain: LTP, volume, OI, IV and Greeks for every strike (one call).
        * Groww's per-contract quote, for the strikes within `quote_width` of ATM only (to stay well
          inside Groww's rate limits): previous close, premium change and OI change. Other strikes
          show these as unavailable rather than estimated.
        Nothing is filled in or estimated; a value Groww doesn't send stays None."""
        now = self.now()
        day = now.date()
        open_ = market_status(now)["state"] == "open"
        width, quote_width = max(1, min(int(width), 20)), max(0, min(int(quote_width), CHAIN_QUOTE_WIDTH))
        exps = [e for e in self.market.expiries(day) if e >= day]
        if not exps:
            raise LookupError("Groww returned no NIFTY expiries.")
        if expiry is None:
            expiry = exps[0]
        elif expiry not in exps:
            raise ValueError(f"{expiry} is not a listed NIFTY expiry.")
        ch = self._chain(expiry)
        if ch.value is None:
            raise RuntimeError(f"Option chain unavailable: {ch.error}")
        strikes = {}
        for k, v in ((ch.value or {}).get("strikes") or {}).items():
            s = _f(k)
            if s is not None and isinstance(v, dict):
                strikes[s] = v
        if not strikes:
            raise RuntimeError("Groww returned an empty option chain.")
        under = _f(ch.value.get("underlying_ltp"))
        q = self.quote(open_)
        ref = under or q.get("price")
        keys = sorted(strikes)
        atm = min(keys, key=lambda s: abs(s - ref)) if ref else keys[len(keys) // 2]
        i = keys.index(atm)
        shown = keys[max(0, i - width): i + width + 1]
        near = set(keys[max(0, i - quote_width): i + quote_width + 1])
        symbols = [r.get("trading_symbol") for s in shown if s in near
                   for r in (strikes[s].get("CE"), strikes[s].get("PE")) if isinstance(r, dict) and r.get("trading_symbol")]
        qs = self._get(f"chainq|{expiry}|{atm}|{quote_width}", CHAIN_QUOTES_TTL if open_ else CLOSED_CHAIN_QUOTES_TTL,
                       lambda: self._quotes(symbols))

        def side(row: dict | None) -> dict | None:
            if not isinstance(row, dict):
                return None
            g = row.get("greeks") or {}
            sym = row.get("trading_symbol")
            out = {"symbol": sym, "ltp": _f(row.get("ltp")), "volume": _f(row.get("volume")), "oi": _f(row.get("open_interest")),
                   "iv": _f(g.get("iv")), "delta": _f(g.get("delta")), "gamma": _f(g.get("gamma")),
                   "theta": _f(g.get("theta")), "vega": _f(g.get("vega")),
                   "prev_close": None, "change": None, "change_pct": None, "prev_oi": None, "oi_change": None, "oi_change_pct": None}
            qq = (qs.value or {}).get(sym)
            if qq:
                # OI change = the quote's OI minus its previous OI. Groww's own `oi_day_change` field is not
                # used: it came back scaled (x0.65 of that difference) while its percentage matched it.
                oi_q, prev_oi = _f(qq.get("open_interest")), _f(qq.get("previous_open_interest"))
                d_oi = oi_q - prev_oi if oi_q is not None and prev_oi is not None else None
                out.update({"prev_close": _f((qq.get("ohlc") or {}).get("close")), "change": _f(qq.get("day_change")),
                            "change_pct": _f(qq.get("day_change_perc")), "prev_oi": prev_oi, "oi_change": d_oi,
                            "oi_change_pct": round(d_oi / prev_oi * 100, 2) if d_oi is not None and prev_oi else None})
            return out

        rows = [{"strike": s, "atm": s == atm, "ce": side(strikes[s].get("CE")), "pe": side(strikes[s].get("PE"))} for s in shown]
        tot = lambda leg, k: sum((r[leg] or {}).get(k) or 0 for r in rows)   # noqa: E731
        ce_oi, pe_oi = tot("ce", "oi"), tot("pe", "oi")
        lot = None
        try:
            from app.services.options import lot_sizes
            lot = lot_sizes.lot_size_for(expiry, exps)[0]
        except Exception:
            pass
        return {
            "expiry": expiry.isoformat(), "expiries": [e.isoformat() for e in exps], "days_to_expiry": (expiry - day).days,
            "lot_size": lot, "spot": {k: q.get(k) for k in ("price", "change", "change_pct", "prev_close", "state", "as_of")},
            "underlying_ltp": under, "atm": atm, "width": width, "quote_width": quote_width,
            "rows": rows,
            "totals": {"ce_oi": ce_oi, "pe_oi": pe_oi, "ce_volume": tot("ce", "volume"), "pe_volume": tot("pe", "volume"),
                       "pcr": round(pe_oi / ce_oi, 2) if ce_oi else None},
            "chain_as_of": ch.good_at.isoformat() if ch.good_at else None, "chain_error": ch.error,
            "quotes_as_of": qs.good_at.isoformat() if qs.good_at else None, "quotes_error": qs.error,
            "market": market_status(now)["state"],
        }

    def _quotes(self, symbols: list[str]) -> dict:
        """Per-contract Groww quotes, a few at a time. Fails only if every request fails."""
        from concurrent.futures import ThreadPoolExecutor

        def one(sym):
            try:
                return sym, self.api("get_quote", trading_symbol=sym, exchange="NSE", segment="FNO", timeout=5), None
            except Exception as exc:
                return sym, None, str(exc) or type(exc).__name__
        with ThreadPoolExecutor(max_workers=6) as ex:
            res = list(ex.map(one, symbols))
        good = {s: v for s, v, _ in res if v}
        if symbols and not good:
            raise RuntimeError(next((e for _, _, e in res if e), "no quotes returned"))
        return good

    # -------------------------------------------------- recommendation
    def recommend(self, sig: dict, spot: float, bars: pd.DataFrame, day: date, now: datetime,
                  exec_mode: str, roll: bool, capital: float | None, risk_pct: float) -> dict:
        """Contract, premium, stop/target and size for a BUY signal. Raises nothing: problems
        are reported in `error`, and no size is given unless every quote is verified."""
        d = 1 if sig["action"] == "BUY CE" else -1
        mode = exec_mode if st.MODES.get(exec_mode, ("SELL",))[0] == "BUY" else "ATM_BUY"
        strike, typ, _ = st.option_for(mode, d, spot)
        rec = {"strike": strike, "opt_type": typ, "strike_rule": st.MODE_LABELS[mode], "verified": False}
        try:
            expiry = st.pick_expiry(day, self.market.expiries(day), roll)
        except Exception as exc:
            return {**rec, "error": f"Could not load NIFTY expiries from Groww: {exc}"}
        if not expiry:
            return {**rec, "error": "No usable NIFTY expiry found."}
        rec["expiry"] = expiry.isoformat()
        ch = self._chain(expiry)
        if ch.value is None:
            return {**rec, "error": f"Option chain unavailable: {ch.error}"}
        row = chain_row(ch.value, strike, typ)
        if not row or not row.get("trading_symbol"):
            return {**rec, "error": f"Strike {strike:.0f} {typ} is not in the {expiry} option chain."}
        try:
            c = self.market.contract(day, expiry, strike, typ)
        except Exception as exc:
            return {**rec, "error": f"Instrument master unavailable: {exc}"}
        if not c:
            return {**rec, "error": f"NIFTY {expiry} {strike:.0f} {typ} not found in the instrument master."}
        if c.trading_symbol != row["trading_symbol"]:
            return {**rec, "error": f"Option chain symbol {row['trading_symbol']} does not match the "
                                    f"instrument master ({c.trading_symbol}); not recommending."}
        rec.update({"symbol": c.trading_symbol, "lot_size": c.lot_size,
                    "chain_ltp": _f(row.get("ltp")), "delta": _f((row.get("greeks") or {}).get("delta")),
                    "iv": _f((row.get("greeks") or {}).get("iv")), "oi": _f(row.get("open_interest"))})
        oq = self._opt_quote(c.trading_symbol)
        premium = _f((oq.value or {}).get("last_price"))
        age = (now - oq.good_at).total_seconds() if oq.good_at else None
        if not premium or oq.error or age is None or age > LIVE_MAX_AGE:
            return {**rec, "error": f"Option quote for {c.trading_symbol} could not be verified"
                                    f"{': ' + oq.error if oq.error else ''}. No order size is given."}
        if abs(premium - spot) < 1 or premium > spot * 0.5:
            return {**rec, "error": "The option premium looks like an index price; not recommending."}
        asks = [_f(x.get("price")) for x in ((oq.value.get("depth") or {}).get("sell") or []) if _f(x.get("price"))]
        entry = min(asks) if asks else costs.buy_fill(premium)
        rec.update({"premium": premium, "entry": round(entry, 2),
                    "entry_basis": "best offer in the order book" if asks else "LTP plus the backtest slippage",
                    "quote_as_of": oq.good_at.isoformat(), "verified": True})
        done = bars[bars["close_ts"] <= pd.Timestamp(now)]
        atr = _f(done["atr"].iloc[-1]) if not done.empty else None
        delta = abs(rec["delta"]) if rec["delta"] else None
        if not atr or not delta:
            return {**rec, "error": "ATR or option delta unavailable, so no stop/target can be estimated."}
        stop = _tick_down(entry - delta * STOP_ATR * atr)
        target = costs._round_tick_up(entry + delta * TARGET_ATR * atr)
        rec.update({"stop": stop, "target": target, "atr": round(atr, 2),
                    "nifty_stop": round(spot - d * STOP_ATR * atr, 2), "nifty_target": round(spot + d * TARGET_ATR * atr, 2)})
        avail, merr = self.margin()
        cap = capital if capital and capital > 0 else avail
        if cap is None:
            rec["sizing_error"] = f"Available margin unknown ({merr}). Enter your capital to size the trade."
            return rec
        if cap <= 0:
            # Groww reports zero or a negative option-buy balance (e.g. after buying with the whole balance).
            rec["sizing_error"] = (f"Groww option-buy balance is ₹{cap:,.2f}, so no size can be given. "
                                   "Enter your capital to size the trade.")
            return rec
        rec["sizing"] = size_position(entry, stop, target, c.lot_size, cap, risk_pct, avail)
        if merr:
            rec["sizing"]["margin_error"] = merr
        return rec

    # -------------------------------------------------- everything the page needs
    def dashboard(self, tf: int = 5, entry_start: str = "09:30", cutoff: str = "14:30", exec_mode: str = "ATM_BUY",
                  roll: bool = True, capital: float | None = None, risk_pct: float = 1.0) -> dict:
        now = self.now()
        day = now.date()
        mk = market_status(now)
        with self._lock:
            q = self.quote(mk["state"] == "open")
            bars, today1m, bars_err = self.bars(day, tf)
            out = {"now": now.isoformat(), "market": mk, "quote": q, "timeframe": tf,
                   "entry_start": entry_start, "cutoff": cutoff, "bars_error": bars_err}
            if bars is None:
                out["chart"] = {"day": None, "bars": [], "forming": None}
                out["signal"] = {"action": "HOLD", "reason": "NIFTY candles unavailable: " + (bars_err or "")}
                out["holiday"] = False
                return out
            # holiday / no session: market "open" by the clock but no candles after 09:20
            if mk["state"] == "open" and today1m.empty and now.time() >= time(9, 20):
                out["market"] = {"state": "closed", "label": "No trading today (holiday?)"}
                if q["state"] in ("live", "delayed"):
                    q["state"] = "closed"
            out["warnings"] = data_checks(today1m, q, now) if out["market"]["state"] == "open" else []
            done = bars[bars["close_ts"] <= pd.Timestamp(now)]
            days = sorted(done["day"].unique())
            chart_day = day if day in days else (days[-1] if days else None)
            show = done[done["day"] == chart_day] if chart_day else done.iloc[0:0]
            out["chart"] = {"day": chart_day.isoformat() if chart_day else None, "bars": [_bar_json(r) for r in show.itertuples(index=False)],
                "forming": self._forming(today1m, tf, now, q)
                if out["market"]["state"] == "open" and not out["warnings"] else None}
            last = show.iloc[-1] if not show.empty else None
            out["ema"] = None if last is None else {
                "fast": round(float(last["ema9"]), 2), "slow": round(float(last["ema21"]), 2),
                "close": round(float(last["close"]), 2), "bar_close": pd.Timestamp(last["close_ts"]).isoformat(),
                "gap": round(float(last["ema9"] - last["ema21"]), 2)}
            crosses = st.find_crosses(done)
            crosses = crosses[crosses["day"] == chart_day] if chart_day else crosses.iloc[0:0]
            out["crosses"] = [{"ts": pd.Timestamp(c["close_ts"]).isoformat(), "direction": int(c["direction"]),
                               "close": round(float(c["close"]), 2)} for _, c in crosses.iterrows()]
            sig = signal_state(bars, day, now, entry_start, cutoff)
            out["markers"] = event_markers(signal_events(bars, chart_day, now, entry_start, cutoff)) if chart_day else []
            ctx = self.context(day, tf, entry_start, cutoff)
            if out["market"]["state"] != "open" and sig["action"] != "HOLD":
                sig = {**sig, "action": "HOLD", "alert": False, "reason": "Market closed: no new entries."}
            if sig["action"] != "HOLD":
                age = (now - datetime.fromisoformat(sig["since"])).total_seconds()
                sig["age_sec"] = round(age)
                if age > STALE_SIGNAL_SEC:
                    sig["late"] = (f"The strategy entered at {sig['since'][11:16]}. Entering now is later than the "
                                   f"backtested entry, so the premium and risk differ from the backtest.")
                if q["state"] != "live":
                    sig["rec"] = {"verified": False, "error": "NIFTY quote is not live; no recommendation until it is."}
                elif out["warnings"]:
                    sig["rec"] = {"verified": False, "error": "Live data failed a consistency check (see the warning "
                                                              "above); no recommendation until it passes."}
                else:
                    sig["rec"] = self.recommend(sig, q["price"], bars, day, now, exec_mode, roll, capital, risk_pct)
            out["signal"] = sig
            try:
                out["premiums"] = self.premiums(q, day, now, out["market"]["state"] == "open", roll, sig)
            except Exception as exc:
                log.warning("premium monitor failed: %s", exc)
                out["premiums"] = {"error": f"Premium monitor failed: {exc}", "ce": None, "pe": None}
            # Explanation, plan and patterns: closed bars only; none of them changes the signal.
            sday = chart_day or day
            try:
                out["explain"] = insight.explain(sig, done, sday, tf, ctx["regime"], ctx["scorer"], entry_start, cutoff)
            except Exception as exc:
                log.warning("explanation failed: %s", exc)
                out["explain"] = {"summary": f"Explanation unavailable: {exc}", "checks": []}
            try:
                plan = insight.trading_plan(sday, now, q, today1m, ctx["prev"], done, ctx["regime"], ctx["avg_range"],
                                            tf, entry_start, cutoff)
                out["plan"] = self._plan_history(sday, tf, plan)
            except Exception as exc:
                log.warning("plan failed: %s", exc)
                out["plan"] = None
            pats = patterns.detect(done[done["day"] == sday].tail(80))
            out["patterns"] = [{**x, "effect": patterns.effect(x, sig["action"])} for x in pats][-12:]
        if sig.get("alert") and sig.get("since"):
            record_signal(day, tf, entry_start, cutoff, sig, now)
        return out

    def _plan_history(self, day: date, tf: int, plan: dict) -> dict:
        """Keep the plan's changes for the day (memory + trading_plans table) with the reason for each."""
        key = (day, tf)
        h = getattr(self, "_plans", {}).get(key)
        if h is None:
            h = {"last": None, "changes": []}
            try:
                if not self.use_db:
                    raise LookupError("no database")
                from app.database import db
                from sqlalchemy import text
                with db.engine().connect() as c:
                    rows = c.execute(text("SELECT ts, reason, plan FROM trading_plans WHERE day=:d AND timeframe=:tf ORDER BY id"),
                                     {"d": day, "tf": tf}).fetchall()
                h["changes"] = [{"ts": r[0].isoformat(), "reason": r[1], "preferred": r[2].get("preferred")} for r in rows]
                h["last"] = rows[-1][2] if rows else None
            except Exception:
                pass
            self._plans = {**getattr(self, "_plans", {}), key: h}
        reason = insight.plan_change_reason(h["last"], plan)
        if reason:
            h["last"] = plan
            h["changes"].append({"ts": plan["computed_at"], "reason": reason, "preferred": plan["preferred"]})
        if reason and self.use_db:
            try:
                import json
                from app.database import db
                from sqlalchemy import text
                with db.engine().begin() as c:
                    c.execute(text("INSERT INTO trading_plans (day, timeframe, ts, preferred, reason, plan) "
                                   "VALUES (:d, :tf, :ts, :p, :r, CAST(:j AS JSONB))"),
                              {"d": day, "tf": tf, "ts": plan["computed_at"], "p": plan["preferred"], "r": reason,
                               "j": json.dumps(plan, default=str)})
            except Exception as exc:
                log.warning("plan history not stored: %s", exc)
        return {**plan, "created_at": h["changes"][0]["ts"] if h["changes"] else plan["computed_at"],
                "updated_at": h["changes"][-1]["ts"] if h["changes"] else plan["computed_at"], "changes": h["changes"][-10:]}

    @staticmethod
    def _forming(today1m: pd.DataFrame, tf: int, now: datetime, q: dict) -> dict | None:
        """The bar in progress: completed 1m candles in it plus the live price. No EMA (not closed)."""
        if q.get("state") != "live" or not q.get("price"):
            return None
        open_dt = datetime.combine(now.date(), st.SESSION_OPEN)
        start = open_dt + timedelta(minutes=((now - open_dt).seconds // 60 // tf) * tf)
        part = today1m[today1m["ts"] >= pd.Timestamp(start)]
        p = q["price"]
        if part.empty:
            return {"t": start.isoformat(), "o": p, "h": p, "l": p, "c": p}
        return {"t": start.isoformat(), "o": float(part["open"].iloc[0]), "h": max(float(part["high"].max()), p),
                "l": min(float(part["low"].min()), p), "c": p}


def _bar_json(r) -> dict:
    """One chart bar: OHLC, EMA 9/21, basis-adjusted futures VWAP, futures volume, RSI and MACD."""
    n = lambda x, d=2: None if x is None or pd.isna(x) else round(float(x), d)
    vwap = (r.fut_vwap - (r.fut_close - r.close)) if pd.notna(getattr(r, "fut_vwap", None)) and pd.notna(getattr(r, "fut_close", None)) else None
    return {"t": pd.Timestamp(r.start).isoformat(), "o": r.open, "h": r.high, "l": r.low, "c": r.close,
            "e9": round(r.ema9, 2), "e21": round(r.ema21, 2), "vwap": n(vwap), "v": n(getattr(r, "fut_volume", None), 0),
            "rsi": n(getattr(r, "rsi", None), 1), "macd": n(getattr(r, "macd", None)), "macd_signal": n(getattr(r, "macd_signal", None)),
            "macd_hist": n(getattr(r, "macd_hist", None))}


# ====================================================================== alerts
def record_signal(day: date, tf: int, entry_start: str, cutoff: str, sig: dict, now: datetime) -> None:
    """Store a signal once. The key ties it to the bar that produced it, so polling never repeats it."""
    key = f"{SIGNAL_MODE}|{day}|{tf}|{entry_start}|{cutoff}|{sig['action']}|{sig['since']}"
    rec = sig.get("rec") or {}
    payload = {"signal_ts": sig["since"], "direction": sig.get("direction"), "nifty": sig.get("nifty"),
               "reason": sig["reason"], "timeframe": tf,
               **{k: rec.get(k) for k in ("strike", "opt_type", "expiry", "symbol", "premium", "entry", "stop", "target")
                  if rec.get("verified") and rec.get(k) is not None}}
    alerts.store(key, SIGNAL_MODE, day, now, sig["action"], payload)


_feed: Feed | None = None
_feed_lock = threading.Lock()


def feed() -> Feed:
    global _feed
    with _feed_lock:
        if _feed is None:
            _feed = Feed()
        return _feed

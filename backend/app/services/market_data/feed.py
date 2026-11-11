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
from app.services.strategy.signals import STOP_ATR, TARGET_ATR

log = logging.getLogger("live.feed")

QUOTE_TTL = 3            # seconds, market open
CLOSED_TTL = 60          # seconds, market closed (the price doesn't move)
SPOT_TTL = 15            # 1m candles
CHAIN_TTL = 10
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
    start_t, cut_t = _hm(entry_start), _hm(cutoff)
    legs, _ = st.generate_legs(done, {day}, start_t, cut_t)
    events = []                          # (ts, order, kind, payload); exits sort before entries
    used = set()
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
        key = (day, e.good_at, tf)
        if self._derived.get("key") != key:
            spot = e.value
            b = st.add_emas(st.resample(spot, tf))
            b["atr"] = ind.atr(b)
            self._derived = {"key": key, "bars": b, "today": spot[spot["ts"].dt.date == day]}
        return self._derived["bars"], self._derived["today"], e.error

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

    def _opt_quote(self, symbol: str) -> _Entry:
        return self._get(f"oq|{symbol}", OPT_QUOTE_TTL, lambda: self.api(
            "get_quote", trading_symbol=symbol, exchange="NSE", segment="FNO", timeout=5))

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
        if not cap:
            rec["sizing_error"] = f"Available margin unknown ({merr}). Enter your capital to size the trade."
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
            out["chart"] = {"day": chart_day.isoformat() if chart_day else None, "bars": [
                {"t": pd.Timestamp(r.start).isoformat(), "o": r.open, "h": r.high, "l": r.low, "c": r.close,
                 "e9": round(r.ema9, 2), "e21": round(r.ema21, 2)} for r in show.itertuples(index=False)],
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
        if sig.get("alert") and sig.get("since"):
            record_signal(day, tf, entry_start, cutoff, sig, now)
        return out

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

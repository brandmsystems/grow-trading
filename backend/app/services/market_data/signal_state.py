"""Pure live-signal logic: market hours, the strategy's current call from closed bars, chart markers and
data-trust checks. No I/O and no clock reads (callers pass `now`), so every function is unit tested directly.
`feed.py` re-exports these names; nothing else needs to change.
"""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

from app.services.strategy import rules as st
from app.utils.timeutil import parse_hm

FROZEN_N = 4             # identical completed 1m candles in a row = frozen candle feed
QUOTE_GAP_PCT = 0.5      # quote vs latest 1m close; NIFTY rarely moves this much in a few minutes

_hm = parse_hm


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

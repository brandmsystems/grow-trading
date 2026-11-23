"""Daily OHLC and range analysis for NIFTY spot, aggregated from the stored 1-minute candles.

Nothing new is stored or downloaded: PostgreSQL groups `candles_1m` by Asia/Kolkata market date and only
the daily rows (a few hundred) leave the database. Missing minutes are never filled in. A day is

* **complete**   - all 375 minutes 09:15..15:29 are stored; used for every range statistic,
* **partial**    - fewer minutes (a data gap or a short special session): shown and flagged, left out of the
                   range statistics and never used as a "previous close", because its open/high/low/close
                   are not the session's,
* **in progress** - today before the 15:29 candle: shown, flagged, left out of the averages.

Weekends and days without candles are excluded. Range % is the day's range as a percentage of its open;
change % is the close against the previous complete session's close. The ADR here is the same measure as
`strategy.indicators.adr` (mean high-low of the previous N completed sessions).
"""
from __future__ import annotations

import threading
import time as _time
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.database import db
from app.services.market_data.history import SESSION_MINUTES, SYMBOL
from app.utils.timeutil import now_naive

_now = now_naive            # module-level so tests can patch the clock
_mono = _time.monotonic

IST = "Asia/Kolkata"
FIRST_MINUTE, LAST_MINUTE = time(9, 15), time(15, 29)
AVG_WINDOWS = (10, 20, 50)
LOOKBACK_DAYS = 100         # calendar days read before the window so the 50-session average is complete from its first day
MAX_SPAN_DAYS = 366 * 6
TREND_BAND = 0.10           # 10-day average this far above/below the 50-day one = expanding / contracting
LIVE_TTL, HISTORY_TTL, CACHE_SIZE = 30.0, 300.0, 32

_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


_AGG = text(f"""
SELECT (ts AT TIME ZONE '{IST}')::date AS day,
       (array_agg(open  ORDER BY ts))[1]      AS open,
       max(high)                              AS high,
       min(low)                               AS low,
       (array_agg(close ORDER BY ts DESC))[1] AS close,
       count(*)                               AS n,
       min(ts AT TIME ZONE '{IST}')           AS first,
       max(ts AT TIME ZONE '{IST}')           AS last
FROM candles_1m
WHERE symbol = :s
  AND ts >= (CAST(:a AS timestamp) AT TIME ZONE '{IST}')
  AND ts <  (CAST(:b AS timestamp) AT TIME ZONE '{IST}')
  AND ts + interval '1 minute' <= (CAST(:now AS timestamp) AT TIME ZONE '{IST}')
  AND extract(isodow FROM ts AT TIME ZONE '{IST}') < 6
  AND open > 0 AND high > 0 AND low > 0 AND close > 0 AND high >= low
GROUP BY 1 ORDER BY 1
""")


def _aggregate(start: date, end: date, now: datetime, symbol: str = SYMBOL) -> pd.DataFrame:
    """One row per market day in [start, end] (weekdays with at least one valid candle)."""
    with db.engine().connect() as c:
        rows = c.execute(_AGG, {"s": symbol, "a": datetime.combine(start, time(0)),
                                "b": datetime.combine(end + timedelta(days=1), time(0)), "now": now}).fetchall()
    df = pd.DataFrame(rows, columns=["day", "open", "high", "low", "close", "n", "first", "last"])
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["n"] = df["n"].astype(int)
    return df


def _classify(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Adds complete / in_progress / partial flags."""
    df = df.copy()
    if df.empty:
        for col in ("complete", "in_progress", "partial"):
            df[col] = pd.Series(dtype=bool)
        return df
    df["complete"] = ((df["n"] == SESSION_MINUTES) & (df["first"].dt.time == FIRST_MINUTE)
                      & (df["last"].dt.time == LAST_MINUTE))
    df["in_progress"] = (df["day"] == today) & ~df["complete"]
    df["partial"] = ~df["complete"] & ~df["in_progress"]
    return df


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Range, change against the previous complete close, and trailing range averages (complete sessions only)."""
    df = df.copy()
    df["range"] = df["high"] - df["low"]
    df["range_pct"] = 100 * df["range"] / df["open"]
    done = df["complete"]
    # previous complete session strictly before the row: shift past the row itself, then carry forward
    df["prev_close"] = df["close"].where(done).shift(1).ffill()
    df["prev_day"] = df["day"].where(done).shift(1).ffill()
    df["change"] = df["close"] - df["prev_close"]
    df["change_pct"] = 100 * df["change"] / df["prev_close"]
    cs = df.loc[done, "range"]
    for n in AVG_WINDOWS:
        df[f"avg{n}"] = cs.rolling(n, min_periods=n).mean().reindex(df.index)     # NaN on rows that are not complete
    return df


def _num(v, nd: int = 2):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def _row(r) -> dict:
    status = "complete" if r.complete else "in_progress" if r.in_progress else "partial"
    return {
        "date": r.day.isoformat(), "open": _num(r.open), "high": _num(r.high), "low": _num(r.low), "close": _num(r.close),
        "range": _num(r.range), "range_pct": _num(r.range_pct, 3),
        "prev_close": _num(r.prev_close), "prev_date": None if pd.isna(r.prev_day) else r.prev_day.isoformat(),
        "change": _num(r.change), "change_pct": _num(r.change_pct, 3),
        "avg10": _num(r.avg10), "avg20": _num(r.avg20), "avg50": _num(r.avg50),
        "candles": int(r.n), "status": status,
        "first": r.first.strftime("%H:%M"), "last": r.last.strftime("%H:%M"),
    }


def _pick(df: pd.DataFrame, col: str, high: bool) -> dict | None:
    done = df[df["complete"]]
    if done.empty:
        return None
    r = done.loc[done[col].idxmax() if high else done[col].idxmin()]
    return {"date": r.day.isoformat(), "range": _num(r["range"]), "range_pct": _num(r["range_pct"], 3),
            "high": _num(r.high), "low": _num(r.low)}


def _prior_adr(df: pd.DataFrame, upto: int) -> dict[int, float | None]:
    """Mean range of the N complete sessions before row `upto` (the row itself is never in its own average)."""
    prior = df.iloc[:upto]
    rng = prior.loc[prior["complete"], "range"]
    return {n: (float(rng.iloc[-n:].mean()) if len(rng) >= n else None) for n in AVG_WINDOWS}


def _current(df: pd.DataFrame) -> dict | None:
    """The newest stored session against the average range of the sessions before it."""
    if df.empty:
        return None
    i = len(df) - 1
    r = df.iloc[i]
    adr = _prior_adr(df, i)
    rng = float(r["range"])
    out = {
        "date": r.day.isoformat(), "status": "complete" if r.complete else "in_progress" if r.in_progress else "partial",
        "open": _num(r.open), "high": _num(r.high), "low": _num(r.low), "close": _num(r.close),
        "range": _num(rng), "range_pct": _num(r.range_pct, 3), "last": r["last"].strftime("%H:%M"),
        "adr": {str(n): _num(v) for n, v in adr.items()},
        "utilization": {str(n): (_num(100 * rng / v, 1) if v else None) for n, v in adr.items()},
        "remaining": {str(n): (_num(max(0.0, v - rng)) if v else None) for n, v in adr.items()},
    }
    if not r.complete and not r.in_progress:
        out["note"] = "This session has missing minutes, so its range may be understated."
    return out


def _trend(rows: pd.DataFrame) -> dict | None:
    done = rows[rows["complete"] & rows["avg50"].notna()]
    if done.empty:
        return None
    last = done.iloc[-1]
    ratio = float(last.avg10 / last.avg50) if last.avg50 else None
    label = None if ratio is None else "expanding" if ratio >= 1 + TREND_BAND else "contracting" if ratio <= 1 - TREND_BAND else "steady"
    return {"avg10": _num(last.avg10), "avg50": _num(last.avg50), "ratio": _num(ratio, 3), "label": label,
            "as_of": last.day.isoformat(), "band": TREND_BAND}


def default_window(symbol: str = SYMBOL) -> tuple[date, date] | None:
    """The previous 1 year, ending on the newest stored session (None when nothing is stored)."""
    with db.engine().connect() as c:
        first, last = c.execute(text(f"SELECT min(ts AT TIME ZONE '{IST}'), max(ts AT TIME ZONE '{IST}') "
                                     "FROM candles_1m WHERE symbol = :s"), {"s": symbol}).fetchone()
    if last is None:
        return None
    end = last.date()
    try:
        return end.replace(year=end.year - 1) + timedelta(days=1), end
    except ValueError:   # 29 Feb
        return end.replace(year=end.year - 1, day=28) + timedelta(days=1), end


def _build(start: date, end: date, now: datetime, symbol: str) -> dict:
    today = now.date()
    frame = _aggregate(start - timedelta(days=LOOKBACK_DAYS), end, now, symbol)
    frame = _enrich(_classify(frame, today))
    win = frame[(frame["day"] >= start) & (frame["day"] <= end)]
    complete = win[win["complete"]]

    # newest stored session overall, for "current price" and today's range, whatever window is asked for
    with db.engine().connect() as c:
        newest = c.execute(text(
            f"SELECT (ts AT TIME ZONE '{IST}')::date FROM candles_1m WHERE symbol = :s "
            "AND ts + interval '1 minute' <= (CAST(:now AS timestamp) AT TIME ZONE :tz) "
            "AND extract(isodow FROM ts AT TIME ZONE :tz) < 6 ORDER BY ts DESC LIMIT 1"),
            {"s": symbol, "now": now, "tz": IST}).scalar()
    cur = None
    if newest is not None:
        recent = _enrich(_classify(_aggregate(newest - timedelta(days=LOOKBACK_DAYS), newest, now, symbol), today))
        cur = _current(recent)

    summary = None
    if not win.empty:
        hi, lo = win.loc[win["high"].idxmax()], win.loc[win["low"].idxmin()]
        summary = {
            "high": {"price": _num(hi.high), "date": hi.day.isoformat()},
            "low": {"price": _num(lo.low), "date": lo.day.isoformat()},
            "current": None if cur is None else {"price": cur["close"], "date": cur["date"], "time": cur["last"],
                                                  "status": cur["status"]},
            "adr": _num(complete["range"].mean()) if not complete.empty else None,
            "adr_pct": _num(complete["range_pct"].mean(), 3) if not complete.empty else None,
            "highest_range": _pick(win, "range", True),
            "lowest_range": _pick(win, "range", False),
            "median_range": _num(complete["range"].median()) if not complete.empty else None,
            "bullish_days": int((complete["close"] >= complete["open"]).sum()),
            "bearish_days": int((complete["close"] < complete["open"]).sum()),
        }
    return {
        "symbol": symbol,
        "window": {"from": start.isoformat(), "to": end.isoformat()},
        "as_of": None if win.empty else win.iloc[-1]["last"].isoformat(),
        "counts": {"days": len(win), "complete": int(win["complete"].sum()), "partial": int(win["partial"].sum()),
                   "in_progress": int(win["in_progress"].sum())},
        "days": [_row(r) for r in win.itertuples(index=False)],
        "summary": summary,
        "analysis": {"windows": list(AVG_WINDOWS), "trend": _trend(win), "current": cur},
        "rules": {"session_minutes": SESSION_MINUTES, "range_pct_of": "open", "change_pct_of": "previous complete close"},
    }


def daily_range(start: date | None = None, end: date | None = None, symbol: str = SYMBOL) -> dict:
    """Daily OHLC + range statistics for [start, end] (default: previous 1 year). Raises ValueError on a bad range."""
    if (start is None) != (end is None):
        raise ValueError("Give both a start and an end date, or neither.")
    if start is None:
        window = default_window(symbol)
        if window is None:
            return {"symbol": symbol, "window": None, "as_of": None, "days": [], "summary": None,
                    "counts": {"days": 0, "complete": 0, "partial": 0, "in_progress": 0},
                    "analysis": {"windows": list(AVG_WINDOWS), "trend": None, "current": None}, "rules": {}}
        start, end = window
    if start > end:
        raise ValueError("Start date is after end date.")
    if (end - start).days > MAX_SPAN_DAYS:
        raise ValueError("Choose a range of at most 6 years.")
    now = _now()
    key = (db.engine().url.database, symbol, start, end)
    ttl = LIVE_TTL if end >= now.date() - timedelta(days=4) else HISTORY_TTL
    with _lock:
        hit = _cache.get(key)
        if hit and _mono() - hit[0] < ttl:
            return hit[1]
    out = _build(start, end, now, symbol)
    with _lock:
        _cache[key] = (_mono(), out)
        while len(_cache) > CACHE_SIZE:
            _cache.pop(next(iter(_cache)))
    return out

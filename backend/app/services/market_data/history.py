"""Historical 1-minute data: incremental download, validation and coverage reports.

Only candles Groww actually returns are stored. Nothing is estimated or filled in;
gaps are recorded and reported instead.
"""
from __future__ import annotations

import json
import logging
import threading
import time as _time
from collections import Counter
from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import text

from app.database import db
from app.services.strategy import rules as st

log = logging.getLogger("data_manager")

SYMBOL = "NSE-NIFTY"
SEGMENT = "CASH"
CHUNK_SPAN_DAYS = 29        # Groww allows 30 days per 1-minute request
MAX_GAP_DAYS = 5            # don't re-request a long run of days already stored
MAX_ATTEMPTS = 3
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)
SESSION_MINUTES = 375
SPIKE_PCT = 0.05            # a 5% move between adjacent minutes is flagged for review
TARGET_YEARS = 5
MAX_CHART_BARS = 20000

_stop = threading.Event()


class DownloadError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now()


def _sleep(seconds: float) -> None:
    _time.sleep(seconds)


def default_fetch(segment: str, symbol: str, a: datetime, b: datetime) -> pd.DataFrame:
    from app.services.market_data import providers
    return providers.GrowwProvider()._candles(segment, symbol, a, b, dedupe=False)


# ---------------------------------------------------------------- validation
def validate(df: pd.DataFrame, now: datetime) -> tuple[pd.DataFrame, Counter]:
    """Return (usable rows, rejection counts). A minute still forming is dropped, not rejected."""
    rejected: Counter = Counter()
    if df.empty:
        return df, rejected
    df = df[df["ts"] + pd.Timedelta(minutes=1) <= now]
    prices = df[["open", "high", "low", "close"]]
    t = df["ts"].dt.time
    checks = {
        "not_minute_aligned": (df["ts"].dt.second != 0),
        "outside_session": ~t.between(SESSION_OPEN, time(15, 29)),
        "bad_price": ~(prices > 0).all(axis=1),
        "inconsistent_ohlc": (df["high"] < prices[["open", "close"]].max(axis=1))
                             | (df["low"] > prices[["open", "close"]].min(axis=1)),
    }
    bad = pd.Series(False, index=df.index)
    for name, mask in checks.items():
        fresh = mask & ~bad
        if fresh.any():
            rejected[name] = int(fresh.sum())
        bad |= mask
    return df[~bad], rejected


# ---------------------------------------------------------------- planning
def plan_chunks(symbol: str, start: date, end: date, today: date) -> list[tuple[date, date]]:
    """Group the days still needed into requests Groww will accept."""
    with db.engine().connect() as c:
        done = {r[0] for r in c.execute(text(
            "SELECT day FROM fetch_log WHERE symbol=:s AND day BETWEEN :a AND :b"),
            {"s": symbol, "a": start, "b": end})}
    need, d = [], start
    while d <= end:
        # Yesterday and today are always refreshed: they may have been stored unfinished.
        if d.weekday() < 5 and (d >= today - timedelta(days=1) or d not in done):
            need.append(d)
        d += timedelta(days=1)
    chunks: list[tuple[date, date]] = []
    for d in need:
        if chunks and (d - chunks[-1][0]).days <= CHUNK_SPAN_DAYS and (d - chunks[-1][1]).days <= MAX_GAP_DAYS:
            chunks[-1] = (chunks[-1][0], d)
        else:
            chunks.append((d, d))
    return chunks


# ---------------------------------------------------------------- quality
def _missing_ranges(present: set[datetime], day: date) -> tuple[int, list[list[str]]]:
    ranges: list[list[str]] = []
    missing = 0
    t = datetime.combine(day, SESSION_OPEN)
    for _ in range(SESSION_MINUTES):
        if t not in present:
            missing += 1
            hm = t.strftime("%H:%M")
            if ranges and (datetime.strptime(ranges[-1][1], "%H:%M") + timedelta(minutes=1)).strftime("%H:%M") == hm:
                ranges[-1][1] = hm
            else:
                ranges.append([hm, hm])
        t += timedelta(minutes=1)
    return missing, ranges


def _spikes(day_df: pd.DataFrame) -> int:
    return int((day_df["close"].pct_change().abs() > SPIKE_PCT).sum())


def record_quality(symbol: str, start: date, end: date, today: date,
                   rejected_by_day: dict[date, int] | None = None,
                   outside_by_day: dict[date, int] | None = None) -> None:
    """Recompute quality for every weekday (and any session) in the range from stored candles."""
    df = db.load_candles(symbol, datetime.combine(start, time(0)), datetime.combine(end + timedelta(days=1), time(0)))
    by_day = {d: g for d, g in df.groupby(df["ts"].dt.date)} if not df.empty else {}
    days = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    days = {d for d in days if d.weekday() < 5} | set(by_day)
    rows = []
    for d in sorted(days):
        g = by_day.get(d)
        outside = (outside_by_day or {}).get(d, 0)
        if g is None:
            if d >= today:
                continue
            # A day with only out-of-hours candles is a special session (e.g. evening Muhurat trading).
            count, missing, ranges, spikes = 0, SESSION_MINUTES, [], 0
            status = "special_session" if outside else "no_data"
        else:
            count, spikes = len(g), _spikes(g)
            missing, ranges = _missing_ranges({t.to_pydatetime() for t in g["ts"]}, d)
            status = "in_progress" if d == today and missing else "complete" if not missing else "partial"
        rows.append({"s": symbol, "d": d, "c": count, "m": missing, "r": json.dumps(ranges), "sp": spikes,
                     "st": status, "x": (rejected_by_day or {}).get(d, 0), "o": outside})
    if not rows:
        return
    with db.engine().begin() as c:
        c.execute(text(
            "INSERT INTO data_day_quality (symbol, day, candles, missing_minutes, missing_ranges, rejected, "
            "outside_session, spikes, status) VALUES (:s,:d,:c,:m,CAST(:r AS JSONB),:x,:o,:sp,:st) "
            "ON CONFLICT (symbol, day) DO UPDATE SET candles=EXCLUDED.candles, missing_minutes=EXCLUDED.missing_minutes, "
            "missing_ranges=EXCLUDED.missing_ranges, rejected=EXCLUDED.rejected, outside_session=EXCLUDED.outside_session, "
            "spikes=EXCLUDED.spikes, status=EXCLUDED.status, checked_at=now()"), rows)


# ---------------------------------------------------------------- download
def _fatal(exc: Exception) -> bool:
    """Retrying can't fix a permission or credentials problem."""
    name, msg = type(exc).__name__, str(exc).lower()
    return "Authori" in name or "Authenti" in name or "Keys" in name or "forbidden" in msg


def _explain(exc: Exception) -> str:
    if "forbidden" in str(exc).lower():
        return ("Groww refused market data (403 Access forbidden). Your API access doesn't include it yet: "
                "activate the Trading API subscription, generate a new key, and try again.")
    return str(exc) or type(exc).__name__


def _update(run_id: int, **fields) -> None:
    sets = ", ".join(f"{k}=:{k}" for k in fields)
    with db.engine().begin() as c:
        c.execute(text(f"UPDATE data_downloads SET {sets} WHERE id=:id"), {**fields, "id": run_id})


def request_stop() -> None:
    _stop.set()


def recover_interrupted() -> int:
    """Mark downloads left 'running' by a previous process, so they can be resumed."""
    with db.engine().begin() as c:
        return c.execute(text("UPDATE data_downloads SET status='interrupted', finished_at=now(), "
                              "error='The app stopped during this download.' WHERE status='running'")).rowcount


def download(start: date, end: date, fetch=None, progress=None, symbol: str = SYMBOL, segment: str = SEGMENT) -> dict:
    """Download every day still needed in [start, end]. Safe to re-run after any failure."""
    fetch = fetch or default_fetch
    say = progress or (lambda *_: None)
    now = _now()
    today = now.date()
    end = min(end, today)
    if start > end:
        raise ValueError("Start date is after end date")
    _stop.clear()
    chunks = plan_chunks(symbol, start, end, today)
    with db.engine().begin() as c:
        run_id = c.execute(text("INSERT INTO data_downloads (symbol, start_date, end_date, chunks_total) "
                                "VALUES (:s,:a,:b,:n) RETURNING id"),
                           {"s": symbol, "a": start, "b": end, "n": len(chunks)}).scalar_one()
    totals = Counter()
    for i, (a, b) in enumerate(chunks):
        if _stop.is_set():
            _update(run_id, status="stopped", finished_at=_now())
            return {"id": run_id, "status": "stopped", "rows": totals["new"]}
        say(i / max(1, len(chunks)), f"{'NIFTY' if symbol == SYMBOL else symbol} {a:%d %b %Y} – {b:%d %b %Y}")
        start_ts, end_ts = datetime.combine(a, SESSION_OPEN), datetime.combine(b, SESSION_CLOSE)
        df = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                df = fetch(segment, symbol, start_ts, end_ts)
                break
            except Exception as exc:
                if _fatal(exc) or attempt == MAX_ATTEMPTS:
                    message = _explain(exc)
                    _update(run_id, status="failed", error=message, finished_at=_now())
                    raise DownloadError(message) from exc
                log.warning("chunk %s-%s attempt %d failed: %s", a, b, attempt, exc)
                _sleep(2 ** attempt)

        received = len(df)
        repeated = int(df["ts"].duplicated().sum()) if received else 0
        unique = df.drop_duplicates("ts") if received else df
        good, rejected = validate(unique, _now())
        stored = db.load_candles(symbol, start_ts, end_ts + timedelta(minutes=1))
        known = set(stored["ts"])
        overlap = int(good["ts"].isin(known).sum()) if len(good) else 0
        db.upsert_candles(symbol, good)

        bad_rows = unique[~unique.index.isin(good.index) & (unique["ts"] + pd.Timedelta(minutes=1) <= _now())] if received else unique
        out_mask = ~bad_rows["ts"].dt.time.between(SESSION_OPEN, time(15, 29)) if len(bad_rows) else None
        per_day = lambda rows: rows.groupby(rows["ts"].dt.date).size().to_dict() if len(rows) else {}
        rejected_by_day = per_day(bad_rows[~out_mask]) if len(bad_rows) else {}
        outside_by_day = per_day(bad_rows[out_mask]) if len(bad_rows) else {}
        record_quality(symbol, a, b, today, rejected_by_day=rejected_by_day, outside_by_day=outside_by_day)
        counts = good.groupby(good["ts"].dt.date).size().to_dict() if len(good) else {}
        d = a
        while d <= b:
            if d.weekday() < 5 and d < today:
                db.mark_fetched(symbol, d, int(counts.get(d, 0)))
            d += timedelta(days=1)

        outside = rejected.pop("outside_session", 0)
        totals.update(received=received, new=len(good) - overlap, duplicate=repeated + overlap,
                      rejected=sum(rejected.values()), outside=outside)
        _update(run_id, chunks_done=i + 1, rows_received=totals["received"], rows_new=totals["new"],
                rows_duplicate=totals["duplicate"], rows_rejected=totals["rejected"],
                rows_outside_session=totals["outside"])
    _update(run_id, status="done", finished_at=_now())
    say(1.0, "Download complete")
    return {"id": run_id, "status": "done", "rows": totals["new"], "chunks": len(chunks)}


# ---------------------------------------------------------------- futures (volume for VWAP)
def fut_symbol(expiry: date) -> str:
    return f"NSE-NIFTY-{expiry:%d%b%y}-FUT"


def monthly_expiries(start: date, end: date) -> list[date]:
    """Expiry of each month's NIFTY future, confirmed against Groww's contract list.

    The monthly expiry is normally the month's last expiry, but holidays move it, so
    each month's expiries are checked (latest first) until one lists a -FUT contract.
    Confirmed dates are stored under dataset 'groww_fut'.
    """
    from app.services.market_data import providers
    prov = providers.GrowwProvider()
    exps = prov.ensure_expiries(start, end)
    have = set(db.load_expiries("groww_fut"))
    done = {(e.year, e.month) for e in have}
    by_month: dict[tuple[int, int], list[date]] = {}
    for e in exps:
        if start <= e <= end + timedelta(days=45):
            by_month.setdefault((e.year, e.month), []).append(e)
    for ym, candidates in sorted(by_month.items()):
        if ym in done:
            continue
        for e in sorted(candidates, reverse=True):
            resp = prov._call("get_contracts", exchange="NSE", underlying_symbol="NIFTY", expiry_date=e.isoformat())
            from app.services.market_data import providers as _p
            if any(str(x).upper().endswith("-FUT") for x in _p._first_list(resp)):
                db.save_expiries("groww_fut", [e])
                break
    return sorted(db.load_expiries("groww_fut"))


def front_month_ranges(start: date, end: date, expiries: list[date]) -> list[tuple[str, date, date]]:
    """(contract, first day, last day) for the near-month future, rolling on expiry day."""
    out, prev = [], None
    for e in sorted(expiries):
        a = max(start, prev if prev else start)
        b = min(end, e - timedelta(days=1))
        if a <= b:
            out.append((fut_symbol(e), a, b))
        prev = e
        if e > end:
            break
    return out


def download_futures(start: date, end: date, fetch=None, progress=None) -> dict:
    say = progress or (lambda *_: None)
    ranges = front_month_ranges(start, min(end, _now().date()), monthly_expiries(start, end + timedelta(days=45)))
    rows = 0
    for i, (sym, a, b) in enumerate(ranges):
        say(i / max(1, len(ranges)), f"Futures {sym[10:17]}: {a:%d %b %Y} – {b:%d %b %Y}")
        rows += download(a, b, fetch=fetch, symbol=sym, segment="FNO")["rows"]
    return {"rows": rows, "contracts": len(ranges)}


def download_all(start: date, end: date, fetch=None, progress=None) -> dict:
    """NIFTY spot, then near-month futures (the volume source for VWAP and volume checks)."""
    say = progress or (lambda *_: None)
    spot = download(start, end, fetch=fetch, progress=lambda f, m: say(f * 0.6, m))
    fut = download_futures(start, end, fetch=fetch, progress=lambda f, m: say(0.6 + f * 0.4, m))
    return {"spot": spot, "futures": fut}


def futures_1m(start: date, end: date) -> pd.DataFrame:
    """Continuous near-month futures candles, contract by contract. Never back-adjusted."""
    frames = []
    for sym, a, b in front_month_ranges(start, end, db.load_expiries("groww_fut")):
        df = db.load_candles(sym, datetime.combine(a, time(0)), datetime.combine(b + timedelta(days=1), time(0)))
        if not df.empty:
            frames.append(df.assign(contract=sym))
    if not frames:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "oi", "contract"])
    return pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)


# ---------------------------------------------------------------- reports
def default_target() -> tuple[date, date]:
    today = _now().date()
    try:
        return today.replace(year=today.year - TARGET_YEARS), today
    except ValueError:   # 29 Feb
        return today.replace(year=today.year - TARGET_YEARS, day=28), today


def _periods(days: list[date]) -> list[dict]:
    """Merge weekdays into contiguous periods (a weekend doesn't break a period)."""
    out: list[dict] = []
    for d in days:
        if out:
            prev = date.fromisoformat(out[-1]["to"])
            between = [prev + timedelta(days=k) for k in range(1, (d - prev).days)]
            if all(x.weekday() >= 5 for x in between):
                out[-1]["to"] = d.isoformat()
                out[-1]["days"] += 1
                continue
        out.append({"from": d.isoformat(), "to": d.isoformat(), "days": 1})
    return out


def coverage(start: date | None = None, end: date | None = None, symbol: str = SYMBOL) -> dict:
    """What is stored for the window, what is missing, and how good it is."""
    d_start, d_end = default_target()
    start, end = start or d_start, end or d_end
    now = _now()
    with db.engine().connect() as c:
        q = {r.day: r for r in c.execute(text(
            "SELECT day, candles, missing_minutes, missing_ranges, rejected, outside_session, spikes, status "
            "FROM data_day_quality "
            "WHERE symbol=:s AND day BETWEEN :a AND :b ORDER BY day"), {"s": symbol, "a": start, "b": end})}
    last_expected = end if now.date() > end or now.time() >= time(9, 16) else end - timedelta(days=1)
    weekdays, d = [], start
    while d <= min(last_expected, now.date()):
        if d.weekday() < 5:
            weekdays.append(d)
        d += timedelta(days=1)
    days = sorted(set(weekdays) | set(q))
    months: dict[str, Counter] = {}
    not_downloaded, no_data, special = [], [], []
    for d in days:
        row = q.get(d)
        status = row.status if row else "not_downloaded"
        months.setdefault(f"{d:%Y-%m}", Counter())[status] += 1
        if status == "not_downloaded":
            not_downloaded.append(d)
        elif status == "no_data":
            no_data.append(d)
        elif status == "special_session":
            special.append(d)
    sessions = [r for r in q.values() if r.candles > 0]
    summary = db.data_summary(symbol)
    complete = sum(r.status == "complete" for r in q.values())
    partial = [r for r in q.values() if r.status == "partial"]
    in_window_first = min((r.day for r in sessions), default=None)
    if not sessions:
        verdict = "none"
    elif not_downloaded or (in_window_first and (in_window_first - start).days > 7):
        verdict = "partial"
    else:
        verdict = "full"
    return {
        "symbol": symbol,
        "target": {"from": start.isoformat(), "to": end.isoformat()},
        "verdict": verdict,
        "summary": {
            "sessions": len(sessions), "weekdays": len(weekdays), "complete": complete, "partial": len(partial),
            "no_data": len(no_data), "not_downloaded": len(not_downloaded),
            "candles": sum(r.candles for r in sessions),
            "missing_minutes": sum(r.missing_minutes for r in sessions),
            "rejected": sum(r.rejected for r in q.values()), "spikes": sum(r.spikes for r in q.values()),
            "outside_session": sum(r.outside_session for r in q.values()), "special_sessions": len(special),
            "first": summary["first"], "last": summary["last"],
            "coverage_pct": round(100 * len(sessions) / max(1, len(sessions) + len(not_downloaded)), 1),
        },
        "months": [{"month": m, **c} for m, c in sorted(months.items())],
        "not_downloaded": _periods(not_downloaded),
        "no_data": _periods(no_data),
        "special_sessions": [d.isoformat() for d in special],
        "partial_days": [{"day": r.day.isoformat(), "candles": r.candles, "missing": r.missing_minutes,
                          "ranges": r.missing_ranges} for r in partial][-200:],
    }


def downloads(limit: int = 15, symbol: str = SYMBOL) -> list[dict]:
    with db.engine().connect() as c:
        rows = [dict(r) for r in c.execute(text(
            "SELECT * FROM data_downloads WHERE symbol=:s ORDER BY id DESC LIMIT :n"),
            {"s": symbol, "n": limit}).mappings()]
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, (datetime, date)):
                r[k] = v.isoformat()
    return rows


def candles(start: date, end: date, tf: int, symbol: str = SYMBOL) -> dict:
    """Stored candles for the chart, at 1/5/15/30 minutes. Bars still forming are left out."""
    if tf not in (1, 5, 15, 30):
        raise ValueError("timeframe must be 1, 5, 15 or 30")
    if start > end:
        raise ValueError("Start date is after end date")
    df = db.load_candles(symbol, datetime.combine(start, time(0)), datetime.combine(end + timedelta(days=1), time(0)))
    now = _now()
    df = df[df["ts"] + pd.Timedelta(minutes=1) <= now]
    bars = st.resample(df, tf)
    if not df.empty and df["ts"].max().date() == now.date():
        asof = df["ts"].max() + pd.Timedelta(minutes=1)
        bars = bars[bars["close_ts"] <= asof]
    if len(bars) > MAX_CHART_BARS:
        raise ValueError(f"That range has {len(bars):,} bars. Choose a shorter range or a larger timeframe.")
    return {"bars": [{"t": r.start.isoformat(), "o": r.open, "h": r.high, "l": r.low, "c": r.close}
                     for r in bars.itertuples(index=False)]}


def instruments() -> dict:
    """What is stored per instrument: spot, near-month futures and option contracts."""
    spot = db.data_summary(SYMBOL)
    with db.engine().connect() as c:
        fut = c.execute(text(
            "SELECT count(DISTINCT symbol), max(day) FILTER (WHERE rows > 0), sum(rows) FROM fetch_log "
            "WHERE symbol LIKE 'NSE-NIFTY-%-FUT'")).fetchone()
        fut_last = c.execute(text(
            "SELECT symbol, max(ts) FROM candles_1m WHERE symbol = ("
            "  SELECT symbol FROM fetch_log WHERE symbol LIKE 'NSE-NIFTY-%-FUT' AND rows > 0 ORDER BY day DESC LIMIT 1"
            ") GROUP BY 1")).fetchone()
        opt = c.execute(text(
            "SELECT count(DISTINCT symbol), min(day) FILTER (WHERE rows > 0), max(day) FILTER (WHERE rows > 0), sum(rows) "
            "FROM fetch_log WHERE symbol LIKE 'NSE-NIFTY-%' AND symbol NOT LIKE '%-FUT'")).fetchone()
        last_ok = {r[0]: r[1] for r in c.execute(text(
            "SELECT CASE WHEN symbol = :s THEN 'spot' WHEN symbol LIKE '%-FUT' THEN 'futures' ELSE 'options' END, "
            "max(finished_at) FROM data_downloads WHERE status = 'done' GROUP BY 1"), {"s": SYMBOL})}
    iso = lambda v: v.isoformat() if v else None
    return {
        "spot": {"symbol": SYMBOL, "first": spot["first"], "last": spot["last"], "candles": spot["rows"],
                 "sessions": spot["days"], "last_success": iso(last_ok.get("spot"))},
        "futures": {"contracts": fut[0], "last_day": iso(fut[1]), "candles": int(fut[2] or 0),
                    "latest_contract": fut_last[0] if fut_last else None, "last": iso(fut_last[1]) if fut_last else None,
                    "last_success": iso(last_ok.get("futures"))},
        "options": {"contracts": opt[0], "first_day": iso(opt[1]), "last_day": iso(opt[2]), "candles": int(opt[3] or 0),
                    "last_success": iso(last_ok.get("options"))},
        "intervals": [1, 5, 15, 30],
    }

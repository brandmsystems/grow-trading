"""Pre-market analysis: build the day's report, store it, recalculate when data changes, settle it after the close,
measure how it did, and give the trading engine a read-only stamp. No Flask imports. Paper trading only: nothing here
can place an order, and the stamp is an extra column of information in a paper trade, never an entry signal.

Causality: every figure is read as of `now`. NIFTY candles are cut at `now`; today's daily bar is never part of the
daily indicators; the opening gap is used only once today's first candle exists. Missing data scores 0 and is flagged.
"""
from __future__ import annotations

import json
import logging
import threading
import time as _time
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.database import db
from app.services.market_data import history as data_manager
from app.services.premarket import news_analysis, scoring, sources
from app.services.strategy import bias
from app.utils.timeutil import now_naive

log = logging.getLogger("premarket")
_now = now_naive
SPOT = "NSE-NIFTY"
FLAT_PCT = 0.15              # a day that closed within +-0.15% of the previous close counts as flat when settling
NEWS_HOURS = 96              # articles back to the previous trading day (a Monday needs the weekend and Friday)
REPORT_NEWS = 60             # articles kept in the stored report
RUN_AT = [time(8, 30), time(8, 55), time(9, 10), time(9, 30)]       # pre-open refreshes, then half-hourly until 15:30
SETTLE_AT = time(15, 45)
lock = threading.Lock()


def _eng(eng=None):
    return eng or db.engine()


# ------------------------------------------------------------------ NIFTY structure (closed candles only)
def nifty_structure(now: datetime, eng=None) -> dict | None:
    start = now - timedelta(days=430)
    spot = db.load_candles(SPOT, start, now, eng=eng)
    spot = spot[spot["ts"] < now]
    if spot.empty:
        return None
    today = now.date()
    try:
        fut = data_manager.futures_1m(start.date(), now.date())
        fut = fut[fut["ts"] < now] if fut is not None and not fut.empty else None
    except Exception:
        fut = None
    days = bias.tf_bars(spot, fut, 375)                               # one bar per session
    days = days[days["day"] < today].reset_index(drop=True)
    if len(days) < 60:
        return None
    last = days.iloc[-1]
    dv = bias.votes(days)
    ds = bias.tf_score(dv, bias.INDICATORS).iloc[-1]
    b15 = bias.tf_bars(spot, fut, 15)
    m15 = bias.tf_score(bias.votes(b15), bias.INDICATORS).iloc[-1] if not b15.empty else np.nan
    h, lo = days["high"].to_numpy(), days["low"].to_numpy()
    swing = 1.0 if h[-1] > h[-2] > h[-3] and lo[-1] > lo[-2] > lo[-3] else -1.0 if h[-1] < h[-2] < h[-3] and lo[-1] < lo[-2] < lo[-3] else 0.0
    atr_d = float(last["atr"]) if pd.notna(last["atr"]) else None
    ts_today = spot[spot["ts"].dt.date == today]
    gap_vote, gap_txt = None, "unknown until the market opens (Gift Nifty is not available)"
    if not ts_today.empty and atr_d:
        gap = float(ts_today.iloc[0]["open"]) - float(last["close"])
        gap_vote = float(np.clip(gap / (0.5 * atr_d), -1, 1))
        gap_txt = f"{'gap-up' if gap > 0 else 'gap-down' if gap < 0 else 'flat open'} {gap:+.1f} pts ({gap / float(last['close']) * 100:+.2f}%)"
    close = float(last["close"])
    pivot = (float(last["high"]) + float(last["low"]) + close) / 3
    hi20, lo20 = float(days["high"].tail(20).max()), float(days["low"].tail(20).min())
    cand = {"Previous-day high": float(last["high"]), "Previous-day low": float(last["low"]), "Pivot": pivot,
            "R1": 2 * pivot - float(last["low"]), "S1": 2 * pivot - float(last["high"]), "20-day high": hi20, "20-day low": lo20,
            "Daily EMA 21": float(last["ema21"]), "Daily EMA 50": float(last["ema50"]), "Daily EMA 200": float(last["ema200"])}
    cand = {k: round(v, 1) for k, v in cand.items() if pd.notna(v)}
    sup = sorted(((k, v) for k, v in cand.items() if v < close), key=lambda kv: -kv[1])[:3]
    res = sorted(((k, v) for k, v in cand.items() if v > close), key=lambda kv: kv[1])[:3]
    w = lambda x: "bullish" if x is not None and x >= 0.2 else "bearish" if x is not None and x <= -0.2 else "mixed"     # noqa: E731
    f = lambda v: "n/a" if pd.isna(v) else f"{v:,.1f}"                                                                    # noqa: E731
    rows = [("Daily trend", f"{w(ds)} (score {ds:+.2f})" if pd.notna(ds) else "n/a"),
            ("15-minute trend", f"{w(m15)} (score {m15:+.2f})" if pd.notna(m15) else "n/a"),
            ("Higher highs / lows", {1.0: "higher highs and higher lows (3 sessions)", -1.0: "lower highs and lower lows (3 sessions)", 0.0: "no clean sequence"}[swing]),
            ("EMA 9 / 21 / 50 / 200 (daily)", " / ".join(f(last[f"ema{n}"]) for n in (9, 21, 50, 200))),
            ("RSI 14 (daily)", f(last["rsi"])), ("MACD histogram (daily)", f"{last['macd_hist']:+.1f}" if pd.notna(last["macd_hist"]) else "n/a"),
            ("Bollinger bands (daily)", f"{f(last['bb_lo'])} to {f(last['bb_up'])}"),
            ("Previous session VWAP (futures)", f(last["fut_vwap"]) + (f", close {'above' if last['fut_close'] > last['fut_vwap'] else 'below'}" if pd.notna(last["fut_close"]) and pd.notna(last["fut_vwap"]) else "")),
            ("Previous-day high / low", f"{last['high']:,.1f} / {last['low']:,.1f}"), ("Opening gap", gap_txt)]
    last_ts = spot["ts"].iloc[-1].to_pydatetime()
    warn = []
    if fut is None:
        warn.append("No futures candles: the VWAP and volume votes were left out.")
    expected = today - timedelta(days=3 if today.weekday() == 0 else 1)
    if days["day"].iloc[-1] < expected:
        warn.append(f"The latest stored session is {days['day'].iloc[-1]}; newer NIFTY candles are missing (Data page).")
    return {"day": str(last["day"]), "open": float(last["open"]), "high": float(last["high"]), "low": float(last["low"]), "close": close,
            "daily_score": None if pd.isna(ds) else float(ds), "m15_score": None if pd.isna(m15) else float(m15), "swing": swing, "gap_vote": gap_vote,
            "rows": rows, "asof": last_ts.isoformat(timespec="minutes"), "warnings": warn,
            "freshness": f"stored candles up to {last_ts:%d %b %H:%M}",
            "headline": f"previous close {close:,.1f}; " + rows[0][1] + " daily, " + rows[1][1] + " on 15m.",
            "levels": {"support": [{"name": k, "price": v} for k, v in sup], "resistance": [{"name": k, "price": v} for k, v in res],
                       "breakout": round(float(last["high"]), 1), "breakdown": round(float(last["low"]), 1), "pivot": round(pivot, 1),
                       "previous_close": round(close, 1)}}


# ------------------------------------------------------------------ manual inputs
def latest_fii(now: datetime, eng=None) -> dict | None:
    """The most recent FII/DII entry describing a day BEFORE today, at most 5 days old."""
    with _eng(eng).connect() as c:
        r = c.execute(text("SELECT for_day, payload, source, entered_at FROM premarket_inputs WHERE kind='fii_dii' AND for_day < :d AND for_day >= :a "
                           "ORDER BY for_day DESC, entered_at DESC LIMIT 1"), {"d": now.date(), "a": now.date() - timedelta(days=5)}).first()
    if not r:
        return None
    return {**r[1], "day": str(r[0]), "source": r[2] or "entered by hand", "entered_at": r[3].replace(tzinfo=None).isoformat(timespec="minutes")}


NUM = ("fii_net_cash", "dii_net_cash", "fii_index_fut_long", "fii_index_fut_short")


def add_input(kind: str, for_day: date, payload: dict, source: str | None, now: datetime, eng=None) -> dict:
    """Store figures entered by hand. FII/DII must describe a day before today; nothing in the future is accepted."""
    if kind == "fii_dii":
        if for_day >= now.date():
            raise ValueError("FII/DII figures must be for a day before today.")
        clean = {}
        for k in NUM:
            if payload.get(k) not in (None, ""):
                try:
                    clean[k] = float(payload[k])
                except (TypeError, ValueError):
                    raise ValueError(f"{k} must be a number.")
        if not clean:
            raise ValueError("Enter at least one figure.")
    elif kind == "event":
        title = str(payload.get("title") or "").strip()
        if not title or for_day != now.date():
            raise ValueError("An event needs a title and today's date.")
        clean = {"title": title[:200]}
    else:
        raise ValueError("Unknown input kind.")
    with _eng(eng).begin() as c:
        c.execute(text("INSERT INTO premarket_inputs (kind, for_day, payload, source) VALUES (:k,:d,CAST(:p AS JSONB),:s)"),
                  {"k": kind, "d": for_day, "p": json.dumps(clean), "s": (source or "entered by hand")[:120]})
    return clean


def todays_events(now: datetime, eng=None) -> list[dict]:
    with _eng(eng).connect() as c:
        rows = c.execute(text("SELECT payload FROM premarket_inputs WHERE kind='event' AND for_day=:d ORDER BY id"), {"d": now.date()}).all()
    return [{"kind": "event", "title": r[0]["title"], "basis": "entered by hand"} for r in rows]


# ------------------------------------------------------------------ build and store
def _events(now: datetime, news: list[dict], eng=None) -> tuple[list[dict], bool]:
    """Today's events: the weekly expiry, events typed in, and headlines that mention something happening today (unverified)."""
    events = todays_events(now, eng) + scoring.headline_events(news, now)
    expiry = _expiry_today(now.date(), eng)
    if expiry:
        events.insert(0, {"kind": "calendar", "title": "Weekly NIFTY options expiry", "basis": "from the stored expiry list"})
    return events, expiry


def news_feed(now: datetime | None = None, eng=None, force: bool = False) -> dict:
    """The live news page: every article from the feeds (related coverage combined, analysed), today's events and the state of each
    source. `status` is live, stale (a refresh failed: the last good fetch is shown with its own time) or unavailable (nothing)."""
    now = now or _now()
    r = sources.fetch_news(now, force=force)
    arts = news_analysis.analyze(r["items"], now)
    try:
        events, _ = _events(now, arts, eng)
    except Exception as exc:
        log.warning("events failed: %s", exc)
        events = []
    feeds = r["feeds"]
    publishers: dict = {}
    for f in feeds:
        if f["kind"] == "feed":
            p = publishers.setdefault(f["name"], {"name": f["name"], "feeds_ok": 0, "feeds": 0, "articles": 0})
            p["feeds"] += 1
            p["feeds_ok"] += 1 if f["ok"] else 0
            p["articles"] += f["count"]
    searches = [f for f in feeds if f["kind"] == "search"]
    cnt = news_analysis.counts(arts)
    status = "unavailable" if not r["items"] and not any(f["ok"] and f["count"] for f in feeds) else "stale" if r["stale"] else "live"
    return {"now": now.isoformat(timespec="seconds"), "fetched_at": r["fetched_at"].isoformat(timespec="seconds") if r["fetched_at"] else None,
            "status": status, "cached": r["cached"], "articles": arts, "events": events,
            "categories": [{"key": k, "label": lbl, "count": cnt[k]} for k, lbl in news_analysis.CATEGORIES],
            "periods": [{"key": k, "label": lbl} for k, lbl in news_analysis.PERIODS], "summary": news_analysis.feed_summary(arts),
            "sources": {"publishers": list(publishers.values()), "searches_ok": sum(1 for f in searches if f["ok"]), "searches": len(searches)},
            "warnings": r["warnings"], "previous_trading_day": str(news_analysis.previous_trading_day(now.date())),
            "method": "Sentiment, NIFTY direction, impact level, sectors and the reason it matters come from fixed keyword rules applied to the "
                      "publisher's headline and summary. A rough first read, not a forecast. Summaries are the publisher's own."}


def _expiry_today(day: date, eng=None) -> bool:
    try:
        return day in set(db.load_expiries("groww", eng=eng))
    except Exception:
        return False


def build(now: datetime | None = None, quotes: dict | None = None, news_items: list | None = None, structure: dict | None = None,
          fii: dict | None = None, eng=None) -> dict:
    """The full report for `now` (inputs may be passed in for tests; otherwise fetched). Not stored."""
    now = now or _now()
    q = quotes if quotes is not None else sources.quotes()
    if news_items is None:
        news_items, news_warn = sources.news(now, max_age_h=NEWS_HOURS)
    else:
        news_warn = []
    st = structure if structure is not None else nifty_structure(now, eng)
    fii = fii if fii is not None else latest_fii(now, eng)
    factors = [scoring.global_factor(q), scoring.fii_factor(fii, str(now.date())), scoring.crude_factor(q), scoring.vix_factor(q),
               scoring.structure_factor(st)]
    tot = scoring.total(factors)
    articles = news_analysis.analyze(news_items, now)
    news = articles[:REPORT_NEWS]
    evidence = news_analysis.factor_evidence(articles, factors, now=now)       # evidence only: scores come from market data
    for f in factors:
        f["news"] = evidence.get(f["key"], [])
    events, expiry = _events(now, news, eng)
    concl = scoring.conclusion(factors, (st or {}).get("levels", {}), tot, events, expiry)
    warnings = [w for f in factors for w in f["warnings"]] + news_warn
    if not news:
        warnings.append("No headlines from trusted outlets could be fetched." if news_warn else "No relevant headlines since the previous trading day.")
    return {"day": str(now.date()), "generated_at": now.isoformat(timespec="seconds"), "total": tot, "factors": factors, "conclusion": concl,
            "news": news, "news_meta": {**news_analysis.feed_summary(articles), "fetched_at": now.isoformat(timespec="seconds")},
            "events": events, "warnings": warnings,
            "unavailable": {k: v for k, v in sources.UNAVAILABLE.items() if k != "fii_dii" or not fii},
            "note": "Pre-market direction is context, not a trade signal. It has not been validated as a predictor (see docs/PREMARKET.md)."}


def _signature(rep: dict) -> list:
    return [rep["total"]["total"]] + [f["score"] for f in rep["factors"]]


def save(rep: dict, eng=None) -> dict:
    """Upsert today's row; append a snapshot only when the total or any factor changed. Returns {changed, report}."""
    e = _eng(eng)
    day = date.fromisoformat(rep["day"])
    c = rep["conclusion"]
    with lock, e.begin() as cx:
        row = cx.execute(text("SELECT report, snapshots FROM premarket_reports WHERE day=:d FOR UPDATE"), {"d": day}).first()
        snaps = list(row[1]) if row else []
        changed = row is None or _signature(row[0]) != _signature(rep)
        if changed:
            snaps.append({"at": rep["generated_at"], "total": rep["total"]["total"], "scores": {f["key"]: f["score"] for f in rep["factors"]}})
        if row:
            cx.execute(text("UPDATE premarket_reports SET updated_at=now(), total_score=:t, bias=:b, preference=:p, confidence=:c, "
                            "report=CAST(:r AS JSONB), snapshots=CAST(:s AS JSONB) WHERE day=:d"),
                       {"t": rep["total"]["total"], "b": rep["total"]["bias"], "p": c["preference"], "c": c["confidence"],
                        "r": json.dumps(rep, default=str), "s": json.dumps(snaps), "d": day})
        else:
            cx.execute(text("INSERT INTO premarket_reports (day, total_score, bias, preference, confidence, report, snapshots) "
                            "VALUES (:d,:t,:b,:p,:c,CAST(:r AS JSONB),CAST(:s AS JSONB))"),
                       {"t": rep["total"]["total"], "b": rep["total"]["bias"], "p": c["preference"], "c": c["confidence"],
                        "r": json.dumps(rep, default=str), "s": json.dumps(snaps), "d": day})
    return {"changed": changed, "snapshots": snaps}


def refresh(now: datetime | None = None, eng=None) -> dict:
    now = now or _now()
    rep = build(now, eng=eng)
    out = save(rep, eng)
    return {**rep, "changed": out["changed"], "snapshots": out["snapshots"]}


def get(day: date, eng=None) -> dict | None:
    with _eng(eng).connect() as c:
        r = c.execute(text("SELECT report, snapshots, actual, outcome, updated_at FROM premarket_reports WHERE day=:d"), {"d": day}).first()
    if not r:
        return None
    return {**r[0], "snapshots": r[1], "actual": r[2], "outcome": r[3], "updated_at": r[4].replace(tzinfo=None).isoformat(timespec="seconds")}


# ------------------------------------------------------------------ after the close
def outcome_for(total: int, change_pct: float) -> str:
    """CORRECT / INCORRECT when the day's bias (|total| >= 2) had a direction and the day was not flat; NEUTRAL otherwise."""
    if abs(total) < 2 or abs(change_pct) < FLAT_PCT:
        return "NEUTRAL"
    return "CORRECT" if (total > 0) == (change_pct > 0) else "INCORRECT"


def actual_for(day: date, eng=None) -> dict | None:
    """NIFTY open/high/low/close of a finished day: stored candles first, then Yahoo's daily bars."""
    e = _eng(eng)
    df = db.load_candles(SPOT, datetime.combine(day - timedelta(days=7), time(0)), datetime.combine(day + timedelta(days=1), time(0)), eng=e)
    if not df.empty and (df["ts"].dt.date == day).any():
        d = df[df["ts"].dt.date == day]
        prev = df[df["ts"].dt.date < day]
        if len(prev):
            return {"open": float(d.iloc[0]["open"]), "high": float(d["high"].max()), "low": float(d["low"].min()),
                    "close": float(d.iloc[-1]["close"]), "prev_close": float(prev.iloc[-1]["close"]), "source": "stored candles"}
    bars = sources.nifty_daily("1mo")
    byday = {b["day"]: b for b in bars}
    if day in byday:
        earlier = [b for b in bars if b["day"] < day]
        if earlier:
            b = byday[day]
            return {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "prev_close": earlier[-1]["close"], "source": "Yahoo Finance"}
    return None


def settle(day: date, eng=None) -> bool:
    """Fill in what NIFTY actually did for a finished day and score the report. False if the data is not there yet."""
    rep = get(day, eng)
    if not rep or rep.get("actual"):
        return False
    a = actual_for(day, eng)
    if not a:
        return False
    chg = (a["close"] / a["prev_close"] - 1) * 100
    a.update(change_pct=round(chg, 2), open_to_close_pct=round((a["close"] / a["open"] - 1) * 100, 2),
             gap_pct=round((a["open"] / a["prev_close"] - 1) * 100, 2),
             direction="UP" if chg >= FLAT_PCT else "DOWN" if chg <= -FLAT_PCT else "FLAT")
    out = outcome_for(rep["total"]["total"], chg)
    with _eng(eng).begin() as c:
        c.execute(text("UPDATE premarket_reports SET actual=CAST(:a AS JSONB), outcome=:o WHERE day=:d"), {"a": json.dumps(a), "o": out, "d": day})
    return True


def settle_pending(now: datetime | None = None, eng=None) -> int:
    now = now or _now()
    with _eng(eng).connect() as c:
        days = [r[0] for r in c.execute(text("SELECT day FROM premarket_reports WHERE actual IS NULL AND day < :t OR (actual IS NULL AND day = :t AND :h) ORDER BY day"),
                                        {"t": now.date(), "h": now.time() >= SETTLE_AT})]
    return sum(1 for d in days if settle(d, eng))


# ------------------------------------------------------------------ history and effectiveness
def history(limit: int = 60, eng=None) -> dict:
    """Stored days with the result and the paper-trading outcome of that day, plus accuracy so far (counts, never a claim)."""
    with _eng(eng).connect() as c:
        rows = c.execute(text("SELECT r.day, r.total_score, r.bias, r.preference, r.confidence, r.actual, r.outcome, "
                              "(SELECT count(*) FROM live_trades t WHERE t.day=r.day AND t.trade_mode='paper' AND t.status='CLOSED'), "
                              "(SELECT COALESCE(sum(t.net),0) FROM live_trades t WHERE t.day=r.day AND t.trade_mode='paper' AND t.status='CLOSED') "
                              "FROM premarket_reports r ORDER BY r.day DESC LIMIT :n"), {"n": limit}).all()
    days = [{"day": str(r[0]), "total": r[1], "bias": r[2], "preference": r[3], "confidence": r[4], "actual": r[5], "outcome": r[6],
             "paper_trades": r[7], "paper_net": round(float(r[8]), 2)} for r in rows]
    called = [d for d in days if d["outcome"] in ("CORRECT", "INCORRECT")]
    ok = sum(1 for d in called if d["outcome"] == "CORRECT")
    acc = {"days": len(days), "settled": sum(1 for d in days if d["actual"]), "calls": len(called), "correct": ok,
           "hit_pct": round(100 * ok / len(called), 1) if called else None,
           "note": ("Too few days to say anything: a coin flip is within ±" + str(round(98 / max(len(called), 1) ** 0.5)) + " points of 50%." if len(called) < 100
                    else "Interpret against 50%, with the ± band for this many calls.")}
    return {"days": days, "accuracy": acc, "effectiveness": effectiveness(eng)}


def effectiveness(eng=None) -> list[dict]:
    """Paper and replay trades grouped by whether the pre-market bias agreed with the trade direction."""
    with _eng(eng).connect() as c:
        rows = c.execute(text("SELECT COALESCE(analysis->'premarket'->>'agrees','none') AS a, count(*), "
                              "count(*) FILTER (WHERE net > 0), COALESCE(sum(net),0) FROM live_trades "
                              "WHERE status='CLOSED' AND trade_mode IN ('paper','replay') AND analysis ? 'premarket' GROUP BY 1")).all()
    name = {"true": "agreed", "false": "opposed", "none": "no view (neutral or missing)"}
    return [{"group": name.get(r[0], r[0]), "trades": r[1], "wins": r[2], "win_pct": round(100 * r[2] / r[1], 1) if r[1] else None,
             "net": round(float(r[3]), 2)} for r in rows]


# ------------------------------------------------------------------ engine stamp
def stamp(day: date, direction: int, eng=None) -> dict | None:
    """What today's stored pre-market report says about a trade in `direction` (+1 CE side, -1 PE side). Read-only.
    agrees: True / False, or None when the bias is neutral or no report exists (then nothing is blocked)."""
    try:
        with _eng(eng).connect() as c:
            r = c.execute(text("SELECT total_score, bias, preference, confidence, updated_at FROM premarket_reports WHERE day=:d"), {"d": day}).first()
    except Exception:
        return None
    if not r:
        return None
    agrees = None if abs(r[0]) < 2 else (r[0] > 0) == (direction > 0)
    return {"total": r[0], "bias": r[1], "preference": r[2], "confidence": r[3], "agrees": agrees,
            "report_at": r[4].replace(tzinfo=None).isoformat(timespec="minutes")}


# ------------------------------------------------------------------ the daily schedule
def due(now: datetime, last_run: datetime | None, have_report: bool) -> bool:
    """True when a refresh should run: weekdays 08:30-15:30, at the pre-open times then every 30 minutes, and at once if
    today still has no report. Pure, so it can be tested."""
    if now.weekday() >= 5 or not (time(8, 30) <= now.time() <= time(15, 30)):
        return False
    if not have_report:
        return True
    marks = [datetime.combine(now.date(), t) for t in RUN_AT]
    t = datetime.combine(now.date(), time(10, 0))
    while t <= datetime.combine(now.date(), time(15, 30)):
        marks.append(t)
        t += timedelta(minutes=30)
    passed = [m for m in marks if m <= now]
    return bool(passed) and (last_run is None or last_run < max(passed))


_started = False


def start_scheduler(poll_sec: int = 60) -> None:
    """Background thread: refresh the report on the schedule above and settle finished days. Call once at server start."""
    global _started
    if _started:
        return
    _started = True

    def loop():
        last = None
        while True:
            try:
                now = _now()
                have = get(now.date()) is not None
                if due(now, last, have):
                    last = now
                    r = refresh(now)
                    log.info("pre-market report %s: %+d (%s)%s", r["day"], r["total"]["total"], r["total"]["bias"], " [changed]" if r["changed"] else "")
                if now.time() >= SETTLE_AT:
                    settle_pending(now)
            except Exception as exc:
                log.warning("pre-market scheduler: %s", exc)
            _time.sleep(poll_sec)

    threading.Thread(target=loop, name="premarket", daemon=True).start()

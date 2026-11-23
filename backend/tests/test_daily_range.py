"""Daily range dashboard: aggregation of 1-minute candles into daily OHLC and range statistics.

Runs on a throwaway database. Each expectation is computed independently from the seeded minutes.
"""
import time as clock
from datetime import date, datetime, time, timedelta

import pandas as pd
import psycopg2
import pytest

import app.main as app_module
from app.config import settings as config
from app.database import db
from app.services.market_data import daily_range as dr
from app.services.market_data import history as dm

TEST_DB = "groww_trading_test_range"
SYM = dm.SYMBOL
NOW = datetime(2026, 3, 20, 18, 0)          # a Friday evening, after the close


@pytest.fixture(autouse=True)
def test_db(monkeypatch):
    conn = psycopg2.connect(**{**config.PG, "dbname": "postgres"})
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {TEST_DB}")
    old = db._engine
    db._engine = db.engine(TEST_DB)
    db.init()
    monkeypatch.setattr(dr, "_now", lambda: NOW)
    dr.clear_cache()
    yield
    dr.clear_cache()
    db._engine.dispose()
    db._engine = old
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.close()


def minutes(day, n=375, base=22000.0, up=0.0, down=0.0, start=time(9, 15), skip=()):
    """`n` one-minute candles from `start`. open(i)=base+i, close(i)=base+i+1, high=close+1, low=open-1.
    A spike of `up` points above the high at minute 100 and `down` points below the low at minute 200."""
    rows = []
    t0 = datetime.combine(day, start)
    for i in range(n):
        if i in skip:
            continue
        o = base + i
        hi, lo = o + 2, o - 1
        if i == 100:
            hi += up
        if i == 200:
            lo -= down
        rows.append((t0 + timedelta(minutes=i), o, hi, lo, o + 1, 0.0, 0.0))
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "oi"])


def expected(day, n=375, base=22000.0, up=0.0, down=0.0):
    """OHLC of `minutes(...)`, worked out from the formula, not from the code under test."""
    return {"open": base, "high": max(base + n - 1 + 2, base + 100 + 2 + up), "low": min(base - 1, base + 200 - 1 - down),
            "close": base + n}


def store(day, **kw):
    db.upsert_candles(SYM, minutes(day, **kw))


def weekdays(end, count):
    out, d = [], end
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def seed(days, ranges, base=22000.0):
    """One complete session per day; day k has a high spike so its range is distinct."""
    for k, d in enumerate(days):
        store(d, base=base + k * 10, up=ranges[k % len(ranges)], down=0.0)


def get(day_list, **kw):
    out = dr.daily_range(day_list[0], day_list[-1], **kw)
    return {r["date"]: r for r in out["days"]}, out


# ----------------------------------------------------------------------------- OHLC accuracy

def test_daily_ohlc_matches_the_source_minutes():
    days = weekdays(date(2026, 3, 20), 6)
    for k, d in enumerate(days):
        store(d, base=22000 + 37 * k, up=15 * k, down=9 * k)
    rows, out = get(days)
    assert len(rows) == 6 and out["counts"] == {"days": 6, "complete": 6, "partial": 0, "in_progress": 0}
    for k, d in enumerate(days):
        r, e = rows[d.isoformat()], expected(d, base=22000 + 37 * k, up=15 * k, down=9 * k)
        assert (r["open"], r["high"], r["low"], r["close"]) == (e["open"], e["high"], e["low"], e["close"])
        assert r["range"] == round(e["high"] - e["low"], 2)
        assert r["range_pct"] == pytest.approx(100 * (e["high"] - e["low"]) / e["open"], abs=1e-3)
        assert r["candles"] == 375 and r["status"] == "complete" and (r["first"], r["last"]) == ("09:15", "15:29")


def test_open_and_close_are_the_first_and_last_minute_whatever_the_insert_order():
    d = date(2026, 3, 18)
    df = minutes(d).sample(frac=1, random_state=3)          # shuffled
    db.upsert_candles(SYM, df)
    r = get([d])[0][d.isoformat()]
    assert (r["open"], r["close"]) == (22000.0, 22375.0)


def test_change_uses_the_previous_session_close():
    days = weekdays(date(2026, 3, 20), 3)
    for k, d in enumerate(days):
        store(d, base=22000 + 100 * k)
    rows, _ = get(days)
    a, b, c = (rows[d.isoformat()] for d in days)
    assert a["prev_close"] is None and a["change"] is None and a["change_pct"] is None
    assert b["prev_close"] == a["close"] and b["prev_date"] == days[0].isoformat()
    assert b["change"] == round(b["close"] - a["close"], 2)
    assert c["change_pct"] == pytest.approx(100 * (c["close"] - b["close"]) / b["close"], abs=1e-3)


def test_the_first_day_of_a_window_still_gets_a_previous_close_from_before_it():
    days = weekdays(date(2026, 3, 20), 4)
    for k, d in enumerate(days):
        store(d, base=22000 + 100 * k)
    out = dr.daily_range(days[2], days[3])
    assert out["days"][0]["prev_date"] == days[1].isoformat()
    assert out["days"][0]["prev_close"] == 22100 + 375


# ----------------------------------------------------------------------------- dates, holidays, gaps

def test_weekends_and_days_without_candles_are_left_out():
    fri, sat, mon, tue = date(2026, 3, 6), date(2026, 3, 7), date(2026, 3, 9), date(2026, 3, 10)
    for d in (fri, sat, tue):               # Monday 9 Mar is a holiday: nothing stored
        store(d)
    rows, out = get([fri, tue])
    assert sorted(rows) == [fri.isoformat(), tue.isoformat()]
    assert sat.isoformat() not in rows and mon.isoformat() not in rows
    assert rows[tue.isoformat()]["prev_date"] == fri.isoformat()      # the holiday is skipped, nothing invented
    assert out["counts"]["days"] == 2


def test_missing_minutes_are_never_filled_in():
    d = date(2026, 3, 18)
    store(d, skip=range(10, 20))
    r = get([d])[0][d.isoformat()]
    assert r["candles"] == 365 and r["status"] == "partial"


def test_partial_sessions_are_flagged_and_kept_out_of_the_statistics():
    days = weekdays(date(2026, 3, 20), 5)
    for k, d in enumerate(days):
        if k == 2:
            store(d, n=120, up=900)                     # a gap: only 120 minutes, huge "range"
        else:
            store(d, base=22000 + 10 * k, up=20)
    rows, out = get(days)
    p = rows[days[2].isoformat()]
    assert p["status"] == "partial" and out["counts"] == {"days": 5, "complete": 4, "partial": 1, "in_progress": 0}
    done = [r for r in out["days"] if r["status"] == "complete"]
    assert out["summary"]["highest_range"]["date"] != days[2].isoformat()
    assert out["summary"]["adr"] == pytest.approx(sum(r["range"] for r in done) / 4, abs=0.01)
    # a partial session is not a previous close: the day after it compares with the one before it
    nxt = rows[days[3].isoformat()]
    assert nxt["prev_date"] == days[1].isoformat()
    # ...but its real prices still count for the period high
    assert out["summary"]["high"]["price"] == max(r["high"] for r in out["days"])


def test_a_short_special_session_is_partial_not_complete():
    d = date(2026, 3, 18)
    store(d, n=60, start=time(13, 45))                  # an evening-style short session
    r = get([d])[0][d.isoformat()]
    assert r["status"] == "partial" and (r["first"], r["last"]) == ("13:45", "14:44")


def test_from_equals_to_returns_just_that_day_and_dates_are_ist():
    days = weekdays(date(2026, 3, 20), 3)
    for d in days:
        store(d)
    one = dr.daily_range(days[1], days[1])
    assert [r["date"] for r in one["days"]] == [days[1].isoformat()]
    assert one["days"][0]["first"] == "09:15" and one["days"][0]["last"] == "15:29"
    # stored as instants: 09:15 IST is 03:45 UTC, still the same calendar day
    with db.engine().connect() as c:
        first_utc = c.exec_driver_sql("SELECT min(ts AT TIME ZONE 'UTC')::text FROM candles_1m").scalar()
    assert first_utc == f"{days[0]} 03:45:00"


def test_candles_near_midnight_ist_belong_to_their_ist_date_not_the_utc_date():
    prev, d = date(2026, 3, 17), date(2026, 3, 18)
    store(prev)
    # 00:05 IST on the 18th is 18:35 UTC on the 17th; 23:59 IST on the 17th is 18:29 UTC the same day
    stray = pd.DataFrame([(datetime(2026, 3, 18, 0, 5), 100.0, 101.0, 99.0, 100.5, 0.0, 0.0)],
                         columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    db.upsert_candles(SYM, stray)
    rows, _ = get([prev, d])
    assert rows["2026-03-17"]["candles"] == 375 and rows["2026-03-17"]["status"] == "complete"
    assert rows["2026-03-18"]["candles"] == 1 and rows["2026-03-18"]["open"] == 100.0


def test_invalid_prices_are_ignored():
    d = date(2026, 3, 18)
    df = minutes(d)
    df.loc[5, "low"] = 0                                 # zero price
    df.loc[6, ["high", "low"]] = [10.0, 20.0]            # high below low
    db.upsert_candles(SYM, df)
    r = get([d])[0][d.isoformat()]
    assert r["candles"] == 373 and r["status"] == "partial"


def test_today_in_progress_is_shown_but_not_averaged_and_the_forming_minute_is_excluded(monkeypatch):
    days = weekdays(date(2026, 3, 20), 12)
    for k, d in enumerate(days[:-1]):
        store(d, base=22000 + 10 * k, up=20)
    today = days[-1]
    store(today, n=200, up=0)                            # 09:15 .. 12:34
    monkeypatch.setattr(dr, "_now", lambda: datetime.combine(today, time(12, 30, 30)))   # 12:30 is still forming
    rows, out = get(days)
    r = rows[today.isoformat()]
    assert r["status"] == "in_progress" and r["last"] == "12:29" and r["candles"] == 195
    assert out["counts"] == {"days": 12, "complete": 11, "partial": 0, "in_progress": 1}
    assert r["avg10"] is None
    assert out["summary"]["current"] == {"price": r["close"], "date": today.isoformat(), "time": "12:29", "status": "in_progress"}
    assert out["summary"]["adr"] == pytest.approx(sum(x["range"] for x in out["days"][:-1]) / 11, abs=0.01)


# ----------------------------------------------------------------------------- range analysis

def test_trailing_averages_and_trend():
    days = weekdays(date(2026, 3, 20), 60)
    spikes = [10 + (k % 7) * 5 for k in range(60)]
    for k, d in enumerate(days):
        store(d, base=22000 + k, up=spikes[k] + 400)       # range = max(...)-low, distinct per day
    rows, out = get(days)
    rng = [rows[d.isoformat()]["range"] for d in days]
    assert rows[days[8].isoformat()]["avg10"] is None and rows[days[9].isoformat()]["avg10"] == pytest.approx(sum(rng[:10]) / 10, abs=0.01)
    assert rows[days[49].isoformat()]["avg50"] == pytest.approx(sum(rng[:50]) / 50, abs=0.01)
    assert rows[days[-1].isoformat()]["avg20"] == pytest.approx(sum(rng[-20:]) / 20, abs=0.01)
    t = out["analysis"]["trend"]
    assert t["avg10"] == pytest.approx(sum(rng[-10:]) / 10, abs=0.01) and t["avg50"] == pytest.approx(sum(rng[-50:]) / 50, abs=0.01)
    assert t["ratio"] == pytest.approx(t["avg10"] / t["avg50"], abs=1e-3) and t["label"] in ("expanding", "contracting", "steady")
    assert t["as_of"] == days[-1].isoformat()


def test_trend_labels_follow_the_band():
    days = weekdays(date(2026, 3, 20), 60)
    for k, d in enumerate(days):
        store(d, base=22000, up=(1500 if k >= 50 else 0))     # the last ten sessions are far wider
    assert dr.daily_range(days[0], days[-1])["analysis"]["trend"]["label"] == "expanding"
    dr.clear_cache()
    for k, d in enumerate(days):
        store(d, base=22000, up=(0 if k >= 50 else 1500))     # now far narrower (upsert replaces the minutes)
    assert dr.daily_range(days[0], days[-1])["analysis"]["trend"]["label"] == "contracting"


def test_highest_and_lowest_range_days():
    days = weekdays(date(2026, 3, 20), 15)
    ups = [400 + 7 * k for k in range(15)]
    ups[4], ups[9] = 1500, 0                                 # widest and narrowest
    for k, d in enumerate(days):
        store(d, base=22000, up=ups[k])
    s = dr.daily_range(days[0], days[-1])["summary"]
    assert s["highest_range"]["date"] == days[4].isoformat() and s["lowest_range"]["date"] == days[9].isoformat()
    assert s["highest_range"]["range"] > s["adr"] > s["lowest_range"]["range"]


def test_period_high_low_and_counts():
    days = weekdays(date(2026, 3, 20), 5)
    for k, d in enumerate(days):
        store(d, base=22000 + 50 * k, up=10 * k, down=5 * k)
    out = dr.daily_range(days[0], days[-1])
    s = out["summary"]
    assert s["high"] == {"price": max(r["high"] for r in out["days"]), "date": max(out["days"], key=lambda r: r["high"])["date"]}
    assert s["low"]["price"] == min(r["low"] for r in out["days"])
    assert s["bullish_days"] + s["bearish_days"] == 5
    assert s["current"]["price"] == out["days"][-1]["close"] and s["current"]["status"] == "complete"


def test_todays_range_against_the_average_and_utilization(monkeypatch):
    days = weekdays(date(2026, 3, 20), 12)
    for k, d in enumerate(days[:-1]):
        store(d, base=22000, up=300)                          # identical sessions: range 301
    today = days[-1]
    store(today, n=150, base=22000)                           # a quiet morning
    monkeypatch.setattr(dr, "_now", lambda: datetime.combine(today, time(11, 45)))
    cur = dr.daily_range(days[0], today)["analysis"]["current"]
    full = get(days[:-1])[0][days[-2].isoformat()]["range"]
    assert cur["date"] == today.isoformat() and cur["status"] == "in_progress"
    assert cur["adr"]["10"] == full and cur["adr"]["20"] is None          # only 11 earlier sessions exist
    assert cur["utilization"]["10"] == pytest.approx(100 * cur["range"] / full, abs=0.1)
    assert cur["remaining"]["10"] == pytest.approx(full - cur["range"], abs=0.01)


def test_utilization_can_exceed_100_and_remaining_never_goes_negative():
    days = weekdays(date(2026, 3, 20), 12)
    for k, d in enumerate(days):
        store(d, base=22000, up=(2000 if k == 11 else 10))
    cur = dr.daily_range(days[0], days[-1])["analysis"]["current"]
    assert cur["utilization"]["10"] > 100 and cur["remaining"]["10"] == 0.0


def test_the_current_day_never_enters_its_own_average():
    days = weekdays(date(2026, 3, 20), 11)
    for k, d in enumerate(days):
        store(d, base=22000, up=(2000 if k == 10 else 10))
    out = dr.daily_range(days[0], days[-1])
    quiet = out["days"][0]["range"]
    assert out["days"][-1]["range"] > 1000 and out["analysis"]["current"]["adr"]["10"] == quiet     # ten quiet sessions only


# ----------------------------------------------------------------------------- windows, errors, cache

def test_default_window_is_the_previous_year_ending_on_the_newest_session():
    store(date(2025, 3, 5))
    store(date(2026, 3, 18))
    out = dr.daily_range()
    assert out["window"] == {"from": "2025-03-19", "to": "2026-03-18"}
    assert [r["date"] for r in out["days"]] == ["2026-03-18"]            # 5 Mar 2025 is older than a year


def test_default_window_on_29_february():
    store(date(2024, 2, 29))
    assert dr.default_window() == (date(2023, 3, 1), date(2024, 2, 29))


def test_empty_database_and_empty_window_give_empty_results_not_errors():
    out = dr.daily_range()
    assert out["days"] == [] and out["summary"] is None and out["window"] is None
    store(date(2026, 3, 18))
    out = dr.daily_range(date(2026, 1, 1), date(2026, 1, 31))
    assert out["days"] == [] and out["summary"] is None and out["counts"]["days"] == 0
    assert out["analysis"]["current"]["date"] == "2026-03-18"            # the newest session is independent of the window


def test_bad_ranges_raise_value_error():
    with pytest.raises(ValueError, match="after end"):
        dr.daily_range(date(2026, 3, 10), date(2026, 3, 1))
    with pytest.raises(ValueError, match="both a start and an end"):
        dr.daily_range(date(2026, 3, 10), None)
    with pytest.raises(ValueError, match="at most 6 years"):
        dr.daily_range(date(2015, 1, 1), date(2026, 3, 1))


def test_results_are_cached_and_expire(monkeypatch):
    store(date(2026, 3, 18))
    calls, t = [], [1000.0]
    real = dr._aggregate
    monkeypatch.setattr(dr, "_aggregate", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    monkeypatch.setattr(dr, "_mono", lambda: t[0])
    a = dr.daily_range(date(2026, 3, 1), date(2026, 3, 20))
    n = len(calls)
    assert n >= 1 and dr.daily_range(date(2026, 3, 1), date(2026, 3, 20)) is a and len(calls) == n
    assert dr.daily_range(date(2026, 3, 2), date(2026, 3, 20)) is not a                 # another window is its own entry
    t[0] += dr.LIVE_TTL + 1
    assert dr.daily_range(date(2026, 3, 1), date(2026, 3, 20)) is not a                 # expired
    dr.clear_cache()
    assert not dr._cache


def test_old_windows_are_cached_longer_than_recent_ones():
    assert dr.HISTORY_TTL > dr.LIVE_TTL


# ----------------------------------------------------------------------------- API and speed

@pytest.fixture()
def client():
    return app_module.app.test_client()


def test_api_returns_the_daily_rows_for_a_window(client):
    days = weekdays(date(2026, 3, 20), 4)
    for d in days:
        store(d)
    body = client.get(f"/api/data/daily-range?from={days[0]}&to={days[-1]}").get_json()
    assert body["ok"] is True
    data = body["data"]
    assert data["window"] == {"from": days[0].isoformat(), "to": days[-1].isoformat()}
    assert [r["date"] for r in data["days"]] == [d.isoformat() for d in days]
    assert set(data["days"][0]) >= {"date", "open", "high", "low", "close", "range", "range_pct", "prev_close", "change", "change_pct", "status"}
    assert data["summary"]["current"]["price"] == data["days"][-1]["close"]


def test_api_defaults_to_the_previous_year_and_reports_errors(client):
    store(date(2026, 3, 18))
    assert client.get("/api/data/daily-range").get_json()["data"]["window"]["to"] == "2026-03-18"
    bad = client.get("/api/data/daily-range?from=2026-03-10&to=2026-03-01")
    assert bad.status_code == 400 and "after end" in bad.get_json()["error"]
    assert client.get("/api/data/daily-range?from=not-a-date&to=2026-03-01").status_code == 400
    assert client.get("/api/data/daily-range?from=2026-03-01").status_code == 400


def test_a_year_of_sessions_is_aggregated_quickly_and_only_daily_rows_are_returned(client):
    days = weekdays(date(2026, 3, 20), 250)
    frames = [minutes(d, base=22000 + k, up=k % 50) for k, d in enumerate(days)]
    db.upsert_candles(SYM, pd.concat(frames, ignore_index=True))
    t = clock.perf_counter()
    r = client.get(f"/api/data/daily-range?from={days[0]}&to={days[-1]}")
    took = clock.perf_counter() - t
    data = r.get_json()["data"]
    assert len(data["days"]) == 250 and data["counts"]["complete"] == 250
    assert len(r.data) < 400_000                      # 93,750 minutes in, a few hundred KB of daily rows out
    assert took < 3.0
    t = clock.perf_counter()
    client.get(f"/api/data/daily-range?from={days[0]}&to={days[-1]}")
    assert clock.perf_counter() - t < took            # the repeat is served from the cache

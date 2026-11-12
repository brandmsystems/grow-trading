"""Download manager, timezone storage, migrations and the data API, on a throwaway database."""
from datetime import date, datetime, time, timedelta

import pandas as pd
import psycopg2
import pytest
from sqlalchemy import text

import app.main as app_module
from app.config import settings as config
from app.services.market_data import history as dm
from app.database import db

TEST_DB = "groww_trading_test_data"
SYM = dm.SYMBOL


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
    monkeypatch.setattr(dm, "_now", lambda: datetime(2026, 3, 20, 18, 0))
    monkeypatch.setattr(dm, "_sleep", lambda s: None)
    yield
    db._engine.dispose()
    db._engine = old
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.close()


def session(day, minutes=375, skip=()):
    rows = []
    for i in range(minutes):
        if i in skip:
            continue
        ts = datetime.combine(day, time(9, 15)) + timedelta(minutes=i)
        px = 22000 + i
        rows.append((ts, px, px + 2, px - 2, px + 1, 0.0, 0.0))
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "oi"])


class Fake:
    """Stands in for Groww: serves full sessions except on `holidays`."""

    def __init__(self, holidays=(), fail_on=None, error=None, fail_times=99):
        self.calls, self.holidays = [], set(holidays)
        self.fail_on, self.error, self.fail_times = fail_on, error, fail_times

    def __call__(self, segment, symbol, a, b):
        self.calls.append((a.date(), b.date()))
        if self.fail_on and a.date() <= self.fail_on <= b.date() and self.fail_times > 0:
            self.fail_times -= 1
            raise self.error
        frames, d = [], a.date()
        while d <= b.date():
            if d.weekday() < 5 and d not in self.holidays:
                frames.append(session(d))
            d += timedelta(days=1)
        return pd.concat(frames, ignore_index=True) if frames else session(a.date(), minutes=0)


def status_of(day):
    with db.engine().connect() as c:
        return c.execute(text("SELECT status FROM data_day_quality WHERE symbol=:s AND day=:d"),
                         {"s": SYM, "d": day}).scalar()


def test_migrations_apply_once_and_record_versions():
    db.init()
    with db.engine().connect() as c:
        versions = [r[0] for r in c.execute(text("SELECT version FROM schema_migrations ORDER BY 1"))]
    assert versions == sorted(p.stem for p in db.MIGRATIONS_DIR.glob("*.sql"))
    assert versions[:4] == ["0001_baseline", "0002_timestamptz", "0003_data_management", "0004_outside_session"]


def test_timestamps_stored_as_ist_instants():
    db.upsert_candles(SYM, session(date(2026, 3, 2), minutes=1))
    with db.engine().connect() as c:
        kind = c.execute(text("SELECT data_type FROM information_schema.columns "
                              "WHERE table_name='candles_1m' AND column_name='ts'")).scalar()
        utc = c.execute(text("SELECT (ts AT TIME ZONE 'UTC')::text FROM candles_1m")).scalar()
    assert kind == "timestamp with time zone"
    assert utc == "2026-03-02 03:45:00"          # 09:15 IST
    df = db.load_candles(SYM, datetime(2026, 3, 2), datetime(2026, 3, 3))
    assert df["ts"].iloc[0] == datetime(2026, 3, 2, 9, 15) and df["ts"].dt.tz is None
    assert db.candle_days(SYM) == [date(2026, 3, 2)]


def test_migration_converts_existing_naive_rows():
    """A pre-migration IST value keeps its wall-clock meaning."""
    with db.engine().begin() as c:
        c.exec_driver_sql("CREATE TABLE t_old (ts TIMESTAMP)")
        c.exec_driver_sql("INSERT INTO t_old VALUES ('2026-03-02 09:15:00')")
        c.exec_driver_sql("ALTER TABLE t_old ALTER COLUMN ts TYPE TIMESTAMPTZ USING ts AT TIME ZONE 'Asia/Kolkata'")
        assert c.exec_driver_sql("SELECT (ts AT TIME ZONE 'UTC')::text FROM t_old").scalar() == "2026-03-02 03:45:00"


def test_chunks_respect_groww_limit():
    chunks = dm.plan_chunks(SYM, date(2021, 3, 1), date(2026, 3, 1), date(2026, 3, 20))
    assert all((b - a).days <= dm.CHUNK_SPAN_DAYS for a, b in chunks)
    assert chunks[0][0] == date(2021, 3, 1) and chunks[-1][1] == date(2026, 2, 27)
    assert 55 < len(chunks) < 75


def test_download_stores_and_reports():
    fake = Fake(holidays={date(2026, 3, 3)})
    out = dm.download(date(2026, 3, 2), date(2026, 3, 6), fetch=fake)
    assert out["status"] == "done" and out["rows"] == 4 * 375
    assert status_of(date(2026, 3, 2)) == "complete" and status_of(date(2026, 3, 3)) == "no_data"
    rep = dm.coverage(date(2026, 3, 2), date(2026, 3, 6))
    assert rep["summary"]["sessions"] == 4 and rep["summary"]["no_data"] == 1 and rep["verdict"] == "full"
    assert rep["no_data"] == [{"from": "2026-03-03", "to": "2026-03-03", "days": 1}]


def test_download_is_incremental():
    fake = Fake()
    dm.download(date(2026, 3, 2), date(2026, 3, 6), fetch=fake)
    first = len(fake.calls)
    out = dm.download(date(2026, 3, 2), date(2026, 3, 6), fetch=fake)
    assert len(fake.calls) == first and out["chunks"] == 0
    dm.download(date(2026, 3, 2), date(2026, 3, 10), fetch=fake)
    assert fake.calls[-1] == (date(2026, 3, 9), date(2026, 3, 10))


def test_duplicates_counted_not_double_stored():
    def fetch(seg, sym, a, b):
        df = session(a.date())
        return pd.concat([df, df.head(10)], ignore_index=True)
    dm.download(date(2026, 3, 2), date(2026, 3, 2), fetch=fetch)
    run = dm.downloads()[0]
    assert run["rows_new"] == 375 and run["rows_duplicate"] == 10 and run["rows_received"] == 385
    with db.engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM candles_1m")).scalar() == 375


def test_missing_candles_detected_never_filled():
    skip = {10, 11, 12, 200}
    dm.download(date(2026, 3, 2), date(2026, 3, 2), fetch=lambda *a: session(date(2026, 3, 2), skip=skip))
    rep = dm.coverage(date(2026, 3, 2), date(2026, 3, 2))
    day = rep["partial_days"][0]
    assert day["missing"] == 4 and day["candles"] == 371
    assert day["ranges"] == [["09:25", "09:27"], ["12:35", "12:35"]]
    with db.engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM candles_1m")).scalar() == 371


def test_invalid_candles_rejected():
    def fetch(seg, sym, a, b):
        df = session(a.date()).copy()
        df.loc[0, "high"] = df.loc[0, "open"] - 50          # high below open
        df.loc[1, "open"] = 0                               # non-positive price
        extra = df.iloc[[2]].copy()
        extra["ts"] = datetime.combine(a.date(), time(16, 0))   # outside the session
        return pd.concat([df, extra], ignore_index=True)
    dm.download(date(2026, 3, 2), date(2026, 3, 2), fetch=fetch)
    run = dm.downloads()[0]
    assert run["rows_rejected"] == 2 and run["rows_outside_session"] == 1
    assert status_of(date(2026, 3, 2)) == "partial"
    s = dm.coverage(date(2026, 3, 2), date(2026, 3, 2))["summary"]
    assert s["rejected"] == 2 and s["outside_session"] == 1


def test_pre_open_after_close_and_muhurat_kept_apart():
    """Groww sends 09:00-09:14 and 15:30+ candles; an evening-only day is a special session."""
    def fetch(seg, sym, a, b):
        reg = session(a.date())
        pre = reg.head(15).assign(ts=[datetime.combine(a.date(), time(9, m)) for m in range(15)])
        post = reg.head(30).assign(ts=[datetime.combine(a.date(), time(15, 30 + m)) for m in range(30)])
        muhurat = reg.head(60).assign(ts=[datetime.combine(b.date(), time(18, 0)) + timedelta(minutes=m) for m in range(60)])
        return pd.concat([pre, reg, post, muhurat], ignore_index=True)
    dm.download(date(2026, 3, 2), date(2026, 3, 3), fetch=fetch)
    run = dm.downloads()[0]
    assert run["rows_rejected"] == 0 and run["rows_outside_session"] == 105
    assert status_of(date(2026, 3, 2)) == "complete" and status_of(date(2026, 3, 3)) == "special_session"
    rep = dm.coverage(date(2026, 3, 2), date(2026, 3, 3))
    assert rep["special_sessions"] == ["2026-03-03"] and rep["no_data"] == []
    assert rep["summary"]["outside_session"] == 105 and rep["summary"]["sessions"] == 1


def test_forming_minute_and_future_never_stored(monkeypatch):
    monkeypatch.setattr(dm, "_now", lambda: datetime(2026, 3, 20, 12, 0, 30))
    day = date(2026, 3, 20)
    dm.download(day, day, fetch=lambda *a: session(day))
    df = db.load_candles(SYM, datetime(2026, 3, 20), datetime(2026, 3, 21))
    assert df["ts"].max() == datetime(2026, 3, 20, 11, 59)
    assert status_of(day) == "in_progress"
    assert not db.fetched(SYM, day)


def test_transient_error_retried():
    fake = Fake(fail_on=date(2026, 3, 2), error=TimeoutError("slow"), fail_times=2)
    assert dm.download(date(2026, 3, 2), date(2026, 3, 3), fetch=fake)["status"] == "done"
    assert len(fake.calls) == 3


def test_forbidden_stops_immediately_with_clear_message():
    fake = Fake(fail_on=date(2026, 3, 2), error=RuntimeError("Access forbidden for this request."))
    with pytest.raises(dm.DownloadError, match="subscription"):
        dm.download(date(2026, 3, 2), date(2026, 3, 3), fetch=fake)
    assert len(fake.calls) == 1
    run = dm.downloads()[0]
    assert run["status"] == "failed" and "403" in run["error"]


def test_resume_after_failure_skips_finished_chunks():
    start, end = date(2026, 1, 1), date(2026, 3, 13)
    fake = Fake(fail_on=date(2026, 2, 16), error=TimeoutError("down"))
    with pytest.raises(dm.DownloadError):
        dm.download(start, end, fetch=fake)
    assert dm.downloads()[0]["status"] == "failed"
    done_before = db.candle_days(SYM)
    assert done_before and max(done_before) < date(2026, 2, 16)

    retry = Fake()
    assert dm.download(start, end, fetch=retry)["status"] == "done"
    assert retry.calls[0][0] > max(done_before)
    assert dm.coverage(start, end)["summary"]["not_downloaded"] == 0


def test_interrupted_download_is_recoverable():
    with db.engine().begin() as c:
        c.execute(text("INSERT INTO data_downloads (symbol, start_date, end_date) VALUES (:s,'2026-01-01','2026-01-02')"),
                  {"s": SYM})
    assert dm.recover_interrupted() == 1
    assert dm.downloads()[0]["status"] == "interrupted"


def test_stop_request_ends_download():
    start, end = date(2026, 1, 1), date(2026, 3, 13)
    fake = Fake()

    def fetch(*args):
        dm.request_stop()
        return fake(*args)
    assert dm.download(start, end, fetch=fetch)["status"] == "stopped"
    assert len(fake.calls) == 1


def test_coverage_with_nothing_stored_lists_exact_gap():
    rep = dm.coverage(date(2026, 3, 2), date(2026, 3, 13))
    assert rep["verdict"] == "none" and rep["summary"]["not_downloaded"] == 10
    assert rep["not_downloaded"] == [{"from": "2026-03-02", "to": "2026-03-13", "days": 10}]


@pytest.mark.parametrize("tf,count,first_close", [(1, 375, None), (5, 75, None), (15, 25, None), (30, 13, None)])
def test_resampled_chart_aligned_to_open(tf, count, first_close):
    day = date(2026, 3, 2)
    db.upsert_candles(SYM, session(day))
    bars = dm.candles(day, day, tf)["bars"]
    assert len(bars) == count and bars[0]["t"] == "2026-03-02T09:15:00"
    assert bars[0]["o"] == 22000 and bars[1]["t"] == (datetime(2026, 3, 2, 9, 15) + timedelta(minutes=tf)).isoformat()


def test_chart_leaves_out_forming_bar(monkeypatch):
    monkeypatch.setattr(dm, "_now", lambda: datetime(2026, 3, 20, 9, 37, 10))
    day = date(2026, 3, 20)
    db.upsert_candles(SYM, session(day))
    bars = dm.candles(day, day, 15)["bars"]
    assert [b["t"][11:16] for b in bars] == ["09:15"]     # 09:30 bar closes at 09:45


def test_chart_rejects_huge_range():
    with pytest.raises(ValueError):
        dm.candles(date(2026, 3, 2), date(2026, 3, 2), 7)
    db.upsert_candles(SYM, session(date(2026, 3, 2)))
    dm.MAX_CHART_BARS, old = 10, dm.MAX_CHART_BARS
    try:
        with pytest.raises(ValueError, match="shorter range"):
            dm.candles(date(2026, 3, 2), date(2026, 3, 2), 1)
    finally:
        dm.MAX_CHART_BARS = old


def test_pages_and_api():
    c = app_module.app.test_client()
    assert c.get("/data").headers["Location"].endswith("/app/data") and c.get("/history").headers["Location"].endswith("/app/history")
    r = c.get("/api/data/overview?from=2026-03-02&to=2026-03-06")
    assert r.json["ok"] and r.json["data"]["coverage"]["verdict"] == "none"
    assert c.get("/api/data/overview?from=nonsense").status_code == 400
    assert c.post("/api/data/download", json={"from": "bad", "to": "2026-03-06"}).status_code == 400
    assert c.post("/api/data/download", json={"from": "2026-03-06", "to": "2026-03-02"}).status_code == 400
    assert c.get("/api/data/candles?from=2026-03-02&to=2026-03-02&tf=7").status_code == 400
    assert c.get("/api/data/candles?from=2026-03-02&to=2026-03-02&tf=5").json["data"]["bars"] == []


def test_app_refuses_synthetic_data():
    c = app_module.app.test_client()
    body = {"dataset": "synthetic", "start_date": "2026-03-02", "end_date": "2026-03-06"}
    assert c.post("/api/bt/run", json=body).status_code == 400
    assert c.post("/api/bt/data", json=body).status_code == 400
    meta = c.get("/api/bt/meta").json["data"]
    assert list(meta["datasets"]) == ["groww"] and meta["defaults"]["dataset"] == "groww"


def test_groww_provider_uses_download_manager(monkeypatch):
    from app.services.market_data import providers
    seen = {}

    def fake_download(start, end, fetch=None, progress=None, symbol=None):
        seen.update(start=start, end=end, symbol=symbol)
        return {"rows": 0}
    monkeypatch.setattr(dm, "download", fake_download)
    providers.GrowwProvider().ensure_spot(date(2026, 3, 2), date(2026, 3, 3))
    assert seen == {"start": date(2026, 3, 2), "end": date(2026, 3, 3), "symbol": "NSE-NIFTY"}

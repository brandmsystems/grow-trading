"""Lot sizes from NSE circulars, the option-history plan, resumable download and its API."""
from datetime import date, datetime, time, timedelta

import pandas as pd
import psycopg2
import pytest
from sqlalchemy import text

import app.main as app_module
from app.config import settings as config
from app.database import db
from app.services.market_data import history as data_manager
from app.services.market_data import options_history as oh
from app.services.options import lot_sizes

TEST_DB = "groww_trading_test_options"


@pytest.fixture(scope="module", autouse=True)
def test_db():
    conn = psycopg2.connect(**{**config.PG, "dbname": "postgres"})
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {TEST_DB}")
    old = db._engine
    db._engine = db.engine(TEST_DB)
    db.init()
    lot_sizes.clear_cache()
    yield
    lot_sizes.clear_cache()
    db._engine.dispose()
    db._engine = old
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.close()


# Real NIFTY expiries around each NSE cutover.
EXPIRIES = [date(2024, 4, 18), date(2024, 4, 25), date(2024, 5, 2), date(2024, 5, 30),
            date(2024, 12, 19), date(2024, 12, 26), date(2025, 1, 2), date(2025, 1, 30), date(2025, 2, 27),
            date(2025, 12, 23), date(2025, 12, 30), date(2026, 1, 6), date(2026, 1, 27)]


@pytest.mark.parametrize("expiry, cycle, lot", [
    (date(2024, 4, 18), "weekly", 50), (date(2024, 4, 25), "monthly", 50),     # before NSE/FAOP/61415
    (date(2024, 5, 2), "weekly", 25), (date(2024, 5, 30), "monthly", 25),      # first with 25
    (date(2024, 12, 19), "weekly", 25), (date(2024, 12, 26), "monthly", 25),   # last weekly with 25
    (date(2025, 1, 2), "weekly", 75), (date(2025, 1, 30), "monthly", 25),      # NSE/FAOP/64625: weeklies switch first
    (date(2025, 2, 27), "monthly", 75),
    (date(2025, 12, 23), "weekly", 75), (date(2025, 12, 30), "monthly", 75),   # last with 75 (NSE/FAOP/70616)
    (date(2026, 1, 6), "weekly", 65), (date(2026, 1, 27), "monthly", 65),
])
def test_lot_size_matches_nse_circulars(expiry, cycle, lot):
    assert lot_sizes.cycle_of(expiry, EXPIRIES) == cycle
    assert lot_sizes.lot_size_for(expiry, EXPIRIES)[0] == lot


def test_lot_size_unknown_before_table():
    with pytest.raises(lot_sizes.LotSizeUnknown):
        lot_sizes.lot_size_for(date(2021, 6, 24), [date(2021, 6, 24)])
    assert all(r["source"].startswith("NSE/FAOP/") for r in lot_sizes.history())


def test_strikes_and_windows():
    ks = oh.strikes_for(24010, 24120, n=10)
    assert ks[0] == 24000 - 500 and ks[-1] == 24100 + 500 and all(b - a == 50 for a, b in zip(ks, ks[1:]))
    e = date(2024, 3, 28)
    days = [date(2024, 2, 1) + timedelta(days=i) for i in range(0, 57)]
    starts = oh.windows(days, e)
    assert starts[0] == date(2024, 2, 1) and starts[1] == date(2024, 3, 2)   # 30-day request windows
    assert oh.windows([], e) == []


def test_plan_covers_every_expiry_rule():
    exps = [date(2024, 1, 4), date(2024, 1, 11), date(2024, 1, 18), date(2024, 1, 25), date(2024, 2, 1)]
    need = oh.plan(date(2024, 1, 11), date(2024, 1, 11), exps, {date(2024, 1, 11): (21600.0, 21700.0)}, n=2)
    # On expiry day: nearest without roll (11th), nearest with roll (18th), next (25th), monthly (25th).
    assert {e for e, _, _ in need} == {date(2024, 1, 11), date(2024, 1, 18), date(2024, 1, 25)}
    strikes = sorted({k for _, k, _ in need})
    assert strikes[0] == 21500 and strikes[-1] == 21800
    assert {t for _, _, t in need} == {"CE", "PE"}


class FakeProvider:
    """Stands in for Groww: records requests and marks days fetched like the real provider."""
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def ensure_expiries(self, start, end):
        return [date(2024, 1, 18), date(2024, 1, 25)]

    def option_symbol(self, expiry, strike, typ):
        return f"NSE-NIFTY-{expiry:%d%b%y}-{int(strike)}-{typ}"

    def ensure_option_day(self, symbol, day):
        self.calls.append((symbol, day))
        if symbol in self.fail:
            raise RuntimeError("timeout")
        db.mark_fetched(symbol, day, 375)


def _spot(day):
    ts = pd.date_range(datetime.combine(day, time(9, 15)), periods=375, freq="1min")
    df = pd.DataFrame({"ts": ts, "open": 21650.0, "high": 21660.0, "low": 21640.0, "close": 21650.0,
                       "volume": 0.0, "oi": 0.0})
    db.upsert_candles(data_manager.SYMBOL, df)


def test_download_is_resumable_and_reports_failures(monkeypatch):
    monkeypatch.setattr(oh, "_now", lambda: datetime(2024, 1, 20, 10, 0))
    _spot(date(2024, 1, 16))
    bad = "NSE-NIFTY-18Jan24-21650-CE"
    prov = FakeProvider(fail={bad})
    r = oh.download(date(2024, 1, 15), date(2024, 1, 19), n=1, prov=prov, workers=2)
    assert r["requests"] == len(prov.calls) > 0 and r["failed"] == 1
    with db.engine().connect() as c:
        run = c.execute(text("SELECT status, chunks_done, chunks_total, error FROM data_downloads WHERE id=:i"),
                        {"i": r["id"]}).first()
    assert run.status == "done" and run.chunks_done == run.chunks_total and "1 request(s) failed" in run.error
    # Re-run: only the failed window is requested again; then nothing is left.
    prov2 = FakeProvider()
    r2 = oh.download(date(2024, 1, 15), date(2024, 1, 19), n=1, prov=prov2)
    assert prov2.calls == [(bad, date(2024, 1, 16))] and r2["failed"] == 0
    assert oh.download(date(2024, 1, 15), date(2024, 1, 19), n=1, prov=FakeProvider())["requests"] == 0


def test_stop_request(monkeypatch):
    monkeypatch.setattr(oh, "_now", lambda: datetime(2024, 1, 20, 10, 0))
    _spot(date(2024, 1, 17))
    prov = FakeProvider()
    orig = prov.ensure_option_day

    def stop_after_first(symbol, day):
        orig(symbol, day)
        data_manager.request_stop()
    prov.ensure_option_day = stop_after_first
    r = oh.download(date(2024, 1, 17), date(2024, 1, 17), n=3, prov=prov, workers=1)
    assert r["status"] == "stopped" and 0 < r["done"] < r["requests"]


def test_coverage_and_api(monkeypatch):
    monkeypatch.setattr(oh, "_now", lambda: datetime(2024, 1, 20, 10, 0))
    with db.engine().begin() as c:
        c.execute(text("INSERT INTO expiries VALUES ('groww', '2024-01-18'), ('groww', '2024-01-25') ON CONFLICT DO NOTHING"))
    cov = oh.coverage(date(2024, 1, 15), date(2024, 1, 19), n=1)
    assert cov["summary"]["contracts"] > 0 and cov["summary"]["downloaded_days"] <= cov["summary"]["contract_days"]
    assert cov["months"][0]["month"] == "2024-01" and cov["last_run"]["symbol"] == oh.RUN_SYMBOL
    c = app_module.app.test_client()
    r = c.get("/api/data/options?from=2024-01-15&to=2024-01-19")
    assert r.status_code == 200 and r.get_json()["data"]["scope"]["strikes_each_side"] == oh.STRIKE_RANGE
    lots = c.get("/api/data/lot-sizes").get_json()["data"]
    assert {(row["cycle"], row["lot_size"]) for row in lots} >= {("weekly", 65), ("monthly", 65)}
    assert c.post("/api/data/options/download", json={"from": "2024-02-01", "to": "2024-01-01"}).status_code == 400
    assert c.post("/api/data/options/download", json={}).status_code == 400
    inst = c.get("/api/data/overview").get_json()["data"]["instruments"]
    assert set(inst) == {"spot", "futures", "options", "intervals"} and inst["intervals"] == [1, 5, 15, 30]


def test_no_synthetic_rows_in_production_database():
    """Synthetic test data belongs in test databases only (removed from production on 12 Nov 2026)."""
    eng = db.engine(config.PG["dbname"])
    try:
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM candles_1m WHERE symbol LIKE 'SYNTH:%'")).scalar() == 0
    finally:
        eng.dispose()

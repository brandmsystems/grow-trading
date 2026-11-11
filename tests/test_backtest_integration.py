"""End-to-end run on the synthetic dataset, in a throwaway Postgres database."""
from datetime import date, datetime, time, timedelta

import pandas as pd
import psycopg2
import pytest

import backtest
import config
import db

TEST_DB = "groww_trading_test"


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
    backtest.spot_bars.cache_clear()
    backtest.option_candles.cache_clear()
    yield
    db._engine.dispose()
    db._engine = old
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.close()


PARAMS = {"dataset": "synthetic", "start_date": "2025-06-02", "end_date": "2025-07-11",
          "timeframe": 15, "entry_start": "09:30", "cutoff": "14:30"}


@pytest.fixture(scope="module")
def result():
    backtest.ensure_data(PARAMS)
    return backtest.run(PARAMS, use_cache=False)


def test_runs_and_produces_trades(result):
    assert result["signals"] > 5
    for m, s in result["summary"].items():
        assert s["trades"] == len(result["trades"][m]) > 0


def test_trade_invariants(result):
    for mode, trades in result["trades"].items():
        for t in trades:
            e, x = datetime.fromisoformat(t["entry_ts"]), datetime.fromisoformat(t["exit_ts"])
            assert e < x and e.date() == x.date()
            assert time(9, 30) <= e.time() <= time(14, 30)
            assert x.time() <= time(15, 0)
            assert t["net"] == pytest.approx(t["gross"] - t["friction"], abs=0.02)
            assert t["side"] == ("SELL" if mode == "ATM_SELL" else "BUY")
            assert date.fromisoformat(t["expiry"]) > date.fromisoformat(t["day"])  # rolled on expiry day
            if mode == "ITM5_BUY":
                atm = round(t["signal_close"] / 50 + 1e-9)
                assert abs(t["strike"] - atm * 50) == 250
            if t["exit_reason"] == "square_off":
                assert x.time() == time(15, 0)


def test_reversals_chain(result):
    trades = result["trades"]["ATM_BUY"]
    for a, b in zip(trades, trades[1:]):
        if a["exit_reason"] == "opposite_cross" and b["day"] == a["day"] and b["entry_ts"] == a["exit_ts"]:
            assert a["direction"] != b["direction"]


def test_all_modes_share_signals(result):
    keys = [{(t["entry_ts"], t["direction"]) for t in result["trades"][m]} for m in result["trades"]]
    assert keys[0] == keys[1] == keys[2]


def test_weekdays_accounted_for(result):
    traded = {t["day"] for t in result["trades"]["ATM_BUY"]}
    no_trade = {d["day"] for d in result["no_trade_days"]}
    d, s, e = date(2025, 6, 2), date(2025, 6, 2), date(2025, 7, 11)
    while d <= e:
        if d.weekday() < 5:
            assert d.isoformat() in traded | no_trade
        d += timedelta(days=1)


def test_cache_and_chart_payload(result):
    again = backtest.run(PARAMS)
    assert again["hash"] == result["hash"]
    t = result["trades"]["ATM_BUY"][0]
    bars = backtest.spot_bars("synthetic", date.fromisoformat(t["day"]), 15)
    assert len(bars) == 25 and all("e9" in b for b in bars)
    assert backtest.option_candles(t["symbol"], date.fromisoformat(t["day"]))


def test_param_validation():
    with pytest.raises(ValueError):
        backtest.normalise({**PARAMS, "timeframe": 7})
    with pytest.raises(ValueError):
        backtest.normalise({**PARAMS, "cutoff": "15:30"})


def test_today_partial_session(monkeypatch):
    """A run during market hours uses only finished minutes and is never served stale."""
    import providers
    p = {**PARAMS, "start_date": "2025-06-30", "end_date": "2025-07-14", "timeframe": 5}
    day = date(2025, 7, 14)
    asof = datetime(2025, 7, 14, 12, 7)
    noon = asof + timedelta(seconds=30)
    for mod in (backtest, providers):
        monkeypatch.setattr(mod, "_now", lambda: noon)
    backtest.ensure_data(p)
    span = (datetime.combine(day, time(0)), datetime.combine(day, time(23)))
    part = db.load_candles("SYNTH:NIFTY", *span)
    assert part["ts"].max() == pd.Timestamp(asof) - pd.Timedelta(minutes=1)

    r = backtest.run(p, use_cache=True)
    assert r["partial_asof"] == asof.isoformat()
    today = [t for t in r["trades"]["ATM_BUY"] if t["day"] == day.isoformat()]
    assert all(datetime.fromisoformat(t["exit_ts"]) <= asof for t in today)
    assert today[-1]["exit_reason"] == "open"

    late = datetime(2025, 7, 14, 16, 0)
    for mod in (backtest, providers):
        monkeypatch.setattr(mod, "_now", lambda: late)
    backtest.ensure_data(p)
    full = db.load_candles("SYNTH:NIFTY", *span)
    assert len(full) == 375
    merged = part.merge(full, on="ts", suffixes=("_a", "_b"))
    assert len(merged) == len(part) and (merged["close_a"] == merged["close_b"]).all()
    r2 = backtest.run(p, use_cache=True)
    assert r2["partial_asof"] is None
    assert all(t["exit_reason"] != "open" for t in r2["trades"]["ATM_BUY"])


def test_data_stale(monkeypatch):
    wed_noon = datetime(2026, 11, 11, 12, 0, 20)
    monkeypatch.setattr(backtest, "_now", lambda: wed_noon)
    assert backtest.data_stale(None)
    assert backtest.data_stale(datetime(2026, 11, 10, 15, 29))
    assert not backtest.data_stale(datetime(2026, 11, 11, 11, 59))
    assert not backtest.data_stale(datetime(2026, 11, 11, 11, 45))       # within 15 minutes
    assert backtest.data_stale(datetime(2026, 11, 11, 11, 40))
    sunday = datetime(2026, 11, 15, 12, 0)
    monkeypatch.setattr(backtest, "_now", lambda: sunday)
    assert not backtest.data_stale(datetime(2026, 11, 13, 15, 29))

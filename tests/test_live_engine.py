"""The live engine, replayed on a simulated clock, must reproduce the backtest exactly."""
from datetime import date, datetime, time, timedelta

import psycopg2
import pytest
from sqlalchemy import text

import backtest
import config
import db
import live_engine as le
from live_market import OrderError, OrderUnknown, PaperBroker, ReplayMarket

TEST_DB = "groww_trading_test_live"
START, END = date(2025, 6, 2), date(2025, 6, 27)
PARAMS = {"dataset": "synthetic", "start_date": START.isoformat(), "end_date": END.isoformat(),
          "timeframe": 15, "entry_start": "09:30", "cutoff": "14:30"}


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
    backtest.ensure_data(PARAMS)
    yield
    db._engine.dispose()
    db._engine = old
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.close()


@pytest.fixture(autouse=True)
def clean_live_tables():
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions RESTART IDENTITY"))


def run_days(engine, market, days, step=10):
    for d in days:
        market.clock = datetime.combine(d, time(9, 14))
        end = datetime.combine(d, time(15, 31))
        while market.clock <= end:
            engine.tick()
            market.clock += timedelta(seconds=step)


def live_trades():
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(text("SELECT * FROM live_trades ORDER BY id")).mappings()]


def make(cfg_over=None, broker=None, start_day=None):
    market = ReplayMarket("synthetic", START - timedelta(days=12),
                          datetime.combine(start_day or START, time(9, 0)))
    cfg = le.EngineConfig(**{"exec_mode": "ATM_BUY", "max_daily_loss": 0, "max_trades_per_day": 100,
                             **(cfg_over or {})})
    eng = le.Engine(cfg, market, broker or PaperBroker(market))
    eng.start(threaded=False)
    return eng, market


@pytest.mark.parametrize("mode,tf", [("ATM_BUY", 15), ("ATM_SELL", 5), ("ITM5_BUY", 30)])
def test_engine_matches_backtest(mode, tf):
    days = [d for d in (START + timedelta(days=i) for i in range(5, 26)) if d.weekday() < 5]
    bt = backtest.run({**PARAMS, "timeframe": tf}, use_cache=False)
    expected = [t for t in bt["trades"][mode] if days[0].isoformat() <= t["day"] <= days[-1].isoformat()]
    assert expected, "need trades to compare"

    eng, market = make({"exec_mode": mode, "timeframe": tf})
    run_days(eng, market, days)
    got = live_trades()

    assert len(got) == len(expected)
    for g, e in zip(got, expected):
        assert g["status"] == "CLOSED"
        assert g["signal_ts"].isoformat() == e["entry_ts"]
        assert g["direction"] == e["direction"] and g["side"] == e["side"]
        assert g["strike"] == e["strike"] and g["opt_type"] == e["opt_type"]
        assert g["entry_price"] == pytest.approx(e["opt_entry"])
        assert g["exit_price"] == pytest.approx(e["opt_exit"])
        assert g["exit_reason"] == e["exit_reason"]
        assert g["net"] == pytest.approx(e["net"], abs=0.02)


class FlakyBroker(PaperBroker):
    def __init__(self, market, fail=None):
        super().__init__(market)
        self.fail = fail or {}      # call number -> exception
        self.calls = 0

    def execute(self, c, txn, qty, ref):
        self.calls += 1
        if self.calls in self.fail:
            raise self.fail[self.calls]
        return super().execute(c, txn, qty, ref)


def first_trade_day(tf=15):
    bt = backtest.run({**PARAMS, "timeframe": tf}, use_cache=False)
    t = next(t for t in bt["trades"]["ATM_BUY"] if t["day"] >= (START + timedelta(days=5)).isoformat())
    return date.fromisoformat(t["day"]), t


def test_rejected_entry_creates_no_position():
    d, _ = first_trade_day()
    m = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(d, time(9, 0)))
    broker = FlakyBroker(m, {1: OrderError("insufficient margin")})
    eng, market = make(broker=broker, start_day=d)
    eng.market = broker.market = m
    run_days(eng, m, [d])
    assert any("Entry order failed" in e["message"] for e in eng.events)
    assert eng.position is None


def test_unconfirmed_exit_halts_and_sends_nothing_more():
    d, t = first_trade_day()
    m = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(d, time(9, 0)))
    broker = FlakyBroker(m, {2: OrderUnknown("timeout")})
    eng, _ = make(broker=broker, start_day=d)
    eng.market = broker.market = m
    run_days(eng, m, [d])
    assert eng.state == "error"
    assert eng.position is not None          # still tracked as open for manual action
    assert broker.calls == 2                 # no automatic retries / square-off after unknown outcome


def test_failed_exit_is_retried():
    d, t = first_trade_day()
    m = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(d, time(9, 0)))
    broker = FlakyBroker(m, {2: OrderError("network"), 3: OrderError("network")})
    eng, _ = make(broker=broker, start_day=d)
    eng.market = broker.market = m
    run_days(eng, m, [d])
    rows = live_trades()
    assert rows[0]["status"] == "CLOSED" and eng.state != "error"
    assert any("EXIT FAILED (2)" in e["message"] for e in eng.events)


def test_daily_loss_limit_halts():
    eng, market = make({"max_daily_loss": 1})   # any loss trips it
    days = [d for d in (START + timedelta(days=i) for i in range(5, 26)) if d.weekday() < 5]
    for d in days:
        run_days(eng, market, [d])
        if any("Daily loss limit" in e["message"] for e in eng.events):
            break
    assert any("Daily loss limit" in e["message"] for e in eng.events)
    tripped_day = market.clock.date()
    rows = [r for r in live_trades() if r["day"] == tripped_day]
    assert all(r["status"] == "CLOSED" for r in rows)
    assert rows[-1]["exit_reason"] in ("daily_loss_limit", "opposite_cross", "square_off")


def test_max_trades_per_day():
    eng, market = make({"max_trades_per_day": 1, "timeframe": 5})
    days = [d for d in (START + timedelta(days=i) for i in range(5, 12)) if d.weekday() < 5]
    run_days(eng, market, days)
    per_day = {}
    for r in live_trades():
        per_day[r["day"]] = per_day.get(r["day"], 0) + 1
    assert per_day and max(per_day.values()) == 1


def test_late_start_does_not_chase_old_signals_and_resume_after_restart():
    d, t = first_trade_day()
    entry = datetime.fromisoformat(t["entry_ts"])
    # start 20 minutes after the signal: the engine must not enter that old signal
    eng, market = make(start_day=d)
    market.clock = entry + timedelta(minutes=20)
    eng.tick()
    assert eng.position is None

    # restart resume: an engine that crashed while holding a position picks it up again
    eng2, market2 = make(start_day=d)
    market2.clock = entry + timedelta(seconds=10)
    eng2.tick()
    assert eng2.position is not None
    eng3, market3 = make(start_day=d)
    market3.clock = entry + timedelta(minutes=1)
    eng3.tick()
    assert eng3.position is not None and eng3.position["id"] == eng2.position["id"]
    assert any("Resumed open" in e["message"] for e in eng3.events)


def test_config_validation():
    with pytest.raises(ValueError):
        le.EngineConfig(trade_mode="yolo").validate()
    with pytest.raises(ValueError):
        le.EngineConfig(entry_start="14:30", cutoff="11:30").validate()
    with pytest.raises(ValueError):
        le.EngineConfig(lots=0).validate()


def test_restart_right_after_reversal_keeps_new_position():
    bt = backtest.run(PARAMS, use_cache=False)
    trades = [t for t in bt["trades"]["ATM_BUY"] if t["day"] >= (START + timedelta(days=5)).isoformat()]
    rev = next(b for a, b in zip(trades, trades[1:])
               if a["exit_reason"] == "opposite_cross" and a["exit_ts"] == b["entry_ts"])
    d, x = date.fromisoformat(rev["day"]), datetime.fromisoformat(rev["entry_ts"])
    eng, market = make(start_day=d)
    market.clock = datetime.combine(d, time(9, 14))
    while market.clock <= x + timedelta(seconds=20):
        eng.tick(); market.clock += timedelta(seconds=10)
    held = eng.position
    assert held is not None and held["direction"] == (1 if rev["direction"] == "Bullish" else -1)
    # crash + restart 30s later: must keep the new leg, not re-run the reversal bar's exit
    eng2, m2 = make(start_day=d)
    m2.clock = x + timedelta(seconds=50)
    eng2.tick()
    assert eng2.position is not None and eng2.position["id"] == held["id"]
    assert len(live_trades()) == len([t for t in trades if t["day"] == rev["day"] and t["entry_ts"] <= rev["entry_ts"]])

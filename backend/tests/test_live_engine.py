"""The live engine, replayed on a simulated clock, must reproduce the backtest exactly."""
from datetime import date, datetime, time, timedelta

import psycopg2
import pytest
from sqlalchemy import text

from app.services.backtest import engine as backtest
from app.config import settings as config
from app.database import db
from app.services.trading import engine as le
from app.services.market_data.live import ReplayMarket
from app.services.trading.brokers import OrderError, OrderUnknown, PaperBroker

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
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions RESTART IDENTITY CASCADE"))


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
    over = cfg_over or {}
    # These tests check engine mechanics with a fixed number of lots. Since 12 Nov paper trades are
    # sized by the risk module (tested in test_paper_risk.py); these settings make it size exactly
    # `lots` and keep its premium stop and daily limit out of the way. The calculation still runs.
    fixed_lots = {"risk_pct": 100, "max_lots": over.get("lots", 1), "stop_mode": "pct", "stop_pct": 99,
                  "daily_risk_pct": 0}
    cfg = le.EngineConfig(**{"exec_mode": "ATM_BUY", "max_daily_loss": 0, "max_trades_per_day": 100,
                             **fixed_lots, **over})
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

    assert len(got) == len(expected), ([(str(g["day"]), g["signal_ts"].strftime("%H:%M"), g["exit_reason"]) for g in got],
                                       [(e["day"], e["entry_ts"][11:16], e["exit_reason"]) for e in expected],
                                       [(x["ts"][5:16], x["message"][:90]) for x in list(eng.events)[:12]])
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
    # Replay: the open-loss halt as live and replay use it. In paper mode a ₹1 limit now refuses every
    # entry beforehand (maximum loss > remaining limit); that and the paper halt are in test_paper_risk.py.
    eng, market = make({"max_daily_loss": 1, "trade_mode": "replay"})   # any loss trips it
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


class _StubScorer:
    """Scores by time of day: crosses after mid-session score >= 50."""
    built = "test"

    def __init__(self, analysis):
        pass

    def score(self, feats):
        return round(feats["time"] * 100, 2)

    def comparable(self, score):
        return None


def test_prediction_mode_filters_by_score_and_exits_at_refs(monkeypatch):
    import pandas as pd
    from app.services.strategy import signals
    monkeypatch.setattr(le.signals, "latest", lambda *a, **k: {"model": {}})
    monkeypatch.setattr(le.signals, "Scorer", _StubScorer)
    days = [d for d in (START + timedelta(days=i) for i in range(5, 26)) if d.weekday() < 5]
    eng, market = make({"signal_mode": "prediction", "min_score": 50, "timeframe": 15}, start_day=days[0])
    run_days(eng, market, days)
    rows = live_trades()
    assert rows, "need prediction trades"
    for r in rows:
        assert r["signal_mode"] == "prediction" and r["score"] >= 50
        assert r["exit_reason"] in ("stop", "target", "square_off")
        d = 1 if r["direction"] == "Bullish" else -1
        assert r["stop_ref"] == pytest.approx(r["signal_close"] - d * r["atr_ref"], abs=0.02)
        assert r["target_ref"] == pytest.approx(r["signal_close"] + 2 * d * r["atr_ref"], abs=0.02)
        spot = db.load_candles("SYNTH:NIFTY", datetime.combine(r["day"], time(0)), datetime.combine(r["day"], time(23)))
        outcome, at = signals._outcome(spot, r["signal_ts"], r["signal_close"], d, r["atr_ref"])
        expected = {"hit": "target", "miss": "stop" if at else "square_off"}[outcome]
        assert r["exit_reason"] == expected
        if at:   # exit happens once the deciding minute has completed
            assert r["exit_ts"] == pd.Timestamp(at).to_pydatetime() + timedelta(minutes=1)
    with db.engine().connect() as c:
        low = c.execute(text("SELECT count(*) FROM live_events WHERE message LIKE '%below 50%no trade%'")).scalar()
    assert low > 0, "low-score signals must be logged and skipped"


def test_prediction_mode_requires_analysis(monkeypatch):
    monkeypatch.setattr(le.signals, "latest", lambda *a, **k: None)
    market = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(START, time(9, 0)))
    eng = le.Engine(le.EngineConfig(signal_mode="prediction"), market, PaperBroker(market))
    with pytest.raises(ValueError, match="Signals page"):
        eng.start(threaded=False)
    with pytest.raises(ValueError):
        le.EngineConfig(signal_mode="prediction", min_score=120).validate()


def _alerts():
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(text("SELECT * FROM live_alerts ORDER BY id")).mappings()]


@pytest.fixture
def clean_alerts():
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_alerts RESTART IDENTITY"))


def test_alerts_follow_entries_and_exits(clean_alerts):
    days = [d for d in (START + timedelta(days=i) for i in range(5, 12)) if d.weekday() < 5]
    eng, market = make({"timeframe": 15}, start_day=days[0])
    run_days(eng, market, days)
    trades, alerts = live_trades(), _alerts()
    entries = [a for a in alerts if a["action"] in ("BUY CE", "BUY PE")]
    exits = [a for a in alerts if a["action"] == "SELL"]
    assert trades and len(entries) == len(trades) and len(exits) == sum(t["status"] == "CLOSED" for t in trades)
    for a, t in zip(entries, trades):
        assert a["action"] == f"BUY {t['opt_type']}"
        assert a["payload"]["entry_price"] == round(t["entry_price"], 2) and a["payload"]["strike"] == t["strike"]
        assert a["payload"]["nifty"] == round(t["signal_close"], 2)
    assert len({a["alert_key"] for a in alerts}) == len(alerts)


def test_same_signal_never_alerts_twice(clean_alerts):
    from app.services.trading import engine as live_engine
    from app.services.strategy.rules import Leg
    eng, market = make({"timeframe": 15})
    eng.day = START
    leg = Leg(day=START, direction=1, entry_ts=datetime.combine(START, time(10, 0)), signal_close=22000.0,
              signal_bar_start=datetime.combine(START, time(9, 45)), ordinal=1)
    eng._hold(leg, "test"); eng._hold(leg, "test")
    assert len(_alerts()) == 1


def test_market_status():
    from app.services.trading import manager as lm
    assert lm.market_status(datetime(2026, 11, 14, 11, 0))["state"] == "closed"          # Saturday
    assert lm.market_status(datetime(2026, 11, 12, 9, 5))["state"] == "preopen"
    assert lm.market_status(datetime(2026, 11, 12, 9, 15))["state"] == "open"
    assert lm.market_status(datetime(2026, 11, 12, 15, 30))["state"] == "closed"


def test_replaying_a_day_twice_gives_the_same_trades(clean_alerts):
    d = [x for x in (START + timedelta(days=i) for i in range(5, 12)) if x.weekday() < 5][2]
    out = []
    for _ in range(2):
        m = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(d, time(9, 0)))
        eng = le.Engine(le.EngineConfig(trade_mode="replay", exec_mode="ATM_BUY", max_daily_loss=0, max_trades_per_day=100), m, PaperBroker(m))
        eng.start(threaded=False)
        run_days(eng, m, [d])
        eng.stop(square_off=True, reason="done")
        with db.engine().connect() as c:
            out.append([(r[0], r[1]) for r in c.execute(text("SELECT signal_ts, exit_reason FROM live_trades WHERE session_id=:s ORDER BY id"), {"s": eng.session_id})])
    assert out[0] and out[0] == out[1]


class CountingBroker(PaperBroker):
    def __init__(self, market):
        super().__init__(market)
        self.calls = 0

    def execute(self, *a, **k):
        self.calls += 1
        return super().execute(*a, **k)


def _run_until(eng, market, d, pred, step=10):
    market.clock = datetime.combine(d, time(9, 14))
    while market.clock <= datetime.combine(d, time(15, 31)):
        eng.tick()
        if pred():
            return True
        market.clock += timedelta(seconds=step)
    return False


def test_live_manual_confirmation_places_nothing_unless_confirmed():
    d = date(2025, 6, 11)                                   # a day with two in-window signals
    m = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(d, time(9, 0)))
    b = CountingBroker(m)
    eng = le.Engine(le.EngineConfig(trade_mode="live", exec_mode="ATM_BUY", max_daily_loss=0, max_trades_per_day=100), m, b)
    assert eng.cfg.order_confirmation == "manual"          # the default
    eng.start(threaded=False)
    run_days(eng, m, [d])                                   # nobody confirms
    assert b.calls == 0 and not live_trades()
    with db.engine().connect() as c:
        msgs = [r[0] for r in c.execute(text("SELECT message FROM live_events WHERE session_id=:s"), {"s": eng.session_id})]
    assert any("waiting for your confirmation" in x for x in msgs)
    assert any("not confirmed in time" in x for x in msgs)


def test_live_confirmed_order_is_placed_and_rejected_is_not():
    d = date(2025, 6, 11)                                   # a day with two in-window signals
    m = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(d, time(9, 0)))
    b = CountingBroker(m)
    eng = le.Engine(le.EngineConfig(trade_mode="live", exec_mode="ATM_BUY", max_daily_loss=0, max_trades_per_day=100), m, b)
    eng.start(threaded=False)
    assert _run_until(eng, m, d, lambda: eng.pending is not None)
    pid = eng.status()["pending_order"]["id"]
    with pytest.raises(ValueError):
        eng.confirm_pending("wrong-id")
    eng.confirm_pending(pid)
    assert b.calls == 1 and eng.position is not None and len(live_trades()) == 1
    eng.square_off_now()
    assert _run_until(eng, m, d, lambda: eng.pending is not None)
    eng.reject_pending(eng.pending["id"])
    assert eng.pending is None and b.calls == 2              # 1 entry + 1 square-off exit; nothing for the rejected one


def test_paper_mode_never_waits_for_confirmation():
    d = date(2025, 6, 11)                                   # a day with two in-window signals
    eng, market = make({"timeframe": 15}, start_day=d)
    run_days(eng, market, [d])
    assert eng.pending is None and live_trades()


def test_trend_mode_enters_with_the_ema_trend_without_waiting_for_a_cross():
    """Trend mode (13 Nov): when flat, enter at the first bar close in the window in the direction of
    EMA 9 vs EMA 21; exit when the trend flips. Cross mode is unchanged (test_engine_matches_backtest)."""
    from app.services.strategy import rules as st
    days = [d for d in (START + timedelta(days=i) for i in range(5, 12)) if d.weekday() < 5]
    eng, market = make({"signal_mode": "trend", "timeframe": 15})
    run_days(eng, market, days)
    got = live_trades()
    assert got and all(g["status"] == "CLOSED" for g in got)

    full = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(days[-1], time(15, 31)))
    bars = st.add_emas(st.resample(full.spot_1m(days[-1]), 15))
    trend = {pd_ts.to_pydatetime(): (1 if e9 > e21 else -1)
             for pd_ts, e9, e21 in zip(bars["close_ts"], bars["ema9"], bars["ema21"])}
    for g in got:
        d = 1 if g["direction"] == "Bullish" else -1
        assert trend[g["signal_ts"]] == d                          # always with the trend at the signal bar
        assert time(9, 30) <= g["signal_ts"].time() <= time(14, 30)
        assert g["signal_mode"] == "trend"
    # every day starts trading at the first bar in the window (09:30), no crossover needed
    first = {}
    for g in got:
        first.setdefault(g["day"], g["signal_ts"].time())
    assert set(first) == set(days) and all(t == time(9, 30) for t in first.values())
    # positions never overlap
    for a, b in zip(got, got[1:]):
        assert a["exit_ts"] <= b["entry_ts"]
    # more entries than every-crossover mode on the same days
    clean = [r["id"] for r in got]
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions RESTART IDENTITY CASCADE"))
    eng2, m2 = make({"signal_mode": "cross", "timeframe": 15})
    run_days(eng2, m2, days)
    assert len(clean) >= len(live_trades())


def test_trend_mode_is_a_valid_signal_mode():
    assert le.EngineConfig(signal_mode="trend").validate().signal_mode == "trend"
    with pytest.raises(ValueError):
        le.EngineConfig(signal_mode="always").validate()

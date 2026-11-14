"""5-minute scalping analyzer: timing (no look-ahead), exits, sizing, selection and the paper engine mode."""
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import psycopg2
import pytest
from sqlalchemy import text

from app.config import settings as config
from app.database import db
from app.services.backtest import engine as backtest
from app.services.backtest import scalping as sc
from app.services.market_data.live import ReplayMarket
from app.services.trading import charges as costs
from app.services.trading import engine as le
from app.services.trading.brokers import PaperBroker

TEST_DB = "groww_trading_test_scalp"
START, END = date(2025, 6, 2), date(2025, 6, 27)
PARAMS = {"dataset": "synthetic", "start_date": START.isoformat(), "end_date": END.isoformat(),
          "timeframe": 5, "entry_start": "09:30", "cutoff": "14:30"}


@pytest.fixture(scope="module")
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


def candles(opens, highs=None, lows=None, start_min=9 * 60 + 35):
    n = len(opens)
    ts = pd.Series(pd.date_range(datetime(2025, 6, 3, start_min // 60, start_min % 60), periods=n, freq="1min"))
    df = pd.DataFrame({"ts": ts, "open": opens, "high": highs or opens, "low": lows or opens})
    return sc._arrays(df)


# ---------------------------------------------------------------- exits
def test_time_exit_is_the_open_five_minutes_after_entry():
    c = candles([100, 101, 102, 103, 104, 105, 106])
    assert sc.simulate(c, 0, {"kind": "time"}) == (5, 105.0, "time_exit")


def test_time_exit_needs_a_candle_soon_after_the_exit_time():
    c = sc._arrays(pd.DataFrame({"ts": pd.to_datetime(["2025-06-03 09:35", "2025-06-03 09:50"]),
                                 "open": [100, 90], "high": [100, 90], "low": [100, 90]}))
    assert sc.simulate(c, 0, {"kind": "time"}) is None      # no exit price invented


def test_stop_target_and_both_in_one_candle_takes_the_stop():
    ex = {"kind": "sl_target", "stop": 10.0, "target": 10.0}
    assert sc.simulate(candles([100, 100, 100], highs=[100, 111, 100], lows=[100, 100, 100]), 0, ex) == (1, 110.0, "target")
    assert sc.simulate(candles([100, 100, 100], highs=[100, 100, 100], lows=[100, 89, 100]), 0, ex) == (1, 90.0, "stop_loss")
    assert sc.simulate(candles([100, 100], highs=[100, 120], lows=[100, 80]), 0, ex)[2] == "stop_loss"
    # gap through the stop fills at the (worse) open, not at the stop
    assert sc.simulate(candles([100, 85, 85]), 0, ex) == (1, 85.0, "stop_loss")
    # neither hit within 5 minutes: time exit
    assert sc.simulate(candles([100] * 7), 0, ex) == (5, 100.0, "time_exit")


# ---------------------------------------------------------------- signals: completed bars only
def _spot(days=6, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    px = 22000.0
    for k in range(days):
        d = date(2025, 6, 2) + timedelta(days=k)
        for m in range(375):
            ts = datetime.combine(d, time(9, 15)) + timedelta(minutes=m)
            o = px; px = px + rng.normal(0, 6)
            rows.append((ts, o, max(o, px) + 1, min(o, px) - 1, px))
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])


@pytest.mark.parametrize("key", ["ema_9_21", "ema_5_20", "ema_9_21_rsi", "ema_9_21_macd"])
def test_signals_never_change_when_future_candles_arrive(key):
    """No repainting: signals found with data up to T equal the full-history signals up to T."""
    from app.services.strategy import strategies
    spot = _spot()
    days = set(spot["ts"].dt.date)
    full = sc.find_signals(strategies.prepare(spot, None, 5, key), key, days)
    cut = datetime(2025, 6, 6, 12, 0)
    part = sc.find_signals(strategies.prepare(spot[spot["ts"] < cut], None, 5, key), key, days)
    assert [s for s in full if s["ts"] <= cut] == part
    for s in full:      # signal time = close of a completed 5-minute bar, inside the entry window
        assert s["ts"].minute % 5 == 0 and time(9, 30) <= s["ts"].time() <= time(14, 30)
    assert len({s["ts"] for s in full}) == len(full)    # at most one signal per bar


# ---------------------------------------------------------------- one position at a time
def test_signal_while_a_position_is_open_is_skipped():
    from collections import defaultdict
    c = candles(list(np.linspace(100, 110, 30)))
    ts0 = datetime(2025, 6, 3, 9, 35)
    sigs = [("ema_9_21", {"ts": ts0, "direction": 1, "spot": 22000.0}),
            ("ema_9_21", {"ts": ts0 + timedelta(minutes=2), "direction": -1, "spot": 22000.0}),   # inside the 5-min hold
            ("ema_9_21", {"ts": ts0 + timedelta(minutes=5), "direction": 1, "spot": 22000.0})]   # exactly at the exit
    plan = {("ema_9_21", "ATM_BUY", s["ts"]): {"sym": "X", "strike": 22000.0, "typ": "CE", "expiry": date(2025, 6, 5), "lot": 75}
            for _, s in sigs}
    skipped, trades = defaultdict(lambda: defaultdict(int)), defaultdict(list)
    sc.price_day(date(2025, 6, 3), sigs, {"X": c}, plan, [{"key": "time5", "kind": "time"}], {}, skipped, trades, costs.DEFAULT_COSTS)
    got = trades["ema_9_21|ATM_BUY|time5"]
    assert [t["entry_ts"][11:16] for t in got] == ["09:35", "09:40"]
    assert skipped["ema_9_21|ATM_BUY|time5"]["position still open"] == 1
    t = got[0]
    # entry = the open of the first option candle at the signal time; costs are deducted
    assert t["entry"] == round(float(c["o"][0]), 2) and t["hold_min"] == 5
    assert t["net"] == round(t["gross"] - t["friction"], 2) and t["brokerage"] > 0 and t["taxes"] > 0


# ---------------------------------------------------------------- sizing and the verdict
def test_risk_sizing_keeps_the_loss_at_the_stop_within_budget():
    lots = sc.size_lots(100.0, 10.0, 75, 1.0, costs.DEFAULT_COSTS)
    one = -costs.round_trip("BUY", 100.0, 90.0, 75, costs.DEFAULT_COSTS)["net"]
    assert lots >= 1 and lots * one <= sc.CAPITAL * 0.01 < (lots + 1) * one
    assert sc.size_lots(100.0, 10.0, 75, 0.01, costs.DEFAULT_COSTS) == 0


def test_verdict_needs_every_condition_and_ignores_win_rate():
    m = {"net_pnl": 5000.0, "trades": 400, "profit_factor": 1.2, "win_rate": 20.0}
    yearly = {"2022": {"net": 100, "trades": 100}, "2023": {"net": 100, "trades": 100},
              "2024": {"net": 100, "trades": 100}, "2025": {"net": -50, "trades": 100}}
    assert sc.evaluate(m, yearly, 1000.0)["consistent"]
    assert not sc.evaluate(m, yearly, -1.0)["consistent"]                       # out of sample matters
    assert not sc.evaluate({**m, "trades": 50}, yearly, 1000.0)["consistent"]   # sample size matters
    assert not sc.evaluate({**m, "win_rate": 90.0, "net_pnl": -1.0}, yearly, 1000.0)["consistent"]


def test_walk_forward_uses_only_earlier_years():
    cfgs = {"a": {"yearly": {"2022": {"trades": 300}, "2023": {"trades": 300}}, "strategy_label": "A", "contract_label": "x", "exit_label": "y"},
            "b": {"yearly": {"2022": {"trades": 300}, "2023": {"trades": 300}}, "strategy_label": "B", "contract_label": "x", "exit_label": "y"}}
    wf = sc.walk_forward({"a": {"2022": 5000.0, "2023": -9000.0}, "b": {"2022": -100.0, "2023": 99999.0}}, cfgs)
    assert wf["rows"] == [{"year": "2023", "trained_on": "2022–2022", "pick": "a", "pick_label": "A · x · y",
                           "oos_net": -9000.0, "oos_trades": 300}]     # b's great 2023 is not seen when choosing


# ---------------------------------------------------------------- paper mode
def test_engine_config_maps_a_tested_configuration_and_refuses_live():
    cfg = sc.engine_config("ema_9_21_rsi|ITM5_BUY|sl10_tp20", "paper", {"risk_pct": 0.5, "exec_mode": "ATM_SELL"})
    assert cfg["signal_mode"] == "scalp" and cfg["exec_mode"] == "ITM5_BUY" and cfg["timeframe"] == 5
    assert (cfg["scalp_exit"], cfg["stop_pct"], cfg["target_pct"], cfg["risk_pct"]) == ("sl_target", 10.0, 20.0, 0.5)
    le.EngineConfig(**cfg).validate()
    assert sc.engine_config("ema_5_20|ATM_BUY|time5")["scalp_exit"] == "time"
    with pytest.raises(ValueError):
        sc.engine_config("ema_9_21|ATM_BUY|time5", "live")
    with pytest.raises(ValueError):
        sc.engine_config("ema_9_21|ATM_SELL|time5")
    with pytest.raises(ValueError, match="paper mode only"):
        le.EngineConfig(**{**cfg, "trade_mode": "live"}).validate()


def test_analyzer_runs_end_to_end_on_synthetic_data(test_db):
    out = sc.run(start=date(2025, 6, 9), end=END, store=False, dataset="synthetic")
    s = out["summary"]
    assert len(s["configs"]) == len(sc.STRATEGY_KEYS) * len(sc.CONTRACTS) * len(sc.exits())
    total = 0
    for c in s["configs"]:
        ts = out["trades"].get(c["key"], [])
        total += len(ts)
        assert c["trades"] == len(ts)
        assert c["ce"]["trades"] + c["pe"]["trades"] == len(ts)
        for t in ts:
            assert t["entry_ts"] >= t["signal_ts"]                  # never filled before the signal bar closed
            assert t["hold_min"] <= sc.HOLD_MIN + sc.EXIT_WAIT_MIN
            assert t["opt_type"] == ("CE" if t["direction"] == "Bullish" else "PE")
        for a, b in zip(ts, ts[1:]):
            assert b["entry_ts"] >= a["exit_ts"]                   # one position at a time
    assert total > 0
    assert s["selection_rule"] and "Win rate is not used" in s["selection_rule"]


def test_engine_scalp_mode_exits_within_the_holding_time(test_db):
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions RESTART IDENTITY CASCADE"))
    day = date(2025, 6, 10)
    market = ReplayMarket("synthetic", day - timedelta(days=12), datetime.combine(day, time(9, 0)))
    cfg = le.EngineConfig(**{**sc.engine_config("ema_5_20|ATM_BUY|time5", "replay"),
                             "max_daily_loss": 0, "daily_risk_pct": 0, "risk_pct": 100, "max_lots": 1, "max_trades_per_day": 100})
    eng = le.Engine(cfg, market, PaperBroker(market))
    eng.start(threaded=False)
    market.clock = datetime.combine(day, time(9, 14))
    while market.clock <= datetime.combine(day, time(15, 31)):
        eng.tick()
        market.clock += timedelta(seconds=10)
    rows = sc.paper_trades("ema_5_20|ATM_BUY|time5", include_synthetic=True)
    assert rows, "the synthetic day should produce at least one EMA 5/20 cross"
    for r in rows:
        assert r["signal_mode"] == "scalp" and r["strategy"] == "ema_5_20" and r["status"] == "CLOSED"
        held = (datetime.fromisoformat(r["exit_ts"]) - datetime.fromisoformat(r["entry_ts"])).total_seconds() / 60
        assert held <= 6 and r["exit_reason"] in ("time_exit", "stop_loss", "square_off")


def test_engine_scalp_replay_uses_stop_and_target_from_the_fill(test_db):
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions RESTART IDENTITY CASCADE"))
    day = date(2025, 6, 10)
    key = "ema_5_20|ATM_BUY|sl5_tp5"
    market = ReplayMarket("synthetic", day - timedelta(days=12), datetime.combine(day, time(9, 0)))
    cfg = le.EngineConfig(**{**sc.engine_config(key, "replay"), "max_daily_loss": 0, "max_trades_per_day": 100})
    eng = le.Engine(cfg, market, PaperBroker(market))
    eng.start(threaded=False)
    market.clock = datetime.combine(day, time(9, 14))
    while market.clock <= datetime.combine(day, time(15, 31)):
        eng.tick()
        market.clock += timedelta(seconds=10)
    rows = sc.paper_trades(key, include_synthetic=True)
    assert rows
    for r in rows:
        assert r["stop_premium"] == costs._round_tick_down(r["entry_price"] * 0.95)
        assert r["target_premium"] == costs._round_tick_up(r["entry_price"] * 1.05)
        assert r["exit_reason"] in ("time_exit", "stop_loss", "target", "square_off")

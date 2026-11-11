"""Level 2: indicators, strategy confirmation, expiry rules, signal scoring and walk-forward."""
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

import data_manager as dm
import indicators as ind
import research
import signals
import strategies
import strategy as st


# ---------------------------------------------------------------- indicators
def test_rsi_wilder_reference():
    # Classic Wilder example (Welles Wilder, 14-period); RSI uses only past bars.
    closes = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03,
                        45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64])
    r = ind.rsi(closes)
    assert r.iloc[:14].isna().all()
    assert round(r.iloc[14], 2) == 70.46       # Wilder's published value (70.53 with his rounding)
    up = ind.rsi(pd.Series(np.arange(1.0, 40.0)))
    assert up.iloc[-1] == 100.0


def test_macd_and_atr_basics():
    s = pd.Series(np.linspace(100, 200, 200))
    line, sig, hist = ind.macd(s)
    assert line.iloc[-1] > 0 and abs(hist.iloc[-1]) < 1
    bars = pd.DataFrame({"high": [11, 12, 13] * 10, "low": [9, 10, 11] * 10, "close": [10, 11, 12] * 10})
    a = ind.atr(bars)
    assert a.iloc[:13].isna().all() and a.iloc[-1] > 0


def test_session_vwap_resets_each_day():
    ts = [datetime(2026, 3, 2, 9, 15), datetime(2026, 3, 2, 9, 16), datetime(2026, 3, 3, 9, 15)]
    df = pd.DataFrame({"ts": ts, "high": [10, 20, 30], "low": [10, 20, 30], "close": [10, 20, 30], "volume": [1, 3, 5]})
    v = ind.session_vwap(df)
    assert v.tolist() == [10, (10 + 60) / 4, 30]


# ---------------------------------------------------------------- strategies
def _bars_with_cross(confirm_bull: bool):
    day = date(2026, 3, 2)
    starts = [datetime.combine(day, time(9, 15)) + timedelta(minutes=15 * i) for i in range(10)]
    fast = [1, 1, 1, -1, -1, -1, 1, 1, 1, 1]          # bear cross at bar 3, bull cross at bar 6
    return pd.DataFrame({"start": starts, "close_ts": [s + timedelta(minutes=15) for s in starts],
                         "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "day": day,
                         "fast": fast, "slow": [0] * 10,
                         "bull_ok": [confirm_bull] * 10, "bear_ok": [True] * 10})


def test_unconfirmed_cross_exits_but_does_not_enter():
    bars = _bars_with_cross(confirm_bull=False)
    legs, nt = st.generate_legs(bars, {date(2026, 3, 2)}, time(9, 30), time(14, 30), "fast", "slow", confirm=True)
    assert len(legs) == 1 and legs[0].direction == -1
    assert legs[0].exit_reason == "opposite_cross"          # the unconfirmed bull cross still exits
    legs2, _ = st.generate_legs(_bars_with_cross(True), {date(2026, 3, 2)}, time(9, 30), time(14, 30), "fast", "slow", confirm=True)
    assert [l.direction for l in legs2] == [-1, 1]


def test_unconfirmed_day_reason():
    bars = _bars_with_cross(confirm_bull=False)
    bars["bear_ok"] = False
    legs, nt = st.generate_legs(bars, {date(2026, 3, 2)}, time(9, 30), time(14, 30), "fast", "slow", confirm=True)
    assert not legs and "none confirmed" in nt[date(2026, 3, 2)]


def test_all_seven_strategies_and_warmup():
    assert len(strategies.STRATEGIES) == 7
    assert strategies.warmup_sessions("ema_9_21", 15) == 3
    assert strategies.warmup_sessions("ema_20_50", 30) == 12          # 150 bars / 13 per day
    assert strategies.warmup_sessions("ema_9_21_macd", 1) == 3


def test_prepare_confirmation_columns():
    day = date(2026, 3, 2)
    ts = pd.date_range(datetime.combine(day, time(9, 15)), periods=375, freq="1min")
    px = 22000 + np.cumsum(np.random.default_rng(1).normal(0, 3, 375))
    spot = pd.DataFrame({"ts": ts, "open": px, "high": px + 2, "low": px - 2, "close": px, "volume": 0.0, "oi": 0.0})
    fut = spot.assign(close=px + 50, high=px + 52, low=px + 48, volume=100.0)
    b = strategies.prepare(spot, fut, 15, "ema_9_21_vwap")
    assert {"fast", "slow", "rsi", "macd_hist", "atr", "fut_vwap", "bull_ok", "bear_ok"} <= set(b.columns)
    assert (b["bull_ok"] == (b["fut_close"] > b["fut_vwap"])).all()
    nofut = strategies.prepare(spot, None, 15, "ema_9_21_vwap")
    assert not nofut["bull_ok"].any() and not nofut["bear_ok"].any()     # no futures data -> never confirmed


# ---------------------------------------------------------------- expiries
def test_expiry_rules():
    exps = [date(2026, 3, 3), date(2026, 3, 10), date(2026, 3, 17), date(2026, 3, 24), date(2026, 3, 31), date(2026, 4, 7), date(2026, 4, 28)]
    assert st.pick_expiry(date(2026, 3, 2), exps) == date(2026, 3, 3)
    assert st.pick_expiry(date(2026, 3, 2), exps, rule="next") == date(2026, 3, 10)
    assert st.pick_expiry(date(2026, 3, 2), exps, rule="monthly") == date(2026, 3, 31)
    assert st.pick_expiry(date(2026, 3, 31), exps, rule="monthly") == date(2026, 4, 28)    # rolls to April's monthly
    assert st.pick_expiry(date(2026, 3, 31), exps, roll_on_expiry_day=False, rule="monthly") == date(2026, 3, 31)


def test_front_month_futures_roll_on_expiry_day():
    r = dm.front_month_ranges(date(2026, 1, 1), date(2026, 3, 31), [date(2026, 1, 27), date(2026, 2, 24), date(2026, 3, 30)])
    assert r == [("NSE-NIFTY-27Jan26-FUT", date(2026, 1, 1), date(2026, 1, 26)),
                 ("NSE-NIFTY-24Feb26-FUT", date(2026, 1, 27), date(2026, 2, 23)),
                 ("NSE-NIFTY-30Mar26-FUT", date(2026, 2, 24), date(2026, 3, 29))]


# ---------------------------------------------------------------- signal engine
def _path(prices):
    t0 = datetime(2026, 3, 2, 10, 0)
    return pd.DataFrame({"ts": [t0 + timedelta(minutes=i) for i in range(len(prices))],
                         "high": [p[0] for p in prices], "low": [p[1] for p in prices]})


def test_outcome_target_stop_and_same_minute():
    t0 = datetime(2026, 3, 2, 10, 0)
    assert signals._outcome(_path([(101, 99), (121, 100)]), t0, 100, 1, 10)[0] == "hit"      # target 120
    assert signals._outcome(_path([(101, 89), (121, 100)]), t0, 100, 1, 10)[0] == "miss"     # stop 90 first
    assert signals._outcome(_path([(121, 89)]), t0, 100, 1, 10)[0] == "miss"                 # both in one minute
    assert signals._outcome(_path([(101, 79)]), t0, 100, -1, 10)[0] == "hit"                 # short target 80
    assert signals._outcome(_path([(101, 99)]), t0, 100, 1, 10)[0] == "pending"              # day not finished


def test_logistic_fit_learns_and_is_calibrated_on_training_data():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(4000, 2))
    p = 1 / (1 + np.exp(-(0.5 + 1.5 * X[:, 0])))
    y = (rng.random(4000) < p).astype(float)
    m = signals.fit(X, y, lam=0.1)
    assert abs(m["w"][1] - 1.5) < 0.25 and abs(m["w"][2]) < 0.15
    pred = signals.predict(m, X)
    assert abs(pred.mean() - y.mean()) < 0.01
    assert signals.auc(pred, y) > 0.75
    assert signals.auc(np.zeros(4), np.array([1.0, 0, 1, 0])) == 0.5


def test_bands():
    assert signals.band(49.9) == "No strong signal"
    assert signals.band(50) == "Watch / Moderate signal"
    assert signals.band(84.9) == "Strong signal"
    assert signals.band(85) == "Very strong signal"
    assert signals.band(None) == "Not scored"


def test_daily_regime_uses_only_previous_days():
    days = pd.bdate_range("2025-01-01", periods=80)
    rows = []
    for i, d in enumerate(days):
        for m in range(2):
            px = 100 + i
            rows.append((pd.Timestamp(d) + pd.Timedelta(hours=9, minutes=15 + m), px, px + 1, px - 1, px))
    spot = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
    reg = signals.daily_regime(spot)
    assert reg["regime"].iloc[5] == "unknown"
    assert reg.loc[days[-1].date(), "close"] == 100 + 78          # yesterday's close, not today's


# ---------------------------------------------------------------- research
def _cell(strategy, tf, yearly_daily):
    daily = [[f"{y}-06-01", v] for y, v in yearly_daily.items()]
    m = {"daily": daily, "net_pnl": sum(yearly_daily.values())}
    return {"strategy": strategy, "timeframe": tf, "summary": {"modes": {"ATM_BUY": m}}}


def test_walk_forward_never_uses_the_test_year():
    cells = [_cell("ema_9_21", 15, {"2022": 100, "2023": -50, "2024": 10}),
             _cell("ema_5_20", 5, {"2022": -10, "2023": 500, "2024": -200})]
    wf = research.walk_forward(cells, "ATM_BUY")
    rows = {r["year"]: r for r in wf["rows"]}
    assert "2022" not in rows                                    # nothing earlier to choose with
    assert rows["2023"]["pick"]["strategy"] == "ema_9_21" and rows["2023"]["oos_net"] == -50
    assert rows["2023"]["hindsight_best"]["label"] == "EMA 5/20"
    assert rows["2024"]["pick"]["strategy"] == "ema_5_20" and rows["2024"]["oos_net"] == -200   # 490 vs 50 earlier
    assert wf["total_oos"] == -250 and wf["baseline_total"] == -40


def test_compact_summary():
    trades = [{"day": "2025-01-02", "net": 100.0, "gross": 120.0, "friction": 20.0},
              {"day": "2025-01-02", "net": -50.0, "gross": -40.0, "friction": 10.0},
              {"day": "2026-02-03", "net": 30.0, "gross": 35.0, "friction": 5.0}]
    res = {"signals": 3, "trade_days": 2, "params": {"capital": 100000}, "skipped": [{"mode": "ATM_BUY"}],
           "trades": {"ATM_BUY": trades}}
    c = research.compact(res)["modes"]["ATM_BUY"]
    assert c["daily"] == [["2025-01-02", 50.0], ["2026-02-03", 30.0]]
    assert c["yearly"]["2025"] == {"net": 50.0, "trades": 2, "win_rate": 50.0}
    assert c["monthly"] == {"2025-01": 50.0, "2026-02": 30.0} and c["skipped"] == 1
    assert "equity_curve" not in c


def test_option_symbol_falls_back_to_standard_name(monkeypatch):
    import db
    import providers
    p = providers.GrowwProvider()
    monkeypatch.setattr(db, "has_contracts", lambda *a, **k: True)
    monkeypatch.setattr(db, "find_contract", lambda *a, **k: None)
    assert p.option_symbol(date(2026, 10, 6), 22550.0, "CE") == "NSE-NIFTY-06Oct26-22550-CE"


def test_data_refresh_keeps_signal_analyses():
    import psycopg2, config, db
    name = "groww_trading_test_clear"
    conn = psycopg2.connect(**{**config.PG, "dbname": "postgres"}); conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"); cur.execute(f"CREATE DATABASE {name}")
    old = db._engine
    db._engine = db.engine(name)
    try:
        db.init()
        db.save_run("a", {"dataset": "groww", "strategy": "ema_9_21"}, {"x": 1})
        db.save_run("b", {"dataset": "groww", "kind": "signals"}, {"x": 2})
        db.clear_runs("groww")
        assert db.get_run("a") is None and db.get_run("b")["result"] == {"x": 2}
    finally:
        db._engine.dispose(); db._engine = old
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.close()

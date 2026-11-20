"""The bias-mode engine (automated multi-timeframe paper trading), replayed on stored candles."""
from datetime import date, datetime, time, timedelta

import psycopg2
import pytest
from sqlalchemy import text

from app.config import settings as config
from app.database import db
from app.services.backtest import engine as backtest
from app.services.market_data.live import Contract, ReplayMarket
from app.services.trading import engine as le
from app.services.trading.brokers import PaperBroker

TEST_DB = "groww_trading_test_bias"
START, END = date(2025, 6, 2), date(2025, 6, 27)
PARAMS = {"dataset": "synthetic", "start_date": START.isoformat(), "end_date": END.isoformat(),
          "timeframe": 15, "entry_start": "09:30", "cutoff": "14:30"}
DAYS = [d for d in (START + timedelta(days=i) for i in range(8, 13)) if d.weekday() < 5]


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
def clean():
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, candle_bias, paper_stop_changes RESTART IDENTITY CASCADE"))


# thresholds loosened so the synthetic candles produce trades; the logic under test is the same
LOOSE = {"signal_mode": "bias", "trade_mode": "replay", "timeframe": 5, "bias_min_confidence": 30, "bias_min_atr_pct": 0, "bias_trend_thr": 0.1,
         "bias_confirm_thr": 0.05, "min_premium": 0, "max_spread_pct": 0, "min_delta": 0, "max_daily_loss": 0,
         "lots": 1, "max_trades_per_day": 20, "entry_start": "09:30", "cutoff": "14:30", "bias_cooldown_bars": 2,
         "stop_mode": "pct", "stop_pct": 30}


def make(over=None, day=None):
    market = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(day or DAYS[0], time(9, 0)))
    eng = le.Engine(le.EngineConfig(**{**LOOSE, **(over or {})}), market, PaperBroker(market))
    eng.start(threaded=False)
    return eng, market


def run_days(eng, market, days, step=10):
    for d in days:
        market.clock = datetime.combine(d, time(9, 14))
        end = datetime.combine(d, time(15, 31))
        while market.clock <= end:
            eng.tick()
            market.clock += timedelta(seconds=step)


def q(sql, **kw):
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(text(sql), kw).mappings()]


@pytest.fixture(scope="module")
def baseline():
    """One multi-day replay shared by the invariant checks (the fixtures above clean between tests, so it is rebuilt)."""
    return None


def test_live_real_money_is_refused_for_bias_mode():
    with pytest.raises(ValueError, match="paper only"):
        le.EngineConfig(trade_mode="live", signal_mode="bias").validate()
    cfg = le.EngineConfig(signal_mode="bias", trade_mode="paper", timeframe=5).validate()
    assert cfg.timeframe == 5 and cfg.bias_confirm_tf == 15


def test_validation_messages():
    for over, msg in (({"bias_allow": []}, "choose at least one"), ({"bias_allow": ["BUY_XX"]}, "choose at least one"),
                      ({"bias_indicators": ["nope"]}, "at least one indicator"), ({"bias_min_confidence": 150}, "between"),
                      ({"max_trades_per_day": 0}, "at least 1"), ({"trail_pct": 120}, "between"),
                      ({"timeframe": 30}, "must be 5 or 15"), ({"timeframe": 15, "bias_confirm_tf": 15}, "longer than the analysis"),
                      ({"bias_confirm_tf": 20}, "15, 30 or 60"), ({"timeframe": 15, "bias_confirm_tf": 45}, "15, 30 or 60")):
        with pytest.raises(ValueError, match=msg):
            le.EngineConfig(**{**LOOSE, **over}).validate()


def test_every_candle_is_analysed_stored_and_settled_without_look_ahead():
    eng, market = make()
    run_days(eng, market, DAYS[:2])
    rows = q("SELECT * FROM candle_bias WHERE trade_mode='replay' ORDER BY bar_close")
    assert len(rows) == 148                                   # the 74 candles closing 09:20-15:25, x 2 days, each once
    assert len({r["bar_close"] for r in rows}) == 148
    for r in rows:
        assert r["predicted"] in ("UP", "DOWN", "NEUTRAL") and r["bias"] in (
            "STRONG BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "STRONG BEARISH")
        assert 0 <= r["confidence"] <= 100 and set(r["votes"]) == {"5m", "15m"}
    settled = [r for r in rows if r["outcome"]]
    assert len(settled) == 146                                # all but the last candle of each day
    for a, b in zip(rows, rows[1:]):
        if a["day"] == b["day"]:
            assert a["next_close"] == pytest.approx(b["nifty_close"])      # the actual result is the NEXT candle's close
            assert a["outcome"] in ("CORRECT", "INCORRECT", "NEUTRAL")
            if a["predicted"] == "NEUTRAL":
                assert a["outcome"] == "NEUTRAL"
        else:
            assert a["outcome"] is None


def test_trades_follow_the_rules_and_are_explained():
    eng, market = make()
    run_days(eng, market, DAYS)
    trades = q("SELECT * FROM live_trades ORDER BY id")
    assert trades, "the loosened thresholds must produce trades on these days"
    for t in trades:
        assert t["status"] == "CLOSED" and t["signal_mode"] == "bias" and t["trade_mode"] == "replay"
        assert t["signal_ts"].minute % 5 == 0 and t["signal_ts"].second == 0
        assert time(9, 30) <= t["signal_ts"].time() <= time(14, 30)             # inside the entry window
        assert t["exit_ts"].time() <= time(15, 0, 30)                          # all squared off by 15:00
        a = t["analysis"]
        assert a["signal"] in ("BUY CE", "BUY PE") and a["supports"] and a["indicators"] and a["contract_checks"]
        assert t["action"] in ("BUY CE", "BUY PE") and t["confidence"] == pytest.approx(a["confidence"])
        assert (t["action"] == "BUY CE") == (t["direction"] == "Bullish")
        assert t["exit_detail"]["reason"] == t["exit_reason"]
        assert t["stop_premium"] is not None and t["target_premium"] is not None and t["target_premium"] > t["entry_price"]
        assert t["exit_reason"] in ("opposite_signal", "stop_loss", "target", "time_exit", "square_off", "manual_stop")
    # an entry happens on a candle whose stored analysis says the same thing, and one signal episode is traded once
    rows = q("SELECT bar_close, signal FROM candle_bias ORDER BY bar_close")
    sig = {r["bar_close"]: r["signal"] for r in rows}
    for t in trades:
        assert sig[t["signal_ts"]] == t["action"]
    for a, b in zip(trades, trades[1:]):
        if a["day"] == b["day"] and a["direction"] == b["direction"]:
            between = [r["signal"] for r in rows if a["signal_ts"] < r["bar_close"] < b["signal_ts"]]
            assert any(s != a["action"] for s in between), "the same unchanged signal was traded twice"
    # one position at a time: a trade only opens after the previous one closed
    for a, b in zip(trades, trades[1:]):
        assert b["entry_ts"] >= a["exit_ts"]
    # a reversal is never entered on the bar that closed the previous trade
    for a, b in zip(trades, trades[1:]):
        if a["exit_reason"] == "opposite_signal" and a["day"] == b["day"]:
            assert b["signal_ts"] >= a["exit_ts"].replace(second=0) + timedelta(minutes=5 * 2 - 5)


def test_daily_trade_limit_is_a_hard_cap_and_never_forced():
    eng, market = make({"max_trades_per_day": 1})
    run_days(eng, market, DAYS)
    per_day = {}
    for t in q("SELECT day FROM live_trades"):
        per_day[t["day"]] = per_day.get(t["day"], 0) + 1
    assert per_day and max(per_day.values()) == 1
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, candle_bias RESTART IDENTITY CASCADE"))
    eng3, market3 = make({"bias_min_atr_pct": 5.0})            # a market that never moves 5% per candle: weak, so no trades
    run_days(eng3, market3, DAYS[:2])
    assert q("SELECT count(*) AS n FROM live_trades")[0]["n"] == 0     # the limit is a cap, never a target
    assert any("volatility too low" in e["message"] for e in eng3.events)


def test_only_enabled_instruments_are_traded_and_writing_uses_sell_side():
    eng, market = make({"bias_allow": ["BUY_PE"]})
    run_days(eng, market, DAYS)
    ts = q("SELECT * FROM live_trades")
    assert all(t["opt_type"] == "PE" and t["side"] == "BUY" for t in ts)
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, candle_bias RESTART IDENTITY CASCADE"))
    eng, market = make({"bias_allow": ["SELL_CE", "SELL_PE"]})
    run_days(eng, market, DAYS)
    ts = q("SELECT * FROM live_trades")
    assert ts and all(t["side"] == "SELL" for t in ts)
    assert all((t["opt_type"] == "PE") == (t["direction"] == "Bullish") for t in ts)    # bullish -> write PE, bearish -> write CE
    assert all(t["stop_premium"] > t["entry_price"] and t["target_premium"] < t["entry_price"] for t in ts)


def test_time_exit_closes_after_the_holding_limit():
    eng, market = make({"bias_max_hold_min": 10, "bias_exit_opposite": False})
    run_days(eng, market, DAYS)
    ts = q("SELECT * FROM live_trades")
    assert ts
    for t in ts:
        if t["exit_reason"] == "time_exit":
            assert timedelta(minutes=10) <= t["exit_ts"] - t["entry_ts"] < timedelta(minutes=11)
        else:
            assert t["exit_ts"] - t["entry_ts"] < timedelta(minutes=11) or t["exit_reason"] in ("square_off", "target", "stop_loss")


class FakeMarket:
    """Just enough market for _bias_exits: a clock and a controllable option price."""
    def __init__(self):
        self.t = datetime(2025, 6, 9, 11, 0)
        self.price = 100.0

    def now(self):
        return self.t

    def option_ltp(self, c):
        return self.price


def position(side="BUY"):
    c = Contract("NIFTY25JUN25000CE", "NSE-NIFTY-12Jun25-25000-CE", date(2025, 6, 12), 25000.0, "CE", 75)
    return {"id": 1, "direction": 1 if side == "BUY" else -1, "side": side, "contract": c, "qty": 75,
            "entry_price": 100.0, "entry_ts": datetime(2025, 6, 9, 10, 55), "signal_ts": datetime(2025, 6, 9, 10, 55),
            "entry_ref": 25000.0, "stop_premium": 80.0 if side == "BUY" else 120.0,
            "target_premium": 140.0 if side == "BUY" else 60.0, "levels_set": True}


def bare_engine(over=None, side="BUY"):
    m = FakeMarket()
    e = le.Engine(le.EngineConfig(**{**LOOSE, "trade_mode": "replay", **(over or {})}), m, PaperBroker(m))
    e.state, e.day = "running", m.t.date()
    with db.engine().begin() as c:
        e.session_id = c.execute(text("INSERT INTO live_sessions (trade_mode, config) VALUES ('replay','{}') RETURNING id")).scalar_one()
        tid = c.execute(text("INSERT INTO live_trades (session_id, trade_mode, day, exec_mode, direction, side, trading_symbol, groww_symbol, "
                             "strike, opt_type, expiry, qty, signal_ts, signal_close, entry_ts, entry_price, status, signal_mode) VALUES "
                             "(:s,'replay',:d,'ATM_BUY','Bullish',:side,'X','X',25000,'CE',:d,75,:t,25000,:t,100,'OPEN','bias') RETURNING id"),
                        {"s": e.session_id, "d": m.t.date(), "side": side, "t": m.t}).scalar_one()
    e.position = {**position(side), "id": tid}
    e.exits = []
    e._exit = lambda reason: (e.exits.append(reason), setattr(e, "position", None))
    return e, m


def feed(e, m, price):
    m.price = price
    sym = e.position["contract"].trading_symbol
    e.last_ltp[sym], e.last_ltp_at[sym] = price, m.now()
    e._bias_exits(m.now())


def test_trailing_stop_only_tightens_and_exits_through_the_stop():
    e, m = bare_engine({"trail_pct": 10, "trail_activate_pct": 10})
    feed(e, m, 108)                                     # +8%: trail not active yet
    assert e.position["stop_premium"] == 80.0
    feed(e, m, 120)                                     # +20%: stop follows the best premium, 10% below it
    assert e.position["stop_premium"] == pytest.approx(108.0, abs=0.06)
    feed(e, m, 115)                                     # pulled back: the stop never loosens
    assert e.position["stop_premium"] == pytest.approx(108.0, abs=0.06)
    feed(e, m, 130)
    assert e.position["stop_premium"] == pytest.approx(117.0, abs=0.06)
    assert e.exits == []
    rec = q("SELECT source FROM paper_stop_changes ORDER BY id")
    assert [r["source"] for r in rec] == ["trail", "trail"]


def test_target_and_replay_stop_exits_for_buy_and_sell():
    e, m = bare_engine()
    feed(e, m, 141)
    assert e.exits == ["target"]
    e, m = bare_engine()
    feed(e, m, 79)
    assert e.exits == ["stop_loss"]
    e, m = bare_engine(side="SELL")
    feed(e, m, 59)
    assert e.exits == ["target"]
    e, m = bare_engine(side="SELL")
    feed(e, m, 121)
    assert e.exits == ["stop_loss"]


def test_a_stale_price_never_triggers_an_exit():
    e, m = bare_engine()
    m.price = 70
    sym = e.position["contract"].trading_symbol
    e.last_ltp[sym], e.last_ltp_at[sym] = 70, m.now() - timedelta(seconds=60)
    e._bias_exits(m.now())
    assert e.exits == []


def test_settings_change_without_restart_and_bad_values_change_nothing():
    eng, market = make()
    out = eng.update_settings({"bias_min_confidence": 70, "bias_allow": ["BUY_CE"], "trail_pct": 5})
    assert len(out["changed"]) == 3 and eng.cfg.bias_min_confidence == 70 and eng.cfg.bias_allow == ["BUY_CE"]
    with pytest.raises(ValueError):
        eng.update_settings({"bias_min_confidence": 500})
    assert eng.cfg.bias_min_confidence == 70
    with pytest.raises(ValueError, match="cannot be changed"):
        eng.update_settings({"trade_mode": "live"})
    assert eng.cfg.trade_mode == "replay"
    assert "Settings changed" in eng.events[0]["message"]


def test_status_carries_the_dashboard_data():
    eng, market = make()
    run_days(eng, market, DAYS[:1])
    s = eng.status()
    b = s["bias"]
    assert b["latest"]["bias"] and b["latest"]["indicators"] and b["max_trades"] == 20
    assert b["remaining_trades"] == 20 - b["trades_today"] and len(b["history"]) > 10
    assert any(h["outcome"] for h in b["history"])


def test_contract_checks_refuse_a_bad_contract_and_skip_unknown_data():
    eng, market = make({"min_premium": 1e6})
    run_days(eng, market, DAYS[:2])
    assert q("SELECT count(*) AS n FROM live_trades")[0]["n"] == 0
    assert any("NO TRADE" in e["message"] and "minimum" in e["message"] for e in eng.events)
    eng, market = make({"min_oi": 1, "max_spread_pct": 5, "min_delta": 0.3})
    c = Contract("X", "X", date(2025, 6, 12), 25000.0, "CE", 75)
    market.option_ltp = lambda c_: 50.0
    market.option_quote = lambda c_: {"oi": None, "bid": None, "ask": None, "delta": None}
    eng.day = date(2025, 6, 9)
    refs = {"analysis": {}}
    assert eng._bias_contract_check(c, "BUY", refs) is None                 # unknown data is recorded, not guessed
    assert [x["ok"] for x in refs["analysis"]["contract_checks"] if x["check"] in ("open_interest", "spread", "delta")] == [None] * 3
    market.option_quote = lambda c_: {"oi": 10.0, "bid": 40.0, "ask": 60.0, "delta": 0.1}
    why = eng._bias_contract_check(c, "BUY", {"analysis": {}})
    assert "spread" in why and "delta" in why



# ---------------------------------------------------------------- continuous automation: net profit target, re-entry, pause
from app.services.strategy import rules as _st                          # noqa: E402
from app.services.trading import charges as _costs                     # noqa: E402


def net_at(price, side="BUY", entry=100.0, qty=75):
    return _costs.round_trip(side, entry, price, qty, _costs.DEFAULT_COSTS)["net"]


def real_engine(over=None, side="BUY", stop=None, target=None):
    """Like bare_engine but the real _exit runs (paper fill, P&L, database row, alerts)."""
    e, m = bare_engine(over, side)
    del e._exit
    e.position.update(stop_premium=stop if stop is not None else (1.0 if side == "BUY" else 900.0),
                      target_premium=target if target is not None else (900.0 if side == "BUY" else 1.0))
    return e, m


def test_profit_target_exits_on_net_profit_after_charges_not_gross():
    e, m = bare_engine({"profit_target_net": 1500})
    e.position.update(stop_premium=1.0, target_premium=900.0)
    price = 100.0
    while net_at(price) < 1500:
        price = round(price + 0.05, 2)
    assert net_at(price - 0.05) < 1500 <= net_at(price)
    gross_only = 100 + 1500 / 75                        # the premium where GROSS profit is 1,500: net is still short of the target
    assert net_at(gross_only) < 1500
    feed(e, m, gross_only)
    assert e.exits == []                                # slippage and charges are deducted first
    feed(e, m, round(price - 0.05, 2))
    assert e.exits == []
    feed(e, m, price)
    assert e.exits == ["profit_target"]


def test_profit_target_sell_side_and_off_by_default():
    e, m = bare_engine({"profit_target_net": 1500}, side="SELL")
    e.position.update(stop_premium=900.0, target_premium=1.0)
    feed(e, m, 80)
    assert e.exits == []                                # +1,500 gross for a writer is not +1,500 net
    price = 100.0
    while net_at(price, "SELL") < 1500:
        price = round(price - 0.05, 2)
    feed(e, m, price)
    assert e.exits == ["profit_target"]
    e, m = bare_engine()                                # default: off, only the stop, the risk-reward target and the rest apply
    e.position.update(stop_premium=1.0, target_premium=900.0)
    feed(e, m, 160)
    assert e.exits == []


def test_a_stale_price_never_triggers_the_profit_target():
    e, m = bare_engine({"profit_target_net": 1500})
    e.position.update(stop_premium=1.0, target_premium=900.0)
    sym = e.position["contract"].trading_symbol
    e.last_ltp[sym], e.last_ltp_at[sym] = 200, m.now() - timedelta(seconds=60)
    e._bias_exits(m.now())
    assert e.exits == []


def test_profit_target_exit_records_net_blocks_the_exit_candle_and_releases_the_signal():
    e, m = real_engine({"profit_target_net": 1500})
    e._last_entry_signal = datetime(2025, 6, 9, 10, 55)        # the signal that opened this trade
    m.t = datetime(2025, 6, 9, 11, 7, 3)                       # mid-candle: the 11:05-11:10 candle
    feed(e, m, 130)
    assert e.position is None and e.target_hits_today == 1
    row = q("SELECT * FROM live_trades")[0]
    assert row["exit_reason"] == "profit_target" and row["status"] == "CLOSED" and row["net"] >= 1500
    assert row["net"] == pytest.approx(net_at(130)) and e.realised_today == pytest.approx(row["net"])
    assert e._last_entry_signal is None                         # the same unchanged signal may enter again ...
    assert e._no_entry_through == datetime(2025, 6, 9, 11, 10)  # ... but never on the candle that exited
    assert row["exit_detail"]["reason"] == "profit_target"
    # a stop-loss exit does not release the signal (no stacking after a loss) and is not a target hit
    e, m = real_engine({"profit_target_net": 1500}, stop=80.0, target=900.0)
    e._last_entry_signal = datetime(2025, 6, 9, 10, 55)
    feed(e, m, 79)
    assert e.position is None
    assert q("SELECT exit_reason FROM live_trades ORDER BY id DESC")[0]["exit_reason"] == "stop_loss"
    assert e._last_entry_signal == datetime(2025, 6, 9, 10, 55) and e.target_hits_today == 0
    assert e._no_entry_through == datetime(2025, 6, 9, 11, 5)


def test_automation_phase_says_what_the_engine_is_doing():
    e, m = bare_engine({"profit_target_net": 1500})
    m.t = datetime(2025, 6, 9, 11, 7, 3)
    nxt = datetime(2025, 6, 9, 11, 10)
    a = e._automation(nxt)
    assert a["phase"] == "holding" and "1,500" in a["detail"] and a["profit_target_net"] == 1500
    e.position["pending_reason"] = "profit_target"
    assert e._automation(nxt)["phase"] == "exiting"
    e.position = None
    e._no_entry_through = datetime(2025, 6, 9, 11, 10)
    a = e._automation(nxt)
    assert a["phase"] == "waiting" and "11:15" in a["detail"]
    e._no_entry_through = None
    e.trades_today = 1
    a = e._automation(nxt)
    assert a["phase"] == "ready" and a["label"] == "Ready for re-entry" and "30%" in a["detail"]
    e.trades_today = 0
    assert e._automation(nxt)["label"] == "Ready for entry"
    e.paused = True
    assert e._automation(nxt)["phase"] == "paused"
    e.paused = False
    e.trades_today = e.cfg.max_trades_per_day
    assert e._automation(nxt)["phase"] == "limit"
    e.trades_today = 0
    e.state, e.halt_reason = "halted", "Daily loss limit reached: no more trades today"
    a = e._automation(nxt)
    assert a["phase"] == "halted" and "loss limit" in a["detail"]


def test_pause_and_resume_change_only_new_entries():
    e, m = bare_engine({"profit_target_net": 1500})
    e.pause()
    assert e.paused and "paused" in e.events[0]["message"]
    e.position.update(stop_premium=1.0, target_premium=900.0)
    feed(e, m, 130)
    assert e.exits == ["profit_target"]                        # an open position is still managed while paused
    e.resume()
    assert not e.paused
    plain = le.Engine(le.EngineConfig(trade_mode="paper", signal_mode="cross"), FakeMarket(), PaperBroker(FakeMarket()))
    with pytest.raises(ValueError, match="bias engine only"):
        plain.pause()


def test_profit_target_setting_validates_and_changes_without_restart():
    with pytest.raises(ValueError, match="profit target net must be between"):
        le.EngineConfig(**{**LOOSE, "profit_target_net": -1}).validate()
    eng, market = make()
    assert eng.cfg.profit_target_net == 0
    out = eng.update_settings({"profit_target_net": 1500, "bias_min_confidence": 70})
    assert eng.cfg.profit_target_net == 1500 and eng.cfg.bias_min_confidence == 70 and len(out["changed"]) == 2
    with pytest.raises(ValueError):
        eng.update_settings({"profit_target_net": -5})
    assert eng.cfg.profit_target_net == 1500


def test_daily_loss_limit_stops_new_entries():
    e, m = bare_engine({"max_daily_loss": 100, "profit_target_net": 1500})
    e.position = None
    e.realised_today = -200.0
    e._risk_check(m.now())
    assert e.state == "halted" and "loss limit" in e.halt_reason
    leg = _st.Leg(day=m.t.date(), direction=1, entry_ts=m.t, signal_close=25000.0, signal_bar_start=m.t, ordinal=1)
    e._try_entry(m.t, leg)
    assert e.position is None and any("engine halted" in x["message"] for x in e.events)
    assert q("SELECT count(*) AS n FROM live_trades WHERE status='OPEN'")[0]["n"] == 1      # only the fixture's own row


def test_restart_recovery_keeps_the_target_the_exit_candle_and_the_release():
    e, m = real_engine({"profit_target_net": 1500})
    e._last_entry_signal = datetime(2025, 6, 9, 10, 55)
    m.t = datetime(2025, 6, 9, 11, 7, 3)
    feed(e, m, 130)                                              # trade 1 closes by the net profit target
    cfg = {**LOOSE, "trade_mode": "replay", "profit_target_net": 1500}
    fresh = le.Engine(le.EngineConfig(**cfg), FakeMarket(), PaperBroker(FakeMarket()))
    fresh.session_id, fresh.day = e.session_id, e.day
    fresh._load_day_state(e.day)                                 # what a restarted engine reads back
    assert fresh.target_hits_today == 1 and fresh.trades_today == 1 and fresh.position is None
    assert fresh._no_entry_through == datetime(2025, 6, 9, 11, 10) and fresh._last_entry_signal is None
    assert fresh.realised_today >= 1500
    # an open position is resumed and still exits at the same net target
    with db.engine().begin() as c:
        c.execute(text("INSERT INTO live_trades (session_id, trade_mode, day, exec_mode, direction, side, trading_symbol, groww_symbol, "
                       "strike, opt_type, expiry, qty, signal_ts, signal_close, entry_ts, entry_price, status, signal_mode, "
                       "stop_premium, target_premium) VALUES (:s,'replay',:d,'ATM_BUY','Bullish','BUY','Y','Y',25000,'CE',:d,75,:t,25000,:t,"
                       "100,'OPEN','bias',1,900)"),
                  {"s": e.session_id, "d": e.day, "t": datetime(2025, 6, 9, 11, 20)})
    m2 = FakeMarket()
    m2.t = datetime(2025, 6, 9, 11, 30)
    fresh2 = le.Engine(le.EngineConfig(**cfg), m2, PaperBroker(m2))
    fresh2.session_id, fresh2.day, fresh2.state = e.session_id, e.day, "running"
    fresh2._load_day_state(e.day)
    assert fresh2.position and fresh2.position["entry_price"] == 100 and fresh2.trades_today == 2
    fresh2.exits = []
    fresh2._exit = lambda reason: (fresh2.exits.append(reason), setattr(fresh2, "position", None))
    sym = fresh2.position["contract"].trading_symbol
    fresh2.last_ltp[sym], fresh2.last_ltp_at[sym] = 130, m2.now()
    fresh2._bias_exits(m2.now())
    assert fresh2.exits == ["profit_target"]


def test_entries_need_the_confidence_threshold_and_never_repeat_on_one_candle():
    eng, market = make({"bias_min_confidence": 70, "profit_target_net": 300})
    run_days(eng, market, DAYS)
    trades = q("SELECT * FROM live_trades ORDER BY id")
    assert trades, "the synthetic days must produce trades at a 70% threshold"
    assert all(t["confidence"] >= 70 for t in trades)                             # below 70% never enters
    assert all(t["status"] == "CLOSED" and t["exit_ts"].time() <= time(15, 0, 30) for t in trades)
    for a, b in zip(trades, trades[1:]):
        assert b["entry_ts"] >= a["exit_ts"]                                      # one position at a time
        if a["day"] == b["day"]:
            assert b["signal_ts"] != a["signal_ts"]                              # one entry per candle
            assert b["signal_ts"] > eng._candle_close_after(a["exit_ts"])        # a candle that opened after the exit
    assert len({(t["day"], t["signal_ts"]) for t in trades}) == len(trades)
    for t in trades:
        if t["exit_reason"] == "profit_target":
            assert t["net"] >= 300


def test_repeated_sequential_trades_after_target_hits_and_a_paused_engine_takes_none():
    eng, market = make({"profit_target_net": 150, "bias_cooldown_bars": 0})
    run_days(eng, market, DAYS)
    trades = q("SELECT * FROM live_trades ORDER BY id")
    hits = [i for i, t in enumerate(trades[:-1]) if t["exit_reason"] == "profit_target" and trades[i + 1]["day"] == t["day"]]
    assert hits, "a target hit must be followed by another trade on at least one day"
    i = hits[0]
    assert trades[i + 1]["signal_ts"] > eng._candle_close_after(trades[i]["exit_ts"])
    per_day = {}
    for t in trades:
        per_day[t["day"]] = per_day.get(t["day"], 0) + 1
    assert 2 <= max(per_day.values()) <= 20                                          # several sequential trades, within the cap
    assert all(t["status"] == "CLOSED" for t in trades)                              # market close: everything squared off
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, candle_bias RESTART IDENTITY CASCADE"))
    eng, market = make({"profit_target_net": 150})
    eng.pause()
    run_days(eng, market, DAYS[:2])
    assert q("SELECT count(*) AS n FROM live_trades")[0]["n"] == 0
    assert any("paused" in e["message"] for e in eng.events)
    assert q("SELECT count(*) AS n FROM candle_bias")[0]["n"] > 100                  # the analysis kept running

"""The continuous opportunity scanner (entry strategy `scanner`): the quality score, independent strategies, concurrent positions,
the risk limits, no fixed daily trade count, duplicate-signal protection and restart recovery. Paper and replay only."""
import json
from datetime import date, datetime, time, timedelta

import pandas as pd
import psycopg2
import pytest
from sqlalchemy import text

from app.config import settings as config
from app.database import db
from app.services.backtest import engine as backtest
from app.services.market_data.live import ReplayMarket
from app.services.strategy import evidence, scanner
from app.services.strategy import rules as st
from app.services.trading import engine as le
from app.services.trading import trading_settings as ts
from app.services.trading.brokers import PaperBroker

TEST_DB = "groww_trading_test_scanner"
START, END = date(2025, 6, 2), date(2025, 6, 27)
PARAMS = {"dataset": "synthetic", "start_date": START.isoformat(), "end_date": END.isoformat(), "timeframe": 15, "entry_start": "09:30", "cutoff": "14:30"}
DAYS = [d for d in (START + timedelta(days=i) for i in range(8, 13)) if d.weekday() < 5]
CROSSES = ["ema_9_21", "ema_5_20", "ema_8_21"]


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
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, candle_bias, paper_stop_changes, trading_settings RESTART IDENTITY CASCADE"))
    ts.invalidate()


LOOSE = {"signal_mode": "bias", "trade_mode": "replay", "timeframe": 5, "bias_min_atr_pct": 0, "min_premium": 0, "max_spread_pct": 0, "min_delta": 0,
         "max_daily_loss": 0, "lots": 1, "max_trades_per_day": 0, "entry_start": "09:30", "cutoff": "14:30", "bias_cooldown_bars": 2,
         "stop_mode": "pct", "stop_pct": 30, "entry_strategy": "scanner", "max_open_positions": 3, "max_strategy_positions": 1,
         "scan_min_quality": 0, "scan_allow_unvalidated": True}


def saved(on=CROSSES, **rules):
    d = ts.defaults()
    for k in d["strategies"]:
        d["strategies"][k]["enabled"] = k in on
    d["rules"].update(stop_mode="pct", daily_loss_pct=0.0, daily_loss_rupees=0.0, max_trades_per_day=0, max_open_positions=3, max_strategy_positions=1,
                      max_open_risk_pct=0.0, max_strategy_risk_pct=0.0, scan_min_quality=0.0, scan_allow_unvalidated=True)
    d["rules"].update(rules)
    d["timeframes"]["trend_filter"] = False
    return ts.save(d)


def make(over=None):
    market = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(DAYS[0], time(9, 0)))
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
    with db.engine().begin() as c:
        return [dict(r) for r in c.execute(text(sql), kw).mappings()]


# ---------------------------------------------------------------- the score
def row(**votes):
    base = {f"v5_{k}": 0.0 for k in ("ema_9_21", "ema_5_20", "ema_8_21", "ema_20_50", "ema_200", "vwap", "rsi", "rsi_divergence", "macd", "bollinger", "volume", "sr")}
    base.update({f"v5_{k}": v for k, v in votes.items()})
    return pd.Series({**base, "s15": votes.pop("s15", 0.0) if "s15" in votes else 0.0})


def test_the_components_add_up_to_exactly_100_and_the_score_is_not_a_probability(monkeypatch):
    full = pd.Series({**{f"v5_{k}": 1.0 for k in ("ema_9_21", "ema_5_20", "ema_8_21", "ema_20_50", "ema_200", "vwap", "rsi", "rsi_divergence", "macd", "bollinger", "volume", "sr")}, "s15": 1.0})
    comps = scanner.candle_components(full, 1)
    assert sum(c["max"] for c in comps) == 65 and scanner.total(comps) == 65
    monkeypatch.setitem(evidence.EVIDENCE, "ema_9_21", {"status": "positive", "trades": 1000, "oos_net": 5000, "note": "x"})
    comps.append(scanner.evidence_component("ema_9_21"))
    ok = [{"check": "premium", "ok": True, "text": "p"}, {"check": "open_interest", "ok": True, "text": "o"}, {"check": "spread", "ok": True, "text": "s"},
          {"check": "delta", "ok": True, "text": "d"}]
    comps += scanner.contract_components(ok, "BUY")
    comps.append(scanner.reward_risk_component(2.5, "n"))
    assert sum(c["max"] for c in comps) == 100 and scanner.total(comps) == 100
    assert scanner.KNOWN_MAX + scanner.LATE_MAX == 100


def test_a_signal_against_the_trend_and_votes_scores_low_and_missing_data_scores_zero_and_is_flagged():
    against = pd.Series({**{f"v5_{k}": -1.0 for k in ("ema_9_21", "ema_20_50", "vwap", "rsi", "macd", "volume", "sr")}, "s15": -0.8})
    comps = scanner.candle_components(against, 1)
    assert scanner.total(comps) == 8.0                         # only the 8 points for the strategy's own signal
    nan = pd.Series({"s15": float("nan")})
    comps = scanner.candle_components(nan, 1)
    missing = {c["key"]: c for c in comps}
    assert all(not c["available"] and c["points"] == 0 and "not available" in c["note"] for k, c in missing.items() if k != "signal")
    assert missing["signal"]["points"] == 8
    c = scanner.contract_components([{"check": "premium", "ok": True, "text": "p"}, {"check": "delta", "ok": None, "text": "delta not available: not checked"}], "BUY")
    assert c[0]["points"] == 3 and c[1]["points"] == 0 and not c[1]["available"]       # Greeks missing: 0 points, flagged, never guessed


def test_reward_risk_is_measured_after_costs_and_a_target_that_does_not_cover_them_is_flagged():
    from app.services.trading import charges as costs
    cc = costs.CostConfig()
    rr, note = scanner.reward_risk("BUY", 100.0, 70.0, 160.0, 75, cc)
    gross = (160 - 100) / (100 - 70)
    assert 0 < rr < gross and "after all costs" in note                          # costs shrink the reward and enlarge the loss
    rr2, note2 = scanner.reward_risk("BUY", 100.0, 99.0, 100.2, 75, cc)
    assert rr2 < 0.5 and "does not cover the costs" in note2
    assert scanner.reward_risk("BUY", 100.0, None, 160.0, 75, cc)[0] is None


def test_every_registered_strategy_is_labelled_negative_and_only_a_validated_positive_one_is_eligible():
    for key in ts.STRATEGIES:
        e = evidence.evidence_for(key)
        assert e["status"] == "negative" and e["points"] == 0 and not evidence.eligible(key) and e["note"]
    assert evidence.evidence_for("scored")["oos_net"] == -56591


def test_the_signal_episode_starts_at_the_first_candle_of_the_unbroken_run():
    idx = pd.DatetimeIndex(["2025-06-09 10:00", "2025-06-09 10:05", "2025-06-09 10:10", "2025-06-09 10:15", "2025-06-09 10:20"])
    s = pd.Series([1, 1, 0, 1, 1], index=idx)
    assert scanner.episode_start(s, 1, pd.Timestamp("2025-06-09 10:20")) == pd.Timestamp("2025-06-09 10:15")
    assert scanner.episode_start(s, 1, pd.Timestamp("2025-06-09 10:05")) == pd.Timestamp("2025-06-09 10:00")


# ---------------------------------------------------------------- configuration
def test_scanner_settings_validate_paper_only_and_a_zero_trade_cap_means_no_cap():
    cfg = le.EngineConfig(signal_mode="bias", trade_mode="paper", timeframe=5, entry_strategy="scanner", max_open_positions=4, max_trades_per_day=0).validate()
    assert cfg.max_open_positions == 4 and cfg.max_trades_per_day == 0 and cfg.scan_min_quality == 55
    with pytest.raises(ValueError, match="paper only"):
        le.EngineConfig(signal_mode="bias", trade_mode="live", entry_strategy="scanner").validate()
    for bad in ({"max_open_positions": 21}, {"max_strategy_positions": 0}, {"max_open_risk_pct": 101}, {"scan_min_quality": -1}, {"max_trades_per_day": -1}):
        with pytest.raises(ValueError):
            le.EngineConfig(signal_mode="bias", trade_mode="paper", timeframe=5, entry_strategy="scanner", **bad).validate()


# ---------------------------------------------------------------- the engine
def test_strategies_are_independent_positions_are_capped_and_no_signal_is_traded_twice():
    saved()
    eng, market = make()
    run_days(eng, market, DAYS[:5])
    trades = q("SELECT * FROM live_trades ORDER BY id")
    assert trades, "three crossover strategies on five synthetic days must produce trades"
    assert {t["analysis"]["strategy"] for t in trades} <= set(CROSSES) and len({t["analysis"]["strategy"] for t in trades}) >= 2    # independent strategies
    # (strategy, signal candle) is traded once: no duplicate entry from the same signal
    keys = [(t["analysis"]["strategy"], t["signal_ts"]) for t in trades]
    assert len(keys) == len(set(keys))
    # concurrency: at no moment more than 3 open in all, nor more than 1 for a single strategy
    events = sorted([(t["entry_ts"], 1, t["analysis"]["strategy"]) for t in trades] + [(t["exit_ts"], -1, t["analysis"]["strategy"]) for t in trades if t["exit_ts"]],
                    key=lambda e: (e[0], e[1]))
    live, per, peak = 0, {}, 0
    for _, d, k in events:
        live += d
        per[k] = per.get(k, 0) + d
        peak = max(peak, live)
        assert live <= 3 and per[k] <= 1
    assert peak >= 2, "the strategies must actually have overlapped for this test to mean something"
    for t in trades:                                                                       # every trade explains its score
        qa = t["analysis"]["quality"]
        assert qa["final"] and len(qa["components"]) == 10 and sum(c["max"] for c in qa["components"]) == 100 and 0 <= qa["total"] <= 100
        assert t["exit_reason"] and t["status"] == "CLOSED" and t["confidence"] == qa["total"]
    assert eng.status()["bias"]["scan"]["candles_scanned"] > 0 and eng.cfg.max_trades_per_day == 0


def test_a_strategy_without_a_validated_positive_result_does_not_trade_by_default_and_the_page_is_told_why():
    saved(scan_allow_unvalidated=False)
    eng, market = make({"scan_allow_unvalidated": False})
    run_days(eng, market, DAYS[:3])
    assert q("SELECT count(*) AS n FROM live_trades")[0]["n"] == 0
    rej = eng.status()["bias"]["scan"]["rejected"]
    ev = [r for r in rej if "negative validated result" in r["reason"]]
    assert ev and all("allow strategies without a validated positive result" in r["reason"] for r in ev)       # the other refusals are the window, cool-downs ...
    opp = {o["strategy"]: o for o in eng.status()["bias"]["scan"]["state"]["opportunities"]}["ema_9_21"]
    assert opp["evidence"]["status"] == "negative" and opp["decision"] in ("HOLD", "REJECTED")


def test_the_minimum_quality_refuses_with_the_exact_score_and_the_weak_components():
    saved(scan_min_quality=75.0)
    eng, market = make({"scan_min_quality": 75})
    run_days(eng, market, DAYS[:3])
    assert q("SELECT count(*) AS n FROM live_trades")[0]["n"] == 0
    reasons = [r["reason"] for r in eng.status()["bias"]["scan"]["rejected"]]
    assert reasons and any("is below the minimum 75" in r and "weak:" in r for r in reasons)


def test_max_open_positions_one_behaves_like_one_position_at_a_time():
    saved(max_open_positions=1)
    eng, market = make({"max_open_positions": 1})
    run_days(eng, market, DAYS[:4])
    trades = q("SELECT * FROM live_trades ORDER BY entry_ts")
    assert trades
    for a, b in zip(trades, trades[1:]):
        assert a["exit_ts"] is not None and a["exit_ts"] <= b["entry_ts"]


def test_the_daily_trade_count_has_no_cap_when_zero_but_a_cap_still_works_when_set():
    saved()
    eng, market = make()
    run_days(eng, market, DAYS[:5])
    assert not any("daily trade limit" in e["message"] for e in eng.events)
    st_ = eng.status()["bias"]
    assert st_["max_trades"] is None and st_["remaining_trades"] is None and eng._automation(None)["trade_cap"] is None
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, candle_bias RESTART IDENTITY CASCADE"))
    saved(max_trades_per_day=2)
    eng, market = make({"max_trades_per_day": 2})
    run_days(eng, market, DAYS[:1])
    assert eng.trades_today <= 2


def test_opposite_signals_from_different_strategies_never_hedge_each_other():
    saved()
    eng, market = make()
    run_days(eng, market, DAYS[:5])
    trades = q("SELECT * FROM live_trades ORDER BY entry_ts")
    for t in trades:
        for u in trades:
            if u["id"] != t["id"] and u["entry_ts"] >= t["entry_ts"] and (t["exit_ts"] is None or u["entry_ts"] < t["exit_ts"]):
                assert u["direction"] == t["direction"]           # a position opened while another is open never points the other way


def test_a_restart_restores_every_open_position_and_each_strategys_last_entry_and_exit_candle():
    saved()
    eng, market = make()
    fresh, _ = make()                                                                       # the process restarted: a new engine, same database
    day = DAYS[0]
    t0 = datetime.combine(day, time(10, 5))
    with db.engine().begin() as c:
        for i, (k, status) in enumerate([("ema_9_21", "OPEN"), ("ema_5_20", "OPEN"), ("ema_8_21", "CLOSED")]):
            c.execute(text("INSERT INTO live_trades (session_id, trade_mode, day, exec_mode, direction, side, trading_symbol, groww_symbol, strike, opt_type, expiry, qty, "
                           "signal_ts, signal_close, entry_ts, entry_price, status, signal_mode, analysis, exit_ts, exit_reason, net) VALUES "
                           "(:s,'replay',:d,'ATM_BUY','Bullish','BUY',:sym,:sym,25000,'CE',:d,75,:t,25000,:t,100,:st,'bias',CAST(:a AS JSONB),:xt,:xr,:net)"),
                      {"s": fresh.session_id, "d": day, "sym": f"X{i}", "t": t0 + timedelta(minutes=5 * i), "st": status, "a": json.dumps({"strategy": k}),
                       "xt": (t0 + timedelta(minutes=17)) if status == "CLOSED" else None, "xr": "stop_loss" if status == "CLOSED" else None,
                       "net": -50.0 if status == "CLOSED" else None})
    fresh._load_day_state(day)
    assert len(fresh.book) == 2 and {fresh._strategy_of(p) for p in fresh.book} == {"ema_9_21", "ema_5_20"}
    assert set(fresh.strat_entry) == {"ema_9_21", "ema_5_20", "ema_8_21"}                   # no signal can be traded a second time
    assert fresh.strat_block["ema_8_21"] == datetime.combine(day, time(10, 25))             # the candle of that strategy's exit stays closed to it only
    assert "ema_9_21" not in fresh.strat_block
    assert fresh.trades_today == 3


def test_the_total_and_per_strategy_open_risk_limits_refuse_the_next_entry_with_the_numbers():
    saved()
    eng, market = make({"trade_mode": "paper", "max_open_risk_pct": 6.0, "max_strategy_risk_pct": 0.0, "risk_pct": 5.0, "max_lots": 20, "daily_risk_pct": 0.0})
    day = DAYS[0]
    market.clock = datetime.combine(day, time(10, 30))
    eng.day = day
    expiry = st.pick_expiry(day, market.expiries(day), True)
    spot = float(market.spot_ltp())
    strike, typ, side = st.option_for("ATM_BUY", 1, spot)
    c = market.contract(day, expiry, strike, typ)
    leg = st.Leg(day=day, direction=1, entry_ts=market.clock, signal_close=spot, signal_bar_start=market.clock, ordinal=0, extra={"strategy_keys": ["ema_9_21"]})
    base = eng._paper_risk(leg, c, "BUY")
    assert base["decision"] == "TRADE" and base["checks"]["total_open_risk"], base.get("reason")
    cap = base["capital"] if "capital" in base else base["balance"]
    eng.book.append({"id": 99, "direction": 1, "side": "BUY", "contract": c, "qty": 75, "entry_price": base["entry"], "entry_ts": market.clock,
                     "risk": {"max_loss": cap * 0.03}, "analysis": {"strategy": "ema_5_20"}, "stop_premium": base["stop"]})
    refused = eng._paper_risk(leg, c, "BUY")
    assert refused["decision"] == "NO TRADE" and not refused["checks"]["total_open_risk"] and "Total open risk would be" in refused["reason"]
    assert refused["portfolio"]["open_positions"] == 1
    eng.update_settings({"max_open_risk_pct": 0.0, "max_strategy_risk_pct": 4.0})              # the per-strategy limit, and the limit is live-tunable
    eng.book[0]["analysis"]["strategy"] = "ema_9_21"
    again = eng._paper_risk(leg, c, "BUY")
    assert again["decision"] == "NO TRADE" and "This strategy's open risk would be" in again["reason"]
    eng.book[0]["analysis"]["strategy"] = "ema_5_20"                                            # another strategy's risk does not count against this one
    assert eng._paper_risk(leg, c, "BUY")["decision"] == "TRADE"


def test_the_engine_never_places_a_live_order_in_scanner_mode():
    eng, _ = make()
    assert eng.broker.name == "paper" and eng.cfg.trade_mode in ("paper", "replay")
    with pytest.raises(ValueError):
        le.Engine(le.EngineConfig(signal_mode="bias", trade_mode="live", entry_strategy="scanner"), None, None)

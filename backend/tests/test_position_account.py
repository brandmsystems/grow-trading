"""Position trading: the separate virtual account, multi-day paper positions, entry rules, exits, restart recovery, settings and the API. Paper only."""
import ast
import json
from datetime import date, datetime, time, timedelta
from pathlib import Path

import psycopg2
import pytest
from sqlalchemy import text

import app.main as app_module
from app.config import settings as config
from app.database import db
from app.services.position import account, analysis
from app.services.position import settings as pset

TEST_DB = "groww_trading_test_position"
NOW = datetime(2026, 11, 26, 16, 0)


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
    yield
    db._engine.dispose()
    db._engine = old
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.close()


@pytest.fixture(autouse=True)
def clean():
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE position_trades, position_decisions, position_settings, position_accounts RESTART IDENTITY CASCADE"))


RISK = {"risk_pct": 1.0, "max_open_positions": 2, "max_portfolio_risk_pct": 3.0, "max_lots": 20, "hold_days": 5, "min_score": 60.0}


def opp(direction=1, strategy="daily_ema_trend", decision="BUY CE", premium=200.0, symbol="NSE-NIFTY-10Dec26-25000-CE", expiry=date(2026, 12, 10), score=72.0, evidence="negative"):
    typ = "CE" if direction > 0 else "PE"
    return {"direction": direction, "type": typ, "strategies": [strategy], "strategy_labels": [strategy], "score": score, "decision": decision, "why": "score 72 of 100", "gates": [],
            "components": [{"key": "weekly", "label": "Weekly trend", "max": 15, "points": 15, "available": True, "note": "n"}],
            "evidence": [{"status": evidence, "label": f"{evidence} result", "note": "x"}],
            "contract": {"symbol": symbol, "expiry": expiry, "strike": 25000.0, "typ": typ, "premium": premium, "lot_size": 65, "quality": 7.0, "dte": 14.0, "usable": True, "notes": [],
                         "estimate": {"available": False}, "volume": 100000.0, "oi": 200000.0},
            "plan": {"stop_premium": premium * 0.65, "target1": premium * 1.7, "target2": premium * 2.4, "invalidation": 24500.0, "planned_exit": "2026-12-04", "expiry": expiry.isoformat(),
                     "entry": {"premium": premium}}}


def test_the_migration_creates_only_new_tables_and_the_account_starts_with_500000():
    with db.engine().connect() as c:
        tabs = {r[0] for r in c.execute(text("select table_name from information_schema.tables where table_schema='public'"))}
    assert {"position_accounts", "position_trades", "position_decisions", "position_settings"} <= tabs
    a = account.active()
    assert a["capital"] == account.DEFAULT_CAPITAL == 500000.0
    st = account.state()
    assert st["balance"] == st["available"] == 500000.0 and st["open_positions"] == 0 and st["equity"] == 500000.0


def test_a_paper_position_is_sized_by_risk_costs_and_recorded_with_its_analysis():
    r = account.open_position(opp(), "2026-11-26", RISK, NOW)
    assert r["lots"] >= 1 and r["qty"] == r["lots"] * 65 and r["max_loss"] <= 500000 * 0.01 + 1
    p = account.positions()[0]
    assert p["status"] == "OPEN" and p["strategy"] == "daily_ema_trend" and p["direction"] == "Bullish" and p["entry_price"] == 200.0
    assert p["stop_premium"] == pytest.approx(130.0, abs=0.1) and p["target1"] == pytest.approx(340.0, abs=0.1) and p["forced_exit"] == "2026-12-09"
    assert p["risk"]["fill_basis"].startswith("last traded premium") and p["risk"]["max_loss"] == r["max_loss"]
    with db.engine().connect() as c:
        an = c.execute(text("select analysis from position_trades")).scalar()
    assert an["components"][0]["label"] == "Weekly trend" and an["strategies"] == ["daily_ema_trend"]
    st = account.state()
    assert st["open_positions"] == 1 and st["invested"] == pytest.approx(200.0 * r["qty"]) and st["available"] == pytest.approx(500000 - 200.0 * r["qty"]) and st["open_risk"] == r["max_loss"]


def test_only_buy_ideas_open_a_position_and_the_same_signal_is_never_entered_twice():
    for dec in ("HOLD", "NO TRADE"):
        with pytest.raises(account.Refused, match=dec):
            account.open_position(opp(decision=dec), "2026-11-26", RISK, NOW)
    with pytest.raises(account.Refused, match="no usable option contract"):
        account.open_position({**opp(), "contract": None}, "2026-11-26", RISK, NOW)
    account.open_position(opp(), "2026-11-26", RISK, NOW)
    with pytest.raises(account.Refused, match="duplicate"):
        account.open_position(opp(), "2026-11-26", RISK, NOW)
    assert len(account.positions()) == 1
    account.open_position(opp(strategy="adx_trend"), "2026-11-26", RISK, NOW)           # another strategy's signal is a separate position
    assert len(account.positions()) == 2


def test_the_open_position_and_portfolio_risk_limits_refuse_the_next_entry_with_the_numbers():
    account.open_position(opp(), "2026-11-26", RISK, NOW)
    account.open_position(opp(strategy="adx_trend"), "2026-11-26", RISK, NOW)
    with pytest.raises(account.Refused, match=r"2 positions are open \(maximum 2\)"):
        account.open_position(opp(strategy="macd_momentum"), "2026-11-26", RISK, NOW)
    tight = {**RISK, "max_open_positions": 5, "max_portfolio_risk_pct": 1.5, "risk_pct": 2.0}
    with pytest.raises(account.Refused, match=r"portfolio risk would be ₹[\d,]+ .* above the limit of 1.5% of capital"):
        account.open_position(opp(strategy="macd_momentum"), "2026-11-26", tight, NOW)
    assert len(account.positions()) == 2
    with pytest.raises(account.Refused, match="sizing"):
        account.open_position(opp(premium=900.0, strategy="rsi_divergence"), "2026-11-26", {**RISK, "max_open_positions": 5, "risk_pct": 0.05}, NOW)


def test_automatic_entry_needs_a_validated_positive_strategy():
    with pytest.raises(account.Refused, match="validated positive"):
        account.open_position(opp(), "2026-11-26", RISK, NOW, auto=True)
    account.open_position(opp(evidence="positive"), "2026-11-26", RISK, NOW, auto=True)
    assert len(account.positions()) == 1


def feed(price, minutes_ago=0):
    return lambda p: (price, NOW - timedelta(minutes=minutes_ago))


def test_the_stop_loss_closes_with_costs_and_a_missing_or_stale_price_changes_nothing():
    r = account.open_position(opp(), "2026-11-26", RISK, NOW)
    t = NOW + timedelta(days=1)
    assert account.manage(t, lambda p: None)[0]["note"].startswith("no price")
    assert account.manage(t, feed(120.0, minutes_ago=60))[0]["note"].startswith("the price is stale")
    assert account.positions()[0]["status"] == "OPEN"
    ev = account.manage(t, lambda p: (125.0, t))
    assert ev[0]["reason"] == "stop_loss"
    p = account.positions()[0]
    assert p["status"] == "CLOSED" and p["exit_reason"] == "stop_loss" and p["exit_price"] == 125.0 and p["net"] < (125.0 - 200.0) * r["qty"] and p["net"] == ev[0]["net"]
    assert account.state()["realised"] == p["net"] and account.state()["open_positions"] == 0
    s = account.summary()
    assert s["overall"]["trades"] == 1 and s["overall"]["net"] == p["net"] and s["by_strategy"]["daily_ema_trend"]["win_rate"] == 0.0


def test_target_one_moves_the_stop_to_the_entry_then_trails_and_target_two_closes():
    account.open_position(opp(), "2026-11-26", RISK, NOW)
    t = NOW + timedelta(days=1)
    ev = account.manage(t, lambda p: (345.0, t))                                       # Target 1 (340) reached
    assert any("Target 1 reached" in e.get("note", "") for e in ev)
    p = account.positions()[0]
    assert p["status"] == "OPEN" and p["t1_hit"] and p["stop_premium"] >= 200.0 and p["best_premium"] == 345.0
    account.manage(t, lambda p: (400.0, t))
    p = account.positions()[0]
    assert p["stop_premium"] == pytest.approx(300.0, abs=0.1)                          # 25% below the best premium 400
    ev = account.manage(t, lambda p: (290.0, t))
    assert ev[-1]["reason"] == "trailing_stop" and ev[-1]["net"] > 0                    # a profit protected, not a loss
    account.open_position(opp(strategy="adx_trend"), "2026-11-26", RISK, NOW)
    ev = account.manage(t, lambda p: (490.0, t))
    assert ev[-1]["reason"] == "target2"


def test_time_and_expiry_exits_happen_at_1515_on_their_day_and_not_before():
    account.open_position(opp(), "2026-11-26", RISK, NOW)
    assert not [e for e in account.manage(datetime(2026, 12, 4, 14, 0), lambda p: (210.0, datetime(2026, 12, 4, 14, 0))) if "reason" in e]
    ev = account.manage(datetime(2026, 12, 4, 15, 20), lambda p: (210.0, datetime(2026, 12, 4, 15, 20)))
    assert ev[-1]["reason"] == "time_exit"
    account.open_position(opp(strategy="adx_trend", expiry=date(2026, 12, 2)), "2026-11-26", {**RISK}, NOW)
    with db.engine().begin() as c:
        c.execute(text("update position_trades set planned_exit='2026-12-20' where strategy='adx_trend'"))
    ev = account.manage(datetime(2026, 12, 1, 15, 20), lambda p: (210.0, datetime(2026, 12, 1, 15, 20)))        # the trading day before the 2 Dec expiry
    assert ev[-1]["reason"] == "expiry_exit"


def test_a_restart_loses_nothing_open_positions_stops_and_the_duplicate_rule_come_back_from_the_database():
    r = account.open_position(opp(), "2026-11-26", RISK, NOW)
    account.manage(NOW + timedelta(days=1), lambda p: (345.0, NOW + timedelta(days=1)))
    db._engine.dispose()                                                               # a new process: nothing is held in memory
    p = account.positions(status="OPEN")[0]
    assert p["t1_hit"] and p["last_price"] == 345.0 and p["qty"] == r["qty"]
    assert account.state()["open_positions"] == 1 and account.state()["open_pnl"] != 0
    with pytest.raises(account.Refused, match="duplicate"):
        account.open_position(opp(), "2026-11-26", RISK, NOW)


def test_a_new_account_is_separate_and_keeps_the_old_trades():
    account.open_position(opp(), "2026-11-26", RISK, NOW)
    account.reset(250000.0)
    assert account.state()["balance"] == 250000.0 and account.positions() == []
    with db.engine().connect() as c:
        assert c.execute(text("select count(*) from position_trades")).scalar() == 1 and c.execute(text("select count(*) from position_accounts")).scalar() == 2
    with pytest.raises(ValueError):
        account.reset(0)


def test_settings_are_saved_as_versions_and_an_invalid_save_changes_nothing():
    assert pset.current()["version"] == 0 and pset.current()["config"]["risk"]["risk_pct"] == 2.0
    out = pset.save({"risk": {"risk_pct": 0.5}, "strategies": {"adx_trend": {"enabled": False}}})
    assert out["version"] == 1 and pset.current()["config"]["risk"]["risk_pct"] == 0.5 and pset.current()["config"]["strategies"]["adx_trend"]["enabled"] is False
    with pytest.raises(ValueError):
        pset.save({"risk": {"risk_pct": 99}})
    assert pset.current()["version"] == 1
    with db.engine().begin() as c:
        c.execute(text("insert into position_settings (config) values (CAST(:c AS JSONB))"), {"c": json.dumps({"risk": {"risk_pct": -1}})})
    cur = pset.current()
    assert cur["error"] and cur["config"]["risk"]["risk_pct"] == 2.0                    # unreadable settings fall back to the defaults and say so


# ---------------------------------------------------------------- the API
def client():
    return app_module.app.test_client()


FAKE = {"day": "2026-11-26", "decision": "BUY CE", "direction": 1, "score": 72.0, "reasons": ["ok"], "strategies": [{"key": "daily_ema_trend", "signal": 1}], "market": {"close": 25000.0},
        "comparison": {}, "opportunities": [opp()], "asof": "2026-11-26T16:00:00"}


def test_the_api_opens_a_position_from_the_analysis_and_refuses_with_the_reason(monkeypatch):
    import app.api.position as api
    monkeypatch.setattr(api, "_analysis", lambda force=False: FAKE)
    c = client()
    j = c.post("/api/position/open", json={"direction": 1}).get_json()
    assert j["ok"] and j["data"]["lots"] >= 1 and j["data"]["entry_price"] == 200.0
    r = c.post("/api/position/open", json={"direction": 1})
    assert r.status_code == 409 and "duplicate" in r.get_json()["error"]
    r = c.post("/api/position/open", json={"direction": -1})
    assert r.status_code == 409 and "no analysed opportunity" in r.get_json()["error"]
    assert c.post("/api/position/open", json={"direction": "x"}).status_code == 400
    pos = c.get("/api/position/positions").get_json()["data"]
    assert len(pos) == 1 and c.get("/api/position/positions?status=CLOSED").get_json()["data"] == []
    acct = c.get("/api/position/account").get_json()["data"]
    assert acct["state"]["open_positions"] == 1 and acct["summary"]["overall"]["trades"] == 0
    assert c.post("/api/position/account/reset", json={"capital": "abc"}).status_code == 400
    assert c.post("/api/position/account/reset", json={"capital": 300000}).get_json()["ok"]


def test_the_api_records_one_decision_per_day_and_never_overwrites_it(monkeypatch):
    import app.api.position as api
    monkeypatch.setattr(api, "_analysis", lambda force=False: FAKE)
    c = client()
    assert c.post("/api/position/decide").get_json()["data"]["recorded"] is True
    monkeypatch.setattr(api, "_analysis", lambda force=False: {**FAKE, "decision": "HOLD", "score": None, "reasons": ["changed"]})
    assert c.post("/api/position/decide").get_json()["data"]["recorded"] is False
    d = c.get("/api/position/decisions").get_json()["data"]
    assert len(d) == 1 and d[0]["decision"] == "BUY CE" and d[0]["reasons"] == ["ok"]


def test_the_api_validates_settings_and_serves_config_and_the_stored_backtest(monkeypatch, tmp_path):
    c = client()
    cfg = c.get("/api/position/config").get_json()["data"]
    assert len(cfg["strategies"]) == 9 and cfg["risk_schema"]["risk_pct"]["default"] == 2.0 and "not a probability" in cfg["note"]
    r = c.put("/api/position/settings", json={"config": {"risk": {"risk_pct": 99}}})
    assert r.status_code == 400 and "risk_pct" in r.get_json()["error"]
    assert c.put("/api/position/settings", json={"config": {"risk": {"max_open_positions": 4}}}).get_json()["data"]["version"] == 1
    monkeypatch.setattr(analysis, "RESEARCH", tmp_path / "missing.json")
    assert c.get("/api/position/backtest").status_code == 404
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"cells": [], "pooled_by_hold": {}, "meta": {}, "evidence": {}}))
    monkeypatch.setattr(analysis, "RESEARCH", f)
    assert c.get("/api/position/backtest").get_json()["data"]["cells"] == []


def test_position_trading_is_paper_only_it_imports_no_broker_or_live_engine_and_returns_no_groww_account_data():
    root = Path(__file__).resolve().parents[1] / "app"
    files = list((root / "services" / "position").glob("*.py")) + [root / "api" / "position.py"]
    banned = ("brokers", "LiveBroker", "trading.engine", "trading.manager", "groww.client", "place_order")
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            names = ([n.module or ""] if isinstance(n, ast.ImportFrom) else []) + ([a.name for a in n.names] if isinstance(n, (ast.Import, ast.ImportFrom)) else [])
            for nm in names:
                assert not any(b in nm for b in banned), (f.name, nm)
    for f in files:                                                                      # code only (docstrings may name what the module refuses to do)
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            ident = n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else ""
            assert ident not in ("LiveBroker", "place_order", "get_funds", "get_margin"), (f.name, ident)

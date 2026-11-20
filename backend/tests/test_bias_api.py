"""Automated bias trading API: paper/replay only, settings, reports. Groww is mocked; nothing here starts an engine."""
import pytest

import app.main as app_module
from app.api import account
from app.services.trading import bias_report
from app.services.trading import manager as live_manager


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(live_manager, "_engine", None)

    def no_broker(*a, **k):
        pytest.fail("test reached the real Groww client")
    monkeypatch.setattr(account.groww_client, "login", no_broker)
    monkeypatch.setattr(account.groww_client, "call", no_broker)
    return app_module.app.test_client()


def test_config_has_the_brief_defaults_and_every_indicator(client):
    d = client.get("/api/bias/config").get_json()["data"]
    assert d["running"] is False and d["defaults"]["max_trades_per_day"] == 20
    assert (d["defaults"]["timeframe"], d["defaults"]["bias_confirm_tf"]) == (5, 15)
    assert d["defaults"]["bias_allow"] == ["BUY_CE", "BUY_PE"]          # writing is off until you switch it on
    assert [i["key"] for i in d["indicators"]] == d["defaults"]["bias_indicators"] and len(d["indicators"]) == 12
    assert "not a probability" in d["note"]


def test_start_is_paper_or_replay_only_and_never_reaches_live(client, monkeypatch):
    seen = []
    monkeypatch.setattr(live_manager, "start", lambda cfg, confirm="", day=None, speed=120: seen.append((cfg, confirm)) or {"state": "waiting"})
    for mode in ("live", "real", ""):
        r = client.post("/api/bias/start", json={"trade_mode": mode})
        assert r.status_code == 400 and "paper or replay" in r.get_json()["error"]
    assert seen == []
    r = client.post("/api/bias/start", json={"config": {"bias_min_confidence": 70, "trade_mode": "live", "signal_mode": "cross",
                                                         "timeframe": 15, "bogus": 1}})
    assert r.status_code == 200
    cfg, confirm = seen[0]
    assert cfg["trade_mode"] == "paper" and cfg["signal_mode"] == "bias"                             # not overridable
    assert cfg["timeframe"] == 15                                                                      # the analysis interval is a setting
    assert cfg["bias_min_confidence"] == 70 and cfg["max_trades_per_day"] == 20 and "bogus" not in cfg and confirm == ""


def test_start_with_an_invalid_setting_is_a_400_not_a_crash(client):
    r = client.post("/api/bias/start", json={"config": {"bias_min_confidence": 500}})
    assert r.status_code == 400 and "between" in r.get_json()["error"]
    r = client.post("/api/bias/start", json={"config": {"timeframe": 15, "bias_confirm_tf": 15}})
    assert r.status_code == 400 and "longer than the analysis interval" in r.get_json()["error"]


def test_settings_and_target_need_a_running_engine(client):
    assert client.post("/api/bias/settings", json={"trail_pct": 5}).status_code == 409
    assert client.post("/api/paper/position/target", json={"target": 150}).status_code == 409
    assert client.get("/api/bias/status").get_json()["data"] == {"running": False}


def test_report_endpoints_answer_with_the_documented_shapes(client):
    assert isinstance(client.get("/api/bias/predictions?limit=5").get_json()["data"], list)
    a = client.get("/api/bias/accuracy").get_json()["data"]
    assert set(a) == {"candles", "rows", "timeframes"} and len(a["rows"]) == 1 + 12 * 2
    s = client.get("/api/bias/summary").get_json()["data"]
    assert {"trades", "wins", "losses", "win_rate", "net", "by_indicator", "by_confidence", "note"} <= set(s)
    assert isinstance(client.get("/api/bias/trades").get_json()["data"], list)
    assert client.get("/api/bias/trade/2147483000").status_code == 404
    assert client.get("/api/bias/predictions?day=nope").status_code == 400


def test_live_rows_can_never_be_requested_from_the_bias_reports(client):
    for url in ("/api/bias/trades?mode=live", "/api/bias/summary?mode=live", "/api/bias/predictions?mode=live"):
        r = client.get(url).get_json()
        assert r["ok"] is True
    assert bias_report._mode("live") == "paper" and bias_report._mode("replay") == "replay"


def test_accuracy_tally_counts_calls_neutral_and_flat_correctly():
    rows = [
        {"predicted": "UP", "actual": "UP", "votes": {"5m": {"rsi": 0.8, "macd": -0.5}, "15m": {"rsi": 0.05}}},
        {"predicted": "UP", "actual": "DOWN", "votes": {"5m": {"rsi": 0.6, "macd": -0.4}, "15m": {"rsi": None}}},
        {"predicted": "NEUTRAL", "actual": "UP", "votes": {"5m": {"rsi": -0.9}, "15m": {}}},
        {"predicted": "DOWN", "actual": "FLAT", "votes": {"5m": {"rsi": -0.9}, "15m": {}}},
    ]
    t = {(r["key"], r["timeframe"]): r for r in bias_report._tally(rows)}
    c = t[("combined", "5m+15m")]
    assert (c["correct"], c["incorrect"], c["neutral"], c["n"], c["accuracy"]) == (1, 1, 2, 2, 50.0)
    r5 = t[("rsi", "5m")]            # UP/UP right, UP/DOWN wrong, DOWN vs UP wrong, DOWN vs FLAT not counted
    assert (r5["correct"], r5["incorrect"], r5["neutral"]) == (1, 2, 1)
    m5 = t[("macd", "5m")]           # DOWN vs UP wrong, DOWN vs DOWN right, two with no vote
    assert (m5["correct"], m5["incorrect"], m5["neutral"]) == (1, 1, 2)
    assert t[("rsi", "15m")]["n"] == 0 and t[("rsi", "15m")]["accuracy"] is None      # weak or missing votes make no call


def test_continuous_automation_defaults_and_pause_need_a_running_engine(client, monkeypatch):
    d = client.get("/api/bias/config").get_json()["data"]["defaults"]
    assert d["bias_min_confidence"] == 70 and d["profit_target_net"] == 1500
    assert client.post("/api/bias/pause").status_code == 409 and client.post("/api/bias/resume").status_code == 409
    seen = []
    monkeypatch.setattr(live_manager, "start", lambda cfg, confirm="", day=None, speed=120: seen.append(cfg) or {"state": "waiting"})
    client.post("/api/bias/start", json={"config": {"profit_target_net": 2000}})
    client.post("/api/bias/start", json={})
    assert seen[0]["profit_target_net"] == 2000 and seen[1]["profit_target_net"] == 1500 and seen[1]["bias_min_confidence"] == 70
    r = client.post("/api/bias/start", json={"config": {"profit_target_net": -5}})
    assert r.status_code == 200          # start is mocked here: validation is covered in the engine tests

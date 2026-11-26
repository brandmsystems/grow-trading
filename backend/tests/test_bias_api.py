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
    assert d["running"] is False and d["defaults"]["max_trades_per_day"] == 0
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
    assert cfg["bias_min_confidence"] == 70 and cfg["max_trades_per_day"] == 0 and "bogus" not in cfg and confirm == ""


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
    assert d["bias_min_confidence"] == 70 and d["profit_target_net"] == 0
    assert client.post("/api/bias/pause").status_code == 409 and client.post("/api/bias/resume").status_code == 409
    seen = []
    monkeypatch.setattr(live_manager, "start", lambda cfg, confirm="", day=None, speed=120: seen.append(cfg) or {"state": "waiting"})
    client.post("/api/bias/start", json={"config": {"profit_target_net": 2000}})
    client.post("/api/bias/start", json={})
    assert seen[0]["profit_target_net"] == 2000 and seen[1]["profit_target_net"] == 0 and seen[1]["bias_min_confidence"] == 70
    r = client.post("/api/bias/start", json={"config": {"profit_target_net": -5}})
    assert r.status_code == 200          # start is mocked here: validation is covered in the engine tests


# ---------------------------------------------------------------- confluence strategy
def test_config_lists_the_confluence_factors_and_the_default_strategy_is_still_bias(client):
    d = client.get("/api/bias/config").get_json()["data"]
    assert [f["key"] for f in d["confluence_factors"]] == ["ema", "vwap", "fvg", "structure"] and d["adr_periods"] == [5, 10, 20]
    df = d["defaults"]
    assert df["entry_strategy"] == "bias" and df["cf_factors"] == ["ema", "vwap", "fvg", "structure"] and df["cf_require"] == []
    assert (df["cf_min_score"], df["cf_adr_filter"], df["cf_adr_period"], df["cf_adr_max_used"], df["cf_htf"]) == (75.0, True, 10, 100.0, True)


def test_start_passes_the_confluence_settings_through_and_still_cannot_reach_live(client, monkeypatch):
    seen = []
    monkeypatch.setattr(live_manager, "start", lambda cfg, confirm="", day=None, speed=120: seen.append(cfg) or {"state": "waiting"})
    r = client.post("/api/bias/start", json={"config": {"entry_strategy": "confluence", "cf_factors": ["ema", "fvg"], "cf_require": ["fvg"],
                                                         "cf_min_score": 80, "cf_adr_period": 20, "trade_mode": "live"}})
    assert r.status_code == 200
    cfg = seen[0]
    assert cfg["entry_strategy"] == "confluence" and cfg["cf_factors"] == ["ema", "fvg"] and cfg["cf_adr_period"] == 20
    assert cfg["trade_mode"] == "paper" and cfg["signal_mode"] == "bias"                              # the strategy cannot change the mode
    assert client.post("/api/bias/start", json={"trade_mode": "live", "config": {"entry_strategy": "confluence"}}).status_code == 400
    assert client.post("/api/bias/settings", json={"cf_min_score": 80}).status_code == 409           # needs a running engine


def test_analysis_previews_the_confluence_factors_and_takes_the_settings_from_the_query(client, monkeypatch):
    import pandas as pd
    from app.api import bias as bias_api
    from app.services.market_data import feed as live_feed
    from tests.test_bias import candles
    spot = candles(days=30, drift=0.12, seed=3, futures=True, vol=6.0)
    fut = spot.copy()
    fut["close"] += 9

    class FakeFeed:
        def now(self):
            return pd.Timestamp("2026-11-11 15:30").to_pydatetime()

        def candles(self, day):
            return spot, fut, None
    monkeypatch.setattr(live_feed, "feed", lambda: FakeFeed())
    monkeypatch.setattr(bias_api.config, "load_keys", lambda: None)
    bias_api._cache.update(key=None, at=0.0, value=None)

    r = client.get("/api/bias/analysis")
    assert r.status_code == 200
    c = r.get_json()["data"]["analysis"]["confluence"]
    assert [f["key"] for f in c["factors"]] == ["ema", "vwap", "fvg", "structure"] and all(f["enabled"] for f in c["factors"])
    assert [x["period"] for x in c["adr"]["rows"]] == [5, 10, 20] and c["adr"]["period"] == 10 and c["adr"]["filter"] is True
    assert all(f["condition"] for f in c["factors"]) and c["min_score"] == 75.0 and "probability" in c["note"]

    r = client.get("/api/bias/analysis?cf_factors=ema,vwap&cf_require=vwap&cf_min_score=60&cf_adr_period=20&cf_adr_filter=false")
    c = r.get_json()["data"]["analysis"]["confluence"]
    assert [f["enabled"] for f in c["factors"]] == [True, True, False, False] and [f["required"] for f in c["factors"]] == [False, True, False, False]
    assert c["min_score"] == 60 and c["adr"]["period"] == 20 and c["adr"]["filter"] is False
    assert client.get("/api/bias/analysis?cf_adr_period=7").status_code == 400                         # a bad setting is a 400, not a crash
    bias_api._cache.update(key=None, at=0.0, value=None)


# ---------------------------------------------------------------- scored strategy
def test_config_offers_the_scored_components_and_the_specified_risk_preset(client):
    d = client.get("/api/bias/config").get_json()["data"]
    assert [c["key"] for c in d["scored_components"]] == ["trend", "ema", "vwap", "fvg", "momentum", "volume", "adr"]
    assert sum(c["max"] for c in d["scored_components"]) == 100
    p = d["presets"]["scored"]
    assert (p["risk_pct"], p["target_rr"], p["stop_mode"], p["daily_risk_pct"], p["max_trades_per_day"], p["sc_min_score"]) == (0.5, 2.0, "atr", 0.0, 5, 80.0)
    assert (p["timeframe"], p["bias_confirm_tf"]) == (5, 15)
    df = d["defaults"]
    assert df["entry_strategy"] == "bias" and df["sc_min_score"] == 80.0 and df["max_trades_per_day"] == 0 and df["risk_pct"] == 1.0     # nothing changes unless the preset is used


def test_start_passes_the_scored_settings_through_and_still_cannot_reach_live(client, monkeypatch):
    seen = []
    monkeypatch.setattr(live_manager, "start", lambda cfg, confirm="", day=None, speed=120: seen.append(cfg) or {"state": "waiting"})
    r = client.post("/api/bias/start", json={"config": {"entry_strategy": "scored", "sc_min_score": 85, "sc_ctx_tf": 30, "risk_pct": 0.5, "trade_mode": "live"}})
    assert r.status_code == 200
    assert seen[0]["entry_strategy"] == "scored" and seen[0]["sc_min_score"] == 85 and seen[0]["sc_ctx_tf"] == 30 and seen[0]["risk_pct"] == 0.5
    assert seen[0]["trade_mode"] == "paper" and seen[0]["signal_mode"] == "bias"
    assert client.post("/api/bias/start", json={"trade_mode": "live", "config": {"entry_strategy": "scored"}}).status_code == 400


def test_analysis_previews_the_scored_strategy_only_when_asked_and_validates_its_settings(client, monkeypatch):
    import pandas as pd
    from app.api import bias as bias_api
    from app.services.market_data import feed as live_feed
    from tests.test_bias import candles
    spot = candles(days=30, drift=0.12, seed=3, futures=True, vol=6.0)
    fut = spot.copy()
    fut["close"] += 9

    class FakeFeed:
        def now(self):
            return pd.Timestamp("2026-11-11 15:30").to_pydatetime()

        def candles(self, day):
            return spot, fut, None
    monkeypatch.setattr(live_feed, "feed", lambda: FakeFeed())
    monkeypatch.setattr(bias_api.config, "load_keys", lambda: None)
    bias_api._cache.update(key=None, at=0.0, value=None)

    assert "scored" not in client.get("/api/bias/analysis").get_json()["data"]["analysis"]
    r = client.get("/api/bias/analysis?entry_strategy=scored&sc_min_score=60&sc_adr_period=20&sc_ctx_tf=30&timeframe=15&bias_confirm_tf=30")
    assert r.status_code == 200
    s = r.get_json()["data"]["analysis"]["scored"]
    assert [c["key"] for c in s["components"]] == ["trend", "ema", "vwap", "fvg", "momentum", "volume", "adr"]
    assert s["min_score"] == 60 and (s["entry_tf"], s["confirm_tf"], s["ctx_tf"]) == (15, 30, 30) and any(g["key"] == "ctx" for g in s["gates"])
    assert 0 <= s["score"] <= 100 and "probability" in s["note"] and all(g["text"] for g in s["gates"])
    assert client.get("/api/bias/analysis?entry_strategy=scored&sc_adr_period=7").status_code == 400
    bias_api._cache.update(key=None, at=0.0, value=None)

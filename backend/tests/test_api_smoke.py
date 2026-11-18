"""API contract smoke tests for endpoints that had no direct coverage.

Groww is always mocked and no background job or engine is started: nothing here can place an
order or call the broker. Read endpoints run against the configured database (read-only).
"""
import pytest

import app.main as app_module
from app.api import account
from app.config import settings as config
from app.services.trading import manager as live_manager


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(live_manager, "_engine", None)        # no engine, whatever ran before

    def no_broker(*a, **k):
        pytest.fail("test reached the real Groww client")
    monkeypatch.setattr(account.groww_client, "login", no_broker)
    monkeypatch.setattr(account.groww_client, "call", no_broker)
    return app_module.app.test_client()


# ----- account (Groww mocked) -----

def test_account_endpoints_wrap_groww_calls(client, monkeypatch):
    calls = []
    monkeypatch.setattr(account.groww_client, "login", lambda force=False: calls.append(("login", force)))
    monkeypatch.setattr(account.groww_client, "logout", lambda: calls.append(("logout",)))
    monkeypatch.setattr(account.groww_client, "call", lambda name, **kw: {"called": name})
    assert client.post("/api/login").get_json() == {"ok": True}
    assert client.post("/api/logout").get_json() == {"ok": True}
    assert client.get("/api/profile").get_json()["data"] == {"called": "get_user_profile"}
    assert client.get("/api/funds").get_json()["data"] == {"called": "get_available_margin_details"}
    assert calls == [("login", True), ("logout",)]


def test_account_endpoints_report_missing_keys_as_400(client, monkeypatch):
    def no_keys(*a, **k):
        raise config.KeysError("keys missing")
    monkeypatch.setattr(account.groww_client, "login", no_keys)
    monkeypatch.setattr(account.groww_client, "call", no_keys)
    for method, url in (("post", "/api/login"), ("get", "/api/profile"), ("get", "/api/funds")):
        r = getattr(client, method)(url)
        assert r.status_code == 400 and r.get_json()["kind"] == "keys", url


def test_account_endpoints_report_broker_failures_as_502(client, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("groww down")
    monkeypatch.setattr(account.groww_client, "call", boom)
    r = client.get("/api/funds")
    assert r.status_code == 502 and r.get_json() == {"ok": False, "error": "groww down", "kind": "ConnectionError"}


# ----- live engine guard rails (no engine running) -----

@pytest.mark.parametrize("url,status", [
    ("/api/live/stop", 400), ("/api/live/squareoff", 400),
    ("/api/live/confirm", 409), ("/api/live/reject", 409),
])
def test_live_controls_refuse_when_engine_is_stopped(client, url, status):
    r = client.post(url, json={"id": "x"})
    assert r.status_code == status and r.get_json()["ok"] is False


@pytest.mark.parametrize("confirm", ["", "nope", "LIV"])
def test_live_start_needs_the_confirm_phrase_before_anything_else(client, monkeypatch, confirm):
    """Real-money mode must be refused before keys are read or any broker call is made."""
    monkeypatch.setattr(config, "load_keys", lambda: pytest.fail("keys must not be read"))
    r = client.post("/api/live/start", json={"config": {"trade_mode": "live"}, "confirm": confirm})
    assert r.status_code == 400 and "LIVE" in r.get_json()["error"]


def test_live_start_caps_lots_in_live_mode(client, monkeypatch):
    monkeypatch.setattr(config, "load_keys", lambda: pytest.fail("keys must not be read"))
    r = client.post("/api/live/start", json={"config": {"trade_mode": "live", "lots": 999}, "confirm": "live"})
    assert r.status_code == 400 and "capped" in r.get_json()["error"]


def test_live_trades_shape(client):
    # /api/live/status is not exercised here: it logs in to Groww for market data.
    t = client.get("/api/live/trades").get_json()
    assert t["ok"] and isinstance(t["data"], list)


# ----- jobs / results not found -----

@pytest.mark.parametrize("url", ["/api/jobs/nope", "/api/bt/result/nope", "/api/bt/chart/nope/1"])
def test_unknown_ids_return_404(client, url):
    r = client.get(url)
    assert r.status_code == 404 and r.get_json()["ok"] is False


def test_data_stop_is_idempotent(client):
    assert client.post("/api/data/stop").get_json() == {"ok": True}


# ----- read-only research endpoints -----

def test_research_signals_scalping_reads(client):
    for url in ("/api/research", "/api/signals", "/api/scalping", "/api/scalping/paper/trades"):
        r = client.get(url)
        assert r.status_code == 200 and r.get_json()["ok"] is True, url


def test_scalping_config_requires_a_known_configuration(client):
    r = client.get("/api/scalping/config")
    assert r.status_code == 404 and r.get_json()["kind"] == "ValueError"

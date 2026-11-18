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

def test_login_and_logout_wrap_groww_calls(client, monkeypatch):
    calls = []
    monkeypatch.setattr(account.groww_client, "login", lambda force=False: calls.append(("login", force)))
    monkeypatch.setattr(account.groww_client, "logout", lambda: calls.append(("logout",)))
    assert client.post("/api/login").get_json() == {"ok": True}
    assert client.post("/api/logout").get_json() == {"ok": True}
    assert calls == [("login", True), ("logout",)]


def test_login_reports_missing_keys_as_400(client, monkeypatch):
    def no_keys(*a, **k):
        raise config.KeysError("keys missing")
    monkeypatch.setattr(account.groww_client, "login", no_keys)
    r = client.post("/api/login")
    assert r.status_code == 400 and r.get_json()["kind"] == "keys"


def test_login_reports_broker_failures_as_502(client, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("groww down")
    monkeypatch.setattr(account.groww_client, "login", boom)
    r = client.post("/api/login")
    assert r.status_code == 502 and r.get_json() == {"ok": False, "error": "groww down", "kind": "ConnectionError"}


@pytest.mark.parametrize("url", ["/api/profile", "/api/funds", "/api/live/broker"])
def test_real_account_data_is_not_served(client, url):
    """Profile, funds/margin and the broker's positions are personal financial data: no endpoint returns them,
    and (the fixture fails any test that reaches the Groww client) nothing is even requested."""
    r = client.get(url)
    assert r.status_code == 404 and r.get_json()["ok"] is False


def test_live_trades_endpoint_never_returns_real_trades(client):
    r = client.get("/api/live/trades?mode=live")
    assert r.status_code == 200 and r.get_json()["data"] == []
    assert all(t["trade_mode"] != "live" for t in client.get("/api/live/trades").get_json()["data"])


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


# ----- request guards (this app has no login: it must only answer its own pages) -----

def test_foreign_host_is_refused(client):
    r = client.get("/api/data/lot-sizes", headers={"Host": "evil.example"})
    assert r.status_code == 403 and r.get_json()["kind"] == "forbidden"


def test_cross_site_post_is_refused_even_as_text_plain(client):
    """A web page can POST text/plain to 127.0.0.1 with no CORS preflight; the Origin check stops it."""
    r = client.post("/api/live/start", data='{"config":{"trade_mode":"live"},"confirm":"LIVE"}',
                    content_type="text/plain", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5000", "http://localhost:5173", "http://[::1]:5000"])
def test_local_origins_are_allowed(client, origin):
    assert client.post("/api/data/stop", headers={"Origin": origin}).status_code == 200


def test_malformed_json_gets_a_json_400(client):
    r = client.post("/api/live/confirm", data="{not json", content_type="application/json")
    assert r.status_code == 400 and r.get_json()["ok"] is False
    r = client.post("/api/live/confirm", data="[1, 2]", content_type="application/json")
    assert r.status_code == 400 and "JSON object" in r.get_json()["error"]


def test_unknown_api_route_answers_in_json(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.get_json()["ok"] is False


@pytest.mark.parametrize("body,fragment", [
    ({}, "valid from and to"), ({"from": "2026-13-01", "to": "2026-01-01"}, "valid from and to"),
    ({"from": "2026-02-01", "to": "2026-01-01"}, "after end date"),
])
def test_download_endpoints_validate_dates_before_starting_a_job(client, monkeypatch, body, fragment):
    from app.workers import jobs
    monkeypatch.setattr(jobs, "submit", lambda *a, **k: pytest.fail("a job must not start"))
    for url in ("/api/data/download", "/api/data/options/download"):
        r = client.post(url, json=body)
        assert r.status_code == 400 and fragment in r.get_json()["error"], url


def test_only_one_download_runs_at_a_time(client, monkeypatch):
    from app.workers import jobs
    monkeypatch.setattr(jobs, "active", lambda: [{"kind": "options"}])
    for url in ("/api/data/download", "/api/data/options/download"):
        r = client.post(url, json={"from": "2026-01-01", "to": "2026-01-02"})
        assert r.status_code == 409, url

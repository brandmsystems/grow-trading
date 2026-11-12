"""Phase 3: Socket.IO push and the CE/PE premium monitor. No network: the payload builder and Groww are faked."""
from datetime import datetime

import pytest

from app.main import app
from app.api import realtime
from app.services.market_data import feed as lf


@pytest.fixture
def push(monkeypatch):
    """The real Pusher with a counting fake builder; the background loop is not started."""
    calls = []
    state = {"price": 25000.0, "now": 0}

    def build(args):
        calls.append(dict(args))
        state["now"] += 1
        return {"state": "stopped", "feed": {"now": f"t{state['now']}", "market": {"state": "open"},
                                             "quote": {"price": state["price"], "age_sec": state["now"]}, "tf": args["tf"]}}
    p = realtime.Pusher(realtime.socketio, build, app.json.dumps)
    monkeypatch.setattr(realtime, "pusher", p)
    monkeypatch.setattr(p, "ensure_running", lambda: None)
    return p, calls, state


def events(client, name):
    return [e["args"][0] for e in client.get_received() if e["name"] == name]


def received(client):
    out = {}
    for e in client.get_received():
        out.setdefault(e["name"], []).append(e["args"][0])
    return out


def test_connect_says_hello_with_heartbeat_threshold(push):
    c = realtime.socketio.test_client(app)
    hello = events(c, "hello")
    assert hello and hello[0]["heartbeat_stale_sec"] == realtime.HEARTBEAT_STALE_SEC
    c.disconnect()


def test_subscribe_sends_current_state_immediately(push):
    p, calls, _ = push
    c = realtime.socketio.test_client(app)
    c.get_received()
    c.emit("subscribe", {"tf": 5, "mode": "paper"})
    ev = events(c, "dashboard")
    assert len(ev) == 1 and ev[0]["data"]["feed"]["quote"]["price"] == 25000.0 and ev[0]["seq"] == 1
    assert calls[-1]["tf"] == 5 and calls[-1]["mode"] == "paper"
    c.disconnect()
    assert not p.rooms                       # cleaned up on disconnect


def test_bad_settings_are_rejected(push):
    c = realtime.socketio.test_client(app)
    c.get_received()
    c.emit("subscribe", {"tf": 7})
    r = received(c)
    assert "subscribe_error" in r and "dashboard" not in r
    c.disconnect()


def test_unchanged_data_sends_heartbeat_not_a_duplicate(push):
    p, _, state = push
    c = realtime.socketio.test_client(app)
    c.emit("subscribe", {"tf": 5})
    c.get_received()
    p.tick()                                 # only clock-like fields changed
    r = received(c)
    assert "dashboard" not in r and r["heartbeat"][0]["seq"] == 2
    state["price"] = 25010.0                 # real change
    p.tick()
    r = received(c)
    assert r["dashboard"][0]["seq"] == 3 and r["dashboard"][0]["data"]["feed"]["quote"]["price"] == 25010.0
    c.disconnect()


def test_same_settings_share_one_computation(push):
    p, calls, state = push
    a, b = realtime.socketio.test_client(app), realtime.socketio.test_client(app)
    a.emit("subscribe", {"tf": 5}); b.emit("subscribe", {"tf": 5})
    a.get_received(); b.get_received()
    n = len(calls)
    state["price"] = 25020.0
    p.tick()
    assert len(calls) == n + 1 and len(p.rooms) == 1
    assert events(a, "dashboard")[0]["seq"] == events(b, "dashboard")[0]["seq"]
    a.disconnect(); b.disconnect()


def test_different_settings_get_their_own_room_and_resubscribe_moves(push):
    p, _, _ = push
    a = realtime.socketio.test_client(app)
    a.emit("subscribe", {"tf": 5})
    b = realtime.socketio.test_client(app)
    b.emit("subscribe", {"tf": 15})
    assert len(p.rooms) == 2
    b.emit("subscribe", {"tf": 5})           # changing settings leaves the old room
    assert len(p.rooms) == 1
    a.get_received(); b.get_received()
    a.disconnect(); b.disconnect()
    assert not p.rooms and not p.sid_room


def test_build_failure_reports_error_and_keeps_last_data(push, monkeypatch):
    p, _, _ = push
    c = realtime.socketio.test_client(app)
    c.emit("subscribe", {"tf": 5})
    c.get_received()
    monkeypatch.setattr(p, "build", lambda args: (_ for _ in ()).throw(RuntimeError("Groww down")))
    p.tick()
    hb = events(c, "heartbeat")
    assert hb and hb[0]["error"] == "Groww down"
    assert p.rooms[next(iter(p.rooms))]["data"]["feed"]["quote"]["price"] == 25000.0
    c.disconnect()


def test_busy_follows_market_and_engine(push):
    p, _, _ = push
    c = realtime.socketio.test_client(app)
    c.emit("subscribe", {"tf": 5})
    assert p.busy() is True                  # market open in the fake payload
    room = next(iter(p.rooms.values()))
    room["data"] = {"state": "stopped", "feed": {"market": {"state": "closed"}}}
    assert p.busy() is False
    room["data"]["state"] = "running"
    assert p.busy() is True
    c.disconnect()


def test_rest_and_socket_share_the_same_builder(monkeypatch):
    from app.api import live
    monkeypatch.setattr(live, "dashboard_payload", lambda p: {"from": "builder", "tf": p["tf"]})
    r = app.test_client().get("/api/live/dashboard?tf=15")
    assert r.get_json()["data"] == {"from": "builder", "tf": 15}
    assert app.test_client().get("/api/live/dashboard?tf=7").status_code == 400


# ---------------------------------------------------------------- CE / PE premium monitor
from tests.test_live_feed import FakeApi, first_buy_time, make_feed, at, DAY   # noqa: E402


class QuoteApi(FakeApi):
    """Option quotes with change, OI and a last-trade time, like Groww's."""
    def __call__(self, fn, **kw):
        if fn == "get_quote" and kw.get("segment") == "FNO":
            self.calls.append((fn, kw))
            if "quote_fno" in self.fail:
                raise RuntimeError("quote failed")
            ce = kw["trading_symbol"].endswith("CE")
            return {"last_price": 180.0 if ce else 190.0, "day_change": -4.0 if ce else 6.0, "day_change_perc": -2.2 if ce else 3.3,
                    "ohlc": {"close": 184.0 if ce else 184.0}, "volume": 1000, "open_interest": 5000,
                    "last_trade_time": int(datetime(2026, 11, 11, 11, 0).timestamp())}
        return super().__call__(fn, **kw)


def test_premiums_on_hold_show_atm_ce_and_pe(monkeypatch):
    monkeypatch.setattr(lf, "record_signal", lambda *a: None)
    f, _ = make_feed(at("09:40"), QuoteApi(spot=25060.0))
    d = f.dashboard(tf=5)
    assert d["signal"]["action"] == "HOLD"
    pm = d["premiums"]
    assert pm["strike"] == 25050 and pm["expiry"] == "2026-11-17" and "at the money" in pm["basis"]
    assert pm["ce"]["premium"] == 180.0 and pm["pe"]["premium"] == 190.0
    assert pm["ce"]["change"] == -4.0 and pm["pe"]["change_pct"] == 3.3 and pm["ce"]["oi"] == 5000
    assert pm["ce"]["state"] == "live" and pm["ce"]["premium"] != d["quote"]["price"]
    assert pm["lot_size"] == 65


def test_premiums_follow_the_recommended_contract(monkeypatch):
    monkeypatch.setattr(lf, "record_signal", lambda *a: None)
    leg = first_buy_time()
    from datetime import timedelta
    f, _ = make_feed(leg.entry_ts + timedelta(seconds=30), QuoteApi(spot=25060.0))
    d = f.dashboard(tf=5)
    rec = d["signal"]["rec"]
    assert rec.get("verified"), rec
    assert d["premiums"]["strike"] == rec["strike"] and "recommended" in d["premiums"]["basis"]


def test_premiums_closed_market_and_failures(monkeypatch):
    monkeypatch.setattr(lf, "record_signal", lambda *a: None)
    f, _ = make_feed(at("16:00"), QuoteApi())
    pm = f.dashboard(tf=5)["premiums"]
    assert pm["ce"]["state"] == "closed"
    f, _ = make_feed(at("11:00"), QuoteApi(fail={"quote_fno"}))
    pm = f.dashboard(tf=5)["premiums"]
    assert pm["ce"]["state"] == "unavailable" and pm["ce"]["premium"] is None and pm["ce"]["error"]
    f, _ = make_feed(at("11:00"), QuoteApi(fail={"get_option_chain"}))
    pm = f.dashboard(tf=5)["premiums"]
    assert pm["ce"] is None and "Option chain unavailable" in pm["error"]


def test_premium_that_looks_like_the_index_is_not_shown(monkeypatch):
    monkeypatch.setattr(lf, "record_signal", lambda *a: None)

    class IndexLike(QuoteApi):
        def __call__(self, fn, **kw):
            if fn == "get_quote" and kw.get("segment") == "FNO":
                return {"last_price": self.spot}
            return super().__call__(fn, **kw)
    f, _ = make_feed(at("11:00"), IndexLike(spot=25060.0))
    pm = f.dashboard(tf=5)["premiums"]
    assert pm["ce"]["state"] == "unavailable" and "index-like" in pm["ce"]["error"] and "premium" not in pm["ce"]


def test_premium_goes_delayed_when_quote_ages(monkeypatch):
    monkeypatch.setattr(lf, "record_signal", lambda *a: None)
    from datetime import timedelta
    api = QuoteApi()
    f, m = make_feed(at("11:00"), api)
    f.dashboard(tf=5)
    api.fail.add("quote_fno")
    m.clock = at("11:00") + timedelta(seconds=40)
    for e in f._c.values():                  # force the cache to refetch (and fail)
        e.fetched = 0
    pm = f.dashboard(tf=5)["premiums"]
    assert pm["ce"]["state"] == "delayed" and pm["ce"]["premium"] == 180.0 and pm["ce"]["error"]

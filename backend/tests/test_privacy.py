"""privacy.py: what real-money (live) mode is allowed to show the browser."""
from app.services import privacy


def status(mode="live", **kw):
    return {"state": "running", "config": {"trade_mode": mode}, "halt_reason": None,
            "position": {"trading_symbol": "NIFTY26NOV25250CE", "qty": 65, "entry_price": 150.1, "mtm": 812.5},
            "realised_today": -1234.5, "trades_today": 2,
            "pending_order": {"id": "ab12", "side": "BUY", "trading_symbol": "NIFTY26NOV25250PE", "qty": 65},
            "events": [{"ts": "t1", "level": "info", "message": "ENTERED BUY NIFTY26NOV25250CE x65 @ 150.10 (EMAX)"},
                       {"ts": "t2", "level": "info", "message": "EXITED NIFTY26NOV25250CE @ 160.00 (target) · net +512.30"},
                       {"ts": "t3", "level": "info", "message": "Bullish crossover (bar closed 10:00, NIFTY 25000.00) → BUY NIFTY26NOV25250CE x65"},
                       {"ts": "t4", "level": "warn", "message": "Daily loss limit hit (-5,100.00 ≤ -5,000): squaring off"},
                       {"ts": "t5", "level": "error", "message": "Exit failed 5 times: square off manually in the Groww app"},
                       {"ts": "t6", "level": "info", "message": "Bullish signal (bar closed 10:00) is waiting for your confirmation"}],
            **kw}


def test_live_status_loses_position_pnl_and_fill_events():
    s = privacy.redact_live_status(status())
    assert s["position"] is None and s["live_position_open"] is True and s["live_details_hidden"] is True
    assert s["realised_today"] == 0.0
    msgs = [e["message"] for e in s["events"]]
    assert msgs[:4] == [privacy.HIDDEN_EVENT] * 4
    text = repr(s)
    for secret in ("150.1", "812.5", "1234.5", "512.30", "EMAX", "160.00", "5,100"):
        assert secret not in text


def test_live_status_keeps_what_safety_needs():
    s = privacy.redact_live_status(status(halt_reason="Exit failed 5 times"))
    assert s["pending_order"]["id"] == "ab12" and s["pending_order"]["qty"] == 65      # you can confirm what you see
    assert s["halt_reason"] == "Exit failed 5 times"
    msgs = [e["message"] for e in s["events"]]
    assert "Exit failed 5 times: square off manually in the Groww app" in msgs
    assert "Bullish signal (bar closed 10:00) is waiting for your confirmation" in msgs
    assert s["state"] == "running" and s["trades_today"] == 2


def test_no_position_means_live_position_open_is_false():
    assert privacy.redact_live_status(status(position=None))["live_position_open"] is False


def test_paper_and_replay_status_are_untouched():
    for mode in ("paper", "replay"):
        s = status(mode)
        assert privacy.redact_live_status(s) is s
        assert s["position"]["entry_price"] == 150.1 and "live_position_open" not in s


def test_stopped_engine_status_without_config_is_untouched():
    s = {"state": "stopped", "config": None, "position": None, "events": []}
    assert privacy.redact_live_status(s) is s


def test_live_alerts_lose_fill_fields_only():
    a = {"id": 1, "mode": "live", "action": "SELL", "direction": "Bullish", "symbol": "NIFTY26NOV25250CE", "reason": "target",
         "entry_price": 150.1, "exit_price": 160.0, "net": 512.3, "qty": 65, "entry_ts": "x", "exit_ts": "y", "nifty": 25000.0}
    r = privacy.redact_live_alert(a)
    assert set(a) - set(r) == {"entry_price", "exit_price", "net", "qty", "entry_ts", "exit_ts"}
    assert r["action"] == "SELL" and r["reason"] == "target" and r["nifty"] == 25000.0


def test_paper_and_signal_alerts_are_untouched():
    for mode in ("paper", "replay", "signal"):
        a = {"mode": mode, "action": "BUY CE", "entry_price": 150.1, "qty": 65}
        assert privacy.redact_live_alert(a) is a


def test_served_trade_rows_have_no_order_ids():
    row = {"id": 1, "trade_mode": "paper", "entry_price": 150.1, "entry_order_id": "PAPER-E1", "exit_order_id": "PAPER-X1"}
    assert privacy.public_trade(row) == {"id": 1, "trade_mode": "paper", "entry_price": 150.1}

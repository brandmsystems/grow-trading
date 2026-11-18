"""Live / paper / replay engine: status, dashboard feed, start/stop and broker check."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.config import settings as config
from app.services.trading import manager as live_manager
from app.api.common import api_error, log, json_body

bp = Blueprint("live", __name__)


@bp.get("/api/live/status")
def live_status():
    try:
        tf = int(request.args.get("tf", 15))
    except ValueError:
        tf = 15
    return jsonify({"ok": True, "data": live_manager.status(request.args.get("mode"), tf,
                                                             request.args.get("strategy", "ema_9_21"))})


@bp.get("/api/options/chain")
def options_chain():
    """Live NIFTY option chain around ATM (Groww): CE and PE premiums, change, volume, OI, OI change, IV, Greeks."""
    from datetime import date
    from app.services.market_data import feed as live_feed
    a = request.args
    try:
        expiry = date.fromisoformat(a["expiry"]) if a.get("expiry") else None
        width = int(a.get("width", live_feed.CHAIN_WIDTH))
    except (TypeError, ValueError) as exc:
        return api_error(exc, 400)
    try:
        config.load_keys()
        return jsonify({"ok": True, "data": live_feed.feed().option_chain(expiry, width)})
    except config.KeysError as exc:
        return api_error(exc, 400)
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        log.exception("option chain failed")
        return api_error(exc, 502)


def dashboard_args(a) -> dict:
    """Validate the dashboard parameters (query string or socket subscription). Raises ValueError."""
    from app.services.market_data import feed as live_feed
    try:
        tf = int(a.get("tf", 5))
        if tf not in (1, 5, 15, 30):
            raise ValueError("timeframe must be 1, 5, 15 or 30")
        entry_start, cutoff = str(a.get("entry_start", "09:30")), str(a.get("cutoff", "14:30"))
        live_feed._hm(entry_start), live_feed._hm(cutoff)
        capital = float(a["capital"]) if a.get("capital") not in (None, "") else None
        risk_pct = float(a.get("risk_pct", 1))
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError(str(exc)) from exc
    if capital is not None and capital <= 0:
        raise ValueError("capital must be positive")
    if not 0 < risk_pct <= 100:
        raise ValueError("risk % must be between 0 and 100")
    mode = a.get("mode") or None
    if mode not in (None, "paper", "live", "replay"):
        raise ValueError("unknown mode")
    return {"tf": tf, "entry_start": entry_start, "cutoff": cutoff, "exec_mode": str(a.get("exec_mode", "ATM_BUY")),
            "roll": str(a.get("roll", "1")) != "0", "capital": capital, "risk_pct": risk_pct, "mode": mode}


def dashboard_payload(p: dict) -> dict:
    """Everything the Live page shows: engine status, NIFTY feed, signal, option, size. Used by the
    REST endpoint and by the Socket.IO push (app/api/realtime.py), so both send the same data."""
    from app.services.market_data import feed as live_feed
    try:
        config.load_keys()
        feed = live_feed.feed().dashboard(p["tf"], p["entry_start"], p["cutoff"], p["exec_mode"],
                                          p["roll"], p["capital"], p["risk_pct"])
    except config.KeysError as exc:
        feed = {"error": str(exc), "kind": "keys"}
    except Exception as exc:
        log.exception("dashboard feed failed")
        feed = {"error": str(exc) or type(exc).__name__}
    # after the feed, so a signal it just recorded is in this response
    s = live_manager.status(p["mode"], p["tf"], with_snapshot=False)
    mode = (s.get("config") or {}).get("trade_mode") if s["state"] != "stopped" else (p["mode"] or "paper")
    s["alerts"] = live_manager.recent_alerts((live_feed.SIGNAL_MODE, mode), limit=20)
    s["feed"] = feed
    return s


@bp.get("/api/live/dashboard")
def live_dashboard():
    try:
        p = dashboard_args(request.args)
    except ValueError as exc:
        return api_error(exc, 400)
    try:
        return jsonify({"ok": True, "data": dashboard_payload(p)})
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/live/start")
def live_start():
    body = json_body()
    try:
        data = live_manager.start(body.get("config") or {}, body.get("confirm", ""),
                                  body.get("replay_day"), float(body.get("replay_speed") or 120))
        return jsonify({"ok": True, "data": data})
    except config.KeysError as exc:
        return api_error(exc, 400)
    except (ValueError, PermissionError, RuntimeError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)


@bp.post("/api/live/confirm")
def live_confirm():
    """Place the live entry order the engine is holding for confirmation. Body: {"id": ...}."""
    pid = (json_body()).get("id", "")
    try:
        return jsonify({"ok": True, "data": live_manager.confirm_order(pid)})
    except (RuntimeError, ValueError) as exc:
        return api_error(exc, 409)


@bp.post("/api/live/reject")
def live_reject():
    pid = (json_body()).get("id", "")
    try:
        return jsonify({"ok": True, "data": live_manager.reject_order(pid)})
    except (RuntimeError, ValueError) as exc:
        return api_error(exc, 409)


@bp.post("/api/live/stop")
def live_stop():
    try:
        return jsonify({"ok": True, "data": live_manager.stop()})
    except Exception as exc:
        return api_error(exc, 400)


@bp.post("/api/live/squareoff")
def live_squareoff():
    try:
        return jsonify({"ok": True, "data": live_manager.square_off()})
    except Exception as exc:
        return api_error(exc, 400)


@bp.get("/api/live/trades")
def live_trades():
    try:
        return jsonify({"ok": True, "data": live_manager.trades(request.args.get("mode"), request.args.get("day"))})
    except Exception as exc:
        return api_error(exc, 500)

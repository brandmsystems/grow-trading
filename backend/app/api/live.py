"""Live / paper / replay engine: status, dashboard feed, start/stop and broker check."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.config import settings as config
from app.services.groww import client as groww_client
from app.services.trading import manager as live_manager
from app.api.common import api_error, log

bp = Blueprint("live", __name__)


@bp.get("/api/live/status")
def live_status():
    try:
        tf = int(request.args.get("tf", 15))
    except ValueError:
        tf = 15
    return jsonify({"ok": True, "data": live_manager.status(request.args.get("mode"), tf,
                                                             request.args.get("strategy", "ema_9_21"))})


@bp.get("/api/live/dashboard")
def live_dashboard():
    """Everything the Live page shows, in one poll: engine status, NIFTY feed, signal, option, size."""
    from app.services.market_data import feed as live_feed
    a = request.args
    try:
        tf = int(a.get("tf", 5))
        if tf not in (1, 5, 15, 30):
            raise ValueError("timeframe must be 1, 5, 15 or 30")
        entry_start, cutoff = a.get("entry_start", "09:30"), a.get("cutoff", "14:30")
        live_feed._hm(entry_start), live_feed._hm(cutoff)
        capital = float(a["capital"]) if a.get("capital") else None
        risk_pct = float(a.get("risk_pct", 1))
        if capital is not None and capital <= 0:
            raise ValueError("capital must be positive")
        if not 0 < risk_pct <= 100:
            raise ValueError("risk % must be between 0 and 100")
    except (TypeError, ValueError) as exc:
        return api_error(exc, 400)
    try:
        config.load_keys()
        feed = live_feed.feed().dashboard(tf, entry_start, cutoff, a.get("exec_mode", "ATM_BUY"),
                                          a.get("roll", "1") != "0", capital, risk_pct)
    except config.KeysError as exc:
        feed = {"error": str(exc), "kind": "keys"}
    except Exception as exc:
        log.exception("dashboard feed failed")
        feed = {"error": str(exc) or type(exc).__name__}
    try:   # after the feed, so a signal it just recorded is in this response
        s = live_manager.status(a.get("mode"), tf, with_snapshot=False)
        mode = (s.get("config") or {}).get("trade_mode") if s["state"] != "stopped" else (a.get("mode") or "paper")
        s["alerts"] = live_manager.recent_alerts((live_feed.SIGNAL_MODE, mode), limit=20)
    except Exception as exc:
        return api_error(exc, 500)
    s["feed"] = feed
    return jsonify({"ok": True, "data": s})


@bp.post("/api/live/start")
def live_start():
    body = request.get_json(force=True) or {}
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
    pid = (request.get_json(force=True) or {}).get("id", "")
    try:
        return jsonify({"ok": True, "data": live_manager.confirm_order(pid)})
    except (RuntimeError, ValueError) as exc:
        return api_error(exc, 409)


@bp.post("/api/live/reject")
def live_reject():
    pid = (request.get_json(force=True) or {}).get("id", "")
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


@bp.get("/api/live/broker")
def live_broker():
    """Actual Groww F&O positions, for reconciling against the engine."""
    try:
        return jsonify({"ok": True, "data": groww_client.call("get_positions_for_user", segment="FNO", timeout=10)})
    except config.KeysError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)

"""Paper trading risk management: virtual account, daily risk monitor and the risk calculator.
Nothing here can place a Groww order."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from app.api.common import api_error
from app.services.options import sizing
from app.services.trading import charges as costs
from app.services.trading import engine as le
from app.services.trading import manager as live_manager
from app.services.trading import paper_account

bp = Blueprint("paper", __name__)


def _paper_engine():
    eng = live_manager._engine
    return eng if eng is not None and eng.cfg.trade_mode == "paper" and eng.state != "stopped" else None


@bp.get("/api/paper/account")
def paper_account_state():
    try:
        eng = _paper_engine()
        cfg = eng.cfg if eng else le.EngineConfig(trade_mode="paper")
        pos = mtm = None
        if eng and eng.position:
            pos = eng.position
            ltp = eng.last_ltp.get(pos["contract"].trading_symbol)
            mtm = eng._pnl(pos, ltp)["net"] if ltp else None
        st = paper_account.state(datetime.now().date(), cfg, pos, mtm)
        defaults = le.EngineConfig(trade_mode="paper")
        return jsonify({"ok": True, "data": {
            **st, "engine_running": bool(eng), "presets": sizing.PRESETS,
            "settings": {k: getattr(cfg, k) for k in ("risk_pct", "daily_risk_pct", "max_daily_loss", "max_trades_per_day",
                                                      "max_open_positions", "max_lots", "min_balance", "stop_mode",
                                                      "stop_atr", "stop_pct", "stop_points")},
            "defaults": {k: getattr(defaults, k) for k in ("risk_pct", "daily_risk_pct", "max_daily_loss", "max_trades_per_day",
                                                           "max_open_positions", "max_lots", "min_balance", "stop_mode",
                                                           "stop_atr", "stop_pct", "stop_points")},
        }})
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/paper/account")
def paper_account_reset():
    body = request.get_json(force=True) or {}
    if body.get("confirm") != "RESET":
        return jsonify({"ok": False, "error": "Type RESET to start a new virtual account."}), 400
    eng = _paper_engine()
    if eng and eng.position:
        return jsonify({"ok": False, "error": "Close the open paper position first."}), 409
    try:
        return jsonify({"ok": True, "data": paper_account.reset(float(body.get("capital") or 0))})
    except (TypeError, ValueError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/paper/position/stop")
def paper_position_stop():
    """Change the open paper position's stop-loss (refused if it would exceed the risk limits)."""
    body = request.get_json(force=True) or {}
    eng = _paper_engine()
    if not eng:
        return jsonify({"ok": False, "error": "The paper engine isn't running."}), 409
    try:
        return jsonify({"ok": True, "data": eng.set_paper_stop(float(body["stop"]))})
    except (KeyError, TypeError) :
        return jsonify({"ok": False, "error": "Enter the new stop-loss premium."}), 400
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/paper/stop-changes")
def paper_stop_changes():
    from sqlalchemy import text
    from app.database import db
    try:
        tid = int(request.args["trade_id"])
        with db.engine().connect() as c:
            rows = [dict(r) for r in c.execute(text(
                "SELECT ts, old_stop, new_stop, old_max_loss, new_max_loss, source, note FROM paper_stop_changes "
                "WHERE trade_id=:t ORDER BY id"), {"t": tid}).mappings()]
        for r in rows:
            r["ts"] = r["ts"].isoformat()
        return jsonify({"ok": True, "data": rows})
    except (KeyError, ValueError):
        return jsonify({"ok": False, "error": "trade_id is required"}), 400
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/paper/risk-calc")
def paper_risk_calc():
    """The risk calculator: same function and costs the paper engine uses before every trade."""
    b = request.get_json(force=True) or {}
    try:
        f = lambda k, d=None: (float(b[k]) if b.get(k) not in (None, "") else d)
        side = str(b.get("side") or "BUY").upper()
        entry = f("entry")
        stop = f("stop")
        if stop is None and f("stop_pct") is not None and entry:
            sgn = 1 if side == "BUY" else -1
            stop = costs._round_tick_down(entry * (1 - sgn * f("stop_pct") / 100)) if side == "BUY" \
                else costs._round_tick_up(entry * (1 + f("stop_pct") / 100))
        r = sizing.risk_size(side, entry, stop, int(f("lot_size", 0) or 0), f("capital", 0), f("risk_pct", 0),
                             available=f("available"), max_lots=int(f("max_lots", 0) or 0) or None,
                             min_balance=f("min_balance", 0.0), target=f("target"), include_slippage=True)
        return jsonify({"ok": True, "data": r})
    except (TypeError, ValueError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)

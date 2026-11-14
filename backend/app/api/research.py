"""Strategy comparison grid and the signal engine."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.backtest import engine as backtest
from app.services.backtest import research
from app.services.backtest import scalping
from app.services.strategy import signals
from app.services.strategy import strategies
from app.workers import jobs
from app.api.common import api_error, active_job

bp = Blueprint("research", __name__)


@bp.get("/api/research")
def research_results():
    try:
        data = research.results(request.args.get("entry_start", "09:30"), request.args.get("cutoff", "14:30"))
        return jsonify({"ok": True, "data": data, "job": active_job("research")})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/research/run")
def research_run():
    body = request.get_json(force=True) or {}
    if active_job("research"):
        return jsonify({"ok": False, "error": "A comparison run is already in progress."}), 409
    try:
        research.settings(body.get("entry_start", "09:30"), body.get("cutoff", "14:30"))
    except ValueError as exc:
        return api_error(exc, 400)
    return jsonify({"ok": True, "job": jobs.submit("research", research.run_grid, body.get("entry_start", "09:30"),
                                                   body.get("cutoff", "14:30"), lane="research")})


def _signal_args(src) -> tuple[str, int]:
    key, tf = src.get("strategy", strategies.DEFAULT), int(src.get("tf", 15))
    if key not in strategies.STRATEGIES or tf not in backtest.TIMEFRAMES:
        raise ValueError("Unknown strategy or timeframe")
    return key, tf


@bp.get("/api/signals")
def signals_get():
    try:
        key, tf = _signal_args(request.args)
        return jsonify({"ok": True, "data": signals.get(key, tf), "job": active_job("signals")})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/signals/build")
def signals_build():
    try:
        key, tf = _signal_args(request.get_json(force=True) or {})
    except ValueError as exc:
        return api_error(exc, 400)
    if active_job("signals"):
        return jsonify({"ok": False, "error": "A signal analysis is already being built."}), 409
    return jsonify({"ok": True, "job": jobs.submit("signals", signals.build_and_store, key, tf)})


# ---------------------------------------------------------------- 5-minute scalping analyzer
LIGHT = ("trades", "net_pnl", "gross_pnl", "win_rate", "profit_factor", "max_drawdown")


def _light(c: dict) -> dict:
    """A configuration row for the overview table (no daily equity, monthly or trade lists)."""
    out = {k: v for k, v in c.items() if k not in ("equity", "monthly", "regimes", "ce", "pe")}
    out["ce"] = {k: c["ce"][k] for k in LIGHT}
    out["pe"] = {k: c["pe"][k] for k in LIGHT}
    return out


@bp.get("/api/scalping")
def scalping_get():
    try:
        data = scalping.latest()
        if data:
            data = {**data, "configs": [_light(c) for c in data["configs"]]}
        return jsonify({"ok": True, "data": data, "settings": scalping.settings(), "job": active_job("scalping")})
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/scalping/config")
def scalping_config():
    """One configuration in full (monthly, yearly, regimes, CE/PE, equity) with its trades."""
    key = request.args.get("key", "")
    data = scalping.latest()
    if not data:
        return api_error(LookupError("No scalping analysis yet. Run it first."), 404)
    row = next((c for c in data["configs"] if c["key"] == key), None)
    if row is None:
        return api_error(ValueError("Unknown configuration"), 404)
    return jsonify({"ok": True, "data": {**row, "trade_list": scalping.config_trades(data["run_id"], key)}})


@bp.post("/api/scalping/run")
def scalping_run():
    if active_job("scalping"):
        return jsonify({"ok": False, "error": "A scalping analysis is already running."}), 409
    return jsonify({"ok": True, "job": jobs.submit("scalping", scalping.run, lane="research")})


@bp.post("/api/scalping/paper/start")
def scalping_paper_start():
    """Start the engine on a tested configuration. Body: {key, mode: paper|replay, replay_day?, risk: {...}}.
    Paper and replay only; real-money scalping is refused."""
    from app.services.trading import manager as live_manager
    body = request.get_json(force=True) or {}
    try:
        cfg = scalping.engine_config(body.get("key", ""), body.get("mode", "paper"), body.get("risk") or {})
        data = live_manager.start(cfg, "", body.get("replay_day"), float(body.get("replay_speed") or 120))
        return jsonify({"ok": True, "data": data})
    except (ValueError, PermissionError, RuntimeError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)


@bp.get("/api/scalping/paper/trades")
def scalping_paper_trades():
    try:
        return jsonify({"ok": True, "data": scalping.paper_trades(request.args.get("key") or None, request.args.get("mode") or None)})
    except Exception as exc:
        return api_error(exc, 500)

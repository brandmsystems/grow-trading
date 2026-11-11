"""Strategy comparison grid and the signal engine."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.backtest import engine as backtest
from app.services.backtest import research
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

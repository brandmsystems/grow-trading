"""Historical data: coverage report, downloads and stored candles."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.market_data import history as data_manager
from app.services.market_data import options_history
from app.services.options import lot_sizes
from app.workers import jobs
from app.api.common import api_error, date_arg, date_range, json_body

bp = Blueprint("data", __name__)


def _download_running() -> bool:
    """Spot and option downloads share one lane: only one may run at a time."""
    return any(j["kind"] in ("download", "options") for j in jobs.active())


@bp.get("/api/data/overview")
def data_overview():
    try:
        return jsonify({"ok": True, "data": {
            "coverage": data_manager.coverage(date_arg("from"), date_arg("to")),
            "instruments": data_manager.instruments(),
            "downloads": data_manager.downloads(),
            "job": next((j for j in jobs.active() if j["kind"] == "download"), None),
        }})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/data/download")
def data_download():
    if _download_running():
        return jsonify({"ok": False, "error": "A download is already running."}), 409
    try:
        start, end = date_range(json_body())
    except ValueError as exc:
        return api_error(exc, 400)
    return jsonify({"ok": True, "job": jobs.submit("download", data_manager.download_all, start, end)})


@bp.post("/api/data/stop")
def data_stop():
    data_manager.request_stop()
    return jsonify({"ok": True})


@bp.get("/api/data/candles")
def data_candles():
    try:
        return jsonify({"ok": True, "data": data_manager.candles(
            date_arg("from"), date_arg("to"), int(request.args.get("tf", 5)))})
    except (TypeError, ValueError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/data/options")
def data_options():
    """Option candle coverage for the planned scope (ATM ±10 strikes, CE and PE, all expiry rules)."""
    try:
        return jsonify({"ok": True, "data": {
            **options_history.coverage(date_arg("from"), date_arg("to")),
            "job": next((j for j in jobs.active() if j["kind"] == "options"), None),
        }})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/data/options/download")
def data_options_download():
    if _download_running():
        return jsonify({"ok": False, "error": "A download is already running."}), 409
    try:
        start, end = date_range(json_body())
    except ValueError as exc:
        return api_error(exc, 400)
    return jsonify({"ok": True, "job": jobs.submit("options", options_history.download, start, end, lane="options")})


@bp.get("/api/data/lot-sizes")
def data_lot_sizes():
    try:
        return jsonify({"ok": True, "data": lot_sizes.history()})
    except Exception as exc:
        return api_error(exc, 500)

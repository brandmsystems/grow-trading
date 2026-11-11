"""Historical data: coverage report, downloads and stored candles."""
from __future__ import annotations

from datetime import date
from flask import Blueprint, jsonify, request

from app.services.market_data import history as data_manager
from app.workers import jobs
from app.api.common import api_error, date_arg

bp = Blueprint("data", __name__)


@bp.get("/api/data/overview")
def data_overview():
    try:
        return jsonify({"ok": True, "data": {
            "coverage": data_manager.coverage(date_arg("from"), date_arg("to")),
            "downloads": data_manager.downloads(),
            "job": next((j for j in jobs.active() if j["kind"] == "download"), None),
        }})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/data/download")
def data_download():
    body = request.get_json(force=True) or {}
    if any(j["kind"] == "download" for j in jobs.active()):
        return jsonify({"ok": False, "error": "A download is already running."}), 409
    try:
        start, end = date.fromisoformat(body["from"]), date.fromisoformat(body["to"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "Choose a valid from and to date."}), 400
    if start > end:
        return jsonify({"ok": False, "error": "Start date is after end date."}), 400
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

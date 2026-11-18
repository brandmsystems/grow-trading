"""Helpers shared by the API blueprints."""
from __future__ import annotations

import logging

from datetime import date
from urllib.parse import urlsplit
from collections import OrderedDict
from flask import jsonify, request
from werkzeug.exceptions import BadRequest, HTTPException

from app.config import settings as config
from app.database import db
from app.workers import jobs

log = logging.getLogger("app.api")


def api_error(exc: Exception, status: int = 502):
    log.warning("API error: %s: %s", type(exc).__name__, exc)
    kind = "keys" if isinstance(exc, config.KeysError) else type(exc).__name__
    return jsonify({"ok": False, "error": str(exc) or kind, "kind": kind}), status


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def reject_foreign_requests():
    """before_request guard for this local-only app (no login, can place orders).

    * Host must be a loopback name: stops DNS-rebinding pages reading or driving the API.
    * A state-changing request that carries an Origin must come from a loopback page: stops a
      web page in the user's browser posting to http://127.0.0.1:5000 (get_json(force=True)
      accepts text/plain, which browsers send cross-site without a CORS preflight).
    """
    if (request.host.rsplit(":", 1)[0] if not request.host.startswith("[") else request.host.split("]")[0].lstrip("["))             not in LOCAL_HOSTS:
        return jsonify({"ok": False, "error": "Only local access is allowed.", "kind": "forbidden"}), 403
    origin = request.headers.get("Origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS") and (urlsplit(origin).hostname or "") not in LOCAL_HOSTS:
        return jsonify({"ok": False, "error": "Cross-site request refused.", "kind": "forbidden"}), 403
    return None


def json_body() -> dict:
    """The JSON object in the request body ({} when empty). Malformed JSON or a non-object raises
    BadRequest, which `json_error` turns into the usual {"ok": false} JSON 400."""
    raw = request.get_data()
    if not raw.strip():
        return {}
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        raise BadRequest("Request body must be a JSON object.")
    return body


def json_error(exc: HTTPException):
    """HTTP errors under /api answer in the API's JSON envelope instead of Flask's HTML page."""
    if request.path.startswith("/api"):
        return jsonify({"ok": False, "error": exc.description or exc.name, "kind": exc.name}), exc.code
    return exc


def date_range(body: dict) -> tuple[date, date]:
    """`from` / `to` ISO dates of a download request. Raises ValueError with a user-facing message."""
    try:
        start, end = date.fromisoformat(body["from"]), date.fromisoformat(body["to"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("Choose a valid from and to date.") from None
    if start > end:
        raise ValueError("Start date is after end date.")
    return start, end


RESULTS: OrderedDict[str, dict] = OrderedDict()   # small in-memory cache of full results


def remember_result(result: dict) -> dict:
    RESULTS[result["hash"]] = result
    RESULTS.move_to_end(result["hash"])
    while len(RESULTS) > 12:
        RESULTS.popitem(last=False)
    return result


def get_result(h: str) -> dict | None:
    if h in RESULTS:
        return RESULTS[h]
    run = db.get_run(h)
    return remember_result(run["result"]) if run else None


def real_only(params: dict) -> dict:
    if params["dataset"] != "groww":
        raise ValueError("Only real Groww market data can be used.")
    return params


def date_arg(name: str) -> date | None:
    value = request.args.get(name)
    return date.fromisoformat(value) if value else None


def active_job(kind: str):
    return next((j for j in jobs.active() if j["kind"] == kind), None)

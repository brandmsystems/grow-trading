"""Helpers shared by the API blueprints."""
from __future__ import annotations

import logging

from datetime import date
from collections import OrderedDict
from flask import jsonify, request

from app.config import settings as config
from app.database import db
from app.workers import jobs

log = logging.getLogger("app.api")


def api_error(exc: Exception, status: int = 502):
    log.warning("API error: %s: %s", type(exc).__name__, exc)
    kind = "keys" if isinstance(exc, config.KeysError) else type(exc).__name__
    return jsonify({"ok": False, "error": str(exc) or kind, "kind": kind}), status


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

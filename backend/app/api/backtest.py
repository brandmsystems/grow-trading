"""Backtest runs, results and per-trade chart data."""
from __future__ import annotations

from datetime import date

import pandas as pd
from flask import Blueprint, jsonify, request

from app.config import settings as config
from app.database import db
from app.services.backtest import engine as backtest
from app.services.market_data import providers
from app.services.strategy import rules as st
from app.services.strategy import strategies
from app.workers import jobs
from app.api.common import api_error, remember_result, get_result, real_only

bp = Blueprint("backtest", __name__)


@bp.get("/api/bt/meta")
def bt_meta():
    try:
        config.load_keys()
        keys_ok = True
    except config.KeysError:
        keys_ok = False
    data = {}
    for ds in ("groww",):
        try:
            data[ds] = db.data_summary(providers.GrowwProvider.spot_symbol)
            last = data[ds].get("last")
            data[ds]["stale"] = backtest.data_stale(pd.Timestamp(last).to_pydatetime() if last else None)
        except Exception as exc:
            data[ds] = {"error": str(exc)}
    return jsonify({"ok": True, "data": {
        "defaults": backtest.normalise({}),
        "timeframes": backtest.TIMEFRAMES,
        "starts": backtest.START_CHOICES,
        "cutoffs": backtest.CUTOFF_CHOICES,
        "modes": st.MODE_LABELS,
        "strategies": {k: s.label for k, s in strategies.STRATEGIES.items()},
        "expiry_rules": st.EXPIRY_RULES,
        "keys": keys_ok,
        "datasets": data,
        "jobs": jobs.active(),
    }})


@bp.post("/api/bt/data")
def bt_data():
    params = request.get_json(force=True) or {}
    try:
        real_only(backtest.normalise(params))
    except ValueError as exc:
        return api_error(exc, 400)
    jid = jobs.submit("data", backtest.ensure_data, params)
    return jsonify({"ok": True, "job": jid})


@bp.post("/api/bt/run")
def bt_run():
    params = request.get_json(force=True) or {}
    force = bool(params.pop("force", False))
    try:
        p = real_only(backtest.normalise(params))
    except ValueError as exc:
        return api_error(exc, 400)
    h = backtest.param_hash(p)
    if not force:
        cached = get_result(h)
        if cached and not cached.get("partial_asof"):
            return jsonify({"ok": True, "hash": h, "cached": True})

    def work(progress):
        res = backtest.run(p, progress=progress, use_cache=not force)
        remember_result(res)
        return {"hash": res["hash"]}

    return jsonify({"ok": True, "job": jobs.submit("run", work)})


@bp.get("/api/jobs/<jid>")
def job_status(jid):
    j = jobs.get(jid)
    if not j:
        return jsonify({"ok": False, "error": "unknown job"}), 404
    return jsonify({"ok": True, "data": j})


@bp.get("/api/bt/result/<h>")
def bt_result(h):
    res = get_result(h)
    if not res:
        return jsonify({"ok": False, "error": "Run not found (it may have been cleared by a data refresh)."}), 404
    return jsonify({"ok": True, "data": res})


@bp.get("/api/bt/chart/<h>/<trade_id>")
def bt_chart(h, trade_id):
    res = get_result(h)
    if not res:
        return jsonify({"ok": False, "error": "Run not found"}), 404
    mode = trade_id.rsplit("-", 1)[0]
    trade = next((t for t in res["trades"].get(mode, []) if t["id"] == trade_id), None)
    if not trade:
        return jsonify({"ok": False, "error": "Trade not found"}), 404
    day = date.fromisoformat(trade["day"])
    try:
        return jsonify({"ok": True, "data": {
            "trade_id": trade_id,
            "spot": backtest.spot_bars(res["params"]["dataset"], day, int(res["params"]["timeframe"]),
                                       res["params"].get("strategy", "ema_9_21")),
            "fast_label": f"EMA {strategies.STRATEGIES[res['params'].get('strategy', 'ema_9_21')].fast}",
            "slow_label": f"EMA {strategies.STRATEGIES[res['params'].get('strategy', 'ema_9_21')].slow}",
            "option": backtest.option_candles(trade["symbol"], day),
        }})
    except Exception as exc:
        return api_error(exc, 500)

"""Flask entry point for the Groww trading system."""
from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import date

import pandas as pd
from flask import Flask, jsonify, render_template, request

import backtest
import config
import db
import groww_client
import jobs
import live_manager
import providers
import strategy as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
app.json.sort_keys = False

try:
    db.init()
except Exception as exc:  # app still serves the account page without Postgres
    log.error("Database init failed: %s", exc)


def _error(exc: Exception, status: int = 502):
    log.warning("API error: %s: %s", type(exc).__name__, exc)
    kind = "keys" if isinstance(exc, config.KeysError) else type(exc).__name__
    return jsonify({"ok": False, "error": str(exc) or kind, "kind": kind}), status


# ====================================================================== pages
@app.get("/")
def dashboard():
    return render_template("dashboard.html")


@app.get("/account")
def account():
    return render_template("account.html")


# ====================================================================== account API
@app.get("/api/status")
def status():
    try:
        config.load_keys()
        keys_ok, keys_msg = True, "keys.txt found"
    except config.KeysError as exc:
        keys_ok, keys_msg = False, str(exc)
    return jsonify({"ok": True, "keys": keys_ok, "message": keys_msg})


@app.post("/api/login")
def api_login():
    try:
        groww_client.login(force=True)
        return jsonify({"ok": True})
    except config.KeysError as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc)


@app.post("/api/logout")
def api_logout():
    groww_client.logout()
    return jsonify({"ok": True})


@app.get("/api/profile")
def api_profile():
    try:
        return jsonify({"ok": True, "data": groww_client.call("get_user_profile", timeout=10)})
    except config.KeysError as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc)


@app.get("/api/funds")
def api_funds():
    try:
        return jsonify(
            {"ok": True, "data": groww_client.call("get_available_margin_details", timeout=10)}
        )
    except config.KeysError as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc)


# ====================================================================== backtest API
_results: OrderedDict[str, dict] = OrderedDict()   # small in-memory cache of full results


def _remember(result: dict) -> dict:
    _results[result["hash"]] = result
    _results.move_to_end(result["hash"])
    while len(_results) > 12:
        _results.popitem(last=False)
    return result


def _result(h: str) -> dict | None:
    if h in _results:
        return _results[h]
    run = db.get_run(h)
    return _remember(run["result"]) if run else None


@app.get("/api/bt/meta")
def bt_meta():
    try:
        config.load_keys()
        keys_ok = True
    except config.KeysError:
        keys_ok = False
    data = {}
    for ds in ("groww", "synthetic"):
        try:
            data[ds] = db.data_summary(providers.GrowwProvider.spot_symbol if ds == "groww"
                                       else providers.SyntheticProvider.spot_symbol)
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
        "keys": keys_ok,
        "datasets": data,
        "jobs": jobs.active(),
    }})


@app.post("/api/bt/data")
def bt_data():
    params = request.get_json(force=True) or {}
    try:
        backtest.normalise(params)
    except ValueError as exc:
        return _error(exc, 400)
    jid = jobs.submit("data", backtest.ensure_data, params)
    return jsonify({"ok": True, "job": jid})


@app.post("/api/bt/run")
def bt_run():
    params = request.get_json(force=True) or {}
    force = bool(params.pop("force", False))
    try:
        p = backtest.normalise(params)
    except ValueError as exc:
        return _error(exc, 400)
    h = backtest.param_hash(p)
    if not force:
        cached = _result(h)
        if cached and not cached.get("partial_asof"):
            return jsonify({"ok": True, "hash": h, "cached": True})

    def work(progress):
        res = backtest.run(p, progress=progress, use_cache=not force)
        _remember(res)
        return {"hash": res["hash"]}

    return jsonify({"ok": True, "job": jobs.submit("run", work)})


@app.get("/api/jobs/<jid>")
def job_status(jid):
    j = jobs.get(jid)
    if not j:
        return jsonify({"ok": False, "error": "unknown job"}), 404
    return jsonify({"ok": True, "data": j})


@app.get("/api/bt/result/<h>")
def bt_result(h):
    res = _result(h)
    if not res:
        return jsonify({"ok": False, "error": "Run not found (it may have been cleared by a data refresh)."}), 404
    return jsonify({"ok": True, "data": res})


@app.get("/api/bt/chart/<h>/<trade_id>")
def bt_chart(h, trade_id):
    res = _result(h)
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
            "spot": backtest.spot_bars(res["params"]["dataset"], day, int(res["params"]["timeframe"])),
            "option": backtest.option_candles(trade["symbol"], day),
        }})
    except Exception as exc:
        return _error(exc, 500)


# ====================================================================== live / paper engine
@app.get("/live")
def live_page():
    return render_template("live.html")


@app.get("/api/live/status")
def live_status():
    return jsonify({"ok": True, "data": live_manager.status()})


@app.post("/api/live/start")
def live_start():
    body = request.get_json(force=True) or {}
    try:
        data = live_manager.start(body.get("config") or {}, body.get("confirm", ""),
                                  body.get("replay_day"), float(body.get("replay_speed") or 120))
        return jsonify({"ok": True, "data": data})
    except config.KeysError as exc:
        return _error(exc, 400)
    except (ValueError, PermissionError, RuntimeError) as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc)


@app.post("/api/live/stop")
def live_stop():
    try:
        return jsonify({"ok": True, "data": live_manager.stop()})
    except Exception as exc:
        return _error(exc, 400)


@app.post("/api/live/squareoff")
def live_squareoff():
    try:
        return jsonify({"ok": True, "data": live_manager.square_off()})
    except Exception as exc:
        return _error(exc, 400)


@app.get("/api/live/trades")
def live_trades():
    try:
        return jsonify({"ok": True, "data": live_manager.trades(request.args.get("mode"), request.args.get("day"))})
    except Exception as exc:
        return _error(exc, 500)


@app.get("/api/live/broker")
def live_broker():
    """Actual Groww F&O positions, for reconciling against the engine."""
    try:
        return jsonify({"ok": True, "data": groww_client.call("get_positions_for_user", segment="FNO", timeout=10)})
    except config.KeysError as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)

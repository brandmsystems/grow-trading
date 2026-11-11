"""Flask entry point for the Groww trading system."""
from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import date

import pandas as pd
from flask import Flask, jsonify, render_template, request

from app.services.backtest import engine as backtest
from app.config import settings as config
from app.services.market_data import history as data_manager
from app.database import db
from app.services.groww import client as groww_client
from app.workers import jobs
from app.services.trading import manager as live_manager
from app.services.market_data import providers
from app.services.backtest import research
from app.services.strategy import signals
from app.services.strategy import strategies
from app.services.strategy import rules as st

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

# Legacy server-rendered pages, served until each one is replaced by the React frontend.
LEGACY_DIR = config.BACKEND_DIR / "legacy"
app = Flask(__name__, template_folder=str(LEGACY_DIR / "templates"), static_folder=str(LEGACY_DIR / "static"))
app.json.sort_keys = False

try:
    db.init()
    data_manager.recover_interrupted()
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


@app.get("/data")
def data_page():
    return render_template("data.html")


@app.get("/history")
def history_page():
    return render_template("history.html")


@app.get("/compare")
def compare_page():
    return render_template("compare.html")


@app.get("/signals")
def signals_page():
    return render_template("signals.html")


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


def _real_only(params: dict) -> dict:
    if params["dataset"] != "groww":
        raise ValueError("Only real Groww market data can be used.")
    return params


@app.get("/api/bt/meta")
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


@app.post("/api/bt/data")
def bt_data():
    params = request.get_json(force=True) or {}
    try:
        _real_only(backtest.normalise(params))
    except ValueError as exc:
        return _error(exc, 400)
    jid = jobs.submit("data", backtest.ensure_data, params)
    return jsonify({"ok": True, "job": jid})


@app.post("/api/bt/run")
def bt_run():
    params = request.get_json(force=True) or {}
    force = bool(params.pop("force", False))
    try:
        p = _real_only(backtest.normalise(params))
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
            "spot": backtest.spot_bars(res["params"]["dataset"], day, int(res["params"]["timeframe"]),
                                       res["params"].get("strategy", "ema_9_21")),
            "fast_label": f"EMA {strategies.STRATEGIES[res['params'].get('strategy', 'ema_9_21')].fast}",
            "slow_label": f"EMA {strategies.STRATEGIES[res['params'].get('strategy', 'ema_9_21')].slow}",
            "option": backtest.option_candles(trade["symbol"], day),
        }})
    except Exception as exc:
        return _error(exc, 500)


# ====================================================================== data management
def _date_arg(name: str) -> date | None:
    value = request.args.get(name)
    return date.fromisoformat(value) if value else None


@app.get("/api/data/overview")
def data_overview():
    try:
        return jsonify({"ok": True, "data": {
            "coverage": data_manager.coverage(_date_arg("from"), _date_arg("to")),
            "downloads": data_manager.downloads(),
            "job": next((j for j in jobs.active() if j["kind"] == "download"), None),
        }})
    except ValueError as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/data/download")
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


@app.post("/api/data/stop")
def data_stop():
    data_manager.request_stop()
    return jsonify({"ok": True})


@app.get("/api/data/candles")
def data_candles():
    try:
        return jsonify({"ok": True, "data": data_manager.candles(
            _date_arg("from"), _date_arg("to"), int(request.args.get("tf", 5)))})
    except (TypeError, ValueError) as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc, 500)


# ====================================================================== research & signals
def _active(kind: str):
    return next((j for j in jobs.active() if j["kind"] == kind), None)


@app.get("/api/research")
def research_results():
    try:
        data = research.results(request.args.get("entry_start", "09:30"), request.args.get("cutoff", "14:30"))
        return jsonify({"ok": True, "data": data, "job": _active("research")})
    except ValueError as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/research/run")
def research_run():
    body = request.get_json(force=True) or {}
    if _active("research"):
        return jsonify({"ok": False, "error": "A comparison run is already in progress."}), 409
    try:
        research.settings(body.get("entry_start", "09:30"), body.get("cutoff", "14:30"))
    except ValueError as exc:
        return _error(exc, 400)
    return jsonify({"ok": True, "job": jobs.submit("research", research.run_grid, body.get("entry_start", "09:30"),
                                                   body.get("cutoff", "14:30"), lane="research")})


def _signal_args(src) -> tuple[str, int]:
    key, tf = src.get("strategy", strategies.DEFAULT), int(src.get("tf", 15))
    if key not in strategies.STRATEGIES or tf not in backtest.TIMEFRAMES:
        raise ValueError("Unknown strategy or timeframe")
    return key, tf


@app.get("/api/signals")
def signals_get():
    try:
        key, tf = _signal_args(request.args)
        return jsonify({"ok": True, "data": signals.get(key, tf), "job": _active("signals")})
    except ValueError as exc:
        return _error(exc, 400)
    except Exception as exc:
        return _error(exc, 500)


@app.post("/api/signals/build")
def signals_build():
    try:
        key, tf = _signal_args(request.get_json(force=True) or {})
    except ValueError as exc:
        return _error(exc, 400)
    if _active("signals"):
        return jsonify({"ok": False, "error": "A signal analysis is already being built."}), 409
    return jsonify({"ok": True, "job": jobs.submit("signals", signals.build_and_store, key, tf)})


# ====================================================================== live / paper engine
@app.get("/live")
def live_page():
    return render_template("live.html")


@app.get("/api/live/status")
def live_status():
    try:
        tf = int(request.args.get("tf", 15))
    except ValueError:
        tf = 15
    return jsonify({"ok": True, "data": live_manager.status(request.args.get("mode"), tf,
                                                             request.args.get("strategy", "ema_9_21"))})


@app.get("/api/live/dashboard")
def live_dashboard():
    """Everything the Live page shows, in one poll: engine status, NIFTY feed, signal, option, size."""
    from app.services.market_data import feed as live_feed
    a = request.args
    try:
        tf = int(a.get("tf", 5))
        if tf not in (5, 15, 30):
            raise ValueError("timeframe must be 5, 15 or 30")
        entry_start, cutoff = a.get("entry_start", "09:30"), a.get("cutoff", "14:30")
        live_feed._hm(entry_start), live_feed._hm(cutoff)
        capital = float(a["capital"]) if a.get("capital") else None
        risk_pct = float(a.get("risk_pct", 1))
        if capital is not None and capital <= 0:
            raise ValueError("capital must be positive")
        if not 0 < risk_pct <= 100:
            raise ValueError("risk % must be between 0 and 100")
    except (TypeError, ValueError) as exc:
        return _error(exc, 400)
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
        return _error(exc, 500)
    s["feed"] = feed
    return jsonify({"ok": True, "data": s})


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


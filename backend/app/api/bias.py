"""Automated multi-timeframe paper trading: analysis, predictions, accuracy, trades and settings.
Paper and replay only: nothing here can place a Groww order (the bias engine refuses live mode)."""
from __future__ import annotations

import threading
import time as _time
from dataclasses import asdict
from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from app.api.common import api_error, json_body
from app.config import settings as config
from app.services.strategy import bias
from app.services.trading import bias_report
from app.services.trading import engine as le
from app.services.trading import manager as live_manager

bp = Blueprint("bias", __name__)

_FORM = ("timeframe", "bias_confirm_tf", "bias_indicators", "bias_min_confidence", "bias_trend_thr", "bias_confirm_thr", "bias_min_atr_pct", "bias_allow",
         "bias_exit_opposite", "bias_max_hold_min", "bias_cooldown_bars", "target_rr", "trail_pct", "trail_activate_pct",
         "sell_risk_pct", "min_premium", "min_oi", "max_spread_pct", "min_delta", "risk_pct", "daily_risk_pct",
         "max_daily_loss", "max_trades_per_day", "max_lots", "min_balance", "stop_mode", "stop_atr", "stop_pct",
         "stop_points", "entry_start", "cutoff", "exec_mode", "lots")
DEFAULT_MAX_TRADES = 20      # the brief's default; the engine's own default (6) belongs to the older modes

_cache: dict = {"key": None, "at": 0.0, "value": None}
_cache_lock = threading.Lock()


def _engine():
    eng = live_manager._engine
    return eng if eng is not None and eng.cfg.signal_mode == "bias" and eng.state != "stopped" else None


def defaults() -> dict:
    d = asdict(le.EngineConfig(signal_mode="bias", trade_mode="paper", timeframe=5, max_trades_per_day=DEFAULT_MAX_TRADES))
    return {k: d[k] for k in _FORM}


def _int(name, default):
    try:
        return int(request.args.get(name, default))
    except ValueError:
        return default


@bp.get("/api/bias/config")
def bias_config():
    """Form defaults, the indicator list (label, weight) and the current settings of a running engine."""
    eng = _engine()
    return jsonify({"ok": True, "data": {
        "defaults": defaults(), "running": bool(eng),
        "settings": {k: getattr(eng.cfg, k) for k in _FORM} if eng else None,
        "indicators": [{"key": k, "label": v[0], "weight": v[1]} for k, v in bias.INDICATORS.items()],
        "note": "Weights and thresholds are fixed starting values, not fitted to any result. "
                "Confidence means agreement between indicators, not a probability of winning."}})


@bp.get("/api/bias/status")
def bias_status():
    eng = _engine()
    if not eng:
        return jsonify({"ok": True, "data": {"running": False}})
    s = eng.status()
    return jsonify({"ok": True, "data": {"running": True, "state": s["state"], "halt_reason": s["halt_reason"],
                                         "trade_mode": s["config"]["trade_mode"], "day": s["day"], "now": s["now"],
                                         "position": s["position"], "realised_today": s["realised_today"],
                                         "bias": s.get("bias"), "events": s["events"][:40], "next_eval": s["next_eval"],
                                         "nifty": s["nifty"], "conn_error": s["conn_error"],
                                         "session_id": s["session_id"], "config": s["config"]}})


@bp.get("/api/bias/analysis")
def bias_analysis():
    """The bias right now (or at the last close) from stored and live candles, whether or not the engine runs."""
    from app.services.market_data import feed as live_feed
    try:
        config.load_keys()
        eng = _engine()
        params = bias.BiasParams.from_cfg(eng.cfg) if eng else bias.BiasParams()
        f = live_feed.feed()
        day = f.now().date()
        with _cache_lock:
            key = (day, tuple(params.enabled), params.min_confidence, params.trend_thr, params.confirm_thr, params.min_atr_pct, params.primary, params.higher)
            if _cache["key"] == key and _time.monotonic() - _cache["at"] < 15:
                return jsonify({"ok": True, "data": _cache["value"]})
            spot, fut, err = f.candles(day)
            if spot is None:
                return api_error(RuntimeError(err or "No NIFTY candles available."), 502)
            frame = bias.analyse(spot, fut, params)
            if frame.empty:
                return api_error(RuntimeError("Not enough candles yet."), 409)
            last_day = frame["day"].iloc[-1]
            today = frame[frame["day"] == last_day]
            data = {"as_of_day": last_day.isoformat(), "live": last_day == day, "analysis": bias.explain(today.iloc[-1], params),
                    "recent": [{"bar_close": r.close_ts.isoformat(), "close": round(float(r.close), 2), "bias": r.bias,
                                "confidence": float(r.confidence), "predicted": r.predicted}
                               for r in today.tail(24).itertuples()],
                    "futures": fut is not None and len(fut) > 0, "error": err}
            _cache.update(key=key, at=_time.monotonic(), value=data)
        return jsonify({"ok": True, "data": data})
    except config.KeysError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/bias/start")
def bias_start():
    """Start the automated engine in PAPER mode (live clock) or REPLAY (a finished day on stored candles)."""
    b = json_body()
    mode = b.get("trade_mode", "paper")
    if mode not in ("paper", "replay"):
        return jsonify({"ok": False, "error": "Automated trading runs in paper or replay mode only."}), 400
    cfg = {**defaults(), **{k: v for k, v in (b.get("config") or {}).items() if k in _FORM},
           "signal_mode": "bias", "trade_mode": mode}
    try:
        data = live_manager.start(cfg, "", b.get("replay_day"), float(b.get("replay_speed") or 120))
        return jsonify({"ok": True, "data": data})
    except config.KeysError as exc:
        return api_error(exc, 400)
    except (ValueError, PermissionError, RuntimeError, TypeError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)


@bp.post("/api/bias/settings")
def bias_settings():
    """Change settings of the running engine without restarting it (validated as a whole; a bad value changes nothing)."""
    eng = _engine()
    if not eng:
        return jsonify({"ok": False, "error": "The automated engine isn't running."}), 409
    changes = {k: v for k, v in json_body().items() if k in _FORM}
    if not changes:
        return jsonify({"ok": False, "error": "No settings to change."}), 400
    try:
        return jsonify({"ok": True, "data": eng.update_settings(changes)})
    except (ValueError, TypeError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/paper/position/target")
def paper_position_target():
    """Change the open paper position's target premium."""
    eng = live_manager._engine
    if not eng or eng.cfg.trade_mode != "paper" or eng.state == "stopped":
        return jsonify({"ok": False, "error": "The paper engine isn't running."}), 409
    try:
        return jsonify({"ok": True, "data": eng.set_paper_target(float(json_body()["target"]))})
    except (KeyError, TypeError):
        return jsonify({"ok": False, "error": "Enter the new target premium."}), 400
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/bias/predictions")
def bias_predictions():
    try:
        return jsonify({"ok": True, "data": bias_report.predictions(
            request.args.get("day"), request.args.get("mode", "paper"), _int("limit", 120), _int("session", 0) or None)})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/bias/accuracy")
def bias_accuracy():
    try:
        return jsonify({"ok": True, "data": bias_report.accuracy(
            request.args.get("mode", "paper"), request.args.get("from"), request.args.get("to"))})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/bias/history-accuracy")
def bias_history_accuracy():
    """Accuracy of each indicator and of the combined bias over stored candles (default: the last 60 days)."""
    try:
        end = date.fromisoformat(request.args["to"]) if request.args.get("to") else date.today()
        start = date.fromisoformat(request.args["from"]) if request.args.get("from") else end - timedelta(days=60)
        if start > end or (end - start).days > 800:
            return jsonify({"ok": False, "error": "Choose a period of at most 800 days."}), 400
        tf, confirm = int(request.args.get("tf", 5)), int(request.args.get("confirm", 15))
        return jsonify({"ok": True, "data": bias_report.history_accuracy(start, end, tf, confirm)})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/bias/trades")
def bias_trades():
    try:
        return jsonify({"ok": True, "data": bias_report.trades(
            request.args.get("mode", "paper"), request.args.get("day"), _int("limit", 300), _int("session", 0) or None)})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/bias/summary")
def bias_summary():
    try:
        return jsonify({"ok": True, "data": bias_report.summary(
            request.args.get("mode", "paper"), request.args.get("day"), _int("session", 0) or None)})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/bias/trade/<int:tid>")
def bias_trade(tid: int):
    try:
        d = bias_report.trade_detail(tid)
        return (jsonify({"ok": True, "data": d}) if d else (jsonify({"ok": False, "error": "Trade not found."}), 404))
    except Exception as exc:
        return api_error(exc, 500)

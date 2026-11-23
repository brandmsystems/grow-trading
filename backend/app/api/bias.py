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
from app.services.strategy import bias, confluence
from app.services.trading import bias_report
from app.services.trading import engine as le
from app.services.trading import manager as live_manager

bp = Blueprint("bias", __name__)

_FORM = ("timeframe", "bias_confirm_tf", "bias_indicators", "bias_min_confidence", "bias_trend_thr", "bias_confirm_thr", "bias_min_atr_pct", "bias_allow",
         "bias_exit_opposite", "bias_max_hold_min", "bias_cooldown_bars", "target_rr", "trail_pct", "trail_activate_pct",
         "sell_risk_pct", "min_premium", "min_oi", "max_spread_pct", "min_delta", "risk_pct", "daily_risk_pct",
         "max_daily_loss", "max_trades_per_day", "max_lots", "min_balance", "stop_mode", "stop_atr", "stop_pct",
         "stop_points", "entry_start", "cutoff", "exec_mode", "lots", "premarket_mode", "profit_target_net",
         "entry_strategy", "cf_factors", "cf_require", "cf_min_score", "cf_adr_filter", "cf_adr_period", "cf_adr_max_used",
         "cf_fvg_min_atr", "cf_fvg_max_age", "cf_htf", "sc_min_score", "sc_adr_period", "sc_adr_max_used", "sc_fvg_min_atr",
         "sc_fvg_max_age", "sc_ctx_tf", "sc_stop_min_pct", "sc_stop_max_pct")
DEFAULT_MAX_TRADES = 20      # the brief's default; the engine's own default (6) belongs to the older modes
DEFAULT_MIN_CONFIDENCE = 70.0    # continuous automation: entry needs a bias confidence of at least this %
DEFAULT_PROFIT_TARGET = 1500.0   # continuous automation: exit one trade at this net profit (₹, after charges)
# The scored strategy's starting risk, as specified: 0.5% of virtual capital per trade, 2R target, ATR stop, 1.5% daily loss limit,
# at most 5 trades, one open position, a 5-minute entry confirmed by the 15-minute trend. Offered as one click on the page, never forced.
SCORED_PRESET = {"timeframe": 5, "bias_confirm_tf": 15, "risk_pct": 0.5, "target_rr": 2.0, "stop_mode": "atr", "stop_atr": 1.0,
                 "daily_risk_pct": 1.5, "max_trades_per_day": 5, "profit_target_net": 0.0, "sc_min_score": 80.0}

_cache: dict = {"key": None, "at": 0.0, "value": None}
_cache_lock = threading.Lock()


def _engine():
    eng = live_manager._engine
    return eng if eng is not None and eng.cfg.signal_mode == "bias" and eng.state != "stopped" else None


def defaults() -> dict:
    d = asdict(le.EngineConfig(signal_mode="bias", trade_mode="paper", timeframe=5, max_trades_per_day=DEFAULT_MAX_TRADES))
    d.update(bias_min_confidence=DEFAULT_MIN_CONFIDENCE, profit_target_net=DEFAULT_PROFIT_TARGET)
    return {k: d[k] for k in _FORM}


def _cf_params(eng) -> confluence.ConfluenceParams:
    """Confluence settings for the analysis preview: the running engine's, else the defaults overridden by the query string."""
    if eng:
        return confluence.ConfluenceParams.from_cfg(eng.cfg)
    cfg, a = le.EngineConfig(signal_mode="bias", timeframe=5), request.args
    for name in ("cf_factors", "cf_require"):
        if name in a:
            setattr(cfg, name, [k for k in a[name].split(",") if k])
    for name in ("cf_min_score", "cf_adr_max_used", "cf_fvg_min_atr"):
        if name in a:
            setattr(cfg, name, float(a[name]))
    for name in ("cf_adr_period", "cf_fvg_max_age"):
        if name in a:
            setattr(cfg, name, int(a[name]))
    for name in ("cf_adr_filter", "cf_htf"):
        if name in a:
            setattr(cfg, name, a[name].lower() in ("1", "true", "yes"))
    return confluence.ConfluenceParams.from_cfg(cfg.validate())


def _sc_params(eng):
    """Scored-strategy parameters for the analysis preview: the running engine's if it runs that strategy, else (no engine) the
    query string's when `entry_strategy=scored`; None when the scored strategy is not selected."""
    if eng:
        return confluence.params_for(eng.cfg) if eng.cfg.entry_strategy == "scored" else None
    a = request.args
    if a.get("entry_strategy") != "scored":
        return None
    cfg = le.EngineConfig(signal_mode="bias", timeframe=int(a.get("timeframe", 5)), bias_confirm_tf=int(a.get("bias_confirm_tf", 15)), entry_strategy="scored")
    for name in ("sc_min_score", "sc_adr_max_used", "sc_fvg_min_atr", "sc_stop_min_pct", "sc_stop_max_pct"):
        if name in a:
            setattr(cfg, name, float(a[name]))
    for name in ("sc_adr_period", "sc_fvg_max_age", "sc_ctx_tf"):
        if name in a:
            setattr(cfg, name, int(a[name]))
    return confluence.params_for(cfg.validate())


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
        "confluence_factors": [{"key": k, "label": v[0], "weight": v[1]} for k, v in confluence.FACTORS.items()],
        "adr_periods": list(confluence.ADR_PERIODS),
        "scored_components": [{"key": k, "label": v[0], "max": v[1]} for k, v in confluence.SC_COMPONENTS.items()],
        "presets": {"scored": SCORED_PRESET},
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
            cp, sp = _cf_params(eng), _sc_params(eng)
            key = (day, tuple(params.enabled), params.min_confidence, params.trend_thr, params.confirm_thr, params.min_atr_pct, params.primary, params.higher,
                   cp, sp)
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
            # the confluence strategy's factors on the same candle (shown whether or not it is the active strategy)
            cf_frame = confluence.overlay(frame, spot, fut, cp)
            row = cf_frame[cf_frame["day"] == last_day].iloc[-1]
            analysis = bias.explain(today.iloc[-1], params)
            analysis["confluence"] = confluence.explain(row, cp, analysis)["confluence"]
            if sp is not None:
                srow = confluence.overlay(frame, spot, fut, sp)
                srow = srow[srow["day"] == last_day].iloc[-1]
                analysis["scored"] = confluence.explain(srow, sp, analysis)["scored"]
            data = {"as_of_day": last_day.isoformat(), "live": last_day == day, "analysis": analysis,
                    "recent": [{"bar_close": r.close_ts.isoformat(), "close": round(float(r.close), 2), "bias": r.bias,
                                "confidence": float(r.confidence), "predicted": r.predicted}
                               for r in today.tail(24).itertuples()],
                    "futures": fut is not None and len(fut) > 0, "error": err}
            _cache.update(key=key, at=_time.monotonic(), value=data)
        return jsonify({"ok": True, "data": data})
    except (config.KeysError, ValueError) as exc:
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


@bp.post("/api/bias/pause")
def bias_pause():
    """Stop taking new entries; the open position (if any) is still managed. Nothing is closed."""
    eng = _engine()
    if not eng:
        return jsonify({"ok": False, "error": "The automated engine isn't running."}), 409
    eng.pause()
    return jsonify({"ok": True, "data": {"paused": eng.paused}})


@bp.post("/api/bias/resume")
def bias_resume():
    """Allow new entries again from the next closed candle."""
    eng = _engine()
    if not eng:
        return jsonify({"ok": False, "error": "The automated engine isn't running."}), 409
    eng.resume()
    return jsonify({"ok": True, "data": {"paused": eng.paused}})


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

"""Position trading (multi-day NIFTY option ideas): analysis, decisions, settings, the separate virtual account and its paper positions, and the stored
backtest. PAPER ONLY: nothing here imports the live engine or LiveBroker, and no route returns Groww account data."""
from __future__ import annotations

import json
import math
import threading
import time as _time
from datetime import date, datetime

import numpy as np
from flask import Blueprint, jsonify, request

from app.api.common import api_error, json_body
from app.services.position import account, analysis
from app.services.position import settings as psettings
from app.services.position import strategies as pstr

bp = Blueprint("position", __name__)
_cache: dict = {"at": 0.0, "value": None, "key": None}
_lock = threading.Lock()


def clean(v):
    """JSON-safe copy: dates to ISO strings, numpy to Python, NaN / inf to None."""
    if isinstance(v, dict):
        return {str(k): clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _ok(data):
    return jsonify({"ok": True, "data": clean(data)})


def _analysis(force: bool = False) -> dict:
    """The analysis, cached for 60 seconds (it reads about three years of candles)."""
    with _lock:
        s = psettings.current()
        key = (s["version"], bool(s["error"]))
        if not force and _cache["value"] is not None and _cache["key"] == key and _time.monotonic() - _cache["at"] < 60:
            return _cache["value"]
        out = analysis.analyse(cfg=s["config"])
        out["settings_version"] = s["version"]
        out["settings_error"] = s["error"]
        _cache.update(value=out, at=_time.monotonic(), key=key)
        return out


@bp.get("/api/position/analysis")
def position_analysis():
    try:
        return _ok(_analysis(force=request.args.get("refresh") == "1"))
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/position/config")
def position_config():
    s = psettings.current()
    return _ok({"settings": s, "strategies": [{"key": k, "label": v["label"], "params": v["params"], "doc": (v["fn"].__doc__ or "").strip()} for k, v in pstr.STRATEGIES.items()],
                "risk_schema": {k: {"type": t, "min": lo, "max": hi, "default": d, "label": lab} for k, (t, lo, hi, d, lab) in psettings.RISK_SCHEMA.items()},
                "note": "Paper trading only. The score counts sound conditions met; it is not a probability of winning."})


@bp.put("/api/position/settings")
def position_settings_put():
    try:
        out = psettings.save(json_body().get("config") or {})
        _cache["value"] = None
        return _ok(out)
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/position/account")
def position_account():
    try:
        return _ok({"state": account.state(), "summary": account.summary()})
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/position/account/reset")
def position_account_reset():
    try:
        capital = float(json_body().get("capital"))
        return _ok(account.reset(capital))
    except (TypeError, ValueError) as exc:
        return api_error(ValueError("Enter the virtual capital as a number above zero." if not str(exc) or "float" in str(exc) else str(exc)), 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/position/positions")
def position_positions():
    try:
        return _ok(account.positions(status=request.args.get("status") or None))
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/position/open")
def position_open():
    """Open a paper position from the current analysis: body {"direction": 1 | -1}. Refused with the exact reason when a rule says no."""
    from app.utils.timeutil import now_naive
    try:
        b = json_body()
        direction = int(b.get("direction"))
        a = _analysis(force=True)
        opp = next((o for o in a.get("opportunities", []) if o["direction"] == direction), None)
        if not opp:
            return jsonify({"ok": False, "error": "There is no analysed opportunity in that direction right now."}), 409
        s = psettings.current()
        if s["error"]:
            return jsonify({"ok": False, "error": f"Position settings are unreadable ({s['error']}): no paper entry is made."}), 409
        res = account.open_position(opp, a["day"], s["config"]["risk"], now_naive(), price=None, allow_unvalidated=True)
        _cache["value"] = None
        return _ok(res)
    except account.Refused as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except (TypeError, ValueError) as exc:
        return api_error(ValueError("Send direction as 1 (BUY CE) or -1 (BUY PE)."), 400) if "int()" in str(exc) else api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/position/manage")
def position_manage():
    """Apply the exit rules to every open paper position with live prices (read-only quotes; never an order)."""
    from app.utils.timeutil import now_naive
    try:
        return _ok(account.manage(now_naive(), account.live_price))
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/position/decisions")
def position_decisions():
    from sqlalchemy import text
    from app.database import db
    try:
        with db.engine().connect() as c:
            rows = c.execute(text("SELECT day, decided_at, decision, direction, score, strategies, reasons FROM position_decisions ORDER BY day DESC LIMIT :n"),
                             {"n": max(1, min(int(request.args.get("limit", 60)), 400))}).mappings().all()
        return _ok([dict(r) for r in rows])
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/position/decide")
def position_decide():
    """Record today's decision (the last completed daily bar) in the decision history: one row per bar, never overwritten by a later look."""
    try:
        return _ok(record_decision(_analysis(force=True)))
    except Exception as exc:
        return api_error(exc, 500)


def record_decision(a: dict) -> dict:
    from sqlalchemy import text
    from app.database import db
    if not a.get("day"):
        return {"recorded": False, "why": "no completed daily bar"}
    with db.engine().begin() as c:
        n = c.execute(text("INSERT INTO position_decisions (day, decision, direction, score, strategies, reasons, analysis) VALUES (:d,:dec,:dir,:sc,CAST(:st AS JSONB),CAST(:re AS JSONB),CAST(:an AS JSONB)) "
                           "ON CONFLICT (day) DO NOTHING"),
                      {"d": date.fromisoformat(a["day"]), "dec": a["decision"], "dir": a.get("direction") or 0, "sc": a.get("score"),
                       "st": json.dumps(clean([s["key"] for s in a.get("strategies", []) if s["signal"]])), "re": json.dumps(clean(a.get("reasons", []))),
                       "an": json.dumps(clean({"market": a.get("market"), "comparison": a.get("comparison")}))}).rowcount
    return {"recorded": bool(n), "day": a["day"], "decision": a["decision"]}


@bp.get("/api/position/backtest")
def position_backtest():
    try:
        r = json.loads(analysis.RESEARCH.read_text(encoding="utf-8"))
        return _ok(r)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "The position backtest has not been run yet (python scripts/research_position.py run)."}), 404
    except Exception as exc:
        return api_error(exc, 500)


@bp.get("/api/position/chart")
def position_chart():
    """Completed bars with EMA 20/50/100/200 for the chart: tf is 1h, 4h, D or W."""
    from datetime import timedelta
    from app.services.position import bars as pbars, studies
    from app.utils.timeutil import now_naive
    try:
        tf = request.args.get("tf", "D")
        if tf not in pbars.TIMEFRAMES:
            return jsonify({"ok": False, "error": "tf must be 1h, 4h, D or W"}), 400
        asof = now_naive()
        spot, fut = analysis._load_inputs(asof)
        b = pbars.completed(pbars.build(spot, fut)[tf], asof, tf)
        b = studies.add_studies(b, weekly=(tf == "W")).tail(260 if tf in ("D", "W") else 400)
        rows = [{"t": r.close_ts.isoformat(), "o": r.open, "h": r.high, "l": r.low, "c": r.close,
                 **{f"e{n}": getattr(r, f"ema{n}") for n in (20, 50, 100, 200)}} for r in b.itertuples()]
        return _ok({"tf": tf, "bars": rows})
    except Exception as exc:
        return api_error(exc, 500)

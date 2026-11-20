"""Pre-market analysis: the day's report, a refresh, figures entered by hand, and the history. Information only:
nothing here places an order (the engine reads the stored report as an extra, optional confirmation)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, jsonify, request

from app.api.common import api_error, date_arg, json_body
from app.services.premarket import scoring, service, sources

bp = Blueprint("premarket", __name__)


@bp.get("/api/premarket/report")
def report():
    """The stored report of a day (default today); null when none has been generated yet."""
    try:
        day = date_arg("day") or service._now().date()
        rep = service.get(day)
        return jsonify({"ok": True, "data": {"day": str(day), "report": rep, "now": service._now().isoformat(timespec="seconds"),
                                             "thresholds": {"global": scoring.GLOBAL_THR, "vix_move": scoring.VIX_MOVE, "oil_day": scoring.OIL_DAY,
                                                            "fii_cash_cr": scoring.FII_CASH_CR, "structure": scoring.STRUCT_THR},
                                             "unavailable": sources.UNAVAILABLE}})
    except ValueError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)


@bp.get("/api/premarket/news")
def news():
    """The live news feed: articles from publisher RSS feeds and Google News searches with summaries, thumbnails, sentiment, expected
    NIFTY direction, impact level and original links. ?refresh=1 skips the two-minute cache. Failures come back as status
    "unavailable" or "stale" with the time of the last good fetch, never as invented or old news shown as live."""
    try:
        return jsonify({"ok": True, "data": service.news_feed(force=request.args.get("refresh") in ("1", "true"))})
    except Exception as exc:
        return api_error(exc)


@bp.post("/api/premarket/refresh")
def refresh():
    """Fetch the data again and recalculate today's report (the outside sources are read from this machine)."""
    try:
        return jsonify({"ok": True, "data": {"report": service.refresh()}})
    except Exception as exc:
        return api_error(exc)


@bp.post("/api/premarket/input")
def add_input():
    """Figures entered by hand: {"kind": "fii_dii", "day": "YYYY-MM-DD", fii_net_cash, dii_net_cash, fii_index_fut_long, fii_index_fut_short, source}
    or {"kind": "event", "title": "..."}. The report is recalculated at once."""
    b = json_body()
    try:
        kind = str(b.get("kind") or "")
        now = service._now()
        day = date.fromisoformat(b["day"]) if b.get("day") else (now.date() if kind == "event" else None)
        if day is None:
            raise ValueError("day is required")
        service.add_input(kind, day, b, b.get("source"), now)
        return jsonify({"ok": True, "data": {"report": service.refresh(now)}})
    except (ValueError, KeyError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)


@bp.get("/api/premarket/history")
def history():
    try:
        return jsonify({"ok": True, "data": service.history()})
    except Exception as exc:
        return api_error(exc)

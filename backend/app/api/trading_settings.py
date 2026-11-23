"""Trading Settings API: the centrally managed strategy, timeframe, indicator and risk configuration of the paper-trading engine.

Paper and replay only: nothing here places an order, and nothing here returns account, balance or real-trade data.
Saving is validated as a whole (an invalid configuration is a 400 with every problem listed and nothing is stored); every save is a
new version of the append-only `trading_settings` table, which the running engine picks up on its next tick."""
from __future__ import annotations

from flask import Blueprint, jsonify

from app.api.common import api_error, json_body
from app.services.trading import trading_settings as ts

bp = Blueprint("trading_settings", __name__)


def _payload(res: "ts.Resolved", warnings: list | None = None) -> dict:
    return {"version": res.version, "saved_at": res.saved_at.isoformat() if res.saved_at else None, "note": res.note, "config": res.doc,
            "summary": res.summary(), "warnings": warnings if warnings is not None else ts.validate(res.doc)[2], "error": res.error}


def _invalid(exc: "ts.SettingsError"):
    return jsonify({"ok": False, "error": f"The settings are invalid ({len(exc.errors)} problem{'s' if len(exc.errors) != 1 else ''}); nothing was saved.",
                    "kind": "SettingsError", "errors": exc.errors}), 400


@bp.get("/api/trading-settings")
def get_settings():
    """The current configuration (defaults when nothing was saved), its version and time, a summary, and what the page needs to draw its controls."""
    try:
        res = ts.load_current()
        return jsonify({"ok": True, "data": {**_payload(res), "meta": ts.meta(), "defaults": ts.defaults()}})
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/trading-settings/validate")
def validate_settings():
    """Check a draft without saving it: the cleaned configuration, every error and warning, and the summary it would give."""
    try:
        clean, errors, warnings = ts.validate(json_body().get("config"))
        return jsonify({"ok": True, "data": {"valid": not errors, "errors": errors, "warnings": warnings, "config": clean,
                                              "summary": ts.resolve(clean).summary() if not errors else None}})
    except Exception as exc:
        return api_error(exc, 500)


@bp.put("/api/trading-settings")
def save_settings():
    """Save the configuration as a new version. Body: {"config": {...}, "base_version"?: n}. 409 when `base_version` is no longer the
    current one (it was changed elsewhere); 400 listing every problem when invalid."""
    body = json_body()
    try:
        base = body.get("base_version")
        if base is not None and int(base) != ts.load_current().version:
            return jsonify({"ok": False, "error": "The settings were changed elsewhere since you opened this page. Reload to see them.", "kind": "Conflict"}), 409
        res = ts.save(body.get("config"), "saved")
        return jsonify({"ok": True, "data": _payload(res)})
    except ts.SettingsError as exc:
        return _invalid(exc)
    except (TypeError, ValueError) as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc, 500)


@bp.post("/api/trading-settings/reset")
def reset_settings():
    """Store the defaults as a new version (earlier versions are kept)."""
    try:
        return jsonify({"ok": True, "data": _payload(ts.reset())})
    except Exception as exc:
        return api_error(exc, 500)

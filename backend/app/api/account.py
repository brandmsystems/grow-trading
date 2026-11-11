"""Groww account: credentials status, login/logout, profile and funds."""
from __future__ import annotations

from flask import Blueprint, jsonify

from app.config import settings as config
from app.services.groww import client as groww_client
from app.api.common import api_error

bp = Blueprint("account", __name__)


@bp.get("/api/status")
def status():
    try:
        config.load_keys()
        keys_ok, keys_msg = True, "keys.txt found"
    except config.KeysError as exc:
        keys_ok, keys_msg = False, str(exc)
    return jsonify({"ok": True, "keys": keys_ok, "message": keys_msg})


@bp.post("/api/login")
def api_login():
    try:
        groww_client.login(force=True)
        return jsonify({"ok": True})
    except config.KeysError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)


@bp.post("/api/logout")
def api_logout():
    groww_client.logout()
    return jsonify({"ok": True})


@bp.get("/api/profile")
def api_profile():
    try:
        return jsonify({"ok": True, "data": groww_client.call("get_user_profile", timeout=10)})
    except config.KeysError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)


@bp.get("/api/funds")
def api_funds():
    try:
        return jsonify(
            {"ok": True, "data": groww_client.call("get_available_margin_details", timeout=10)}
        )
    except config.KeysError as exc:
        return api_error(exc, 400)
    except Exception as exc:
        return api_error(exc)

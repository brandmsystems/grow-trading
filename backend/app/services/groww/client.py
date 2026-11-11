"""Groww API session management using the TOTP sign-in flow.

Groww access tokens expire daily (around 06:00 IST), so the token is cached on
disk together with the IST trading date it was issued for and reused until then.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pyotp
from growwapi import GrowwAPI

from app.config import settings as config

IST = ZoneInfo("Asia/Kolkata")
_lock = threading.Lock()
_client: GrowwAPI | None = None
_client_valid_until: datetime | None = None


def _next_expiry(now: datetime) -> datetime:
    """Tokens are treated as valid until the next 06:00 IST."""
    cutoff = datetime.combine(now.date(), time(6, 0), IST)
    return cutoff if now < cutoff else cutoff + timedelta(days=1)


def _read_cache() -> tuple[str, datetime] | None:
    try:
        data = json.loads(config.TOKEN_CACHE.read_text())
        return data["token"], datetime.fromisoformat(data["valid_until"])
    except Exception:
        return None


def _write_cache(token: str, valid_until: datetime) -> None:
    config.TOKEN_CACHE.write_text(
        json.dumps({"token": token, "valid_until": valid_until.isoformat()})
    )


def login(force: bool = False) -> GrowwAPI:
    """Return an authenticated client, logging in with TOTP if needed."""
    global _client, _client_valid_until
    with _lock:
        now = datetime.now(IST)
        if not force and _client and _client_valid_until and now < _client_valid_until:
            return _client
        cached = None if force else _read_cache()
        if cached and now < cached[1]:
            token, valid_until = cached
        else:
            api_key, secret = config.load_keys()
            if re.fullmatch(r"[A-Z2-7]+=*", secret):   # base32 means a TOTP seed
                token = GrowwAPI.get_access_token(api_key=api_key, totp=pyotp.TOTP(secret).now())
            else:                                      # otherwise an API secret
                token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
            valid_until = _next_expiry(now)
            _write_cache(token, valid_until)
        _client = GrowwAPI(token)
        _client_valid_until = valid_until
        return _client


def logout() -> None:
    global _client, _client_valid_until
    with _lock:
        _client = None
        _client_valid_until = None
        config.TOKEN_CACHE.unlink(missing_ok=True)


def call(fn_name: str, *args, **kwargs):
    """Call a client method; on an auth failure, re-login once and retry."""
    client = login()
    try:
        return getattr(client, fn_name)(*args, **kwargs)
    except Exception as exc:  # SDK raises GrowwAPIAuthenticationException etc.
        if "Authentication" in type(exc).__name__ or "401" in str(exc):
            client = login(force=True)
            return getattr(client, fn_name)(*args, **kwargs)
        raise

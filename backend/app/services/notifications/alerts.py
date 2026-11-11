"""Trading notifications: stored once per signal (unique key), read back for the dashboard.

Writers: the live/paper engine (entries, exits, skipped signals) and the live feed
(BUY CE / BUY PE / HOLD recommendations). Future channels (e.g. Telegram) read from here.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from sqlalchemy import text

from app.database import db

log = logging.getLogger("notifications")


def store(key: str, mode: str, day: date, ts: datetime, action: str, payload: dict,
          session_id: int | None = None, eng=None) -> None:
    """Insert an alert unless one with the same key exists. Never raises."""
    try:
        with (eng or db.engine()).begin() as c:
            c.execute(text("INSERT INTO live_alerts (alert_key, session_id, trade_mode, day, ts, action, payload) "
                           "VALUES (:k,:s,:m,:d,:t,:a,CAST(:p AS JSONB)) ON CONFLICT (alert_key) DO NOTHING"),
                      {"k": key, "s": session_id, "m": mode, "d": day, "t": ts, "a": action,
                       "p": json.dumps(payload, default=str)})
    except Exception as exc:
        log.warning("alert not stored: %s", exc)


def recent(mode: str | tuple, limit: int = 12) -> list[dict]:
    """Newest alerts first for one mode or several."""
    modes = [mode] if isinstance(mode, str) else list(mode)
    with db.engine().connect() as c:
        rows = c.execute(text("SELECT id, ts, day, action, trade_mode, payload FROM live_alerts "
                              "WHERE trade_mode = ANY(:m) ORDER BY id DESC LIMIT :n"),
                         {"m": modes, "n": limit}).mappings().all()
    return [{"id": r["id"], "ts": r["ts"].isoformat(), "day": r["day"].isoformat(), "action": r["action"],
             "mode": r["trade_mode"], **r["payload"]} for r in rows]

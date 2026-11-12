"""Real-time push (Phase 3): Socket.IO over WebSocket, with REST polling as the fallback.

What is pushed is exactly the /api/live/dashboard payload (one builder, `live.dashboard_payload`):
NIFTY spot, CE/PE premiums, the strategy signal, engine status, position, P&L and notifications.

* A browser connects and sends `subscribe` with its dashboard settings (timeframe, mode, capital...).
  Browsers with the same settings share a room, so each distinct setting is computed once per tick.
* One background loop ticks every PUSH_OPEN_SEC while the market is open or an engine is running,
  otherwise every PUSH_IDLE_SEC. The Groww calls themselves stay behind the feed's caches.
* A `dashboard` event is sent only when the content changed (hash without clock-only fields);
  otherwise the room just gets a `heartbeat`. Every event carries a per-room sequence number, so the
  client can drop duplicates or out-of-order events.
* Socket.IO's own ping/pong (PING_INTERVAL) detects dead connections; the client also treats a
  missing heartbeat for HEARTBEAT_STALE_SEC as stale and falls back to polling.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time as _time
from datetime import datetime

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room

log = logging.getLogger("app.realtime")

PUSH_OPEN_SEC = 1.0
PUSH_IDLE_SEC = 5.0
PING_INTERVAL = 10
PING_TIMEOUT = 10
HEARTBEAT_STALE_SEC = 15      # the client's threshold, sent to it on subscribe
VOLATILE = {"now", "age_sec", "updated", "server_time", "computed_at"}   # change every tick without new information

socketio = SocketIO(async_mode="threading", ping_interval=PING_INTERVAL, ping_timeout=PING_TIMEOUT,
                    cors_allowed_origins=["http://127.0.0.1:5000", "http://localhost:5000",
                                          "http://127.0.0.1:5173", "http://localhost:5173"])


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in VOLATILE}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


class Pusher:
    """Rooms of subscribers and the loop that feeds them. `build` makes one payload from settings."""

    def __init__(self, sio: SocketIO, build, encode):
        self.sio, self.build, self.encode = sio, build, encode
        self.lock = threading.Lock()
        self.rooms: dict[str, dict] = {}     # key -> {"args", "sids", "seq", "hash", "data"}
        self.sid_room: dict[str, str] = {}
        self.thread = None
        self.ticks = 0

    @staticmethod
    def key(args: dict) -> str:
        return "dash:" + hashlib.sha1(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def subscribe(self, sid: str, args: dict) -> str:
        k = self.key(args)
        with self.lock:
            old = self.sid_room.get(sid)
            if old and old != k:
                self._leave(sid, old)
            room = self.rooms.setdefault(k, {"args": args, "sids": set(), "seq": 0, "hash": None, "data": None})
            room["sids"].add(sid)
            self.sid_room[sid] = k
        return k

    def _leave(self, sid: str, k: str) -> None:
        room = self.rooms.get(k)
        if room:
            room["sids"].discard(sid)
            if not room["sids"]:
                del self.rooms[k]

    def unsubscribe(self, sid: str) -> None:
        with self.lock:
            k = self.sid_room.pop(sid, None)
            if k:
                self._leave(sid, k)

    def compute(self, k: str) -> tuple[dict | None, bool]:
        """Build the room's payload; returns (event, changed). The event is None if the room is gone."""
        with self.lock:
            room = self.rooms.get(k)
            args = dict(room["args"]) if room else None
        if args is None:
            return None, False
        try:
            data = json.loads(self.encode(self.build(args)))
            h = hashlib.sha1(json.dumps(_strip(data), sort_keys=True).encode()).hexdigest()
            err = None
        except Exception as exc:
            log.warning("push build failed: %s", exc)
            data, h, err = None, None, str(exc) or type(exc).__name__
        with self.lock:
            room = self.rooms.get(k)
            if room is None:
                return None, False
            room["seq"] += 1
            changed = data is not None and h != room["hash"]
            if changed:
                room["hash"], room["data"] = h, data
            return {"seq": room["seq"], "room": k, "server_time": datetime.now().isoformat(timespec="seconds"),
                    "data": data if changed else None, "error": err}, changed

    def busy(self) -> bool:
        """Tick fast while any room's market is open or an engine is running."""
        with self.lock:
            datas = [r["data"] for r in self.rooms.values() if r["data"]]
        return any((d.get("feed") or {}).get("market", {}).get("state") == "open" or d.get("state") not in (None, "stopped")
                   for d in datas)

    def tick(self) -> int:
        """One round over every room. Returns the number of full dashboard events sent."""
        sent = 0
        with self.lock:
            keys = list(self.rooms)
        for k in keys:
            ev, changed = self.compute(k)
            if ev is None:
                continue
            if changed:
                self.sio.emit("dashboard", ev, to=k)
                sent += 1
            else:
                self.sio.emit("heartbeat", {k2: ev[k2] for k2 in ("seq", "room", "server_time", "error")}, to=k)
        self.ticks += 1
        return sent

    def run(self) -> None:
        while True:
            start = _time.monotonic()
            try:
                if self.rooms:
                    self.tick()
            except Exception:
                log.exception("push loop error")
            wait = (PUSH_OPEN_SEC if self.busy() else PUSH_IDLE_SEC) - (_time.monotonic() - start)
            self.sio.sleep(max(0.2, wait))

    def ensure_running(self) -> None:
        with self.lock:
            if self.thread is None:
                self.thread = self.sio.start_background_task(self.run)


pusher: Pusher | None = None


def init_app(app) -> SocketIO:
    """Attach Socket.IO to the Flask app and register the handlers (called by create_app)."""
    global pusher
    from app.api.live import dashboard_args, dashboard_payload
    socketio.init_app(app)
    pusher = Pusher(socketio, dashboard_payload, app.json.dumps)

    @socketio.on("connect")
    def _connect():
        emit("hello", {"server_time": datetime.now().isoformat(timespec="seconds"),
                       "heartbeat_stale_sec": HEARTBEAT_STALE_SEC})

    @socketio.on("subscribe")
    def _subscribe(args):
        try:
            p = dashboard_args(args or {})
        except ValueError as exc:
            emit("subscribe_error", {"error": str(exc)})
            return
        old = pusher.sid_room.get(request.sid)
        k = pusher.subscribe(request.sid, p)
        if old and old != k:
            leave_room(old)
        join_room(k)
        # Send the current state straight away, so a new subscriber never waits for the next tick.
        with pusher.lock:
            room = pusher.rooms.get(k)
            cached = room and room["data"]
            ev = {"seq": room["seq"], "room": k, "server_time": datetime.now().isoformat(timespec="seconds"),
                  "data": room["data"], "error": None} if cached else None
        if ev is None:
            ev, _ = pusher.compute(k)
        if ev and ev.get("data") is not None:
            emit("dashboard", ev)
        elif ev:
            emit("heartbeat", {k2: ev[k2] for k2 in ("seq", "room", "server_time", "error")})
        pusher.ensure_running()

    @socketio.on("disconnect")
    def _disconnect(*_):
        pusher.unsubscribe(request.sid)

    return socketio

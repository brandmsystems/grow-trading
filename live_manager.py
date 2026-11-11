"""Owns the single engine instance and the start/stop safety checks."""
from __future__ import annotations

import os
import threading
import time as _time
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

import config
import db
import live_engine as le
from live_market import GrowwMarket, LiveBroker, PaperBroker, ReplayMarket

LIVE_MAX_LOTS = int(os.getenv("LIVE_MAX_LOTS", "1"))
CONFIRM_PHRASE = "LIVE"

_lock = threading.Lock()
_engine: le.Engine | None = None
_replay_thread: threading.Thread | None = None


def _running() -> bool:
    return _engine is not None and _engine.state not in ("stopped",)


def start(cfg_in: dict, confirm: str = "", replay_day: str | None = None, replay_speed: float = 120) -> dict:
    global _engine, _replay_thread
    with _lock:
        if _running():
            raise RuntimeError("Engine is already running. Stop it first.")
        cfg = le.EngineConfig(**{k: v for k, v in cfg_in.items() if k in le.EngineConfig.__dataclass_fields__})
        cfg.validate()

        if cfg.trade_mode == "replay":
            day = date.fromisoformat(replay_day) if replay_day else None
            if not day:
                raise ValueError("Pick a replay day")
            if day >= date.today():
                raise ValueError("Replay needs a finished session. Pick an earlier day.")
            if not db.candle_days("SYNTH:NIFTY") or day not in set(db.candle_days("SYNTH:NIFTY")):
                raise ValueError("No synthetic data for that day. Generate it on the Backtest page first.")
            market = ReplayMarket("synthetic", day - timedelta(days=14), datetime.combine(day, time(9, 14)))
            eng = le.Engine(cfg, market, PaperBroker(market))
            eng.start(threaded=False)
            eng.replay_day = day.isoformat()
            _engine = eng
            _replay_thread = threading.Thread(target=_replay_loop, args=(eng, market, replay_speed),
                                              daemon=True, name="replay")
            _replay_thread.start()
            return eng.status()

        if cfg.trade_mode == "live":
            if confirm.strip().upper() != CONFIRM_PHRASE:
                raise PermissionError(f'Type "{CONFIRM_PHRASE}" to confirm real-money trading.')
            if cfg.lots > LIVE_MAX_LOTS:
                raise PermissionError(f"Live lots capped at {LIVE_MAX_LOTS} (set LIVE_MAX_LOTS in .env to change).")
        config.load_keys()   # raises KeysError with a helpful message
        market = GrowwMarket()
        # Preflight: auth, quotes and contract master must work before trading.
        import groww_client
        groww_client.login()
        market.spot_ltp()
        market.expiries(market.now().date())
        broker = LiveBroker(market) if cfg.trade_mode == "live" else PaperBroker(market)
        eng = le.Engine(cfg, market, broker)
        eng.start(threaded=True)
        _engine = eng
        return eng.status()


def _replay_loop(eng: le.Engine, market: ReplayMarket, speed: float):
    """Advance the simulated clock: 10 simulated seconds per step."""
    end = datetime.combine(market.clock.date(), time(15, 31))
    delay = 10.0 / max(speed, 1)
    while eng.state != "stopped" and market.clock <= end:
        try:
            eng.tick()
        except Exception as exc:
            eng.log(f"Engine error: {exc}", "error")
        market.clock += timedelta(seconds=10)
        _time.sleep(delay)
    if eng.state != "stopped":
        eng.stop(square_off=True, reason="replay finished")


def stop() -> dict:
    with _lock:
        if not _engine:
            raise RuntimeError("Engine is not running")
        _engine.stop(square_off=True, reason="stopped by user")
        return _engine.status()


def square_off() -> dict:
    if not _engine or _engine.state == "stopped":
        raise RuntimeError("Engine is not running")
    _engine.square_off_now()
    return _engine.status()


def status() -> dict:
    s = _engine.status() if _engine else {"state": "stopped", "events": [], "bars": [], "position": None,
                                          "config": None, "trades_today": 0, "realised_today": 0}
    s["replay_day"] = getattr(_engine, "replay_day", None)
    s["live_max_lots"] = LIVE_MAX_LOTS
    s["confirm_phrase"] = CONFIRM_PHRASE
    return s


def trades(mode: str | None, day: str | None, limit: int = 200) -> list[dict]:
    q = "SELECT * FROM live_trades WHERE 1=1"
    p: dict = {}
    if mode:
        q += " AND trade_mode=:m"; p["m"] = mode
    if day:
        q += " AND day=:d"; p["d"] = day
    q += " ORDER BY id DESC LIMIT :n"; p["n"] = limit
    with db.engine().connect() as c:
        rows = [dict(r) for r in c.execute(text(q), p).mappings()]
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, (datetime, date)):
                r[k] = v.isoformat()
    return rows

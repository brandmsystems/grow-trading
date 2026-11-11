"""Owns the single engine instance and the start/stop safety checks."""
from __future__ import annotations

import os
import threading
import time as _time
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

import pandas as pd

import config
import db
import live_engine as le
from live_market import GrowwMarket, LiveBroker, PaperBroker, ReplayMarket
from providers import GrowwProvider
from live_feed import market_status  # noqa: F401  (one definition, shared with the feed)

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
            if day not in set(db.candle_days(GrowwProvider.spot_symbol)):
                raise ValueError("No real market data for that day. Download it on the Data page first.")
            market = ReplayMarket("groww", day - timedelta(days=45), datetime.combine(day, time(9, 14)))
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


def status(mode: str | None = None, tf: int = 15, strategy: str = "ema_9_21", with_snapshot: bool = True) -> dict:
    s = _engine.status() if _engine else {"state": "stopped", "events": [], "bars": [], "position": None,
                                          "config": None, "trades_today": 0, "realised_today": 0}
    s["replay_day"] = getattr(_engine, "replay_day", None)
    s["live_max_lots"] = LIVE_MAX_LOTS
    s["confirm_phrase"] = CONFIRM_PHRASE
    running = _engine is not None and _engine.state != "stopped"
    cfg = s.get("config") or {}
    mode = cfg.get("trade_mode") if running else (mode or "paper")
    now = _engine.market.now() if running else GrowwMarket().now()
    s["market"] = market_status(now)
    s["alerts"] = recent_alerts(mode)
    if not with_snapshot:       # the dashboard gets price/EMAs from live_feed instead
        return s
    if running:
        le_ = s.get("last_eval") or {}
        key = cfg.get("strategy", "ema_9_21") if cfg.get("signal_mode") == "prediction" else "ema_9_21"
        s["snapshot"] = {"nifty": (s.get("nifty") or {}).get("price"), "nifty_ts": (s.get("nifty") or {}).get("ts"),
                         "ema_fast": le_.get("ema9"), "ema_slow": le_.get("ema21"), "bar_close": le_.get("bar_close"),
                         **_ema_labels(key), "timeframe": cfg.get("timeframe"),
                         "connection": {"ok": not s.get("conn_error"), "message": s.get("conn_error") or
                                        ("Replay: simulated clock" if mode == "replay" else "Groww connected")}}
    else:
        s["snapshot"] = snapshot(tf, strategy)
    return s


# ------------------------------------------------------------------ dashboard helpers
def recent_alerts(mode: str | tuple, limit: int = 12) -> list[dict]:
    modes = [mode] if isinstance(mode, str) else list(mode)
    with db.engine().connect() as c:
        rows = c.execute(text("SELECT id, ts, day, action, trade_mode, payload FROM live_alerts "
                              "WHERE trade_mode = ANY(:m) ORDER BY id DESC LIMIT :n"),
                         {"m": modes, "n": limit}).mappings().all()
    return [{"id": r["id"], "ts": r["ts"].isoformat(), "day": r["day"].isoformat(), "action": r["action"],
             "mode": r["trade_mode"], **r["payload"]} for r in rows]


def _ema_labels(key: str) -> dict:
    import strategies
    s = strategies.STRATEGIES.get(key) or strategies.STRATEGIES["ema_9_21"]
    return {"fast_label": f"EMA {s.fast}", "slow_label": f"EMA {s.slow}"}


_snap_lock = threading.Lock()
_snap_cache: dict = {}
_snap_market: GrowwMarket | None = None


def snapshot(tf: int = 15, strategy: str = "ema_9_21") -> dict:
    """NIFTY price and EMAs for the dashboard while the engine is off (cached: quote 5 s, EMAs 60 s)."""
    import strategies
    global _snap_market
    key = strategy if strategy in strategies.STRATEGIES else "ema_9_21"
    out = {"nifty": None, "nifty_ts": None, "ema_fast": None, "ema_slow": None, "bar_close": None,
           "timeframe": tf, **_ema_labels(key), "connection": {"ok": False, "message": ""}}
    try:
        config.load_keys()
    except config.KeysError as exc:
        out["connection"]["message"] = str(exc)
        return out
    with _snap_lock:
        _snap_market = _snap_market or GrowwMarket()
        m = _snap_market
        now = _time.monotonic()

        def cached(name, ttl, fn):
            hit = _snap_cache.get(name)
            if hit and now - hit[0] < ttl:
                return hit[1]
            try:
                val = (fn(), None)
            except Exception as exc:
                val = (None, str(exc) or type(exc).__name__)
            _snap_cache[name] = (now, val)
            return val

        (ltp, err1) = cached("ltp", 5, m.spot_ltp)

        def emas():
            spot = m.spot_1m(m.now().date())
            bars = strategies.prepare(spot, None, tf, key)
            last = bars[bars["close_ts"] <= pd.Timestamp(m.now())].tail(1)
            if last.empty:
                return None
            r = last.iloc[0]
            return {"ema_fast": round(float(r["fast"]), 2), "ema_slow": round(float(r["slow"]), 2),
                    "bar_close": pd.Timestamp(r["close_ts"]).isoformat()}
        (em, err2) = cached(f"ema|{tf}|{key}", 60, emas)
    out["nifty"] = ltp
    out["nifty_ts"] = m.now().isoformat() if ltp is not None else None
    out.update(em or {})
    err = err1 or err2
    out["connection"] = {"ok": err1 is None, "message": err or "Groww connected"}
    return out


def trades(mode: str | None, day: str | None, limit: int = 200) -> list[dict]:
    q = "SELECT * FROM live_trades WHERE trading_symbol NOT LIKE 'SYNTH:%'"
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

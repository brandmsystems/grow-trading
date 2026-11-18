"""PostgreSQL storage: 1-minute candles, expiries, contracts and cached backtest runs."""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date, datetime

import numpy as np
import pandas as pd
import psycopg2.extensions
from psycopg2.extras import execute_values
from sqlalchemy import create_engine, text

from app.config import settings as config
from app.utils.timeutil import IST

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
CONNECT_ARGS = {"options": "-c timezone=Asia/Kolkata"}


def _cast_timestamptz(value, cur):
    """Columns hold real instants; the app works in IST wall-clock datetimes."""
    if value is None:
        return None
    return datetime.fromisoformat(value).astimezone(IST).replace(tzinfo=None)


psycopg2.extensions.register_type(psycopg2.extensions.new_type((1184,), "TIMESTAMPTZ_IST", _cast_timestamptz))

_engine = None


def engine(dbname: str | None = None):
    global _engine
    if dbname:
        return create_engine(config.database_url(dbname), pool_pre_ping=True, connect_args=CONNECT_ARGS)
    if _engine is None:
        _engine = create_engine(config.database_url(), pool_pre_ping=True, connect_args=CONNECT_ARGS)
    return _engine


def init(eng=None) -> None:
    """Apply any migrations not yet recorded, all in one transaction."""
    eng = eng or engine()
    with eng.begin() as c:
        c.exec_driver_sql("SELECT pg_advisory_xact_lock(921921)")
        c.exec_driver_sql("CREATE TABLE IF NOT EXISTS schema_migrations ("
                          "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        done = {r[0] for r in c.exec_driver_sql("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.stem not in done:
                c.exec_driver_sql(path.read_text(encoding="utf-8"))
                c.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": path.stem})


# ---------------------------------------------------------------- candles
def upsert_candles(symbol: str, df: pd.DataFrame, eng=None) -> int:
    """df columns: ts, open, high, low, close, volume, oi (oi optional)."""
    if df is None or df.empty:
        return 0
    eng = eng or engine()
    rows = [
        (symbol, r.ts.to_pydatetime() if hasattr(r.ts, "to_pydatetime") else r.ts,
         float(r.open), float(r.high), float(r.low), float(r.close),
         float(getattr(r, "volume", 0) or 0), float(getattr(r, "oi", 0) or 0))
        for r in df.itertuples(index=False)
    ]
    raw = eng.raw_connection()
    try:
        with raw.cursor() as cur:
            execute_values(
                cur,
                "INSERT INTO candles_1m (symbol, ts, open, high, low, close, volume, oi) "
                "VALUES %s ON CONFLICT (symbol, ts) DO UPDATE SET open=EXCLUDED.open, "
                "high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close, "
                "volume=EXCLUDED.volume, oi=EXCLUDED.oi",
                rows, page_size=5000,
            )
        raw.commit()
    finally:
        raw.close()
    return len(rows)


_CANDLE_COLS = ["open", "high", "low", "close", "volume", "oi"]


def load_candles(symbol: str, start: datetime, end: datetime, eng=None) -> pd.DataFrame:
    """1-minute candles for [start, end), oldest first: ts (naive IST wall clock) + OHLCV + OI.

    The hottest query in the app (every backtest loads spot plus hundreds of option windows),
    so it skips the per-value Python timestamp cast: PostgreSQL returns the IST wall-clock
    instant as integer microseconds, and numpy builds the frame in one pass. The result is
    identical to `pd.read_sql` + `_cast_timestamptz` (same values and dtypes, checked bit for
    bit on spot, futures and options). The columns are never NULL (upsert_candles writes 0 for
    missing volume/OI), so the float conversion cannot change a value.
    """
    eng = eng or engine()
    raw = eng.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("SELECT (extract(epoch FROM ts AT TIME ZONE 'Asia/Kolkata') * 1000000)::bigint, "
                        "open, high, low, close, volume, oi FROM candles_1m "
                        "WHERE symbol=%s AND ts>=%s AND ts<%s ORDER BY ts", (symbol, start, end))
            rows = cur.fetchall()
    finally:
        raw.close()
    if not rows:   # same empty frame read_sql produced: object columns, datetime ts
        df = pd.DataFrame([], columns=["ts", *_CANDLE_COLS])
        df["ts"] = pd.to_datetime(df["ts"])
        return df
    values = np.array(rows, dtype=np.float64)
    df = pd.DataFrame(values[:, 1:], columns=_CANDLE_COLS)
    df.insert(0, "ts", pd.to_datetime(np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows)), unit="us"))
    return df


def candle_days(symbol: str, eng=None) -> list[date]:
    eng = eng or engine()
    with eng.connect() as c:
        rows = c.execute(text("SELECT DISTINCT ts::date FROM candles_1m WHERE symbol=:s ORDER BY 1"),
                         {"s": symbol}).fetchall()
    return [r[0] for r in rows]


def data_summary(symbol: str, eng=None) -> dict:
    eng = eng or engine()
    with eng.connect() as c:
        r = c.execute(text("SELECT min(ts), max(ts), count(*), count(DISTINCT ts::date) "
                           "FROM candles_1m WHERE symbol=:s"), {"s": symbol}).fetchone()
    return {"first": r[0].isoformat() if r[0] else None, "last": r[1].isoformat() if r[1] else None,
            "rows": r[2], "days": r[3]}


def fetched(symbol: str, day: date, eng=None) -> bool:
    eng = eng or engine()
    with eng.connect() as c:
        return c.execute(text("SELECT 1 FROM fetch_log WHERE symbol=:s AND day=:d"),
                         {"s": symbol, "d": day}).first() is not None


def mark_fetched(symbol: str, day: date, rows: int, eng=None) -> None:
    eng = eng or engine()
    with eng.begin() as c:
        c.execute(text("INSERT INTO fetch_log (symbol, day, rows) VALUES (:s,:d,:r) "
                       "ON CONFLICT (symbol, day) DO UPDATE SET rows=EXCLUDED.rows, fetched_at=now()"),
                  {"s": symbol, "d": day, "r": rows})


# ---------------------------------------------------------------- expiries / contracts
def save_expiries(dataset: str, expiries: list[date], eng=None) -> None:
    if not expiries:
        return
    eng = eng or engine()
    with eng.begin() as c:
        for e in expiries:
            c.execute(text("INSERT INTO expiries VALUES (:d,:e) ON CONFLICT DO NOTHING"),
                      {"d": dataset, "e": e})


def load_expiries(dataset: str, eng=None) -> list[date]:
    eng = eng or engine()
    with eng.connect() as c:
        return [r[0] for r in c.execute(
            text("SELECT expiry FROM expiries WHERE dataset=:d ORDER BY expiry"), {"d": dataset})]


def save_contracts(dataset: str, rows: list[tuple[str, date, float, str]], eng=None) -> None:
    if not rows:
        return
    eng = eng or engine()
    with eng.begin() as c:
        for sym, exp, strike, typ in rows:
            c.execute(text("INSERT INTO contracts VALUES (:d,:s,:e,:k,:t) ON CONFLICT DO NOTHING"),
                      {"d": dataset, "s": sym, "e": exp, "k": strike, "t": typ})


def find_contract(dataset: str, expiry: date, strike: float, typ: str, eng=None) -> str | None:
    eng = eng or engine()
    with eng.connect() as c:
        r = c.execute(text("SELECT symbol FROM contracts WHERE dataset=:d AND expiry=:e "
                           "AND strike=:k AND opt_type=:t"),
                      {"d": dataset, "e": expiry, "k": strike, "t": typ}).first()
    return r[0] if r else None


def has_contracts(dataset: str, expiry: date, eng=None) -> bool:
    eng = eng or engine()
    with eng.connect() as c:
        return c.execute(text("SELECT 1 FROM contracts WHERE dataset=:d AND expiry=:e LIMIT 1"),
                         {"d": dataset, "e": expiry}).first() is not None


# ---------------------------------------------------------------- backtest cache
def get_run(param_hash: str, eng=None) -> dict | None:
    eng = eng or engine()
    with eng.connect() as c:
        r = c.execute(text("SELECT id, params, result, created_at FROM bt_runs WHERE param_hash=:h"),
                      {"h": param_hash}).first()
    if not r:
        return None
    return {"id": r[0], "params": r[1], "result": r[2], "created_at": r[3].isoformat()}


def save_run(param_hash: str, params: dict, result: dict, eng=None) -> int:
    eng = eng or engine()
    with eng.begin() as c:
        r = c.execute(text(
            "INSERT INTO bt_runs (param_hash, params, result) VALUES (:h, CAST(:p AS JSONB), CAST(:r AS JSONB)) "
            "ON CONFLICT (param_hash) DO UPDATE SET params=EXCLUDED.params, result=EXCLUDED.result, "
            "created_at=now() RETURNING id"),
            {"h": param_hash, "p": json.dumps(params, default=str), "r": json.dumps(result, default=str)})
        return r.scalar_one()


def clear_runs(dataset: str | None = None, eng=None) -> None:
    eng = eng or engine()
    with eng.begin() as c:
        if dataset:
            # Signals analyses stay: they are keyed by their data and prediction mode needs them.
            c.execute(text("DELETE FROM bt_runs WHERE params->>'dataset'=:d AND coalesce(params->>'kind', '') <> 'signals'"),
                      {"d": dataset})
        else:
            c.execute(text("DELETE FROM bt_runs"))

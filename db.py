"""PostgreSQL storage: 1-minute candles, expiries, contracts and cached backtest runs."""
from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
from psycopg2.extras import execute_values
from sqlalchemy import create_engine, text

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles_1m (
    symbol TEXT NOT NULL,
    ts     TIMESTAMP NOT NULL,          -- IST wall-clock candle START time
    open   DOUBLE PRECISION, high DOUBLE PRECISION,
    low    DOUBLE PRECISION, close DOUBLE PRECISION,
    volume DOUBLE PRECISION, oi DOUBLE PRECISION,
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS expiries (
    dataset TEXT NOT NULL, expiry DATE NOT NULL, PRIMARY KEY (dataset, expiry)
);
CREATE TABLE IF NOT EXISTS contracts (
    dataset TEXT NOT NULL, symbol TEXT NOT NULL, expiry DATE NOT NULL,
    strike DOUBLE PRECISION NOT NULL, opt_type TEXT NOT NULL,
    PRIMARY KEY (dataset, expiry, strike, opt_type)
);
-- Records (symbol, day) pairs already requested so empty days are not refetched.
CREATE TABLE IF NOT EXISTS fetch_log (
    symbol TEXT NOT NULL, day DATE NOT NULL, rows INTEGER NOT NULL,
    fetched_at TIMESTAMP NOT NULL DEFAULT now(), PRIMARY KEY (symbol, day)
);
CREATE TABLE IF NOT EXISTS live_sessions (
    id SERIAL PRIMARY KEY, trade_mode TEXT NOT NULL, config JSONB NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT now(), stopped_at TIMESTAMP, stop_reason TEXT
);
CREATE TABLE IF NOT EXISTS live_trades (
    id SERIAL PRIMARY KEY, session_id INTEGER, trade_mode TEXT NOT NULL, day DATE NOT NULL,
    exec_mode TEXT NOT NULL, direction TEXT NOT NULL, side TEXT NOT NULL,
    trading_symbol TEXT NOT NULL, groww_symbol TEXT, strike DOUBLE PRECISION, opt_type TEXT,
    expiry DATE, qty INTEGER NOT NULL, signal_ts TIMESTAMP, signal_close DOUBLE PRECISION,
    entry_ts TIMESTAMP, entry_price DOUBLE PRECISION, entry_order_id TEXT,
    exit_ts TIMESTAMP, exit_price DOUBLE PRECISION, exit_order_id TEXT, exit_reason TEXT,
    gross DOUBLE PRECISION, slippage DOUBLE PRECISION, charges JSONB, net DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'OPEN'          -- OPEN | CLOSED
);
CREATE TABLE IF NOT EXISTS live_events (
    id SERIAL PRIMARY KEY, session_id INTEGER, ts TIMESTAMP NOT NULL,
    level TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bt_runs (
    id SERIAL PRIMARY KEY, param_hash TEXT UNIQUE NOT NULL,
    params JSONB NOT NULL, result JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
"""

_engine = None


def engine(dbname: str | None = None):
    global _engine
    if dbname:
        return create_engine(config.database_url(dbname), pool_pre_ping=True)
    if _engine is None:
        _engine = create_engine(config.database_url(), pool_pre_ping=True)
    return _engine


def init(eng=None) -> None:
    eng = eng or engine()
    with eng.begin() as c:
        c.exec_driver_sql(SCHEMA)


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


def load_candles(symbol: str, start: datetime, end: datetime, eng=None) -> pd.DataFrame:
    eng = eng or engine()
    df = pd.read_sql(
        text("SELECT ts, open, high, low, close, volume, oi FROM candles_1m "
             "WHERE symbol=:s AND ts>=:a AND ts<:b ORDER BY ts"),
        eng, params={"s": symbol, "a": start, "b": end},
    )
    df["ts"] = pd.to_datetime(df["ts"])
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
            c.execute(text("DELETE FROM bt_runs WHERE params->>'dataset'=:d"), {"d": dataset})
        else:
            c.execute(text("DELETE FROM bt_runs"))

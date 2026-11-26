"""Multi-timeframe bars for position trading, built from stored 1-minute candles (pure; no I/O).

Every bar carries `start` and `close_ts`. `completed(bars, asof)` returns only the bars whose close time is at or before `asof`, so an
indicator computed on its result can never see a candle that was still forming (no look-ahead, no repainting). The NSE session is
09:15-15:30; the 4-hour bars are 09:15-13:15 and 13:15-15:30 (the second is the 2h15 remainder, an honest session split, not a padded bar).
Volume comes from the near-month future (the index has none); a bar without futures volume has volume 0 and is not used for volume votes.
"""
from __future__ import annotations

from datetime import time, timedelta

import numpy as np
import pandas as pd

OPEN, CLOSE = time(9, 15), time(15, 30)
SPLIT_4H = time(13, 15)
TIMEFRAMES = ("1h", "4h", "D", "W")


def _agg(df: pd.DataFrame, key: pd.Series) -> pd.DataFrame:
    g = df.groupby(key, sort=True)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last(),
                        "volume": g["volume"].sum(), "start": g["ts"].min(), "last": g["ts"].max(), "n": g["ts"].count()})
    out["close_ts"] = out["last"] + timedelta(minutes=1)
    return out.reset_index(drop=True)


def build(spot: pd.DataFrame, fut: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """{"1h", "4h", "D", "W"} bars from 1-minute spot candles (columns ts, open, high, low, close). Futures volume is joined by minute."""
    if spot is None or spot.empty:
        return {tf: pd.DataFrame(columns=["open", "high", "low", "close", "volume", "start", "last", "n", "close_ts", "day"]) for tf in TIMEFRAMES}
    df = spot[["ts", "open", "high", "low", "close"]].copy()
    df["ts"] = pd.to_datetime(df["ts"])
    if fut is not None and len(fut):
        v = fut.assign(ts=pd.to_datetime(fut["ts"])).drop_duplicates("ts").set_index("ts")["volume"]
        df["volume"] = df["ts"].map(v).fillna(0.0).to_numpy()
    else:
        df["volume"] = 0.0
    df = df[(df["ts"].dt.time >= OPEN) & (df["ts"].dt.time < CLOSE)].sort_values("ts").reset_index(drop=True)
    day = df["ts"].dt.normalize()
    mins = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    hour_slot = (mins - (OPEN.hour * 60 + OPEN.minute)) // 60
    iso = df["ts"].dt.isocalendar()
    out = {
        "1h": _agg(df, day.astype("int64") * 100 + hour_slot),
        "4h": _agg(df, day.astype("int64") * 10 + (mins >= SPLIT_4H.hour * 60 + SPLIT_4H.minute).astype(int)),
        "D": _agg(df, day),
        "W": _agg(df, iso["year"].astype(int) * 100 + iso["week"].astype(int)),
    }
    for tf, b in out.items():
        b["day"] = b["start"].dt.normalize()
    return out


def session_complete(n_minutes: int) -> bool:
    """A trading day is complete only with all 375 minutes (09:15-15:29); a partial day is never used as a finished daily bar."""
    return n_minutes >= 375


def completed(bars: pd.DataFrame, asof, tf: str) -> pd.DataFrame:
    """Bars of timeframe `tf` that were finished at `asof`. Intraday bars: close time <= asof. A daily bar needs the full session.
    A weekly bar needs its last weekday to be over: a later week exists in the data, or `asof` is past that week's Friday close."""
    asof = pd.Timestamp(asof)
    b = bars[bars["close_ts"] <= asof]
    if tf == "D":
        b = b[b["n"].map(session_complete)]
    elif tf == "W" and len(b):
        friday_close = b["start"].dt.normalize() - pd.to_timedelta(b["start"].dt.weekday, unit="D") + pd.Timedelta(days=4, hours=15, minutes=30)
        later = bars["start"].max() > b["start"]
        b = b[later.reindex(b.index, fill_value=False) | (friday_close <= asof)]
    return b.reset_index(drop=True)


def asof_merge(base: pd.DataFrame, other: pd.DataFrame, cols: list[str], suffix: str) -> pd.DataFrame:
    """Add `other`'s columns to `base` as of each base bar's close: the latest `other` bar already closed (backward as-of on close_ts)."""
    if other.empty:
        return base.assign(**{f"{c}{suffix}": np.nan for c in cols})
    o = other[["close_ts", *cols]].rename(columns={c: f"{c}{suffix}" for c in cols}).sort_values("close_ts")
    return pd.merge_asof(base.sort_values("close_ts"), o, on="close_ts", direction="backward")

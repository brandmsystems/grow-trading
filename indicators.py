"""Technical indicators on closed bars. Every value at bar i uses bars <= i only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def wilder(x: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing: the first value is the simple mean of the first n inputs,
    then avg = (prev * (n - 1) + x) / n. Leading NaNs are skipped."""
    v = x.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    idx = np.flatnonzero(~np.isnan(v))
    if len(idx) >= n:
        first = idx[0] + n - 1
        out[first] = np.nanmean(v[idx[0]:first + 1])
        prev = out[first]
        for i in range(first + 1, len(v)):
            if not np.isnan(v[i]):
                prev = (prev * (n - 1) + v[i]) / n
            out[i] = prev
    return pd.Series(out, index=x.index)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), n)
    loss = wilder(-delta.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's ATR. The previous close carries across days, so overnight gaps count."""
    prev = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev).abs(), (bars["low"] - prev).abs()], axis=1).max(axis=1)
    return wilder(tr, n)


def session_vwap(df1m: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP from the day's first candle, per minute. NaN until volume trades."""
    tp = (df1m["high"] + df1m["low"] + df1m["close"]) / 3
    day = df1m["ts"].dt.date
    pv = (tp * df1m["volume"]).groupby(day).cumsum()
    vol = df1m["volume"].groupby(day).cumsum()
    return pv / vol.replace(0, np.nan)

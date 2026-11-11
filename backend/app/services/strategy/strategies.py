"""The strategies compared in research. Each one is a fast/slow EMA cross, optionally
confirmed by a second indicator. All values come from closed bars only.

Confirmation rules (checked on the signal bar itself):
* VWAP: NIFTY futures close above the futures session VWAP for a bullish cross,
  below for a bearish one. The index has no volume, so near-month futures are used.
  Without futures data for the bar the cross is not confirmed (no trade).
* RSI(14) on spot bars: above 50 for bullish, below 50 for bearish.
* MACD(12, 26, 9) histogram on spot bars: above 0 for bullish, below 0 for bearish.
An unconfirmed cross still exits an open opposite trade; it just doesn't open one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from app.services.strategy import indicators as ind
from app.services.strategy import rules as st


@dataclass(frozen=True)
class Strategy:
    key: str
    label: str
    fast: int
    slow: int
    confirm: str | None = None


STRATEGIES = {s.key: s for s in [
    Strategy("ema_9_21", "EMA 9/21", 9, 21),
    Strategy("ema_5_20", "EMA 5/20", 5, 20),
    Strategy("ema_8_21", "EMA 8/21", 8, 21),
    Strategy("ema_20_50", "EMA 20/50", 20, 50),
    Strategy("ema_9_21_vwap", "EMA 9/21 + VWAP", 9, 21, "vwap"),
    Strategy("ema_9_21_rsi", "EMA 9/21 + RSI", 9, 21, "rsi"),
    Strategy("ema_9_21_macd", "EMA 9/21 + MACD", 9, 21, "macd"),
]}
DEFAULT = "ema_9_21"


def warmup_sessions(key: str, tf: int) -> int:
    """Sessions to skip at the start of the data so EMAs and MACD have settled."""
    s = STRATEGIES[key]
    need = 3 * max(s.slow, 26 + 9 if s.confirm == "macd" else 0)
    return max(3, math.ceil(need / math.ceil(375 / tf)))


def futures_bars(fut1m: pd.DataFrame, tf: int) -> pd.DataFrame:
    """Futures close, session VWAP and volume per signal bar, keyed by bar start."""
    if fut1m is None or fut1m.empty:
        return pd.DataFrame(columns=["start", "fut_close", "fut_vwap", "fut_volume"])
    f = fut1m.sort_values("ts").reset_index(drop=True)
    f["vwap"] = ind.session_vwap(f)
    open_ts = f["ts"].dt.normalize() + pd.Timedelta(hours=9, minutes=15)
    mins = (f["ts"] - open_ts).dt.total_seconds() // 60
    f = f[(mins >= 0) & (f["ts"].dt.time < st.SESSION_CLOSE)]
    f["start"] = open_ts.loc[f.index] + pd.to_timedelta((mins.loc[f.index] // tf) * tf, unit="m")
    g = f.groupby("start", sort=True)
    return pd.DataFrame({"fut_close": g["close"].last(), "fut_vwap": g["vwap"].last(),
                         "fut_volume": g["volume"].sum()}).reset_index()


def prepare(spot1m: pd.DataFrame, fut1m: pd.DataFrame | None, tf: int, key: str) -> pd.DataFrame:
    """Signal bars with every indicator the strategies and the signal engine use."""
    s = STRATEGIES[key]
    bars = st.resample(spot1m, tf)
    if bars.empty:
        for c in ("fast", "slow", "rsi", "macd_hist", "atr", "fut_close", "fut_vwap", "fut_volume", "bull_ok", "bear_ok"):
            bars[c] = pd.Series(dtype=float)
        return bars
    bars["fast"] = ind.ema(bars["close"], s.fast)
    bars["slow"] = ind.ema(bars["close"], s.slow)
    bars["rsi"] = ind.rsi(bars["close"])
    bars["macd_hist"] = ind.macd(bars["close"])[2]
    bars["atr"] = ind.atr(bars)
    bars = bars.merge(futures_bars(fut1m, tf), on="start", how="left")
    if s.confirm == "vwap":
        bars["bull_ok"] = bars["fut_close"] > bars["fut_vwap"]
        bars["bear_ok"] = bars["fut_close"] < bars["fut_vwap"]
    elif s.confirm == "rsi":
        bars["bull_ok"], bars["bear_ok"] = bars["rsi"] > 50, bars["rsi"] < 50
    elif s.confirm == "macd":
        bars["bull_ok"], bars["bear_ok"] = bars["macd_hist"] > 0, bars["macd_hist"] < 0
    else:
        bars["bull_ok"] = bars["bear_ok"] = True
    return bars


def legs(bars: pd.DataFrame, trade_days, start, cutoff, key: str):
    s = STRATEGIES[key]
    return st.generate_legs(bars, trade_days, start, cutoff, fast="fast", slow="slow",
                            confirm=s.confirm is not None)

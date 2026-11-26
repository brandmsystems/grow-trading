"""Indicators and trend state on a bar frame (pure). Every value at row i uses rows <= i only, so a later bar never changes an earlier row
(tests check this). The indicators themselves live in `strategy/indicators.py`; nothing is re-implemented here."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.strategy import indicators as ind

EMAS = (20, 50, 100, 200)
SWING_K = 3          # a swing pivot is known only K bars after it formed


def pivots(bars: pd.DataFrame, k: int = SWING_K) -> pd.DataFrame:
    """Confirmed swing highs / lows: `swing_hi` / `swing_lo` hold the latest confirmed pivot price on every row from the bar where it became
    known (K bars after it formed), `piv_hi_idx` / `piv_lo_idx` the row index of that pivot. Never uses a bar after the row."""
    h, l = bars["high"].to_numpy(float), bars["low"].to_numpy(float)
    n = len(bars)
    sh, sl = np.full(n, np.nan), np.full(n, np.nan)
    ih, il = np.full(n, np.nan), np.full(n, np.nan)
    ph = pl = np.nan
    pih = pil = np.nan
    for i in range(n):
        j = i - k                                           # the candidate pivot bar; its k right-hand neighbours are all <= i
        if j - k >= 0:
            if h[j] == h[j - k:j + k + 1].max() and h[j] > h[j - k:j].max():
                ph, pih = h[j], j
            if l[j] == l[j - k:j + k + 1].min() and l[j] < l[j - k:j].min():
                pl, pil = l[j], j
        sh[i], sl[i], ih[i], il[i] = ph, pl, pih, pil
    return pd.DataFrame({"swing_hi": sh, "swing_lo": sl, "piv_hi_idx": ih, "piv_lo_idx": il}, index=bars.index)


def trend_of(close: pd.Series, e20: pd.Series, e50: pd.Series, e100: pd.Series, e200: pd.Series) -> pd.Series:
    """+2 / +1 / 0 / -1 / -2: EMA 20 > 50 > 100 and the close above EMA 50 is a trend (+1); also above EMA 200 and EMA 50 > 200 it is strong (+2).
    A missing EMA (not enough bars) never counts as agreement."""
    up = (e20 > e50) & (e50 > e100) & (close > e50)
    dn = (e20 < e50) & (e50 < e100) & (close < e50)
    strong_up = up & (close > e200) & (e50 > e200)
    strong_dn = dn & (close < e200) & (e50 < e200)
    return pd.Series(np.select([strong_up, up, strong_dn, dn], [2, 1, -2, -1], 0), index=close.index)


def add_studies(bars: pd.DataFrame, vol_n: int = 20, brk_n: int = 20, weekly: bool = False) -> pd.DataFrame:
    """The bar frame plus: ema20/50/100/200, rsi, macd/macd_sig/macd_hist, plus_di/minus_di/adx, atr, atr_pct, vol_ratio, hh/ll (the previous
    `brk_n` bars' high / low, for breakouts), swing pivots and `trend`."""
    b = bars.reset_index(drop=True).copy()
    for n in EMAS:
        b[f"ema{n}"] = ind.ema(b["close"], n).where(pd.Series(np.arange(len(b)) >= n - 1, index=b.index))   # warm-up rows are NaN, not a guess
    b["rsi"] = ind.rsi(b["close"], 14)
    b["macd"], b["macd_sig"], b["macd_hist"] = ind.macd(b["close"])
    b = pd.concat([b, ind.adx(b)], axis=1)
    b["atr"] = ind.atr(b)
    b["atr_pct"] = 100 * b["atr"] / b["close"]
    vol = b["volume"].where(b["volume"] > 0)
    b["vol_ratio"] = vol / vol.shift(1).rolling(vol_n, min_periods=max(5, vol_n // 2)).mean()       # this bar against the previous bars only
    b["hh"] = b["high"].shift(1).rolling(brk_n, min_periods=brk_n).max()
    b["ll"] = b["low"].shift(1).rolling(brk_n, min_periods=brk_n).min()
    b = pd.concat([b, pivots(b)], axis=1)
    b["trend"] = trend_of(b["close"], b["ema20"], b["ema50"], b["ema100"], b["ema200"])
    if weekly:
        # EMA 100 / 200 on weekly bars need 2-4 years of weekly history (the stored data is five years), so the weekly trend uses EMA 10 / 20 / 50
        # (the same rule one step shorter); a strong weekly trend (+2) additionally needs the close above the weekly EMA 50 and EMA 10 > 20 > 50 with a rising EMA 20.
        e10 = ind.ema(b["close"], 10).where(pd.Series(np.arange(len(b)) >= 9, index=b.index))
        b["ema10"] = e10
        t = trend_of(b["close"], e10, b["ema20"], b["ema50"], pd.Series(np.nan, index=b.index))
        rising = b["ema20"] > b["ema20"].shift(4)
        b["trend"] = pd.Series(np.where((t == 1) & rising & (b["close"] > b["ema50"]), 2, np.where((t == -1) & ~rising & (b["close"] < b["ema50"]), -2, t)), index=b.index)
    return b

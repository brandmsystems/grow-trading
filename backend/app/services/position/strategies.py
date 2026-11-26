"""The nine position-trading strategies (pure, causal). Each reads the daily frame prepared by `prepare` and returns +1 (bullish: BUY CE),
-1 (bearish: BUY PE) or 0 on each *completed* daily bar; the decision is made at that bar's close. A row never depends on a later row.

The rules and every default parameter are fixed starting values chosen before any result was looked at (the backtest does not tune them).
Each strategy can be enabled, disabled and configured on its own (`params` below, stored by `settings.py`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.position import bars as pbars
from app.services.position import studies


def prepare(spot: pd.DataFrame, fut: pd.DataFrame | None = None, asof=None) -> pd.DataFrame:
    """The daily frame with indicators, plus the weekly and 4-hour state as of each daily close (only bars already closed then).
    `asof` limits the data to what was known at that moment (the live path); the backtest passes everything and reads row by row."""
    tfs = pbars.build(spot, fut)
    wk = tfs["W"]
    if asof is None and len(wk) and wk["last"].iloc[-1].weekday() < 4:
        wk = wk.iloc[:-1]                                    # the running week is not finished: never used as a weekly bar
    w = studies.add_studies(pbars.completed(tfs["W"], asof, "W") if asof is not None else wk, brk_n=10, weekly=True)
    d = studies.add_studies(pbars.completed(tfs["D"], asof, "D") if asof is not None else tfs["D"][tfs["D"]["n"] >= 375])
    h4 = studies.add_studies(pbars.completed(tfs["4h"], asof, "4h") if asof is not None else tfs["4h"])
    h1 = studies.add_studies(pbars.completed(tfs["1h"], asof, "1h") if asof is not None else tfs["1h"])
    d = pbars.asof_merge(d, w, ["trend", "rsi", "adx", "macd_hist", "close", "ema20", "ema50"], "_w")
    d = pbars.asof_merge(d, h4, ["trend", "rsi", "macd_hist"], "_4h")
    d = pbars.asof_merge(d, h1, ["trend"], "_1h")
    return d.reset_index(drop=True)


def _fresh(bull: pd.Series, bear: pd.Series) -> pd.Series:
    """+1 / -1 on the bar where a condition becomes true (it was false on the previous bar); both true or neither gives 0."""
    bull, bear = bull.fillna(False).astype(bool), bear.fillna(False).astype(bool)
    up = bull & ~bear & ~bull.shift(1, fill_value=False)
    dn = bear & ~bull & ~bear.shift(1, fill_value=False)
    return pd.Series(np.where(up, 1, np.where(dn, -1, 0)), index=bull.index)


def _weekly_ok(d: pd.DataFrame, direction: int) -> pd.Series:
    """The weekly trend is not against `direction` (a missing weekly trend is not 'ok': it needs the data)."""
    return (d["trend_w"] * direction >= 0) & d["trend_w"].notna()


# ---------------------------------------------------------------- strategies
def daily_ema_trend(d, p):
    """Daily EMA trend-following: a trend (EMA 20 > 50 > 100, close above EMA 50) that starts on this bar, with the weekly trend not against."""
    return _fresh((d["trend"] >= 1) & _weekly_ok(d, 1), (d["trend"] <= -1) & _weekly_ok(d, -1))


def weekly_pullback(d, p):
    """Weekly trend + daily pullback: weekly trend agrees; in the last `lookback` bars the low came within `atr_touch` ATR of the daily EMA 20 and
    RSI dipped to `rsi_dip` or lower (higher for bearish); today closes back beyond the EMA 20 in the trend's colour."""
    lb, touch, dip = int(p["lookback"]), p["atr_touch"], p["rsi_dip"]
    near_up = (d["low"] <= d["ema20"] + touch * d["atr"]).rolling(lb, min_periods=1).max().astype(bool)
    near_dn = (d["high"] >= d["ema20"] - touch * d["atr"]).rolling(lb, min_periods=1).max().astype(bool)
    rsi_lo = (d["rsi"] <= dip).rolling(lb, min_periods=1).max().astype(bool)
    rsi_hi = (d["rsi"] >= 100 - dip).rolling(lb, min_periods=1).max().astype(bool)
    bull = (d["trend_w"] >= 1) & near_up & rsi_lo & (d["close"] > d["ema20"]) & (d["close"] > d["open"])
    bear = (d["trend_w"] <= -1) & near_dn & rsi_hi & (d["close"] < d["ema20"]) & (d["close"] < d["open"])
    return _fresh(bull, bear)


def _break_levels(d, side: int, window: int):
    """For each bar the most recent break level within `window` bars: the prior-N-bar high (side +1) / low (-1) at the bar that closed through it."""
    broke = (d["close"] > d["hh"]) if side > 0 else (d["close"] < d["ll"])
    level = d["hh"].where(broke) if side > 0 else d["ll"].where(broke)
    age = (~broke).astype(int).groupby(broke.cumsum()).cumsum()
    lv = level.ffill()
    return lv.where(age <= window), broke


def breakout_retest(d, p):
    """Breakout and retest: a close through the prior `brk` high / low, then within `window` bars a retest of that level (within `atr_touch` ATR)
    that holds, closing back in the breakout's direction on a candle of that colour. Needs the weekly trend not against."""
    w, touch = int(p["window"]), p["atr_touch"]
    lu, bu = _break_levels(d, 1, w)
    ld, bd = _break_levels(d, -1, w)
    retest_up = (~bu) & lu.notna() & (d["low"] <= lu + touch * d["atr"]) & (d["close"] > lu) & (d["close"] > d["open"])
    retest_dn = (~bd) & ld.notna() & (d["high"] >= ld - touch * d["atr"]) & (d["close"] < ld) & (d["close"] < d["open"])
    return _fresh(retest_up & _weekly_ok(d, 1), retest_dn & _weekly_ok(d, -1))


def sr_reversal(d, p):
    """Support / resistance reversal: the low (high) came within `atr_touch` ATR of the last confirmed swing low (high) and the bar closes back
    beyond it with the reversal candle's colour and beyond the previous bar's close; the weekly trend must not be against."""
    t = p["atr_touch"]
    bull = (d["low"] <= d["swing_lo"] + t * d["atr"]) & (d["close"] > d["swing_lo"]) & (d["close"] > d["open"]) & (d["close"] > d["close"].shift(1))
    bear = (d["high"] >= d["swing_hi"] - t * d["atr"]) & (d["close"] < d["swing_hi"]) & (d["close"] < d["open"]) & (d["close"] < d["close"].shift(1))
    return _fresh(bull & _weekly_ok(d, 1), bear & _weekly_ok(d, -1))


def rsi_divergence(d, p):
    """RSI divergence with trend confirmation: price makes a lower low while RSI makes a higher low (bullish; mirrored for bearish) between the two
    latest confirmed pivots, and the bar closes back above (below) the daily EMA 20 within `window` bars of the pivot being confirmed."""
    n = len(d)
    out = np.zeros(n, dtype=int)
    lo, hi = d["low"].to_numpy(float), d["high"].to_numpy(float)
    rsi = d["rsi"].to_numpy(float)
    il, ih = d["piv_lo_idx"].to_numpy(float), d["piv_hi_idx"].to_numpy(float)
    c, e20 = d["close"].to_numpy(float), d["ema20"].to_numpy(float)
    lows, highs = [], []
    seen_l = seen_h = -1
    wd = int(p["window"])
    last_bull = last_bear = -10 ** 9
    for i in range(n):
        if not np.isnan(il[i]) and int(il[i]) != seen_l:
            seen_l = int(il[i]); lows.append((seen_l, lo[seen_l], rsi[seen_l], i))
        if not np.isnan(ih[i]) and int(ih[i]) != seen_h:
            seen_h = int(ih[i]); highs.append((seen_h, hi[seen_h], rsi[seen_h], i))
        if len(lows) >= 2:
            (j0, p0, r0, _), (j1, p1, r1, k1) = lows[-2], lows[-1]
            if p1 < p0 and r1 > r0 and i - k1 <= wd and c[i] > e20[i] and (i - last_bull) > wd:
                out[i], last_bull = 1, i
        if len(highs) >= 2:
            (j0, p0, r0, _), (j1, p1, r1, k1) = highs[-2], highs[-1]
            if p1 > p0 and r1 < r0 and i - k1 <= wd and c[i] < e20[i] and (i - last_bear) > wd and out[i] == 0:
                out[i], last_bear = -1, i
    s = pd.Series(out, index=d.index)
    return s.where(((s > 0) & _weekly_ok(d, 1)) | ((s < 0) & _weekly_ok(d, -1)), 0)


def macd_momentum(d, p):
    """MACD momentum: the histogram turns positive (negative) with the MACD line on the same side of zero and the close beyond the daily EMA 50;
    the weekly trend must not be against."""
    bull = (d["macd_hist"] > 0) & (d["macd"] > 0) & (d["close"] > d["ema50"])
    bear = (d["macd_hist"] < 0) & (d["macd"] < 0) & (d["close"] < d["ema50"])
    return _fresh(bull & _weekly_ok(d, 1), bear & _weekly_ok(d, -1))


def adx_trend(d, p):
    """ADX trend strength: ADX at or above `adx_min` and rising, +DI over -DI (the mirror for bearish) and the close beyond the daily EMA 50."""
    t = p["adx_min"]
    rising = d["adx"] > d["adx"].shift(1)
    bull = (d["adx"] >= t) & rising & (d["plus_di"] > d["minus_di"]) & (d["close"] > d["ema50"])
    bear = (d["adx"] >= t) & rising & (d["minus_di"] > d["plus_di"]) & (d["close"] < d["ema50"])
    return _fresh(bull & _weekly_ok(d, 1), bear & _weekly_ok(d, -1))


def volume_breakout(d, p):
    """Volume-confirmed breakout: the close goes through the prior `brk` high / low on at least `vol_x` times the average futures volume of the
    previous bars. A bar without volume data never qualifies."""
    vx = p["vol_x"]
    bull = (d["close"] > d["hh"]) & (d["vol_ratio"] >= vx)
    bear = (d["close"] < d["ll"]) & (d["vol_ratio"] >= vx)
    return _fresh(bull & _weekly_ok(d, 1), bear & _weekly_ok(d, -1))


def mtf_confluence(d, p):
    """Multi-timeframe confluence: weekly, daily and 4-hour trends all agree, daily RSI is between 50 and `rsi_max` (the mirror below 50), the MACD
    histogram has the same sign and ADX is at least `adx_min`. Fires on the bar where all of that first holds."""
    t, rmax = p["adx_min"], p["rsi_max"]
    bull = (d["trend_w"] >= 1) & (d["trend"] >= 1) & (d["trend_4h"] >= 1) & d["rsi"].between(50, rmax) & (d["macd_hist"] > 0) & (d["adx"] >= t)
    bear = (d["trend_w"] <= -1) & (d["trend"] <= -1) & (d["trend_4h"] <= -1) & d["rsi"].between(100 - rmax, 50) & (d["macd_hist"] < 0) & (d["adx"] >= t)
    return _fresh(bull, bear)


STRATEGIES: dict[str, dict] = {
    "daily_ema_trend": {"label": "Daily EMA trend-following", "fn": daily_ema_trend, "params": {}},
    "weekly_pullback": {"label": "Weekly trend + daily pullback", "fn": weekly_pullback, "params": {"lookback": 5, "atr_touch": 0.5, "rsi_dip": 45.0}},
    "breakout_retest": {"label": "Breakout and retest", "fn": breakout_retest, "params": {"window": 10, "atr_touch": 0.5}},
    "sr_reversal": {"label": "Support / resistance reversal", "fn": sr_reversal, "params": {"atr_touch": 0.5}},
    "rsi_divergence": {"label": "RSI divergence + trend confirmation", "fn": rsi_divergence, "params": {"window": 5}},
    "macd_momentum": {"label": "MACD momentum confirmation", "fn": macd_momentum, "params": {}},
    "adx_trend": {"label": "ADX trend strength", "fn": adx_trend, "params": {"adx_min": 25.0}},
    "volume_breakout": {"label": "Volume-confirmed breakout", "fn": volume_breakout, "params": {"vol_x": 1.5}},
    "mtf_confluence": {"label": "Multi-timeframe confluence", "fn": mtf_confluence, "params": {"adx_min": 20.0, "rsi_max": 70.0}},
}


def signals(d: pd.DataFrame, enabled: dict[str, dict] | None = None) -> pd.DataFrame:
    """A column of +1 / -1 / 0 per strategy. `enabled` maps a strategy key to its params (missing params take the defaults); None = all, defaults."""
    cols = {}
    for k, s in STRATEGIES.items():
        if enabled is not None and k not in enabled:
            continue
        params = {**s["params"], **((enabled or {}).get(k) or {})}
        cols[k] = s["fn"](d, params).astype(int) if len(d) else pd.Series(dtype=int)
    return pd.DataFrame(cols, index=d.index)

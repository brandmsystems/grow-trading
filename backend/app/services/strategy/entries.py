"""Configurable entry methods on closed 5-minute bars, with the 15-minute trend (pure, no I/O).

Each method returns a Series per bar: +1 (buy CE), -1 (buy PE) or 0. A value at bar i uses bars <= i only (rolling
windows, shifts, backward as-of merge of closed 15-minute bars), so a later candle never changes an earlier signal;
`tests/test_entries.py` checks it. A signal is known when its bar closes; the trade fills on the next option candle.

Methods that describe a *state* (trend continuation, EMA stack) fire once, on the bar the state begins, and the
generic cool-down (`COOLDOWN_BARS`) stops a method re-firing every bar. Parameters are the usual textbook values,
fixed before any result was seen; none was fitted.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.strategy import bias

COOLDOWN_BARS = 6                  # a method does not fire again within 6 bars (30 min) of its own last signal

METHODS: dict[str, str] = {
    "cross_9_21": "EMA 9/21 fresh crossover",
    "cross_5_20": "EMA 5/20 fresh crossover",
    "cross_8_21": "EMA 8/21 fresh crossover",
    "cross_9_21_vwap": "EMA 9/21 crossover + VWAP side",
    "continuation_9_21": "EMA 9/21 trend continuation (15m trend agrees)",
    "pullback_9_21": "EMA 9/21 pullback and rejection (15m trend agrees)",
    "stack_20_50_200": "EMA 20/50/200 alignment",
    "rsi_divergence": "RSI divergence + price confirmation",
    "macd_cross": "MACD signal-line crossover",
    "macd_hist_trend": "MACD histogram flip with 15m trend",
    "bb_breakout": "Bollinger breakout with volume",
    "bb_reversal": "Bollinger reversal (back inside the band)",
    "vwap_breakout": "VWAP breakout",
    "vwap_retest": "VWAP retest (15m trend agrees)",
    "sr_breakout": "Previous-day high/low breakout",
    "sr_retest": "Previous-day high/low breakout retest",
    "sr_rejection": "Previous-day high/low rejection",
    "volume_momentum": "Volume-confirmed momentum candle (15m trend agrees)",
    "atr_breakout": "ATR volatility breakout candle",
    "orb": "Opening range breakout (09:15-09:30)",
    "consolidation_breakout": "Consolidation breakout",
    "trend_reversal": "15m trend reversal",
}


def frame(spot1m: pd.DataFrame, fut1m: pd.DataFrame | None) -> pd.DataFrame:
    """Closed 5-minute bars with indicators, the latest closed 15-minute trend and the volume ratio."""
    b = bias.tf_bars(spot1m, fut1m, 5)
    if b.empty:
        return b
    b15 = bias.tf_bars(spot1m, fut1m, 15)
    if not b15.empty:
        t = np.where((b15["ema20"] > b15["ema50"]) & (b15["close"] > b15["ema50"]), 1,
                     np.where((b15["ema20"] < b15["ema50"]) & (b15["close"] < b15["ema50"]), -1, 0))
        h = pd.DataFrame({"close_ts": b15["close_ts"], "trend15": t}).sort_values("close_ts")
        b = pd.merge_asof(b.sort_values("close_ts"), h, on="close_ts", direction="backward")
    else:
        b["trend15"] = 0
    b["trend15"] = b["trend15"].fillna(0).astype(int)
    b["vol_ratio"] = b["fut_volume"] / b["vol_avg20"].where(b["vol_avg20"] > 0)
    b["body"] = (b["close"] - b["open"]).abs()
    return b.reset_index(drop=True)


def _flip(sign: pd.Series) -> pd.Series:
    """+1/-1 on the bar where the sign changes to that value (zeros keep the previous sign)."""
    s = sign.replace(0, np.nan).ffill()
    return (s.where(s != s.shift(1))).where(s.shift(1).notna()).fillna(0).astype(int)


def _begin(state_up: pd.Series, state_dn: pd.Series) -> pd.Series:
    up = state_up.fillna(False).astype(bool)
    dn = state_dn.fillna(False).astype(bool)
    return ((up & ~up.shift(1, fill_value=False)).astype(int) - (dn & ~dn.shift(1, fill_value=False)).astype(int))


def _cooldown(sig: pd.Series, day: pd.Series, bars: int = COOLDOWN_BARS) -> pd.Series:
    """Drop a signal that comes within `bars` bars of the same method's previous signal on the same day."""
    out = np.zeros(len(sig), dtype=int)
    last, last_day = -10**9, None
    v, dd = sig.to_numpy(), day.to_numpy()
    for i in range(len(v)):
        if v[i] != 0 and not (dd[i] == last_day and i - last <= bars):
            out[i] = v[i]
            last, last_day = i, dd[i]
    return pd.Series(out, index=sig.index)


def signals(f: pd.DataFrame, cooldown: bool = True) -> pd.DataFrame:
    """One column per method (+1 / 0 / -1) for every closed bar of `frame`."""
    if f.empty:
        return pd.DataFrame(columns=list(METHODS))
    c, o, h, lo, a = f["close"], f["open"], f["high"], f["low"], f["atr"]
    t15 = f["trend15"]
    up_c, dn_c = c > o, c < o
    out: dict[str, pd.Series] = {}

    def cross(fast: str, slow: str) -> pd.Series:
        return _flip(np.sign(f[fast] - f[slow]))

    out["cross_9_21"] = cross("ema9", "ema21")
    out["cross_5_20"] = cross("ema5", "ema20")
    out["cross_8_21"] = cross("ema8", "ema21")
    vside = np.sign(f["fut_close"] - f["fut_vwap"]).fillna(0)
    out["cross_9_21_vwap"] = out["cross_9_21"].where(out["cross_9_21"] == vside, 0)

    bull_tr = (f["ema9"] > f["ema21"]) & (f["ema21"] > f["ema50"])
    bear_tr = (f["ema9"] < f["ema21"]) & (f["ema21"] < f["ema50"])
    out["continuation_9_21"] = _begin(bull_tr & (t15 > 0) & (c > f["ema9"]), bear_tr & (t15 < 0) & (c < f["ema9"]))
    pull_up = bull_tr & (t15 > 0) & (lo <= f["ema21"] + 0.25 * a) & (c > f["ema9"]) & up_c
    pull_dn = bear_tr & (t15 < 0) & (h >= f["ema21"] - 0.25 * a) & (c < f["ema9"]) & dn_c
    out["pullback_9_21"] = pull_up.astype(int) - pull_dn.astype(int)
    out["stack_20_50_200"] = _begin((f["ema20"] > f["ema50"]) & (f["ema50"] > f["ema200"]) & (c > f["ema20"]),
                                    (f["ema20"] < f["ema50"]) & (f["ema50"] < f["ema200"]) & (c < f["ema20"]))

    div = bias.divergence(f)
    new_div = div.notna() & (div.shift(1).isna() | (div != div.shift(1)))
    d_up = new_div & (div > 0) & up_c & (c > h.shift(1))
    d_dn = new_div & (div < 0) & dn_c & (c < lo.shift(1))
    # the divergence is known 3 bars after its pivot; the confirmation candle may come a bar or two later
    d_up = d_up | (div.shift(1).gt(0) & up_c & (c > h.shift(1)) & ~new_div & div.shift(2).isna())
    d_dn = d_dn | (div.shift(1).lt(0) & dn_c & (c < lo.shift(1)) & ~new_div & div.shift(2).isna())
    out["rsi_divergence"] = d_up.astype(int) - d_dn.astype(int)

    out["macd_cross"] = _flip(np.sign(f["macd"] - f["macd_sig"]))
    hs = _flip(np.sign(f["macd_hist"]))
    out["macd_hist_trend"] = hs.where(hs == t15, 0)

    vol_ok = f["vol_ratio"].isna() | (f["vol_ratio"] >= 1.2)
    out["bb_breakout"] = ((c > f["bb_up"]) & (c.shift(1) <= f["bb_up"].shift(1)) & vol_ok).astype(int) \
        - ((c < f["bb_lo"]) & (c.shift(1) >= f["bb_lo"].shift(1)) & vol_ok).astype(int)
    out["bb_reversal"] = ((c.shift(1) < f["bb_lo"].shift(1)) & (c > f["bb_lo"]) & up_c).astype(int) \
        - ((c.shift(1) > f["bb_up"].shift(1)) & (c < f["bb_up"]) & dn_c).astype(int)

    out["vwap_breakout"] = _flip(vside)
    dist = (f["fut_close"] - f["fut_vwap"])
    far_up, far_dn = dist.shift(1).rolling(6).max() > 0.75 * a, dist.shift(1).rolling(6).min() < -0.75 * a
    near = dist.abs() <= 0.25 * a
    out["vwap_retest"] = (far_up & near & (dist >= -0.25 * a) & up_c & (t15 > 0)).astype(int) \
        - (far_dn & near & (dist <= 0.25 * a) & dn_c & (t15 < 0)).astype(int)

    pdh, pdl = f["pdh"], f["pdl"]
    out["sr_breakout"] = ((c > pdh) & (c.shift(1) <= pdh)).astype(int) - ((c < pdl) & (c.shift(1) >= pdl)).astype(int)
    broke_up = (c.shift(1).rolling(12).max() > pdh + 0.3 * a)
    broke_dn = (c.shift(1).rolling(12).min() < pdl - 0.3 * a)
    out["sr_retest"] = (broke_up & (lo <= pdh + 0.2 * a) & (c > pdh) & up_c).astype(int) \
        - (broke_dn & (h >= pdl - 0.2 * a) & (c < pdl) & dn_c).astype(int)
    out["sr_rejection"] = ((lo <= pdl + 0.1 * a) & (c > pdl) & up_c & (c > pdl + 0.2 * a)).astype(int) \
        - ((h >= pdh - 0.1 * a) & (c < pdh) & dn_c & (c < pdh - 0.2 * a)).astype(int)

    cd = np.sign(c - o).astype(int)
    out["volume_momentum"] = cd.where((f["vol_ratio"] >= 1.8) & (f["body"] >= 0.6 * a) & (cd == t15), 0)
    rng = h - lo
    strong_up = (rng >= 1.5 * a) & ((c - lo) >= 0.75 * rng)
    strong_dn = (rng >= 1.5 * a) & ((h - c) >= 0.75 * rng)
    out["atr_breakout"] = strong_up.astype(int) - strong_dn.astype(int)

    first3 = f.groupby("day").cumcount() < 3
    orb_hi = h.where(first3).groupby(f["day"]).transform("max")
    orb_lo = lo.where(first3).groupby(f["day"]).transform("min")
    after = ~first3
    orb_up, orb_dn = after & (c > orb_hi), after & (c < orb_lo)
    first_dn = orb_dn & (orb_dn.groupby(f["day"]).cumsum() == 1)
    first_up = orb_up & (orb_up.groupby(f["day"]).cumsum() == 1)
    out["orb"] = first_up.astype(int) - first_dn.astype(int)

    rhi, rlo = h.shift(1).rolling(10).max(), lo.shift(1).rolling(10).min()
    tight = (rhi - rlo) <= 2.5 * a.shift(1)
    out["consolidation_breakout"] = ((c > rhi) & tight).astype(int) - ((c < rlo) & tight).astype(int)

    out["trend_reversal"] = _flip(t15)

    res = pd.DataFrame({k: pd.Series(v, index=f.index).fillna(0).astype(int) for k, v in out.items()})[list(METHODS)]
    res = res.where(f["atr"].notna(), 0)
    if cooldown:
        for k in res:
            res[k] = _cooldown(res[k], f["day"])
    return res

"""The position-trading decision score, 0-100 (pure). A count of sound conditions met, **not a probability of winning**: calibration against
out-of-sample results is a separate step (`backtest.py`) and is reported only where the data supports it.

| Component | Max | Source |
|---|---|---|
| Weekly trend | 15 | weekly EMA 20/50/100(/200) trend agrees with the trade |
| Daily trend | 15 | daily EMA trend agrees |
| 4-hour confirmation | 10 | 4-hour EMA trend agrees |
| Momentum | 15 | RSI 5 + MACD histogram 5 + ADX with +DI/-DI 5 |
| Volume | 10 | futures volume against its previous-20-bar average |
| Support / resistance | 10 | room to the nearest opposing level, in ATRs |
| Volatility | 10 | daily ATR % of price inside a workable band (India VIX is live context only: no stored history) |
| Option contract quality | 10 | added after contract selection (liquidity, theta, expiry, gap risk) |
| Risk / reward | 5 | added after the levels are set: target gain over stop loss, after costs |

A missing value earns 0 points and is flagged. Decisions: STRONG BUY CE/PE from `STRONG` points, BUY CE/PE from `BUY`, otherwise HOLD; NO TRADE when
a gate fails (missing data, weekly trend strongly against, no usable contract). Fixed starting values, never tuned to a result.
"""
from __future__ import annotations

import math

import pandas as pd

STRONG, BUY = 75.0, 60.0
ATR_PCT_BAND = (0.5, 1.8)         # daily ATR as % of price: below it there is no movement to pay for, above it the premium is expensive and gappy
MIN_DAILY_BARS = 200               # EMA 200 needs 200 daily bars

COMPONENTS = (("weekly", "Weekly trend", 15), ("daily", "Daily trend", 15), ("h4", "4-hour confirmation", 10), ("momentum", "Momentum", 15),
              ("volume", "Volume", 10), ("sr", "Support / resistance", 10), ("volatility", "Volatility", 10), ("contract", "Option contract quality", 10),
              ("risk_reward", "Risk / reward", 5))
LATE_MAX = 15                      # contract quality 10 + risk/reward 5 are added after selection


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _c(key: str, label: str, mx: float, pts, note: str) -> dict:
    return {"key": key, "label": label, "max": mx, "points": round(0.0 if pts is None else max(0.0, min(mx, pts)), 1), "available": pts is not None,
            "note": note + ("" if pts is not None else " (not available: 0 points)")}


def _trend_points(t, d: int, mx: float, name: str) -> dict:
    t = _num(t)
    if t is None:
        return _c(name, "", mx, None, "no trend yet (not enough bars)")
    a = t * d
    pts = mx if a >= 2 else 0.75 * mx if a >= 1 else 0.25 * mx if a == 0 else 0.0
    word = {2: "strong trend with the trade", 1: "trend with the trade", 0: "no trend (flat or mixed)", -1: "trend against the trade", -2: "strong trend against the trade"}[int(max(-2, min(2, a)))]
    return _c(name, "", mx, pts, word)


def components(r: pd.Series, d: int) -> list[dict]:
    """The candle-derived components for a trade in direction d (+1 BUY CE / -1 BUY PE) from the daily row `r` of `strategies.prepare`."""
    out = []
    for key, label, mx, col in (("weekly", "Weekly trend", 15, "trend_w"), ("daily", "Daily trend", 15, "trend"), ("h4", "4-hour confirmation", 10, "trend_4h")):
        c = _trend_points(r.get(col), d, mx, key)
        c["label"] = label
        out.append(c)
    rsi, mh, adx, pdi, mdi = (_num(r.get(k)) for k in ("rsi", "macd_hist", "adx", "plus_di", "minus_di"))
    parts, notes = [], []
    if rsi is not None:
        a = (rsi - 50) * d
        parts.append(5 if 5 <= a <= 25 else 2 if a > 25 else 1 if 0 < a < 5 else 0)
        notes.append(f"RSI {rsi:.0f}" + (" (stretched)" if a > 25 else ""))
    if mh is not None:
        parts.append(5 if mh * d > 0 else 0)
        notes.append(f"MACD histogram {'with' if mh * d > 0 else 'against'} the trade")
    if adx is not None and pdi is not None and mdi is not None:
        aligned = (pdi - mdi) * d > 0
        parts.append(5 if (adx >= 25 and aligned) else 3 if (adx >= 20 and aligned) else 1 if aligned else 0)
        notes.append(f"ADX {adx:.0f} {'with' if aligned else 'against'} the trade")
    out.append(_c("momentum", "Momentum", 15, sum(parts) if parts else None, ", ".join(notes) or "RSI, MACD and ADX unavailable"))
    vr = _num(r.get("vol_ratio"))
    out.append(_c("volume", "Volume", 10, None if vr is None else 10 * min(1.0, max(0.0, (vr - 0.8) / 0.7)),
                  "futures volume " + ("n/a" if vr is None else f"{vr:.2f}x the previous 20-bar average (full at 1.5x)")))
    close, atr = _num(r.get("close")), _num(r.get("atr"))
    levels = [_num(r.get("swing_hi")), _num(r.get("hh"))] if d > 0 else [_num(r.get("swing_lo")), _num(r.get("ll"))]
    ahead = [abs(x - close) for x in levels if x is not None and close is not None and (x - close) * d > 0]
    if close is None or not atr:
        out.append(_c("sr", "Support / resistance", 10, None, "levels or ATR unavailable"))
    elif not ahead:
        out.append(_c("sr", "Support / resistance", 10, 10, "no opposing level ahead (open space)"))
    else:
        room = min(ahead) / atr
        out.append(_c("sr", "Support / resistance", 10, 10 * min(1.0, room / 2.0), f"{room:.1f} ATR of room to the next opposing level (full at 2.0)"))
    ap = _num(r.get("atr_pct"))
    if ap is None:
        out.append(_c("volatility", "Volatility", 10, None, "ATR unavailable"))
    else:
        lo, hi = ATR_PCT_BAND
        pts = 10 if lo <= ap <= hi else 10 * max(0.0, 1 - (lo - ap) / lo) if ap < lo else 10 * max(0.0, 1 - (ap - hi) / hi)
        out.append(_c("volatility", "Volatility", 10, pts, f"daily ATR {ap:.2f}% of price (workable {lo:g}-{hi:g}%); India VIX is shown as live context, no history is stored"))
    return out


def total(comps: list[dict]) -> float:
    return round(sum(c["points"] for c in comps), 1)


def decide(direction: int, score: float, gates: list[str], buy: float = BUY) -> tuple[str, str]:
    """(decision label, why). `gates` are reasons the trade is not allowed (each one makes it NO TRADE)."""
    if gates:
        return "NO TRADE", "; ".join(gates)
    if direction == 0:
        return "HOLD", "no strategy has a valid setup"
    side = "CE" if direction > 0 else "PE"
    if score >= max(STRONG, buy):
        return f"STRONG BUY {side}", f"score {score:g} of 100 is at least {max(STRONG, buy):g}"
    if score >= buy:
        return f"BUY {side}", f"score {score:g} of 100 is at least {buy:g}"
    return "HOLD", f"score {score:g} of 100 is below {buy:g}"

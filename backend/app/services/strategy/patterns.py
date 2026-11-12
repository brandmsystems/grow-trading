"""Candlestick patterns on CLOSED bars only (the bar still forming is never analysed).

Each pattern is fixed at the bar that completes it; later bars only decide its status
(confirmed / not confirmed), so a detection never moves or disappears (no repainting).
Patterns are context for the 9/21 strategy and never change its signal.

Definitions (body = |close - open|, range = high - low, avg body = mean body of the 10 prior bars):
* Doji: body <= 10% of range.
* Hammer: lower wick >= 2 x body, upper wick <= 0.5 x body, after a decline (close below the close 3 bars earlier).
* Shooting star: upper wick >= 2 x body, lower wick <= 0.5 x body, after a rise.
* Bullish / bearish engulfing: the bar's body covers the previous opposite-colour body.
* Morning / evening star: a long bar against the move (body >= avg), a small bar (body <= 30% of it),
  then a bar closing past the midpoint of the first.
* Strong bullish / bearish candle: body >= 1.5 x avg body and the close in the top / bottom 20% of the range.
* Breakout / breakdown: close above the highest high / below the lowest low of the previous 20 bars.
Status: confirmed when the next closed bar closes beyond the pattern bar's close in its direction;
"awaiting confirmation" while the pattern bar is the latest closed bar; doji are neutral.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOOKBACK_BODY = 10
BREAK_N = 20


def _num(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x) else round(float(x), 2)


def detect(bars: pd.DataFrame, now=None) -> list[dict]:
    """bars: closed signal bars (start, close_ts, open, high, low, close + optional indicator columns)."""
    if now is not None:
        bars = bars[bars["close_ts"] <= pd.Timestamp(now)]
    b = bars.reset_index(drop=True)
    if len(b) < 2:
        return []
    o, h, l, c = (b[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    body = np.abs(c - o)
    rng = h - l
    up_w = h - np.maximum(o, c)
    lo_w = np.minimum(o, c) - l
    avg = pd.Series(body).shift(1).rolling(LOOKBACK_BODY, min_periods=3).mean().to_numpy()
    hh = pd.Series(h).shift(1).rolling(BREAK_N, min_periods=BREAK_N).max().to_numpy()
    ll = pd.Series(l).shift(1).rolling(BREAK_N, min_periods=BREAK_N).min().to_numpy()
    out = []

    def add(i, name, bias, why):
        out.append({"i": i, "name": name, "bias": bias, "why": why})

    for i in range(len(b)):
        if rng[i] <= 0:
            continue
        bull, bear = c[i] > o[i], c[i] < o[i]
        declined = i >= 3 and c[i - 1] < c[i - 3]
        rose = i >= 3 and c[i - 1] > c[i - 3]
        if body[i] <= 0.1 * rng[i]:
            add(i, "Doji", "neutral", f"body {body[i]:.2f} is ≤10% of the {rng[i]:.2f} range")
        elif lo_w[i] >= 2 * body[i] and up_w[i] <= 0.5 * body[i] and declined:
            add(i, "Hammer", "bullish", f"lower wick {lo_w[i]:.2f} ≥ 2× body {body[i]:.2f} after a decline")
        elif up_w[i] >= 2 * body[i] and lo_w[i] <= 0.5 * body[i] and rose:
            add(i, "Shooting star", "bearish", f"upper wick {up_w[i]:.2f} ≥ 2× body {body[i]:.2f} after a rise")
        if i >= 1:
            pb, pr = c[i - 1] > o[i - 1], c[i - 1] < o[i - 1]
            if bull and pr and o[i] <= c[i - 1] and c[i] >= o[i - 1] and body[i] > body[i - 1]:
                add(i, "Bullish engulfing", "bullish", f"body {o[i]:.2f}→{c[i]:.2f} covers the previous red body")
            if bear and pb and o[i] >= c[i - 1] and c[i] <= o[i - 1] and body[i] > body[i - 1]:
                add(i, "Bearish engulfing", "bearish", f"body {o[i]:.2f}→{c[i]:.2f} covers the previous green body")
        if i >= 2 and not np.isnan(avg[i - 2]):
            a, m = i - 2, i - 1
            if c[a] < o[a] and body[a] >= avg[a] and body[m] <= 0.3 * body[a] and bull and c[i] > (o[a] + c[a]) / 2:
                add(i, "Morning star", "bullish", f"long red bar, small bar, then a close {c[i]:.2f} above the first bar's midpoint")
            if c[a] > o[a] and body[a] >= avg[a] and body[m] <= 0.3 * body[a] and bear and c[i] < (o[a] + c[a]) / 2:
                add(i, "Evening star", "bearish", f"long green bar, small bar, then a close {c[i]:.2f} below the first bar's midpoint")
        if not np.isnan(avg[i]) and avg[i] > 0 and body[i] >= 1.5 * avg[i]:
            if bull and c[i] >= h[i] - 0.2 * rng[i]:
                add(i, "Strong bullish candle", "bullish", f"body {body[i]:.2f} = {body[i] / avg[i]:.1f}× average, close near the high")
            if bear and c[i] <= l[i] + 0.2 * rng[i]:
                add(i, "Strong bearish candle", "bearish", f"body {body[i]:.2f} = {body[i] / avg[i]:.1f}× average, close near the low")
        if not np.isnan(hh[i]) and c[i] > hh[i]:
            add(i, "Breakout", "bullish", f"close {c[i]:.2f} above the {BREAK_N}-bar high {hh[i]:.2f}")
        if not np.isnan(ll[i]) and c[i] < ll[i]:
            add(i, "Breakdown", "bearish", f"close {c[i]:.2f} below the {BREAK_N}-bar low {ll[i]:.2f}")

    res = []
    last = len(b) - 1
    for p in out:
        i, bias = p["i"], p["bias"]
        if bias == "neutral":
            status = "neutral (indecision)"
        elif i == last:
            status = "awaiting confirmation"
        else:
            nxt = c[i + 1]
            ok = nxt > c[i] if bias == "bullish" else nxt < c[i]
            status = "confirmed" if ok else "not confirmed"
        r = b.iloc[i]
        conf = {}
        if "rsi" in b and pd.notna(r.get("rsi")):
            conf["rsi"] = round(float(r["rsi"]), 1)
        if "fut_close" in b and pd.notna(r.get("fut_vwap")) and pd.notna(r.get("fut_close")):
            conf["vwap"] = "above" if r["fut_close"] > r["fut_vwap"] else "below"
        for f, s in (("fast", "slow"), ("ema9", "ema21")):
            if f in b and s in b and pd.notna(r.get(f)) and pd.notna(r.get(s)):
                conf["ema"] = "9 above 21" if r[f] > r[s] else "9 below 21"
                break
        res.append({"name": p["name"], "bias": bias, "why": p["why"], "status": status,
                    "ts": pd.Timestamp(r["start"]).isoformat(), "close_ts": pd.Timestamp(r["close_ts"]).isoformat(),
                    "o": _num(r["open"]), "h": _num(r["high"]), "l": _num(r["low"]), "c": _num(r["close"]),
                    "confirmation": conf})
    return res


def effect(pattern: dict, action: str) -> str:
    """How a pattern relates to the strategy's current call. It never changes the call."""
    bias = pattern["bias"]
    if bias == "neutral":
        return "Indecision; no effect on the signal."
    if action == "HOLD":
        return f"{bias.capitalize()} context only; the strategy still needs an EMA 9/21 crossover to enter."
    agrees = (bias == "bullish") == (action == "BUY CE")
    return (f"Agrees with {action}." if agrees else f"Conflicts with {action}; the strategy keeps its signal until "
            f"an opposite crossover or 15:00.")

"""Why the dashboard says BUY CE / BUY PE / HOLD, and today's trading plan.

Both read the strategy's own closed bars (strategies.prepare via signals.signal_bars) and the
signal engine's scoring model (signals.Scorer). Nothing here changes a signal: the 9/21
strategy enters on every crossover inside the entry window. VWAP, RSI, MACD, volume and trend
are shown as confirmation context with their actual values.

Indicator conventions (as in strategies.py / signals.py):
* VWAP: NIFTY futures close vs the futures session VWAP (the index itself has no volume).
* RSI(14) on the signal bars: above 50 supports bullish, below 50 bearish; 45-55 is neutral.
* MACD(12, 26, 9) histogram: positive supports bullish, negative bearish.
* Volume: futures bar volume vs the average of the previous 20 bars (>= 1.2x strong, < 0.8x weak).
* Trend: the daily regime (20-day average and its slope, from previous days only).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.services.strategy import rules as st
from app.services.strategy import signals

NEUTRAL_RSI = 5.0


def _v(x, nd=2):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def _row_at(bars: pd.DataFrame, ts: str | None) -> pd.Series | None:
    if bars.empty:
        return None
    if ts:
        m = bars[bars["close_ts"] == pd.Timestamp(ts)]
        if not m.empty:
            return m.iloc[-1]
    return bars.iloc[-1]


def checks(r: pd.Series, d: int, regime) -> list[dict]:
    """Confirmation checks for direction d (+1 bullish, -1 bearish) on one closed bar."""
    out = []
    want = "bullish" if d > 0 else "bearish"

    def st_(x):  # supports / against / neutral from a signed agreement value
        return "supports" if x > 0 else "against" if x < 0 else "neutral"

    fc, fv = r.get("fut_close"), r.get("fut_vwap")
    if pd.notna(fc) and pd.notna(fv):
        gap = fc - fv
        out.append({"key": "vwap", "label": "VWAP", "status": st_(np.sign(gap) * d),
                    "text": f"NIFTY futures {fc:,.2f} is {'above' if gap > 0 else 'below'} the session VWAP {fv:,.2f} ({gap:+.2f})",
                    "values": {"fut_close": _v(fc), "vwap": _v(fv)}})
    else:
        out.append({"key": "vwap", "label": "VWAP", "status": "unavailable", "text": "Futures VWAP unavailable (no futures candles).", "values": {}})
    rsi = r.get("rsi")
    if pd.notna(rsi):
        x = (rsi - 50) * d
        s = "neutral" if abs(rsi - 50) < NEUTRAL_RSI else st_(x)
        out.append({"key": "rsi", "label": "RSI(14)", "status": s,
                    "text": f"RSI {rsi:.1f}: " + ("neutral (45–55)" if s == "neutral" else
                                                   f"{'supports' if s == 'supports' else 'does not support'} {want} momentum"),
                    "values": {"rsi": _v(rsi, 1)}})
    else:
        out.append({"key": "rsi", "label": "RSI(14)", "status": "unavailable", "text": "RSI not available yet.", "values": {}})
    mh = r.get("macd_hist")
    if pd.notna(mh):
        out.append({"key": "macd", "label": "MACD", "status": st_(np.sign(mh) * d),
                    "text": f"MACD histogram {mh:+.2f}: {'confirms' if mh * d > 0 else 'does not confirm'} the {want} move",
                    "values": {"macd_hist": _v(mh)}})
    else:
        out.append({"key": "macd", "label": "MACD", "status": "unavailable", "text": "MACD not available yet.", "values": {}})
    vol, avg = r.get("fut_volume"), r.get("vol_avg20")
    if pd.notna(vol) and pd.notna(avg) and avg > 0:
        ratio = vol / avg
        s = "supports" if ratio >= 1.2 else "against" if ratio < 0.8 else "neutral"
        out.append({"key": "volume", "label": "Volume", "status": s,
                    "text": f"Futures volume {vol:,.0f} = {ratio:.2f}× the 20-bar average ({'strong' if s == 'supports' else 'weak' if s == 'against' else 'normal'})",
                    "values": {"volume": _v(vol, 0), "avg20": _v(avg, 0), "ratio": _v(ratio)}})
    else:
        out.append({"key": "volume", "label": "Volume", "status": "unavailable", "text": "Futures volume unavailable.", "values": {}})
    if regime is not None and regime.get("regime") not in (None, "unknown"):
        reg = regime["regime"]
        s = st_(regime.get("trend_sign", 0) * d) if reg in ("bullish", "bearish") else "neutral"
        out.append({"key": "trend", "label": "Market trend", "status": s,
                    "text": f"Daily regime {reg} (20-day average {regime['sma']:,.0f}, previous close {regime['close']:,.0f})",
                    "values": {"regime": reg}})
    else:
        out.append({"key": "trend", "label": "Market trend", "status": "unavailable", "text": "Daily regime unavailable.", "values": {}})
    return out


def explain(sig: dict, bars: pd.DataFrame, day: date, tf: int, regime=None, scorer=None,
            entry_start: str = "09:30", cutoff: str = "14:30") -> dict:
    """Explanation of the current signal with actual indicator values (closed bars only)."""
    today = bars[bars["day"] == day] if "day" in bars else bars
    r = _row_at(today, sig.get("since") if sig.get("action") != "HOLD" else None)
    if r is None:
        return {"summary": sig.get("reason") or "No completed bars yet.", "checks": [], "confidence": None}
    action = sig.get("action", "HOLD")
    d = 1 if action == "BUY CE" else -1 if action == "BUY PE" else (
        1 if sig.get("direction") == "Bullish" else -1 if sig.get("direction") == "Bearish" else int(np.sign(r["fast"] - r["slow"]) or 1))
    word = "bullish" if d > 0 else "bearish"
    bar_t = pd.Timestamp(r["close_ts"]).strftime("%H:%M")
    ema = {"label": "EMA 9 / EMA 21", "key": "ema",
           "values": {"ema9": _v(r["fast"]), "ema21": _v(r["slow"]), "gap": _v(r["fast"] - r["slow"]), "close": _v(r["close"])}}
    crosses = st.find_crosses(today, "fast", "slow")
    last_cross = crosses.iloc[-1] if not crosses.empty else None
    if action != "HOLD":
        ema.update(status="supports", text=f"EMA 9 {r['fast']:,.2f} crossed {'above' if d > 0 else 'below'} EMA 21 "
                                            f"{r['slow']:,.2f} on the {tf}m bar closing {bar_t} (NIFTY {r['close']:,.2f}): a {word} crossover")
    else:
        rel = "above" if r["fast"] > r["slow"] else "below"
        lc = (f"; last crossover {'bullish' if last_cross['direction'] > 0 else 'bearish'} at "
              f"{pd.Timestamp(last_cross['close_ts']):%H:%M}") if last_cross is not None else "; no crossover today yet"
        ema.update(status="neutral", text=f"EMA 9 {r['fast']:,.2f} is {rel} EMA 21 {r['slow']:,.2f} on the bar closing {bar_t}{lc}")
    items = [ema] + checks(r, d, regime)
    conf = [c for c in items[1:] if c["status"] != "unavailable"]
    pro, con = sum(c["status"] == "supports" for c in conf), sum(c["status"] == "against" for c in conf)

    confidence = None
    if scorer is not None and action != "HOLD" and pd.notna(r.get("atr")) and r["atr"] > 0:
        feats, _ = signals.features(r, regime, d, float(r["atr"]), pd.Timestamp(r["close_ts"]).to_pydatetime())
        score = scorer.score(feats)
        comp = scorer.comparable(score)
        ci = comp.get("ci") if comp else None
        cal = comp.get("calibrated") if comp else None
        ver = (comp or {}).get("verdict") or {}
        text = ((f"Score {score:.0f}/100 ({signals.band(score)}). On years the model had not seen, signals in "
                 f"this band reached the 2×ATR target before the 1×ATR stop {comp['hit_rate']}% of the time "
                 f"(n={comp['n']}{f', 95% range {ci[0]}–{ci[1]}%' if ci else ''}).") if comp and comp["hit_rate"] is not None
                else f"Score {score:.0f}/100 ({signals.band(score)}); no out-of-sample history for this band.")
        if cal is not None:
            text += f" Calibrated estimate for this score: {cal:.0f}%."
        text += f" {ver['text']}" if ver.get("text") else " A model score, not a probability."
        confidence = {"score": round(score, 1), "band": signals.band(score),
                      "hit_rate": comp["hit_rate"] if comp else None, "n": comp["n"] if comp else None,
                      "ci": ci, "calibrated": cal, "edge": ver.get("edge"), "text": text}
    elif action != "HOLD":
        confidence = {"score": None, "text": f"Not scored: build the {tf}m EMA 9/21 analysis on the Signals page to score live signals."}

    if action != "HOLD":
        why = (f"The 9/21 strategy enters on every EMA crossover closing between {entry_start} and {cutoff}. "
               f"This {word} crossover closed at {bar_t}, inside the window, so the call is {action} rather than HOLD.")
        caution = (f"Weak confirmation: {con} of {len(conf)} indicators disagree. The strategy still trades every crossover; "
                   f"treat this as a higher-risk entry.") if con >= 2 or (conf and con > pro) else None
    else:
        gap = r["fast"] - r["slow"]
        need = ("EMA 9 to close above EMA 21" if gap < 0 else "EMA 9 to close below EMA 21")
        why = (f"{sig.get('reason', '')} A new entry needs {need} (gap now {gap:+.2f}) on a {tf}m bar closing "
               f"between {entry_start} and {cutoff}.").strip()
        caution = None
    bullets = [items[0]["text"]] + [c["text"] for c in conf if c["status"] in ("supports", "against")][:4]
    return {"action": action, "bar_close": pd.Timestamp(r["close_ts"]).isoformat(), "direction": word,
            "summary": f"{action}: {pro} of {len(conf)} confirmations agree, {con} disagree." if action != "HOLD"
            else f"HOLD: {sig.get('reason', '')}", "why": why, "caution": caution, "bullets": bullets,
            "checks": items, "confidence": confidence, "atr": _v(r.get("atr")),
            "note": "Only the EMA 9/21 crossover creates the signal; the other indicators are shown for context."}


# ---------------------------------------------------------------- today's plan
def pivots(h: float, l: float, c: float) -> dict:
    """Classic floor pivots from the previous session's high, low and close."""
    p = (h + l + c) / 3
    return {"P": p, "R1": 2 * p - l, "S1": 2 * p - h, "R2": p + (h - l), "S2": p - (h - l)}


def trading_plan(day: date, now: datetime, quote: dict, today1m: pd.DataFrame, prev: dict | None,
                 bars: pd.DataFrame, regime=None, avg_range: float | None = None, tf: int = 5,
                 entry_start: str = "09:30", cutoff: str = "14:30") -> dict:
    """Session plan from actual candles and quotes. Levels are calculated, not exchange-published."""
    today = bars[(bars["day"] == day) & (bars["close_ts"] <= pd.Timestamp(now))] if not bars.empty else bars
    r = today.iloc[-1] if not today.empty else None
    levels = []
    if prev:
        pv = pivots(prev["high"], prev["low"], prev["close"])
        for k, kind in (("R2", "resistance"), ("R1", "resistance"), ("P", "pivot"), ("S1", "support"), ("S2", "support")):
            levels.append({"name": f"Pivot {k}" if k != "P" else "Pivot", "price": round(pv[k], 2), "kind": kind,
                           "source": "calculated from the previous session's high, low and close"})
        levels += [{"name": "Previous day high", "price": round(prev["high"], 2), "kind": "resistance", "source": "previous session's 1-minute candles"},
                   {"name": "Previous day low", "price": round(prev["low"], 2), "kind": "support", "source": "previous session's 1-minute candles"}]
    orh = orl = None
    or_end = datetime.combine(day, st.SESSION_OPEN) + timedelta(minutes=15)
    if today1m is not None and not today1m.empty and now >= or_end:
        first = today1m[today1m["ts"] < pd.Timestamp(or_end)]
        if len(first):
            orh, orl = round(float(first["high"].max()), 2), round(float(first["low"].min()), 2)
            levels += [{"name": "Opening range high", "price": orh, "kind": "resistance", "source": "today's 09:15–09:30 candles"},
                       {"name": "Opening range low", "price": orl, "kind": "support", "source": "today's 09:15–09:30 candles"}]
    bull_lvl = orh if orh is not None else (round(prev["high"], 2) if prev else None)
    bear_lvl = orl if orl is not None else (round(prev["low"], 2) if prev else None)

    price = float(r["close"]) if r is not None else quote.get("price")
    ema_dir = vwap_pos = None
    votes = {"bull": 0, "bear": 0}
    if r is not None:
        ema_dir = "up (EMA 9 above EMA 21)" if r["fast"] > r["slow"] else "down (EMA 9 below EMA 21)"
        votes["bull" if r["fast"] > r["slow"] else "bear"] += 1
        if pd.notna(r.get("fut_vwap")) and pd.notna(r.get("fut_close")):
            above = r["fut_close"] > r["fut_vwap"]
            vwap_pos = f"futures {'above' if above else 'below'} VWAP ({r['fut_close'] - r['fut_vwap']:+.2f})"
            votes["bull" if above else "bear"] += 1
    if prev and price is not None:
        p = pivots(prev["high"], prev["low"], prev["close"])["P"]
        votes["bull" if price > p else "bear"] += 1
    trend = "unknown"
    if regime is not None and regime.get("regime") not in (None, "unknown"):
        trend = regime["regime"]
        if trend in ("bullish", "bearish"):
            votes["bull" if trend == "bullish" else "bear"] += 1
    preferred = "bullish" if votes["bull"] >= 3 and votes["bear"] <= 1 else "bearish" if votes["bear"] >= 3 and votes["bull"] <= 1 else "none"
    atr = _v(r.get("atr")) if r is not None else None
    day_rng = (quote.get("high") - quote.get("low")) if quote.get("high") and quote.get("low") else None
    vol_txt = None
    if atr:
        vol_txt = f"ATR({tf}m) {atr:.2f} pts ({atr / price * 100:.2f}% of price)" if price else f"ATR {atr:.2f}"
        if day_rng is not None and avg_range:
            ratio = day_rng / avg_range
            vol_txt += f"; today's range {day_rng:.0f} pts = {ratio:.2f}× the 10-day average ({'high' if ratio > 1.3 else 'low' if ratio < 0.7 else 'normal'})"
    rsi = _v(r.get("rsi"), 1) if r is not None else None
    fmt = lambda x: f"{x:,.2f}" if x is not None else "—"
    scenarios = [
        {"key": "bullish", "title": "Bullish scenario → BUY CE", "active": preferred == "bullish",
         "conditions": [f"EMA 9 crosses above EMA 21 on a closed {tf}m bar between {entry_start} and {cutoff} (the strategy's only entry rule)",
                        f"Supportive: NIFTY holding above {fmt(bull_lvl)} ({'opening range high' if orh is not None else 'previous day high'})",
                        "Supportive: futures above VWAP, RSI above 50, MACD histogram positive"]},
        {"key": "bearish", "title": "Bearish scenario → BUY PE", "active": preferred == "bearish",
         "conditions": [f"EMA 9 crosses below EMA 21 on a closed {tf}m bar between {entry_start} and {cutoff}",
                        f"Supportive: NIFTY holding below {fmt(bear_lvl)} ({'opening range low' if orl is not None else 'previous day low'})",
                        "Supportive: futures below VWAP, RSI below 50, MACD histogram negative"]},
        {"key": "sideways", "title": "Sideways → HOLD / no trade", "active": preferred == "none",
         "conditions": [f"NIFTY between {fmt(bear_lvl)} and {fmt(bull_lvl)} with EMAs close together (crossovers likely to whipsaw)",
                        "RSI between 45 and 55 and MACD histogram near zero",
                        f"No crossover inside {entry_start}–{cutoff}, or after {cutoff}: the strategy holds"]},
    ]
    return {
        "day": day.isoformat(), "computed_at": now.isoformat(),
        "bar_close": pd.Timestamp(r["close_ts"]).isoformat() if r is not None else None,
        "prev_close": quote.get("prev_close"), "prev_close_candles": round(prev["close"], 2) if prev else None,
        "open": quote.get("open"), "high": quote.get("high"), "low": quote.get("low"),
        "trend": trend, "ema_direction": ema_dir, "vwap_position": vwap_pos, "rsi": rsi, "volatility": vol_txt,
        "bullish_level": bull_lvl, "bearish_level": bear_lvl, "opening_range": {"high": orh, "low": orl} if orh is not None else None,
        "levels": sorted(levels, key=lambda x: -x["price"]), "preferred": preferred, "votes": votes,
        "scenarios": scenarios,
        "entry_rule": f"Entries only on an EMA 9/21 crossover of a closed {tf}m bar between {entry_start} and {cutoff}; exit on the opposite crossover or at 15:00.",
        "note": "Support/resistance here are calculated from candles (pivots, previous day, opening range), not published by the exchange. "
                "Previous close, open, high and low come from Groww's quote. A plan is not a prediction.",
    }


def plan_change_reason(old: dict | None, new: dict) -> str | None:
    """Why the plan changed (None when it didn't). Judged on closed-bar values only."""
    if old is None:
        return "Session plan created."
    why = []
    if old["preferred"] != new["preferred"]:
        why.append(f"preferred direction {old['preferred']} → {new['preferred']} "
                   f"(bullish votes {new['votes']['bull']}, bearish {new['votes']['bear']}: EMA, VWAP, pivot, daily trend)")
    if old["bullish_level"] != new["bullish_level"] or old["bearish_level"] != new["bearish_level"]:
        if old.get("opening_range") is None and new.get("opening_range") is not None:
            why.append(f"opening range formed: bullish level {new['bullish_level']:,.2f}, bearish level {new['bearish_level']:,.2f}")
        else:
            why.append(f"levels changed: bullish {new['bullish_level']}, bearish {new['bearish_level']}")
    return "; ".join(why).capitalize() + "." if why else None

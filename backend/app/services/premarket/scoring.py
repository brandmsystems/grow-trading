"""Pre-market scoring (pure: no network, no database, no clock). Five factors, one point each: +1 bullish, -1 bearish,
0 neutral. A factor with no data scores 0 and says so; no value is ever guessed. All thresholds are fixed, documented
starting values that were not fitted to any result (see docs/PREMARKET.md)."""
from __future__ import annotations

import re
from datetime import datetime

import numpy as np
import pandas as pd

GLOBAL_THR = 0.40           # average change of the available global indices (%) that counts as a direction
MIN_GLOBAL = 3              # at least this many of the five indices must have data
OIL_DAY, OIL_SOFT, OIL_TREND = 1.0, 0.3, 4.0      # Brent: strong day move %, soft move %, 5-day move % that confirms a soft move
VIX_MOVE, VIX_HIGH = 5.0, 22.0                    # India VIX: change % that counts, level above which a falling VIX is not read as bullish
FII_CASH_CR, FUT_LONG_HI, FUT_LONG_LO = 500.0, 55.0, 40.0   # FII net cash (Rs crore) and index-futures long share (%)
STRUCT_THR = 0.20           # structure score that counts as a direction (same scale as the bias engine's "mild")
BANDS = [(4, "STRONG BULLISH"), (2, "BULLISH"), (-1, "NEUTRAL / MIXED"), (-3, "BEARISH"), (-5, "STRONG BEARISH")]


def bias_label(total: int) -> str:
    for lo, name in BANDS:
        if total >= lo:
            return name
    return "STRONG BEARISH"


def status(score: int | None) -> str:
    return "UNAVAILABLE" if score is None else "BULLISH" if score > 0 else "BEARISH" if score < 0 else "NEUTRAL"


def _row(label, value, note=None):
    return {"label": label, "value": value, **({"note": note} if note else {})}


def _factor(key, title, score, summary, rows, asof=None, source=None, delayed=None, warnings=None, explanation=""):
    """score None = no data (counted as 0 points, shown as unavailable)."""
    return {"key": key, "title": title, "score": 0 if score is None else int(score), "status": status(score), "available": score is not None,
            "summary": summary, "explanation": explanation, "data": rows, "asof": asof, "source": source, "delayed": delayed,
            "warnings": warnings or []}


def _pct(x):
    return f"{x:+.2f}%"


# ------------------------------------------------------------------ 1. global
def global_factor(q: dict) -> dict:
    keys = ["sp500", "nasdaq", "dow", "nikkei", "hangseng"]
    have = [(k, q[k]) for k in keys if q.get(k)]
    rows = [_row(q[k]["name"], f"{q[k]['price']:,.2f} ({_pct(q[k]['change_pct'])})", f"{q[k]['status']}, {q[k]['asof']}") for k in keys if q.get(k)]
    rows += [_row(q[k]["name"] if q.get(k) else k, "unavailable") for k in keys if not q.get(k)]
    rows.append(_row("Gift Nifty", "unavailable", "no free source this app can read; not scored"))
    warn = ["Gift Nifty is unavailable, so the opening gap is not estimated from it."]
    if len(have) < MIN_GLOBAL:
        return _factor("global", "Global markets", None, "Not enough index data to score.", rows,
                       warnings=warn + [f"Only {len(have)} of 5 indices returned data (need {MIN_GLOBAL})."],
                       explanation="No points are awarded when too little data is available.")
    avg = float(np.mean([v["change_pct"] for _, v in have]))
    s = 1 if avg >= GLOBAL_THR else -1 if avg <= -GLOBAL_THR else 0
    us = [v["change_pct"] for k, v in have if k in ("sp500", "nasdaq", "dow")]
    asia = [v["change_pct"] for k, v in have if k in ("nikkei", "hangseng")]
    word = {1: "positive", -1: "negative", 0: "mixed or flat"}[s]
    summary = f"Global cues are {word}: average move {_pct(avg)} across {len(have)} indices" + \
              (f" (US {_pct(float(np.mean(us)))}" if us else "") + (f", Asia {_pct(float(np.mean(asia)))})" if asia else (")" if us else ""))
    asof = max(v["asof"] for _, v in have)
    return _factor("global", "Global markets", s, summary, rows, asof=asof, source="Yahoo Finance",
                   delayed="Asian indices are mid-session before 09:15 IST; quotes may lag up to 15 minutes", warnings=warn,
                   explanation=f"+1 if the average change of the available indices is at least {GLOBAL_THR}%, -1 if at most -{GLOBAL_THR}%, else 0.")


# ------------------------------------------------------------------ 2. FII / DII
def fii_factor(m: dict | None, trading_day: str) -> dict:
    """`m` is the figures entered by hand for the previous trading day (NSE offers no script access)."""
    if not m:
        return _factor("fii_dii", "FII / DII flows", None, "Not available: no figures entered for the previous trading day.",
                       [_row("FII cash", "unavailable"), _row("DII cash", "unavailable"), _row("FII index futures", "unavailable")],
                       warnings=["NSE does not publish FII/DII data to scripts. Enter the figures from the NSE 'FII/DII' report once they are published (about 18:00 IST)."],
                       explanation="No points are awarded for data that is not available.")
    fii, dii = m.get("fii_net_cash"), m.get("dii_net_cash")
    longs, shorts = m.get("fii_index_fut_long"), m.get("fii_index_fut_short")
    rows, parts = [], []
    if fii is not None:
        cs = 1 if fii >= FII_CASH_CR else -1 if fii <= -FII_CASH_CR else 0
        parts.append(cs)
        rows.append(_row("FII net cash (Rs crore)", f"{fii:+,.0f}", "buying" if fii > 0 else "selling"))
    if dii is not None:
        rows.append(_row("DII net cash (Rs crore)", f"{dii:+,.0f}", "buying" if dii > 0 else "selling"))
    if longs is not None and shorts is not None and (longs + shorts) > 0:
        pct = 100 * longs / (longs + shorts)
        fs = 1 if pct >= FUT_LONG_HI else -1 if pct <= FUT_LONG_LO else 0
        parts.append(fs)
        rows.append(_row("FII index futures long share", f"{pct:.1f}%", f"long {longs:,.0f} / short {shorts:,.0f}"))
    if not parts:
        return _factor("fii_dii", "FII / DII flows", None, "Entered figures contain no FII cash or futures data.", rows)
    s = int(np.clip(sum(parts), -1, 1))
    word = {1: "FIIs are net buyers / long", -1: "FIIs are net sellers / short", 0: "institutional flows are mixed or small"}[s]
    return _factor("fii_dii", "FII / DII flows", s, f"{word}.", rows, asof=m.get("entered_at"), source=m.get("source") or "entered by hand",
                   delayed="entered by hand for " + str(m.get("day", trading_day)),
                   explanation=f"FII cash: +1 at net buying of Rs {FII_CASH_CR:g} crore or more, -1 at net selling that size. Index futures: +1 at "
                               f"{FUT_LONG_HI:g}% long or more, -1 at {FUT_LONG_LO:g}% or less. The two readings are added and limited to one point; "
                               "DII flow is shown for context and not scored.")


# ------------------------------------------------------------------ 3. crude oil
def crude_factor(q: dict) -> dict:
    b, w = q.get("brent"), q.get("wti")
    main = b or w
    rows = [_row(x["name"], f"${x['price']:,.2f} ({_pct(x['change_pct'])})", f"{x['status']}, {x['asof']}") for x in (b, w) if x]
    if not main:
        return _factor("crude", "Crude oil", None, "Not available.", [_row("Brent", "unavailable"), _row("WTI", "unavailable")],
                       warnings=["No crude oil quote could be fetched."])
    ser = main["series"]
    t5 = (ser[-1] / ser[-6] - 1) * 100 if len(ser) >= 6 else None
    d = main["change_pct"]
    rows.append(_row("5-day move", _pct(t5) if t5 is not None else "unavailable"))
    if d >= OIL_DAY or (d >= OIL_SOFT and t5 is not None and t5 >= OIL_TREND):
        s, why = -1, "rising crude raises India's import bill, inflation and the rupee's pressure"
    elif d <= -OIL_DAY or (d <= -OIL_SOFT and t5 is not None and t5 <= -OIL_TREND):
        s, why = 1, "falling crude eases India's import bill, inflation and the rupee's pressure"
    else:
        s, why = 0, "no large move; little effect on India"
    return _factor("crude", "Crude oil", s, f"{main['name']} {_pct(d)} today: {why}.", rows, asof=main["asof"], source="Yahoo Finance",
                   delayed="futures quote, may lag up to 15 minutes",
                   explanation=f"India imports most of its oil, so crude is read inversely: -1 if Brent rose {OIL_DAY:g}% or more (or {OIL_SOFT:g}% "
                               f"with a 5-day rise of {OIL_TREND:g}%+), +1 for the mirror fall, else 0. WTI is shown for comparison.")


# ------------------------------------------------------------------ 4. India VIX
def vix_factor(q: dict) -> dict:
    v = q.get("vix")
    if not v:
        return _factor("vix", "India VIX", None, "Not available.", [_row("India VIX", "unavailable")], warnings=["No India VIX quote could be fetched."])
    ser, chg, lvl = v["series"], v["change_pct"], v["price"]
    t5 = (ser[-1] / ser[-6] - 1) * 100 if len(ser) >= 6 else None
    if chg >= VIX_MOVE:
        s, trend = -1, "expanding"
    elif chg <= -VIX_MOVE:
        s, trend = 1, "contracting"
    else:
        s, trend = 0, "steady"
    note = ""
    if s > 0 and lvl >= VIX_HIGH:
        s, note = 0, f" The level {lvl:.1f} is still high (at least {VIX_HIGH:g}), so the fall is not scored as bullish."
    rows = [_row("India VIX", f"{lvl:.2f} ({_pct(chg)})", f"{v['status']}, {v['asof']}"), _row("Previous close", f"{v['prev_close']:.2f}"),
            _row("5-day move", _pct(t5) if t5 is not None else "unavailable"),
            _row("Options risk", "high: premiums are expensive and swings are wide" if lvl >= VIX_HIGH else "normal to low premiums" if lvl < 15 else "moderate")]
    return _factor("vix", "India VIX", s, f"Volatility is {trend} ({_pct(chg)} to {lvl:.1f}).{note}", rows, asof=v["asof"], source="Yahoo Finance",
                   delayed="may lag up to 15 minutes",
                   explanation=f"Rising fear is bearish and falling fear bullish: -1 if VIX rose {VIX_MOVE:g}% or more, +1 if it fell that much, else 0; "
                               f"a fall from a level of {VIX_HIGH:g} or above scores 0. The level also tells you how expensive option buying is.")


# ------------------------------------------------------------------ 5. NIFTY structure
def structure_factor(d: dict | None) -> dict:
    """`d` comes from service.nifty_structure(): the votes and raw levels of closed candles only."""
    if not d:
        return _factor("structure", "NIFTY chart & structure", None, "Not available: no stored NIFTY candles.", [_row("NIFTY candles", "unavailable")],
                       warnings=["Download NIFTY data on the Data page."])
    parts = {"daily": (0.35, d.get("daily_score")), "15m": (0.35, d.get("m15_score")), "swing": (0.15, d.get("swing")), "gap": (0.15, d.get("gap_vote"))}
    use = {k: v for k, (w, v) in parts.items() if v is not None and not np.isnan(v)}
    if not use:
        return _factor("structure", "NIFTY chart & structure", None, "Not enough candles to score.", [], warnings=["Too little history."])
    w = {k: parts[k][0] for k in use}
    score = sum(w[k] * use[k] for k in use) / sum(w.values())
    s = 1 if score >= STRUCT_THR else -1 if score <= -STRUCT_THR else 0
    rows = [_row("Previous session", f"O {d['open']:,.1f}  H {d['high']:,.1f}  L {d['low']:,.1f}  C {d['close']:,.1f}", d["day"])]
    rows += [_row(k, v) for k, v in d["rows"]]
    rows.append(_row("Structure score", f"{score:+.2f}", "daily 35%, 15m 35%, swing 15%, gap 15% (missing parts are left out)"))
    word = {1: "bullish", -1: "bearish", 0: "mixed"}[s]
    return _factor("structure", "NIFTY chart & structure", s, f"NIFTY structure is {word}: {d['headline']}", rows, asof=d["asof"], source="Stored NIFTY 1-minute candles (Groww)",
                   delayed=d["freshness"], warnings=d.get("warnings", []),
                   explanation=f"Weighted vote of the daily trend/indicators, the 15-minute trend, higher-high/higher-low structure and the opening gap "
                               f"(only when today's open is known). +1 at a score of {STRUCT_THR:g} or more, -1 at -{STRUCT_THR:g} or less.")


# ------------------------------------------------------------------ total and conclusion
def total(factors: list[dict]) -> dict:
    t = int(sum(f["score"] for f in factors))
    n = sum(1 for f in factors if f["available"])
    return {"total": t, "bias": bias_label(t), "available_factors": n, "max": 5}


def conclusion(factors: list[dict], levels: dict, tot: dict, events: list[dict], expiry_today: bool) -> dict:
    """Plain-language outcome. A preference is only a lean: entries still need live 5m and 15m confirmation."""
    t, n = tot["total"], tot["available_factors"]
    by = {f["key"]: f for f in factors}
    pref = "BUY CE" if t >= 2 else "BUY PE" if t <= -2 else "HOLD"
    g = by.get("global") or {"available": False}
    gap = {1: "a flat-to-higher opening", -1: "a flat-to-lower opening", 0: "a flat, undecided opening"}[g["score"]] if g["available"] else "an unknown opening (global data missing)"
    risks = []
    for f in factors:
        if not f["available"]:
            risks.append(f"{f['title']} data is unavailable, so it earned no point.")
    vx = by.get("vix")
    if vx and vx["available"] and any(str(r.get("value")).startswith("high") for r in vx["data"]):
        risks.append("India VIX is high: option premiums are expensive and moves can reverse quickly.")
    if len({f["score"] for f in factors if f["available"] and f["score"] != 0}) > 1:
        risks.append("Factors disagree: some point up, some down.")
    if expiry_today:
        risks.append("Weekly NIFTY expiry today: premiums decay and swing fast.")
    risks += [f"{e['title']} ({e['basis']})" for e in events if e.get("kind") == "event"][:4]
    confidence = int(round(100 * abs(t) / 5)) if abs(t) >= 2 else 0
    if confidence:
        why = (f"{abs(t)} of 5 points point the same way ({n} of 5 factors had data). Confidence is agreement between factors, not a probability "
               f"that NIFTY moves that way; it has not been shown to predict anything.")
    else:
        why = "The factors cancel out or are too weak, so there is no directional preference and confidence is 0."
    return {"direction": tot["bias"], "opening": gap, "preference": pref, "confidence": confidence, "confidence_note": why,
            "levels": levels, "risks": risks,
            "action": "This is a lean for the day, not an order. Paper entries still need a completed 5-minute candle signal confirmed by the 15-minute direction.",
            "expiry_today": expiry_today}


# ------------------------------------------------------------------ news
POS = {"rally", "rallies", "surge", "surges", "gain", "gains", "jump", "jumps", "rise", "rises", "record high", "optimism", "rate cut", "cuts rates",
       "eases", "cooling inflation", "beat", "beats", "strong", "upgrade", "recovery", "inflows", "buying", "ceasefire", "deal", "boost"}
NEG = {"fall", "falls", "plunge", "plunges", "slump", "tumble", "drop", "drops", "sell-off", "selloff", "rate hike", "hikes rates", "inflation rises",
       "hotter", "miss", "misses", "weak", "downgrade", "recession", "outflows", "selling", "war", "attack", "tariff", "sanctions", "crisis",
       "default", "fear", "warns", "slows", "slowdown", "tension", "tensions", "losses", "crash"}
TOPICS = [("US markets", r"wall street|s&p|nasdaq|dow|us stocks"), ("Asian markets", r"nikkei|hang seng|asian|asia"),
          ("RBI / rates", r"\brbi\b|repo|monetary policy|mpc"), ("Fed", r"\bfed\b|federal reserve|fomc|powell"),
          ("Inflation", r"inflation|cpi|wpi"), ("Crude oil", r"crude|brent|opec|oil price"), ("Geopolitics", r"war|sanction|tariff|ceasefire|tension|attack"),
          ("Indian market", r"nifty|sensex|fii|dii|indian stocks|dalal")]
_W = re.compile(r"[a-z0-9]+")


def impact(headline: str) -> str:
    """Headline tone from a small word list. A rough first read, not an analysis of the article."""
    h = headline.lower()
    def hit(w):                 # slump, slumps, slumped, slumping
        return re.search(rf"\b{re.escape(w)}(s|es|ed|d|ing)?\b", h)
    p = sum(1 for w in POS if hit(w))
    n = sum(1 for w in NEG if hit(w))
    return "positive" if p > n else "negative" if n > p else "neutral"


def topic(headline: str) -> str:
    for name, pat in TOPICS:
        if re.search(pat, headline.lower()):
            return name
    return "Markets"


def dedupe(items: list[dict], sim: float = 0.6) -> list[dict]:
    """Newest first; a headline that shares most of its words with one already kept is dropped."""
    out, seen = [], []
    for it in sorted(items, key=lambda i: i["published"], reverse=True):
        words = {w for w in _W.findall(it["headline"].lower()) if len(w) > 2}
        if not words or any(len(words & s) / len(words | s) >= sim for s in seen):
            continue
        seen.append(words)
        out.append(it)
    return out


def shape_news(items: list[dict], limit: int = 25) -> list[dict]:
    return [{"headline": i["headline"], "source": i["source"], "published": i["published"].isoformat(timespec="minutes"),
             "impact": impact(i["headline"]), "topic": topic(i["headline"]), "link": i.get("link", ""),
             "verified": "trusted outlet list"} for i in dedupe(items)[:limit]]


EVENT_WORDS = re.compile(r"\b(today|this morning|scheduled|due|to announce|will announce|decision|policy meeting)\b.*\b(rbi|fed|fomc|cpi|gdp|inflation|policy|expiry|results|pmi|jobs)\b|"
                         r"\b(rbi|fed|fomc|cpi|gdp|policy|results)\b.*\b(today|due|scheduled|to announce|will announce)\b", re.I)


def headline_events(news: list[dict], now: datetime) -> list[dict]:
    """Headlines of the last 20 hours that mention something happening today. The schedule itself is NOT verified."""
    out = []
    for n in news:
        if EVENT_WORDS.search(n["headline"]) and (now - datetime.fromisoformat(n["published"])).total_seconds() < 20 * 3600:
            out.append({"kind": "event", "title": n["headline"], "basis": f"headline from {n['source']}, schedule unverified"})
    return out[:5]

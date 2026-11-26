"""The position-trading decision: multi-timeframe analysis -> strategy signals -> CE vs PE contract comparison -> 0-100 score -> decision, plan and reasons.

Completed candles only (`strategies.prepare(..., asof=...)`). Nothing here places an order; paper entries go through `account.py`.
Missing data scores 0 and is flagged, never guessed; implied volatility, delta and theta are labelled model estimates (see `bsm.py`).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.position import contracts as pcontracts
from app.services.position import plan as pplan
from app.services.position import score as pscore
from app.services.position import settings as psettings
from app.services.position import strategies as pstr
from app.services.trading import charges as costs

SIGNAL_VALID_DAYS = 2            # a strategy's signal stays actionable for this many completed daily bars
HISTORY_DAYS = 1100              # calendar days of 1-minute candles read (weekly EMA 50 needs 350, daily EMA 200 about 300)
RESEARCH = Path(__file__).resolve().parents[4] / "data" / "exports" / "position_research.json"
TREND_WORD = {2: "strong up", 1: "up", 0: "flat / mixed", -1: "down", -2: "strong down"}


def research_evidence() -> dict:
    """The stored backtest's verdict per strategy (`scripts/research_position.py`), or {} when the research has not been run."""
    try:
        return json.loads(RESEARCH.read_text(encoding="utf-8")).get("evidence", {})
    except Exception:
        return {}


def _evidence_of(key: str, ev: dict) -> dict:
    e = ev.get(key)
    if not e:
        return {"status": "none", "label": "not validated", "note": "no position backtest has been run for this strategy"}
    label = {"positive": "validated positive", "insufficient": "insufficient evidence", "negative": "negative validated result"}[e["status"]]
    return {"status": e["status"], "label": label, "note": e["note"]}


def _tw(v) -> str:
    return "n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else TREND_WORD.get(int(v), "n/a")


def regime(r: pd.Series) -> dict:
    t, adx, ap = r.get("trend"), r.get("adx"), r.get("atr_pct")
    tw = r.get("trend_w")
    if pd.isna(t) or pd.isna(adx):
        return {"label": "Unknown", "why": "not enough history"}
    strong = adx >= 25
    if t >= 1 and (pd.isna(tw) or tw >= 0):
        lab = "Strong uptrend" if strong else "Uptrend"
    elif t <= -1 and (pd.isna(tw) or tw <= 0):
        lab = "Strong downtrend" if strong else "Downtrend"
    elif adx < 20:
        lab = "Range-bound"
    else:
        lab = "Transition (timeframes disagree)"
    if not pd.isna(ap) and ap > pscore.ATR_PCT_BAND[1]:
        lab += ", volatile"
    return {"label": lab, "why": f"daily trend {_tw(t)}, weekly {_tw(tw)}, ADX {adx:.0f}, ATR {0 if pd.isna(ap) else ap:.2f}% of price"}


def market_context(day: date, eng=None) -> dict:
    """India VIX, global markets, crude and FII/DII from the stored pre-market report of that day (live context only: no history exists for a backtest)."""
    try:
        from app.services.premarket import service
        rep = service.get(day, eng)
    except Exception:
        rep = None
    if not rep:
        return {"available": False, "why": "no stored pre-market report for this day (VIX, global markets, crude and FII/DII are live context only)"}
    out = {"available": True, "bias": (rep.get("total") or {}).get("bias"), "factors": []}
    for f in rep.get("factors", []):
        out["factors"].append({"key": f.get("key"), "label": f.get("title") or f.get("label"), "score": f.get("score"), "available": f.get("available"), "summary": f.get("summary")})
    out["note"] = "context only: it does not change the score (the pre-market validation found no open-to-close relation)"
    return out


def _load_inputs(asof: datetime, eng=None):
    from app.database import db
    from app.services.market_data import history
    start = asof - timedelta(days=HISTORY_DAYS)
    spot = db.load_candles("NSE-NIFTY", start, asof + timedelta(minutes=1), eng)
    try:
        fut = history.futures_1m(start.date(), asof.date())
    except Exception:
        fut = None
    return spot, fut


def analyse(asof: datetime | None = None, cfg: dict | None = None, capital: float | None = None, eng=None, spot=None, fut=None, expiries=None, loader=None,
            macro: bool = True) -> dict:
    from app.utils.timeutil import now_naive
    asof = asof or now_naive()
    s = cfg or psettings.current(eng)["config"]
    risk = s["risk"]
    if spot is None:
        spot, fut = _load_inputs(asof, eng)
    d = pstr.prepare(spot, fut, asof=asof)
    base = {"asof": asof.isoformat(timespec="seconds"), "paper_only": True,
            "note": "A decision aid and paper-trading input only. The score counts sound conditions met; it is not a probability of winning."}
    if len(d) < 2:
        return {**base, "decision": "NO TRADE", "direction": 0, "score": None, "reasons": ["not enough completed daily bars to analyse"], "day": None, "strategies": [],
                "opportunities": [], "market": None}
    ev = research_evidence()
    last = d.iloc[-1]
    day = last["day"].date()
    sig = pstr.signals(d, psettings.enabled_strategies(s))
    rows = []
    for k, st in pstr.STRATEGIES.items():
        on = k in sig.columns
        direction, age = 0, None
        if on:
            for back in range(min(SIGNAL_VALID_DAYS, len(sig))):
                v = int(sig[k].iloc[-1 - back])
                if v:
                    direction, age = v, back
                    break
        rows.append({"key": k, "label": st["label"], "enabled": on, "signal": direction, "age_days": age,
                     "params": {**st["params"], **(s["strategies"][k]["params"] if k in s["strategies"] else {})}, "evidence": _evidence_of(k, ev)})
    fired = {1: [r for r in rows if r["signal"] > 0], -1: [r for r in rows if r["signal"] < 0]}
    market = {"day": day.isoformat(), "close": round(float(last["close"]), 2), "regime": regime(last),
              "timeframes": {"weekly": _tw(last.get("trend_w")), "daily": _tw(last.get("trend")), "h4": _tw(last.get("trend_4h")), "h1": _tw(last.get("trend_1h"))},
              "values": {k: (None if pd.isna(last.get(k)) else round(float(last[k]), 3)) for k in ("rsi", "macd_hist", "adx", "plus_di", "minus_di", "atr", "atr_pct", "vol_ratio",
                                                                                                "ema20", "ema50", "ema100", "ema200", "swing_hi", "swing_lo")}}
    out = {**base, "day": day.isoformat(), "market": market, "strategies": rows, "context": market_context(day, eng) if macro else {"available": False, "why": "not requested"}}
    if len(d) < pscore.MIN_DAILY_BARS:
        out.update(decision="NO TRADE", direction=0, score=None, opportunities=[], reasons=[f"only {len(d)} completed daily bars: the EMA 200 needs {pscore.MIN_DAILY_BARS}"])
        return out
    hold = int(risk["hold_days"])
    atr = None if pd.isna(last.get("atr")) else float(last["atr"])
    close = float(last["close"])
    exps = expiries
    if exps is None:
        from app.database import db
        exps = db.load_expiries("groww", eng)
    load = loader or pcontracts.load
    capital = capital if capital is not None else _capital(eng)
    sides = {}
    for dirn, typ in ((1, "CE"), (-1, "PE")):
        comps = pscore.components(last, dirn)
        cands = load(day, close, typ, hold, atr, exps) if exps else []
        usable = [c for c in cands if c["usable"]]
        best = usable[0] if usable else None
        sides[dirn] = {"direction": dirn, "type": typ, "components": comps, "candle_score": pscore.total(comps), "candidates": cands, "best": best,
                       "explanation": pcontracts.explain_choice(best, [c for c in cands if c is not best]) if best else ["no usable contract: " + ("; ".join(sorted({r for c in cands for r in c["reasons_unusable"]})) or "no stored option candles for the decision day")]}
    opps = []
    for dirn in (1, -1):
        names = fired[dirn]
        if not names:
            continue
        sd = sides[dirn]
        comps = [dict(c) for c in sd["components"]]
        best = sd["best"]
        gates = []
        if np.isnan(last.get("trend_w", np.nan)):
            gates.append("the weekly trend is not available yet (needs 50 weekly bars)")
        elif last["trend_w"] * dirn <= -2:
            gates.append("the weekly trend is strongly against this trade")
        plan = None
        if best is None:
            gates.append("no usable option contract: " + sd["explanation"][0].replace("no usable contract: ", ""))
            comps += [{"key": "contract", "label": "Option contract quality", "max": 10, "points": 0.0, "available": False, "note": "no usable contract (0 points)"},
                      {"key": "risk_reward", "label": "Risk / reward", "max": 5, "points": 0.0, "available": False, "note": "no contract (0 points)"}]
        else:
            comps.append({"key": "contract", "label": "Option contract quality", "max": 10, "points": best["quality"], "available": True, "note": "; ".join(best["notes"])})
            plan = pplan.build(direction=dirn, premium=best["premium"], est=best["estimate"], atr=atr, close=close, swing=(None if pd.isna(last.get("swing_lo" if dirn > 0 else "swing_hi")) else float(last["swing_lo" if dirn > 0 else "swing_hi"])),
                               lot_size=best["lot_size"], capital=capital, risk_pct=risk["risk_pct"], hold_days=hold, expiry=best["expiry"], decision_day=day, max_lots=risk["max_lots"])
            rr = plan["risk_reward"]["ratio"]
            comps.append({"key": "risk_reward", "label": "Risk / reward", "max": 5, "points": 0.0 if not rr or rr <= 0 else round(5 * min(1.0, rr / 2.0), 1), "available": rr is not None,
                          "note": f"target nets ₹{plan['risk_reward']['net_at_target']:,.0f}, stop loses ₹{abs(plan['risk_reward']['net_at_stop']):,.0f} after all costs" + ("" if rr else " (not available)")})
            if rr is not None and rr <= 0:
                gates.append("the target does not cover the costs")
            if plan["lots"] < 1 and plan["sizing"]:
                gates.append("sizing: " + str(plan["sizing"].get("reason")))
        total = pscore.total(comps)
        label, why = pscore.decide(dirn, total, gates, risk["min_score"])
        opps.append({"direction": dirn, "type": sd["type"], "strategies": [r["key"] for r in names], "strategy_labels": [r["label"] for r in names], "score": total, "components": comps,
                     "decision": label, "why": why, "contract": best, "plan": plan, "evidence": [r["evidence"] for r in names],
                     "gates": gates})
    reasons = []
    if fired[1] and fired[-1]:
        decision, direction, score = "HOLD", 0, None
        reasons = ["strategies disagree (" + ", ".join(r["label"] for r in fired[1]) + " bullish; " + ", ".join(r["label"] for r in fired[-1]) + " bearish): no trade"]
    elif not opps:
        decision, direction, score = "HOLD", 0, None
        on = [r for r in rows if r["enabled"]]
        reasons = ["no valid setup: none of the " + str(len(on)) + " enabled strategies has a signal on the last " + str(SIGNAL_VALID_DAYS) + " completed daily bars"] if on else ["no strategy is enabled"]
    else:
        best_opp = max(opps, key=lambda o: o["score"])
        decision, direction, score = best_opp["decision"], best_opp["direction"], best_opp["score"]
        reasons = [best_opp["why"]] + best_opp["gates"]
        if best_opp["evidence"] and all(e["status"] != "positive" for e in best_opp["evidence"]):
            reasons.append("evidence: " + "; ".join(sorted({e["label"] for e in best_opp["evidence"]})) + " (see the backtest): treat this as an idea to study, not an edge")
    out.update(decision=decision, direction=direction, score=score, reasons=reasons, opportunities=opps,
               comparison={"CE": _side_summary(sides[1]), "PE": _side_summary(sides[-1])}, capital=capital)
    return out


def _side_summary(sd: dict) -> dict:
    b = sd["best"]
    return {"candle_score": sd["candle_score"], "contract_quality": None if not b else b["quality"], "total_without_levels": round(sd["candle_score"] + (b["quality"] if b else 0), 1),
            "best": None if not b else {"symbol": b["symbol"], "expiry": b["expiry"].isoformat(), "strike": b["strike"], "premium": b["premium"], "dte": b["dte"], "quality": b["quality"],
                                        "notes": b["notes"], "estimate": b["estimate"], "spread": b["spread"], "gap_pct": b["gap_pct"]},
            "alternatives": [{"expiry": c["expiry"].isoformat(), "strike": c["strike"], "premium": c["premium"], "quality": c["quality"], "usable": c["usable"], "dte": c["dte"],
                              "reasons_unusable": c["reasons_unusable"]} for c in sd["candidates"][:8]],
            "explanation": sd["explanation"]}


def _capital(eng=None) -> float:
    from app.services.position import account
    return account.state(eng=eng)["available"]

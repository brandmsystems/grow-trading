"""Continuous opportunity scanner: independent strategy signals, a transparent 0-100 quality score, ranking (pure, no I/O).

Every closed candle, each strategy that is ON (Trading Settings) is looked at on its own. A strategy that signals becomes an
*opportunity* with a quality score built from ten components that add up to 100. The score counts how many sound conditions a
setup meets; **it is not a probability of winning and no strategy has shown an edge** (see `evidence.py`). A missing value earns 0
points and is flagged, never guessed.

| Component | Max | Earned when |
|---|---|---|
| Trend confirmation | 15 | the closed higher-timeframe (15m) score points the trade's way (full at +-0.5) |
| Entry signal quality | 15 | 8 for the strategy's own signal + up to 7 for the share of enabled indicator votes that agree |
| VWAP / EMA alignment | 10 | VWAP vote 5 + EMA votes (9/21 and 20/50) 5, each aligned with the trade |
| RSI / MACD confirmation | 10 | RSI vote 5 + MACD vote 5, aligned |
| Volume confirmation | 5 | futures volume expansion in the trade's direction |
| Market structure / support-resistance | 10 | the support/resistance and structure vote aligned (FVG scores in the Confluence and Scored strategies) |
| Option liquidity and spread | 10 | premium 3 + open interest 4 + bid-ask spread 3, each checked against your limits |
| IV and Greeks validation | 5 | delta available and inside the allowed range (IV is not provided by the data source) |
| Historical out-of-sample result | 10 | the strategy's validated record (`evidence.py`): negative 0, insufficient 3, positive 10 |
| Risk/reward after costs | 10 | target gain after brokerage, taxes and slippage against the loss at the stop, same costs: 2.0 or better earns 10 |

Everything above the candle (liquidity, Greeks, reward/risk) needs the contract and its premium, so the engine completes the score
when it looks the contract up; the candle part alone gives the ranking.
"""
from __future__ import annotations

import math

import pandas as pd

from app.services.strategy import bias
from app.services.strategy import evidence as ev

KNOWN_MAX = 75          # known from the candle and the record: trend 15, signal 15, vwap/ema 10, rsi/macd 10, volume 5, structure 10, evidence 10
LATE_MAX = 25           # needs the contract and its premium: liquidity 10, greeks 5, reward/risk 10

FULL_TREND = 0.5
FULL_VOTE = 0.5


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _comp(key: str, label: str, mx: float, pts: float | None, note: str) -> dict:
    """One score component. pts None = the data is not available: 0 points, flagged."""
    return {"key": key, "label": label, "max": mx, "points": round(0.0 if pts is None else max(0.0, min(mx, pts)), 1),
            "available": pts is not None, "note": note + ("" if pts is not None else " (not available: 0 points)")}


def _aligned(v, d: int) -> float | None:
    """A vote signed to the trade: positive = agrees with the direction d."""
    x = _num(v)
    return None if x is None else x * d


def candle_components(r: pd.Series, d: int, ip=None) -> list[dict]:
    """The components that come from the closed candle's analysis row (bias frame row `r`), for a trade in direction d (+1 / -1)."""
    out = []
    s15 = _aligned(r.get("s15"), d)
    out.append(_comp("trend", "Trend confirmation", 15, None if s15 is None else 15 * min(1.0, max(0.0, s15) / FULL_TREND),
                     "higher-timeframe score " + ("n/a" if s15 is None else f"{s15:+.2f} with the trade (full at +{FULL_TREND:g})")))
    votes = {k: _aligned(r.get(f"v5_{k}"), d) for k in bias.INDICATORS}
    have = {k: v for k, v in votes.items() if v is not None}
    if have:
        w = {k: bias.INDICATORS[k][1] for k in have}
        share = sum(w[k] for k, v in have.items() if v >= bias.VOTE_MIN) / sum(w.values())
        out.append(_comp("signal", "Entry signal quality", 15, 8 + 7 * share,
                         f"strategy signalled (8) + {100 * share:.0f}% of the enabled indicator votes agree ({round(7 * share, 1)} of 7)"))
    else:
        out.append(_comp("signal", "Entry signal quality", 15, 8, "strategy signalled (8); indicator votes not available"))

    def part(keys, per):
        vs = [votes.get(k) for k in keys if votes.get(k) is not None]
        return None if not vs else per * min(1.0, max(0.0, sum(vs) / len(vs)) / FULL_VOTE)
    vw, em = part(["vwap"], 5), part(["ema_9_21", "ema_20_50"], 5)
    out.append(_comp("vwap_ema", "VWAP / EMA alignment", 10, None if vw is None and em is None else (vw or 0) + (em or 0),
                     "VWAP " + ("n/a" if vw is None else f"{vw:.1f}/5") + ", EMA 9/21 + 20/50 " + ("n/a" if em is None else f"{em:.1f}/5")))
    rs, mc = part(["rsi"], 5), part(["macd"], 5)
    out.append(_comp("rsi_macd", "RSI / MACD confirmation", 10, None if rs is None and mc is None else (rs or 0) + (mc or 0),
                     "RSI " + ("n/a" if rs is None else f"{rs:.1f}/5") + ", MACD " + ("n/a" if mc is None else f"{mc:.1f}/5")))
    vol = votes.get("volume")
    out.append(_comp("volume", "Volume confirmation", 5, None if vol is None else 5 * min(1.0, max(0.0, vol)),
                     "volume expansion vote " + ("n/a (no futures volume)" if vol is None else f"{vol:+.2f} with the trade")))
    sr = part(["sr"], 10)
    out.append(_comp("structure", "Market structure / support-resistance", 10, sr,
                     "support/resistance vote " + ("n/a" if sr is None else f"{sr:.1f}/10") + "; FVG is scored by the Confluence and Scored strategies"))
    return out


def evidence_component(key: str) -> dict:
    e = ev.evidence_for(key)
    return _comp("evidence", "Historical out-of-sample result", 10, e["points"], f"{e['label']}: {e['note']}")


def contract_components(checks: list[dict], side: str) -> list[dict]:
    """Liquidity and Greeks components from the engine's contract checks (`ok` True / False / None = not available)."""
    by = {c["check"]: c for c in checks or []}

    def pts(name, full):
        c = by.get(name)
        if c is None or c["ok"] is None:
            return None, (c["text"] if c else f"{name} not checked")
        return (full if c["ok"] else 0), c["text"]
    p, pn = pts("premium", 3)
    o, on = pts("open_interest", 4)
    s, sn = pts("spread", 3)
    known = [x for x in (p, o, s) if x is not None]
    liq = _comp("liquidity", "Option liquidity and spread", 10, sum(known) if known else None, f"{pn}; {on}; {sn}")
    g, gn = pts("delta", 5)
    return [liq, _comp("greeks", "IV and Greeks validation", 5, g, gn + "; IV is not provided by the data source")]


def reward_risk_component(rr: float | None, note: str) -> dict:
    return _comp("reward_risk", "Risk/reward after costs", 10, None if rr is None else 10 * min(1.0, max(0.0, rr) / 2.0), note)


def reward_risk(side: str, premium: float, stop: float | None, target: float | None, qty: int, cost_cfg) -> tuple[float | None, str]:
    """(reward / risk after charges and slippage, a sentence). Reward = net P&L if the target fills; risk = net loss if the stop fills."""
    from app.services.trading import charges as costs
    if not premium or stop is None or target is None or qty <= 0:
        return None, "stop or target not available"
    win = costs.round_trip(side, premium, target, qty, cost_cfg)["net"]
    loss = costs.round_trip(side, premium, stop, qty, cost_cfg)["net"]
    if loss >= 0:
        return None, "the stop does not lose money"
    rr = win / abs(loss)
    return rr, f"target nets ₹{win:,.0f}, stop loses ₹{abs(loss):,.0f} after all costs: {rr:.2f}R" + ("" if win > 0 else " (the target does not cover the costs)")


def total(components: list[dict]) -> float:
    return round(sum(c["points"] for c in components), 1)


def episode_start(series: pd.Series | None, d: int, bar_close) -> pd.Timestamp:
    """Close time of the first candle of today's unbroken run of signals in direction d that ends at `bar_close`."""
    bc = pd.Timestamp(bar_close)
    if series is None or len(series) == 0:
        return bc
    s = series[(series.index.normalize() == bc.normalize()) & (series.index <= bc)]
    start = bc
    for ts in reversed(list(s.index)):
        if int(s.loc[ts]) == d:
            start = ts
        else:
            break
    return pd.Timestamp(start)


def scan(info: dict, r: pd.Series, cfg, bar_close, keys_order=None) -> dict:
    """Look at every registered strategy on the closed candle `bar_close`. `info` is configured.evaluate's description of the
    candle. Returns {"opps": [...], "by_key": {...}}; each opportunity carries its direction, action label, candle score and the reasons it
    is or is not a candidate. A strategy that signalled in opposite directions with another is marked as a conflict by the caller."""
    series = info.get("series") or {}
    opps = []
    for row in info["strategies"]:
        k = row["key"]
        o = {"strategy": k, "label": row["label"], "kind": row["kind"], "state": row["state"], "direction": int(row["direction"]),
             "action": None, "decision": "OFF" if row["state"] in ("off", "blocked") else "HOLD", "reasons": [], "quality": None,
             "components": [], "evidence": ev.evidence_for(k), "episode_start": None}
        if row["state"] in ("off", "blocked"):
            o["reasons"] = [row["reason"]]
        elif row["state"] == "rejected":
            o["reasons"] = [row["reason"]]
        elif row["state"] == "no signal":
            o["reasons"] = [row["reason"]]
        elif row["state"] == "signal":
            d = o["direction"]
            comps = candle_components(r, d) + [evidence_component(k)]
            o["components"] = comps
            o["quality"] = total(comps)
            o["episode_start"] = episode_start(series.get(k), d, bar_close).isoformat()
            o["decision"] = "CANDIDATE"
        opps.append(o)
    return {"opps": opps, "by_key": {o["strategy"]: o for o in opps}}


def rank_key(o: dict) -> tuple:
    """Highest quality first; ties by the strategy's validated record, then by name (stable and explainable)."""
    return (-(o["quality"] or 0), -o["evidence"]["points"], o["strategy"])

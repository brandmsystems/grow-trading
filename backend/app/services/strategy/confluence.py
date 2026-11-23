"""Confluence strategy: fair value gaps, VWAP, ADR, EMA trend and market structure in one configurable entry rule.

Everything here is pure (no I/O) and causal: the value on a closed bar uses that bar and earlier bars only, so a later
candle never changes an earlier row (`tests/test_confluence.py` checks, as `test_bias.py` does for the bias analysis).
The studies themselves live in `indicators.py` (`fvg_zones`, `adr`, `swing_structure`); the bars, EMAs, ATR, futures
VWAP and the closed 15-minute trend come from `bias.tf_bars` / `entries.frame`, so nothing is calculated twice.

Four factors vote in [-1, +1] (bullish positive); a vote is the full value only when the condition is confirmed:

  ema        +-1 EMA 9 > 21 > 50 with the close beyond EMA 21; +-0.5 EMA 9 vs 21 and the close beyond EMA 21 only
  vwap       +-1 retest or rejection of VWAP held in that direction; +-0.5 the close is on that side (0.1 ATR away or more)
  fvg        +-1 a retest of an unfilled/mitigated gap confirmed on this bar; +-0.5 such a gap is the newest and waits for a retest
  structure  +-1 higher highs and higher lows (lower/lower); +-0.5 a recent break of structure while the swings are mixed

ADR is not a direction: it is a filter. An entry is refused when today's range has already used more than `adr_max_used`
% of the N-day Average Daily Range (a move that has run its course). The confirmation score is the weighted share of the
enabled factors that agree with the direction the factors point to (a half vote counts half). An entry needs the score at
or above `min_score`, every `require`d factor fully confirmed (|vote| = 1), the closed 15-minute trend not against it, ADR
not exhausted and enough volatility. Missing data (no futures candles, too few sessions for the ADR) is left out and shown
as unavailable, never guessed. Weights and thresholds are fixed starting values, not fitted to any result.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.services.strategy import bias, entries
from app.services.strategy import indicators as ind

FACTORS = {"ema": ("EMA trend", 1.0), "vwap": ("VWAP", 1.0), "fvg": ("Fair value gap", 1.0), "structure": ("Market structure", 1.0)}
ADR_PERIODS = (5, 10, 20)
FULL, AGREE = 1.0, 0.5            # |vote| of a fully confirmed factor, and the least that still agrees
WARM_BARS = 150                   # the 5-minute EMA 50 needs 3 x 50 bars to settle


@dataclass
class ConfluenceParams:
    factors: tuple = tuple(FACTORS)        # enabled factors
    require: tuple = ()                    # factors that must be fully confirmed (|vote| = 1) for an entry
    min_score: float = 75.0                # % confirmation needed
    adr_filter: bool = True                # refuse entries once the day's range is used up
    adr_period: int = 10                   # 5, 10 or 20 sessions
    adr_max_used: float = 100.0            # % of the ADR today's range may have used
    fvg_min_atr: float = 0.1               # smallest gap that counts, in ATRs
    fvg_max_age: int = 24                  # bars a gap stays tradable (2 hours of 5-minute bars)
    htf: bool = True                       # the closed 15-minute trend (EMA 20/50) must not be against the trade
    min_atr_pct: float = 0.04              # entries need 5m ATR of at least this % of price (same filter as the bias engine)
    swing_k: int = 3                       # a swing pivot is confirmed 3 bars after it formed
    primary: int = 5                       # entry timeframe in minutes (the engine's analysis interval)
    higher: int = 15                       # trend confirmation timeframe in minutes
    ind: "bias.IndParams | None" = None    # indicator parameters (Trading Settings); None = the long-standing values

    @classmethod
    def from_cfg(cls, cfg) -> "ConfluenceParams":
        fac = tuple(k for k in (cfg.cf_factors or FACTORS) if k in FACTORS) or tuple(FACTORS)
        return cls(factors=fac, require=tuple(k for k in (cfg.cf_require or []) if k in fac), min_score=cfg.cf_min_score,
                   adr_filter=cfg.cf_adr_filter, adr_period=int(cfg.cf_adr_period), adr_max_used=cfg.cf_adr_max_used,
                   fvg_min_atr=cfg.cf_fvg_min_atr, fvg_max_age=int(cfg.cf_fvg_max_age), htf=cfg.cf_htf,
                   min_atr_pct=cfg.bias_min_atr_pct, primary=int(cfg.timeframe), higher=int(cfg.bias_confirm_tf),
                   ind=bias.IndParams.from_dict(getattr(cfg, "ind", None)), swing_k=bias.IndParams.from_dict(getattr(cfg, "ind", None)).swing_k)


# ---------------------------------------------------------------- bars with every study
def frame(spot1m: pd.DataFrame, fut1m: pd.DataFrame | None, p: ConfluenceParams | None = None) -> pd.DataFrame:
    """Closed 5-minute bars with the indicators, the closed 15-minute trend, FVG, ADR, structure and VWAP events."""
    p = p or ConfluenceParams()
    f = entries.frame(spot1m, fut1m, p.primary, p.higher, p.ind)
    if f.empty:
        return f
    if getattr(p, "ctx_tf", 0):
        f = entries.attach_trend(f, bias.tf_bars(spot1m, fut1m, p.ctx_tf, p.ind), "trend_ctx")
    f = f.join(ind.fvg_zones(f, p.fvg_min_atr, p.fvg_max_age)).join(ind.adr(f, ADR_PERIODS)).join(ind.swing_structure(f, p.swing_k))
    a, c, o = f["atr"], f["close"], f["open"]
    dist, far_up, far_dn, near = entries.vwap_geometry(f)
    adj = f["fut_vwap"] - (f["fut_close"] - c)          # the futures VWAP on the index's scale (as the chart draws it)
    up_c, dn_c, prev = c > o, c < o, dist.shift(1)
    f["vwap_adj"], f["vwap_dist"] = adj, dist
    f["vwap_retest_up"] = far_up & near & (dist >= -0.25 * a) & up_c
    f["vwap_retest_dn"] = far_dn & near & (dist <= 0.25 * a) & dn_c
    f["vwap_reject_up"] = (prev > 0) & (f["low"] <= adj + 0.1 * a) & (c > adj) & up_c
    f["vwap_reject_dn"] = (prev < 0) & (f["high"] >= adj - 0.1 * a) & (c < adj) & dn_c
    return f


# ---------------------------------------------------------------- votes, score, gates
def votes(f: pd.DataFrame) -> pd.DataFrame:
    """Every factor's vote on every bar (NaN = cannot vote). All four are always computed, enabled or not."""
    a = f["atr"].where(f["atr"] > 0)
    c, e9, e21, e50 = f["close"], f["ema9"], f["ema21"], f["ema50"]
    n = pd.Series(np.arange(len(f)), index=f.index)
    v = pd.DataFrame(index=f.index)

    full_up, full_dn = (e9 > e21) & (e21 > e50) & (c > e21), (e9 < e21) & (e21 < e50) & (c < e21)
    half_up, half_dn = (e9 > e21) & (c > e21) & ~full_up, (e9 < e21) & (c < e21) & ~full_dn
    v["ema"] = pd.Series(np.select([full_up, full_dn, half_up, half_dn], [1.0, -1.0, 0.5, -0.5], 0.0), index=f.index).where(n >= WARM_BARS)

    side = pd.Series(np.where(f["vwap_dist"].abs() >= 0.1 * a, np.sign(f["vwap_dist"]), 0.0), index=f.index)
    event_up, event_dn = f["vwap_retest_up"] | f["vwap_reject_up"], f["vwap_retest_dn"] | f["vwap_reject_dn"]
    v["vwap"] = pd.Series(np.select([event_up & ~event_dn, event_dn & ~event_up, side > 0, side < 0], [1.0, -1.0, 0.5, -0.5], 0.0),
                          index=f.index).where(f["fut_vwap"].notna() & f["fut_close"].notna())

    live = {s: f[f"fvg_{s}_state"].isin(["unfilled", "mitigated"]) for s in ("bull", "bear")}
    age = {s: f[f"fvg_{s}_age"].where(live[s], np.inf) for s in ("bull", "bear")}
    bull_ret, bear_ret = f["fvg_bull_retest"], f["fvg_bear_retest"]
    v["fvg"] = pd.Series(np.select([bull_ret & ~bear_ret, bear_ret & ~bull_ret, live["bull"] & (age["bull"] < age["bear"]),
                                    live["bear"] & (age["bear"] < age["bull"])], [1.0, -1.0, 0.5, -0.5], 0.0), index=f.index)

    s, bos = f["struct"], f["bos_recent"]
    v["structure"] = pd.Series(np.select([s == 1, s == -1, (s == 0) & (bos > 0), (s == 0) & (bos < 0)], [1.0, -1.0, 0.5, -0.5], 0.0),
                               index=f.index).where(s.notna())
    return v[list(FACTORS)]


def decide(f: pd.DataFrame, v: pd.DataFrame, p: ConfluenceParams) -> pd.DataFrame:
    """Direction the factors point to, the confirmation score, each gate, and the final entry direction (0 = none)."""
    en = list(p.factors)
    w = pd.Series({k: FACTORS[k][1] for k in en})
    V = v[en]
    den = V.notna().mul(w, axis=1).sum(axis=1)
    raw = V.fillna(0.0).mul(w, axis=1).sum(axis=1)
    d = np.sign(raw).astype(int)
    agree = V.mul(d, axis=0).clip(lower=0).mul(w, axis=1).sum(axis=1)
    score = (100 * agree / den.where(den > 0)).where(d != 0, 0.0).fillna(0.0).round(1)

    out = pd.DataFrame(index=f.index)
    out["cf_raw_dir"], out["cf_score"] = d, score
    out["cf_g_score"] = (score >= p.min_score) & (d != 0)
    req_ok = pd.Series(True, index=f.index)
    for k in p.require:
        req_ok &= (V[k].mul(d) >= FULL - 1e-9).fillna(False)
    out["cf_g_require"] = req_ok
    out["cf_g_htf"] = (~pd.Series(p.htf, index=f.index)) | ((f["trend15"] * d) >= 0)
    used = f[f"adr_used{p.adr_period}"]
    out["cf_g_adr"] = (~pd.Series(p.adr_filter, index=f.index)) | used.isna() | (used <= p.adr_max_used)
    out["cf_g_atr"] = (100 * f["atr"] / f["close"]) >= p.min_atr_pct
    ok = out["cf_g_score"] & out["cf_g_require"] & out["cf_g_htf"] & out["cf_g_adr"] & out["cf_g_atr"]
    out["cf_direction"] = d.where(ok, 0).astype(int)
    for k in FACTORS:
        out[f"cf_vote_{k}"] = v[k]
    return out


def analyse(spot1m: pd.DataFrame, fut1m: pd.DataFrame | None, p: ConfluenceParams | None = None) -> pd.DataFrame:
    """One row per closed 5-minute bar: the bar's indicators, every study, the four votes, score, gates and `cf_direction`."""
    p = p or ConfluenceParams()
    f = frame(spot1m, fut1m, p)
    if f.empty:
        return f
    if isinstance(p, ScoredParams):
        return f.join(sc_decide(f, p))
    return f.join(decide(f, votes(f), p))


def overlay(bias_frame: pd.DataFrame, spot1m: pd.DataFrame, fut1m: pd.DataFrame | None, p) -> pd.DataFrame:
    """The bias analysis frame with the confluence strategy's decision as `direction` (the engine then uses its normal
    entry, risk, exit and reporting path). The bias's own candidate is kept as `bias_direction`; its prediction and
    votes are untouched. Rows are matched on the bar's close time."""
    if bias_frame.empty:
        return bias_frame
    cf = analyse(spot1m, fut1m, p)
    extra = [c for c in cf.columns if c not in bias_frame.columns or c == "close_ts"]
    out = bias_frame.merge(cf[extra], on="close_ts", how="left")
    out["bias_direction"] = out["direction"]
    out["direction"] = out["sc_direction" if isinstance(p, ScoredParams) else "cf_direction"].fillna(0).astype(int)
    return out


# ---------------------------------------------------------------- research signals (scripts/research_entries.py)
def research_signals(cf: pd.DataFrame) -> pd.DataFrame:
    """Entry columns for the five-year research, in the entries.py format (+1 / 0 / -1 per bar, fired when the state
    begins; the event methods keep entries.py's 6-bar cool-down). Same rules as the live strategy."""
    if cf.empty:
        return pd.DataFrame(columns=["fvg_retest", "vwap_rejection", "confluence"])
    t15 = cf["trend15"]
    fvg = (cf["fvg_bull_retest"] & (t15 > 0)).astype(int) - (cf["fvg_bear_retest"] & (t15 < 0)).astype(int)
    rej = (cf["vwap_reject_up"] & (t15 > 0)).astype(int) - (cf["vwap_reject_dn"] & (t15 < 0)).astype(int)
    d = cf["cf_direction"]
    begin = pd.Series(np.where((d != 0) & (d != d.shift(1).fillna(0)), d, 0), index=cf.index).astype(int)
    out = pd.DataFrame({"fvg_retest": entries._cooldown(fvg, cf["day"]), "vwap_rejection": entries._cooldown(rej, cf["day"]),
                        "confluence": begin})
    return out.where(cf["atr"].notna(), 0)


# ---------------------------------------------------------------- explanation of one row
def _num(x, nd=2):
    return bias._v(x, nd)


def _status(x) -> str:
    return "unavailable" if x is None else "bullish" if x >= AGREE else "bearish" if x <= -AGREE else "neutral"


def _fvg_side(r: pd.Series, side: str) -> dict | None:
    state = r.get(f"fvg_{side}_state")
    if not isinstance(state, str):
        return None
    return {"state": state, "lo": _num(r[f"fvg_{side}_lo"]), "hi": _num(r[f"fvg_{side}_hi"]),
            "age_bars": int(r[f"fvg_{side}_age"]), "retest": bool(r[f"fvg_{side}_retest"]), "active": int(r[f"fvg_{side}_n"])}


def _conditions(r: pd.Series, p: ConfluenceParams) -> dict[str, tuple[str, dict]]:
    """Plain-language state of each factor on this bar, and the numbers behind it."""
    c = float(r["close"])
    e9, e21, e50 = (float(r[k]) for k in ("ema9", "ema21", "ema50"))
    order = ("EMA 9 above 21 above 50" if e9 > e21 > e50 else "EMA 9 below 21 below 50" if e9 < e21 < e50
             else f"EMA 9 {'above' if e9 > e21 else 'below'} 21, EMA 50 not aligned")
    ema = (f"{order}; close {c:,.2f} is {'above' if c > e21 else 'below'} EMA 21 {e21:,.2f}", {"ema9": _num(e9), "ema21": _num(e21), "ema50": _num(e50)})

    if pd.isna(r.get("fut_vwap")) or pd.isna(r.get("fut_close")):
        vw = ("Futures VWAP unavailable (no futures candles): this factor cannot vote.", {})
    else:
        kind = ("bullish retest" if r["vwap_retest_up"] else "bearish retest" if r["vwap_retest_dn"] else "bullish rejection" if r["vwap_reject_up"]
                else "bearish rejection" if r["vwap_reject_dn"] else None)
        vw = (f"Close {c:,.2f} is {'above' if r['vwap_dist'] > 0 else 'below'} VWAP {r['vwap_adj']:,.2f} ({r['vwap_dist']:+.2f})"
              + (f"; {kind} on this candle" if kind else "; no retest or rejection on this candle"),
              {"vwap": _num(r["vwap_adj"]), "distance": _num(r["vwap_dist"]), "retest": bool(r["vwap_retest_up"] or r["vwap_retest_dn"]),
               "rejection": bool(r["vwap_reject_up"] or r["vwap_reject_dn"])})

    bull, bear = _fvg_side(r, "bull"), _fvg_side(r, "bear")
    parts = []
    for name, z in (("bullish", bull), ("bearish", bear)):
        if z:
            parts.append(f"{name} gap {z['lo']:,.2f}-{z['hi']:,.2f} {z['state']}" + (" and retested now" if z["retest"] else f" ({z['age_bars']} bars old)"))
    fv = ("; ".join(parts) if parts else "No active fair value gap.", {"bullish": bull, "bearish": bear})

    s = r.get("struct")
    if pd.isna(s):
        st_ = ("Not enough swing points yet.", {})
    else:
        word = ("higher highs and higher lows" if s > 0 else "lower highs and lower lows" if s < 0 else "mixed swings")
        bos = int(r["bos_recent"])
        st_ = (f"{word.capitalize()} (swing high {r['swing_hi']:,.2f}, swing low {r['swing_lo']:,.2f})"
               + (f"; {'bullish' if bos > 0 else 'bearish'} break of structure in the last {6} bars" if bos else ""),
               {"swing_hi": _num(r["swing_hi"]), "swing_lo": _num(r["swing_lo"]), "break_of_structure": bos})
    return {"ema": ema, "vwap": vw, "fvg": fv, "structure": st_}


def explain(r: pd.Series, p, expl: dict) -> dict:
    """The bias explanation with this strategy's factors, ADR, FVG, gates and rejection reasons added, and its decision
    in place of the bias entry decision (`signal`, `direction`, `hold_reasons`, `summary`, `entry_score`)."""
    if isinstance(p, ScoredParams):
        return sc_explain(r, p, expl)
    d, direction = int(r["cf_raw_dir"]), int(r["cf_direction"])
    cond = _conditions(r, p)
    factors = []
    for k, (label, weight) in FACTORS.items():
        vote = _num(r.get(f"cf_vote_{k}"))
        on = k in p.factors
        factors.append({"key": k, "label": label, "weight": weight, "enabled": on, "required": k in p.require, "vote": vote,
                        "status": _status(vote), "confirmed": None if vote is None or not d else bool(vote * d >= FULL - 1e-9),
                        "agrees": None if vote is None or not d else bool(vote * d >= AGREE), "condition": cond[k][0], "values": cond[k][1]})
    adr_rows = [{"period": n, "adr": _num(r.get(f"adr{n}")), "used": _num(r.get(f"adr_used{n}"), 1)} for n in ADR_PERIODS]
    used = _num(r.get(f"adr_used{p.adr_period}"), 1)
    adr_ok = None if not p.adr_filter or used is None else bool(used <= p.adr_max_used)
    adr_text = ("ADR unavailable (fewer than " + f"{p.adr_period} earlier sessions): not checked." if used is None else
                f"Today's range {_num(r['range_today']):,.2f} has used {used:.0f}% of the {p.adr_period}-day ADR {_num(r[f'adr{p.adr_period}']):,.2f}"
                + (f" (limit {p.adr_max_used:g}%)." if p.adr_filter else "; the ADR filter is off."))
    side = {1: "BUY CE", -1: "BUY PE"}.get(d)
    why: list[str] = []
    if direction == 0:
        if d == 0:
            why.append("the enabled factors do not point one way (net vote 0)")
        elif not r["cf_g_score"]:
            why.append(f"confirmation score {r['cf_score']:.0f}% is below your minimum {p.min_score:g}%")
        for f_ in factors:
            if d and f_["required"] and f_["enabled"] and not f_["confirmed"]:
                why.append(f"required factor '{f_['label']}' is not fully confirmed for {side}" + (" (it needs a retest of an unfilled gap)" if f_["key"] == "fvg" else ""))
        if d and not r["cf_g_htf"]:
            why.append(f"the closed 15-minute trend is {'bearish' if r['trend15'] < 0 else 'bullish'}, against {side}")
        if d and not r["cf_g_adr"]:
            why.append(f"ADR exhausted: today's range has used {used:.0f}% of the {p.adr_period}-day ADR (limit {p.adr_max_used:g}%)")
        if d and not r["cf_g_atr"]:
            why.append(f"volatility too low ({100 * r['atr'] / r['close']:.3f}% of price; needs {p.min_atr_pct:g}%)")
    score = _num(r["cf_score"], 1)
    summary = (f"CONFLUENCE: {'BUY CE candidate (bullish)' if direction > 0 else 'BUY PE candidate (bearish)'}; confirmation score {score:.0f}% "
               f"(minimum {p.min_score:g}%)" if direction else
               f"CONFLUENCE: HOLD; confirmation score {score:.0f}% (minimum {p.min_score:g}%)")
    return {**expl, "strategy": "confluence", "entry_score": score, "signal": {1: "BUY CE", -1: "BUY PE"}.get(direction, "HOLD"),
            "direction": direction, "hold_reasons": why, "summary": summary, "bias_signal": {1: "BUY CE", -1: "BUY PE"}.get(int(r.get("bias_direction", 0)), "HOLD"),
            "confluence": {"score": score, "min_score": p.min_score, "direction": direction, "candidate": side, "passed": bool(direction),
                           "factors": factors, "rejections": why,
                           "adr": {"period": p.adr_period, "filter": p.adr_filter, "max_used": p.adr_max_used, "ok": adr_ok, "text": adr_text,
                                   "range_today": _num(r["range_today"]), "rows": adr_rows},
                           "htf": {"on": p.htf, "trend15": int(r["trend15"]), "ok": bool(r["cf_g_htf"])},
                           "note": "Fixed starting rules, not fitted to any result. The score is how many enabled factors agree, not a probability of winning."}}


# ================================================================ the scored strategy (points out of 100)
# Market structure + EMA + VWAP + FVG + ADR. Same bars, studies and closed-candle rule as above; a different decision:
# every component earns points and an entry needs hard gates AND a total of at least `min_score`.
SC_COMPONENTS = {"trend": ("Market trend", 25), "ema": ("EMA 20/50/200", 15), "vwap": ("VWAP", 20), "fvg": ("Unmitigated FVG retest", 20),
                 "momentum": ("Momentum (RSI 14 + MACD)", 10), "volume": ("Volume vs SMA 20", 5), "adr": ("ADR", 5)}
SC_GATES = {"trend": "Confirmation-timeframe trend agrees", "ema": "EMA 20/50(/200) aligned", "vwap": "VWAP aligned", "fvg": "Unmitigated FVG retested and closed out",
            "momentum": "Momentum agrees (RSI or MACD)", "adr": "ADR not used up", "atr": "Enough volatility", "conflict": "No conflicting signal",
            "ctx": "Higher-timeframe context not against", "score": "Score at least the minimum"}
SC_VWAP_MIN = 12          # VWAP points that count as aligned (the close is on the right side, 0.1 ATR away or more)
SC_EMA_MIN = 8            # EMA points that count as aligned (20 above 50 and the close beyond EMA 20)


@dataclass
class ScoredParams:
    min_score: float = 80.0                # experimental minimum, out of 100
    adr_period: int = 10
    adr_max_used: float = 100.0            # an entry is refused once today's range has used this % of the ADR
    fvg_min_atr: float = 0.1
    fvg_max_age: int = 24
    ctx_tf: int = 0                        # optional higher-timeframe context (30 or 60 minutes, 0 = off): its trend must not be against
    min_atr_pct: float = 0.04
    primary: int = 5                       # entry timeframe (5 or 15 minutes)
    higher: int = 15                       # trend confirmation timeframe
    swing_k: int = 3
    ind: "bias.IndParams | None" = None    # indicator parameters (Trading Settings); None = the long-standing values

    @classmethod
    def from_cfg(cls, cfg) -> "ScoredParams":
        return cls(min_score=cfg.sc_min_score, adr_period=int(cfg.sc_adr_period), adr_max_used=cfg.sc_adr_max_used, fvg_min_atr=cfg.sc_fvg_min_atr,
                   fvg_max_age=int(cfg.sc_fvg_max_age), ctx_tf=int(cfg.sc_ctx_tf), min_atr_pct=cfg.bias_min_atr_pct,
                   primary=int(cfg.timeframe), higher=int(cfg.bias_confirm_tf), ind=bias.IndParams.from_dict(getattr(cfg, "ind", None)),
                   swing_k=bias.IndParams.from_dict(getattr(cfg, "ind", None)).swing_k)


def params_for(cfg):
    """The strategy parameters an engine configuration selects, or None for the plain bias engine."""
    if cfg.entry_strategy == "confluence":
        return ConfluenceParams.from_cfg(cfg)
    if cfg.entry_strategy == "scored":
        return ScoredParams.from_cfg(cfg)
    return None


def _side_points(f: pd.DataFrame, p: ScoredParams, s: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Points per component and the gates for trading in direction s (+1 buy CE, -1 buy PE)."""
    a = f["atr"].where(f["atr"] > 0)
    c = f["close"]
    n = pd.Series(np.arange(len(f)), index=f.index)
    opp = -s
    pts, g = pd.DataFrame(index=f.index), pd.DataFrame(index=f.index)

    struct, bos = f["struct"], f["bos_recent"]
    pts["trend"] = 15.0 * (f["trend15"] == s) + np.select([struct == s, (struct == 0) & (bos == s)], [10.0, 5.0], 0.0)

    full = (s * (f["ema20"] - f["ema50"]) > 0) & (s * (f["ema50"] - f["ema200"]) > 0) & (s * (c - f["ema20"]) > 0)
    half = (s * (f["ema20"] - f["ema50"]) > 0) & (s * (c - f["ema20"]) > 0)
    pts["ema"] = pd.Series(np.select([full, half], [15.0, 8.0], 0.0), index=f.index)

    side = s * f["vwap_dist"]
    event = (f["vwap_retest_up"] | f["vwap_reject_up"]) if s > 0 else (f["vwap_retest_dn"] | f["vwap_reject_dn"])
    vw = pd.Series(np.select([event & (side > 0), side >= 0.1 * a], [20.0, 12.0], 0.0), index=f.index)
    pts["vwap"] = vw.where(f["fut_vwap"].notna() & f["fut_close"].notna(), 0.0)

    name = "bull" if s > 0 else "bear"
    pts["fvg"] = 20.0 * (f[f"fvg_{name}_retest"] & f[f"fvg_{name}_fresh"])

    ip = p.ind or bias.IndParams()
    rsi_ok = (f["rsi"] > 50) & (f["rsi"] <= ip.rsi_hi) if s > 0 else (f["rsi"] < 50) & (f["rsi"] >= ip.rsi_lo)
    pts["momentum"] = 5.0 * rsi_ok + 5.0 * (s * f["macd_hist"] > 0)
    pts["volume"] = 5.0 * (f["vol_ratio"] >= 1.0)
    used = f[f"adr_used{p.adr_period}"]
    pts["adr"] = 5.0 * (used.notna() & (used <= p.adr_max_used))

    g["trend"] = f["trend15"] == s
    g["ema"] = (pts["ema"] >= SC_EMA_MIN) & (n >= 3 * 200)
    g["vwap"] = pts["vwap"] >= SC_VWAP_MIN
    g["fvg"] = pts["fvg"] >= 20
    g["momentum"] = pts["momentum"] >= 5
    g["adr"] = used.isna() | (used <= p.adr_max_used)
    g["atr"] = (100 * f["atr"] / c) >= p.min_atr_pct
    opp_rsi = (f["rsi"] < 50) if s > 0 else (f["rsi"] > 50)
    opp_fvg = f["fvg_bear_retest"] if s > 0 else f["fvg_bull_retest"]
    g["conflict"] = ~((struct == opp) | (opp_rsi & (opp * f["macd_hist"] > 0)) | opp_fvg)
    g["ctx"] = (f["trend_ctx"] * s >= 0) if "trend_ctx" in f else pd.Series(True, index=f.index)
    return pts, g


def sc_decide(f: pd.DataFrame, p: ScoredParams) -> pd.DataFrame:
    """Per bar: the side that leads, its points per component, each gate and the entry direction (0 = none)."""
    pl, gl = _side_points(f, p, 1)
    ps, gs = _side_points(f, p, -1)
    tl, ts = pl.sum(axis=1), ps.sum(axis=1)
    cand = pd.Series(np.where(tl > ts, 1, np.where(ts > tl, -1, 0)), index=f.index)
    out = pd.DataFrame(index=f.index)
    out["sc_cand"], out["sc_score"] = cand, np.maximum(tl, ts)
    out["sc_score_long"], out["sc_score_short"] = tl, ts
    use_long = cand >= 0                       # no leader: describe the long side
    for k in SC_COMPONENTS:
        out[f"sc_pts_{k}"] = pl[k].where(use_long, ps[k])
    ok = pd.Series(True, index=f.index)
    for k in ("trend", "ema", "vwap", "fvg", "momentum", "adr", "atr", "conflict", "ctx"):
        col = gl[k].where(use_long, gs[k]).astype(bool)
        out[f"sc_g_{k}"] = col
        ok &= col
    out["sc_g_score"] = out["sc_score"] >= p.min_score
    out["sc_direction"] = cand.where(ok & out["sc_g_score"] & (cand != 0), 0).astype(int)
    return out


def sc_explain(r: pd.Series, p: ScoredParams, expl: dict) -> dict:
    """The bias explanation with the scored strategy's points, gates and rejection reasons, and its decision in place of the
    bias entry decision (`signal`, `direction`, `hold_reasons`, `summary`, `entry_score`)."""
    cand, direction = int(r["sc_cand"]), int(r["sc_direction"])
    s = cand or 1
    side = {1: "BUY CE", -1: "BUY PE"}[s]
    word = "bullish" if s > 0 else "bearish"
    hi = f"{p.higher}-minute"
    base = _conditions(r, ConfluenceParams())
    t15 = int(r["trend15"])
    struct = r.get("struct")
    e20, e50, e200, c = (float(r[k]) for k in ("ema20", "ema50", "ema200", "close"))
    rsi, hist, ratio = r.get("rsi"), r.get("macd_hist"), r.get("vol_ratio")
    used = _num(r.get(f"adr_used{p.adr_period}"), 1)
    name = "bull" if s > 0 else "bear"
    z = _fvg_side(r, name)
    cond = {
        "trend": f"{hi} trend is {'bullish' if t15 > 0 else 'bearish' if t15 < 0 else 'neutral'}; 5-minute structure: "
                 + ("not enough swings yet" if pd.isna(struct) else "higher highs and lows" if struct > 0 else "lower highs and lows" if struct < 0 else "mixed swings"),
        "ema": f"EMA 20 {e20:,.2f}, 50 {e50:,.2f}, 200 {e200:,.2f}; close {c:,.2f} is {'above' if c > e20 else 'below'} EMA 20",
        "vwap": base["vwap"][0],
        "fvg": ("no active " + word + " gap" if z is None else
                f"{word} gap {z['lo']:,.2f}-{z['hi']:,.2f} {z['state']}"
                + (", first return retested and closed out now" if z["retest"] and r[f"fvg_{name}_fresh"] else ", retested but it was already mitigated" if z["retest"] else f", {z['age_bars']} bars old, no retest")),
        "momentum": "RSI " + ("n/a" if pd.isna(rsi) else f"{rsi:.1f}") + ", MACD histogram " + ("n/a" if pd.isna(hist) else f"{hist:+.2f}"),
        "volume": "volume " + ("n/a (no futures volume)" if pd.isna(ratio) else f"{ratio:.2f}× its 20-bar average"),
        "adr": "ADR unavailable (too few sessions): not checked" if used is None else f"today's range has used {used:.0f}% of the {p.adr_period}-day ADR (limit {p.adr_max_used:g}%)",
    }
    comps = []
    for k, (label, mx) in SC_COMPONENTS.items():
        pt = float(r[f"sc_pts_{k}"])
        comps.append({"key": k, "label": label, "max": mx, "points": pt, "condition": cond[k], "earned": pt >= mx})
    why_text = {
        "trend": f"the {hi} trend is not {word}", "ema": f"EMA 20/50/200 are not aligned for {side}",
        "vwap": "VWAP is unavailable (no futures candles)" if pd.isna(r.get("fut_vwap")) else f"the close is not on the {'above' if s > 0 else 'below'} side of VWAP by 0.1 ATR",
        "fvg": "no unmitigated fair value gap was retested and closed out on this candle", "momentum": f"neither RSI nor MACD supports {side}",
        "adr": f"ADR exhausted: today's range has used {used if used is not None else 0:.0f}% of the {p.adr_period}-day ADR (limit {p.adr_max_used:g}%)",
        "atr": f"volatility too low ({100 * r['atr'] / r['close']:.3f}% of price; needs {p.min_atr_pct:g}%)",
        "conflict": "a conflicting signal is present (opposite structure, opposite momentum or an opposite gap retest)",
        "ctx": f"the {p.ctx_tf}-minute context trend is against {side}", "score": f"score {r['sc_score']:.0f} is below the minimum {p.min_score:g}",
    }
    gates = [{"key": k, "label": label, "ok": bool(r[f"sc_g_{k}"]), "text": "met" if bool(r[f"sc_g_{k}"]) else why_text[k]} for k, label in SC_GATES.items()
             if k != "ctx" or p.ctx_tf]
    why = [g["text"] for g in gates if not g["ok"]] if cand else ["neither side leads: the long and short scores are equal"]
    score = _num(r["sc_score"], 1)
    sig = {1: "BUY CE", -1: "BUY PE"}.get(direction, "HOLD")
    summary = (f"SCORED: {'BUY CE candidate (bullish)' if direction > 0 else 'BUY PE candidate (bearish)'}; score {score:.0f}/100 (minimum {p.min_score:g})" if direction
               else f"SCORED: HOLD; best score {score:.0f}/100 (minimum {p.min_score:g})")
    return {**expl, "strategy": "scored", "entry_score": score, "signal": sig, "direction": direction, "hold_reasons": why, "summary": summary,
            "bias_signal": {1: "BUY CE", -1: "BUY PE"}.get(int(r.get("bias_direction", 0)), "HOLD"),
            "scored": {"score": score, "min_score": p.min_score, "candidate": side if cand else None, "direction": direction, "passed": bool(direction),
                       "components": comps, "gates": gates, "rejections": why, "score_long": _num(r["sc_score_long"], 1), "score_short": _num(r["sc_score_short"], 1),
                       "entry_tf": p.primary, "confirm_tf": p.higher, "ctx_tf": p.ctx_tf,
                       "note": "Fixed starting rules, not fitted to any result. The score is how many conditions are met, not a probability of winning."}}


def scored_research_signals(cf: pd.DataFrame) -> pd.DataFrame:
    """The scored strategy as an entries.py-style column (+1 / 0 / -1, fired when its entry state begins): same rules as live."""
    d = cf["sc_direction"]
    begin = pd.Series(np.where((d != 0) & (d != d.shift(1).fillna(0)), d, 0), index=cf.index).astype(int)
    return pd.DataFrame({"scored": begin.where(cf["atr"].notna(), 0)})

"""Signals of the strategies that are ON in Trading Settings (entry strategy `configured` of the bias engine; paper and replay only).

Pure (no I/O). Closed candles only and causal: a value on a candle uses that candle and earlier ones, so a later candle never changes
an earlier signal (tests check). Each strategy that is ON and not blocked (a required indicator or the entry timeframe is OFF) gives a
direction per closed entry-timeframe candle; a strategy that is OFF or blocked is never evaluated and can never give a signal.

* crossover strategies (the seven EMA strategies, fast / slow from the settings): a confirmed fresh cross;
* bias, confluence, scored: the existing analysis with the thresholds, indicators and parameters from the settings;
* research entry methods (`entries.py`): their fixed rules.
Crossovers and research methods are also held to the trend timeframe (EMA 20/50 of its closed candles must agree) when the setting
`trend_filter` is on; the bias-family strategies apply their own trend confirmation.

Several strategies may be ON. Signals of the same direction on one candle are ONE order (recorded with every strategy that fired);
opposite directions on one candle are a conflict and no order is placed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.strategy import bias, confluence, entries, strategies
from app.services.strategy import rules as st
from app.services.trading import trading_settings as ts

BIAS_FAMILY = ("bias", "confluence", "scored")


def _by_ts(close_ts: pd.Series, values) -> pd.Series:
    return pd.Series(np.asarray(values), index=pd.DatetimeIndex(close_ts))


def crossover_series(spot, fut, key: str, res: "ts.Resolved") -> pd.Series:
    """+1 / -1 on each closed candle where the strategy's EMAs cross and its confirmation (VWAP, RSI or MACD, if any) agrees, else 0."""
    p = res.params(key)
    bars = strategies.prepare(spot, fut, res.entry_tf, key, res.ind_params(), p["fast"], p["slow"])
    out = pd.Series(0, index=pd.DatetimeIndex(bars["close_ts"]) if len(bars) else pd.DatetimeIndex([]), dtype=int)
    if bars.empty:
        return out
    cx = st.find_crosses(bars, "fast", "slow")
    for r in cx.itertuples():
        ok = bool(r.bull_ok if r.direction > 0 else r.bear_ok)
        if ok:
            out.loc[pd.Timestamp(r.close_ts)] = int(r.direction)
    return out


def evaluate(res: "ts.Resolved", spot: pd.DataFrame, fut: pd.DataFrame | None, bf: pd.DataFrame, cfg, bar_close) -> tuple[pd.DataFrame, dict]:
    """The bias frame `bf` with `direction` replaced by the combined decision of the strategies that are ON (the bias candidate is kept as
    `bias_direction`), and a description of the last candle: what every registered strategy did and why. Rows are matched on close time."""
    out = bf.copy()
    out["bias_direction"] = out["direction"]
    idx = pd.DatetimeIndex(out["close_ts"])
    active = res.active()
    raw: dict[str, pd.Series] = {}
    notes: dict[str, str] = {}

    need_frame = any(ts.STRATEGIES[k]["kind"] in ("crossover", "method") for k in active)
    ef = entries.frame(spot, fut, res.entry_tf, res.trend_tf, res.ind_params()) if need_frame else None
    trend = _by_ts(ef["close_ts"], ef["trend15"]) if ef is not None and not ef.empty else pd.Series(dtype=int)
    sigs = entries.signals(ef) if ef is not None and not ef.empty and any(ts.STRATEGIES[k]["kind"] == "method" for k in active) else None

    cf_frame = sc_frame = None
    for key in active:
        kind = ts.STRATEGIES[key]["kind"]
        if kind == "crossover":
            raw[key] = crossover_series(spot, fut, key, res)
        elif kind == "method":
            raw[key] = _by_ts(ef["close_ts"], sigs[key[2:]].to_numpy()) if sigs is not None else pd.Series(dtype=int)
        elif kind == "bias":
            raw[key] = _by_ts(out["close_ts"], out["bias_direction"].to_numpy())
        elif kind == "confluence":
            cf_frame = confluence.analyse(spot, fut, confluence.ConfluenceParams.from_cfg(cfg))
            raw[key] = _by_ts(cf_frame["close_ts"], cf_frame["cf_direction"].to_numpy()) if not cf_frame.empty else pd.Series(dtype=int)
        elif kind == "scored":
            sc_frame = confluence.analyse(spot, fut, confluence.ScoredParams.from_cfg(cfg))
            raw[key] = _by_ts(sc_frame["close_ts"], sc_frame["sc_direction"].to_numpy()) if not sc_frame.empty else pd.Series(dtype=int)

    final: dict[str, pd.Series] = {}
    for key, s in raw.items():
        s = s[~s.index.duplicated(keep="last")].reindex(idx).fillna(0).astype(int)
        if ts.STRATEGIES[key]["kind"] in ("crossover", "method") and res.trend_filter:
            t = trend[~trend.index.duplicated(keep="last")].reindex(idx).fillna(0).astype(int) if len(trend) else pd.Series(0, index=idx)
            s_f = s.where(t * s > 0, 0)
            notes[key] = "" if s.iloc[-1:].eq(s_f.iloc[-1:]).all() else f"the {res.trend_tf}-minute trend does not agree"
        else:
            s_f = s
        final[key] = (s, s_f)
    D = pd.DataFrame({k: v[1] for k, v in final.items()}, index=idx) if final else pd.DataFrame(index=idx)
    pos = (D > 0).any(axis=1) if len(D.columns) else pd.Series(False, index=idx)
    neg = (D < 0).any(axis=1) if len(D.columns) else pd.Series(False, index=idx)
    direction = pd.Series(np.where(pos & ~neg, 1, np.where(neg & ~pos, -1, 0)), index=idx)
    out["direction"] = direction.to_numpy()
    out["cfg_conflict"] = (pos & neg).to_numpy()

    # the last candle: every registered strategy and what it did
    last = idx[-1] if len(idx) else None
    rows, fired = [], []
    d_last = int(direction.iloc[-1]) if last is not None else 0
    for key, reg in ts.STRATEGIES.items():
        row = {"key": key, "label": reg["label"], "kind": reg["kind"], "direction": 0}
        if not res.strategy_enabled(key):
            row.update(state="off", reason="switched off in Trading Settings")
        elif res.blockers(key):
            row.update(state="blocked", reason="; ".join(res.blockers(key)))
        else:
            raw_d = int(final[key][0].iloc[-1]) if key in final and last is not None else 0
            f_d = int(final[key][1].iloc[-1]) if key in final and last is not None else 0
            row["direction"] = f_d
            if f_d:
                row.update(state="signal", reason=f"{'BUY CE' if f_d > 0 else 'BUY PE'} signal on the {res.entry_tf}-minute candle")
                if f_d == d_last:
                    fired.append(key)
            elif raw_d:
                row.update(state="rejected", reason=notes.get(key) or "filtered")
            else:
                row.update(state="no signal", reason="no entry condition met on this candle")
        rows.append(row)
    score = None
    if last is not None and d_last:
        sc = []
        if "bias" in fired:
            sc.append(float(out["confidence"].iloc[-1]))
        if "confluence" in fired and cf_frame is not None and not cf_frame.empty:
            sc.append(float(cf_frame.loc[pd.DatetimeIndex(cf_frame["close_ts"]) == last, "cf_score"].iloc[0]))
        if "scored" in fired and sc_frame is not None and not sc_frame.empty:
            sc.append(float(sc_frame.loc[pd.DatetimeIndex(sc_frame["close_ts"]) == last, "sc_score"].iloc[0]))
        score = max(sc) if sc else None
    info = {"direction": d_last, "fired": fired, "conflict": bool(pos.iloc[-1] and neg.iloc[-1]) if last is not None else False, "score": score,
            "strategies": rows, "active": active, "entry_tf": res.entry_tf, "trend_tf": res.trend_tf}
    return out, info


def explain(expl: dict, info: dict, res: "ts.Resolved") -> dict:
    """The bias explanation with the configured decision in place of the bias entry decision."""
    d = info["direction"]
    sig = {1: "BUY CE", -1: "BUY PE"}.get(d, "HOLD")
    why = []
    if not d:
        if info["conflict"]:
            why.append("strategies disagree on this candle (one says BUY CE, another BUY PE): no trade")
        if not info["active"]:
            why.append("no strategy is able to trade: none is ON, or every ON strategy is blocked by a disabled indicator or timeframe")
        why += [f"{r['label']}: {r['reason']}" for r in info["strategies"] if r["state"] == "rejected"]
    labels = {r["key"]: r["label"] for r in info["strategies"]}
    summary = (f"CONFIGURED: {sig} candidate from {', '.join(labels[k] for k in info['fired'])}" if d else
               f"CONFIGURED: HOLD ({len(info['active'])} strateg{'y' if len(info['active']) == 1 else 'ies'} active, none signalled)")
    return {**expl, "strategy": info["fired"][0] if info["fired"] else "configured", "signal": sig, "direction": d, "hold_reasons": why, "summary": summary,
            "entry_score": info["score"] if info["score"] is not None else expl.get("confidence"),
            "configured": {"settings_version": res.version, "fired": info["fired"], "conflict": info["conflict"], "strategies": info["strategies"],
                           "entry_tf": info["entry_tf"], "trend_tf": info["trend_tf"], "active": info["active"]}}

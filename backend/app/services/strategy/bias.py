"""Multi-timeframe market bias: every enabled indicator votes on the 5-minute and 15-minute bars,
the votes are combined into a directional bias, a next-candle prediction and an entry candidate.

Everything here is pure (no I/O) and causal: the value on a bar uses that bar and earlier bars only.
`analyse()` works on the whole series in one pass, so the live engine (last row), the prediction log
and the backtest all use the same numbers; tests check that appending later candles never changes an
earlier row (no look-ahead, no repainting).

Votes are in [-1, +1] (bullish positive); NaN means "cannot vote" (not enough bars, no futures data,
no divergence) and is left out of the average instead of counting as neutral:

  ema_9_21, ema_5_20, ema_8_21, ema_20_50   (fast - slow) / (0.35 x ATR)
  ema_200                                   (close - EMA200) / (1.5 x ATR), after 200 bars
  vwap                                      (futures close - session VWAP) / (0.5 x ATR)
  rsi                                       (RSI14 - 50) / 15
  rsi_divergence                            regular +-1.0, hidden +-0.6, from swing pivots confirmed 3 bars
                                            later, kept for 6 bars (a pivot is only known after it formed)
  macd                                      0.6 histogram + 0.2 line side + 0.2 fresh crossover (3 bars)
  bollinger                                 breakout beyond a band +-1, inside the bands 0.5 x %b
  volume                                    futures volume vs the previous 20 bars, signed by the bar's
                                            direction (0 below 1.2x, full at 1.8x)
  sr                                        previous-day high/low breakout +-1; inside the range a lean
                                            toward the nearer side, headwind near the high / floor near the low
  (ATR is not a direction: it only gates entries when volatility is too low.)

A timeframe's score is the weighted mean of its votes. Bias = 0.6 x 15m score + 0.4 x 5m score,
or NEUTRAL when the two timeframes disagree. "Confidence" is the share of the weighted indicator
vote that points the same way (minus half of what points the other way). It measures agreement
between indicators. It is NOT a probability of winning; the weights and thresholds are fixed
constants that were not fitted to any result.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields

import numpy as np
import pandas as pd

from app.services.strategy import indicators as ind
from app.services.strategy import rules as st
from app.services.strategy import strategies

@dataclass(frozen=True)
class IndParams:
    """Indicator parameters (Trading Settings). The defaults are the values this code always used, so passing nothing changes nothing."""
    rsi_period: int = 14
    rsi_hi: float = 75.0           # the scored strategy's momentum counts RSI only inside (50, rsi_hi] for a buy and [rsi_lo, 50) for a sell
    rsi_lo: float = 25.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    vol_sma: int = 20              # period of the volume average (column `vol_avg20` keeps its name)
    div_k: int = 3                 # RSI divergence: a swing pivot is confirmed this many bars later
    div_decay: int = 6             # and a divergence stays valid this many bars
    swing_k: int = 3               # market structure: a swing pivot is confirmed this many bars later

    @classmethod
    def from_dict(cls, d: dict | None) -> "IndParams":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


# key -> (label, weight)
INDICATORS = {
    "ema_9_21": ("EMA 9/21", 1.0),
    "ema_5_20": ("EMA 5/20", 0.5),
    "ema_8_21": ("EMA 8/21", 0.5),
    "ema_20_50": ("EMA 20/50", 1.0),
    "ema_200": ("200 EMA", 1.0),
    "vwap": ("VWAP", 1.0),
    "rsi": ("RSI", 0.75),
    "rsi_divergence": ("RSI divergence", 0.5),
    "macd": ("MACD", 1.0),
    "bollinger": ("Bollinger Bands", 0.75),
    "volume": ("Volume expansion", 0.5),
    "sr": ("Support / resistance", 1.0),
}
_EMA_PAIRS = {"ema_9_21": (9, 21), "ema_5_20": (5, 20), "ema_8_21": (8, 21), "ema_20_50": (20, 50)}
LABELS = ("STRONG BEARISH", "BEARISH", "NEUTRAL", "BULLISH", "STRONG BULLISH")
VOTE_MIN = 0.10     # |vote| below this neither supports nor opposes


@dataclass
class BiasParams:
    enabled: tuple = tuple(INDICATORS)
    trend_thr: float = 0.25        # |15m score| needed for a trend (and for an entry)
    confirm_thr: float = 0.20      # |5m score| needed to confirm an entry
    min_confidence: float = 55.0   # % agreement needed for an entry
    w15: float = 0.60              # weight of the 15m score in the combined bias
    mild: float = 0.20             # |combined| for BULLISH / BEARISH
    strong: float = 0.50           # |combined| for STRONG BULLISH / STRONG BEARISH
    predict_thr: float = 0.15      # |combined| needed to predict a direction (else NEUTRAL)
    min_atr_pct: float = 0.04      # entries need 5m ATR of at least this % of price
    flat_atr: float = 0.10         # next-candle moves below this x ATR count as NEUTRAL (flat)
    primary: int = 5               # analysis candle (minutes); entries are decided on its close
    higher: int = 15               # confirmation candle (minutes); its trend is the primary directional filter
    ind: IndParams = field(default_factory=IndParams)

    @classmethod
    def from_cfg(cls, cfg) -> "BiasParams":
        en = tuple(k for k in (cfg.bias_indicators or INDICATORS) if k in INDICATORS) or tuple(INDICATORS)
        return cls(enabled=en, trend_thr=cfg.bias_trend_thr, confirm_thr=cfg.bias_confirm_thr,
                   min_confidence=cfg.bias_min_confidence, min_atr_pct=cfg.bias_min_atr_pct,
                   primary=int(cfg.timeframe), higher=int(cfg.bias_confirm_tf), ind=IndParams.from_dict(getattr(cfg, "ind", None)))


def _clip(x):
    return np.clip(x, -1.0, 1.0)


# ---------------------------------------------------------------- one timeframe
def tf_bars(spot1m: pd.DataFrame, fut1m: pd.DataFrame | None, tf: int, ip: IndParams | None = None) -> pd.DataFrame:
    """Closed bars of one timeframe with every indicator the votes need (parameters from `ip`, the long-standing values by default)."""
    ip = ip or IndParams()
    b = st.resample(spot1m, tf)
    if b.empty:
        return b
    c = b["close"]
    b["atr"] = ind.atr(b, ip.atr_period)
    b["rsi"] = ind.rsi(c, ip.rsi_period)
    b["macd"], b["macd_sig"], b["macd_hist"] = ind.macd(c, ip.macd_fast, ip.macd_slow, ip.macd_signal)
    for n in (5, 8, 9, 20, 21, 50, 200):
        b[f"ema{n}"] = ind.ema(c, n)
    mid, sd = c.rolling(ip.bb_period).mean(), c.rolling(ip.bb_period).std(ddof=0)
    b["bb_mid"], b["bb_up"], b["bb_lo"] = mid, mid + ip.bb_std * sd, mid - ip.bb_std * sd
    fb = strategies.futures_bars(fut1m, tf)
    if fb.empty:
        for col in ("fut_close", "fut_vwap", "fut_volume"):
            b[col] = np.nan
    else:
        b = b.merge(fb, on="start", how="left")
    b["vol_avg20"] = b["fut_volume"].shift(1).rolling(ip.vol_sma, min_periods=max(2, ip.vol_sma // 2)).mean()
    prev = b.groupby("day").agg(pdh=("high", "max"), pdl=("low", "min"), pdc=("close", "last")).shift(1)
    return b.join(prev, on="day")


def divergence(b: pd.DataFrame, k: int = 3, decay: int = 6) -> pd.Series:
    """RSI divergence votes. A swing low/high at bar j is only known at bar j+k, so it is recorded there."""
    n = len(b)
    low, high, rsi = b["low"].to_numpy(float), b["high"].to_numpy(float), b["rsi"].to_numpy(float)
    win = 2 * k + 1
    lo_piv = (b["low"].shift(k) == b["low"].rolling(win).min()).to_numpy()
    hi_piv = (b["high"].shift(k) == b["high"].rolling(win).max()).to_numpy()
    ev = np.full(n, np.nan)
    last_lo = last_hi = None
    for i in np.flatnonzero(lo_piv | hi_piv):
        j = i - k
        if j < 0 or np.isnan(rsi[j]):
            continue
        val = 0.0
        if lo_piv[i]:
            if last_lo is not None:
                pl, rl = last_lo
                if low[j] < pl and rsi[j] > rl:
                    val += 1.0          # regular bullish: lower low in price, higher low in RSI
                elif low[j] > pl and rsi[j] < rl:
                    val += 0.6          # hidden bullish: higher low in price, lower low in RSI
            last_lo = (low[j], rsi[j])
        if hi_piv[i]:
            if last_hi is not None:
                ph, rh = last_hi
                if high[j] > ph and rsi[j] < rh:
                    val -= 1.0          # regular bearish
                elif high[j] < ph and rsi[j] > rh:
                    val -= 0.6          # hidden bearish
            last_hi = (high[j], rsi[j])
        if val:
            ev[i] = float(np.clip(val, -1, 1))
    return pd.Series(ev, index=b.index).ffill(limit=decay - 1)


def votes(b: pd.DataFrame, ip: IndParams | None = None) -> pd.DataFrame:
    """Every indicator's vote on every bar of one timeframe (NaN = cannot vote)."""
    ip = ip or IndParams()
    v = pd.DataFrame(index=b.index)
    if b.empty:
        return pd.DataFrame(columns=list(INDICATORS))
    a = b["atr"].where(b["atr"] > 0)
    n = pd.Series(np.arange(len(b)), index=b.index)
    close = b["close"]
    for key, (f, s) in _EMA_PAIRS.items():
        v[key] = pd.Series(_clip((b[f"ema{f}"] - b[f"ema{s}"]) / (0.35 * a)), index=b.index).where(n >= 3 * s)
    v["ema_200"] = pd.Series(_clip((close - b["ema200"]) / (1.5 * a)), index=b.index).where(n >= 200)
    v["vwap"] = pd.Series(_clip((b["fut_close"] - b["fut_vwap"]) / (0.5 * a)), index=b.index)
    v["rsi"] = _clip((b["rsi"] - 50) / 15)
    v["rsi_divergence"] = divergence(b, ip.div_k, ip.div_decay)

    sgn = np.sign(b["macd_hist"])
    crossed = (sgn != sgn.shift(1)) & sgn.shift(1).notna() & (sgn != 0)
    fresh = (crossed.astype(float) * sgn).where(crossed).ffill(limit=2).fillna(0.0)
    v["macd"] = (0.6 * _clip(b["macd_hist"] / (0.1 * a)) + 0.2 * np.sign(b["macd"]) + 0.2 * fresh).where(n >= 35)

    half = (b["bb_up"] - b["bb_lo"]) / 2
    pb = (close - b["bb_mid"]) / half.where(half > 0)
    v["bollinger"] = pd.Series(np.where(close > b["bb_up"], 1.0, np.where(close < b["bb_lo"], -1.0, 0.5 * pb)),
                               index=b.index).where(b["bb_up"].notna())

    ratio = b["fut_volume"] / b["vol_avg20"].where(b["vol_avg20"] > 0)
    v["volume"] = (np.sign(close - b["open"]) * np.clip((ratio - 1.2) / 0.6, 0, 1))

    rng = (b["pdh"] - b["pdl"])
    lean = 0.4 * _clip((close - (b["pdh"] + b["pdl"]) / 2) / (rng / 2).where(rng > 0))
    lean = lean.mask((b["pdh"] - close).between(0, 0.3 * a) & (lean > 0), -0.3)    # headwind just under the high
    lean = lean.mask((close - b["pdl"]).between(0, 0.3 * a) & (lean < 0), 0.3)     # floor just above the low
    v["sr"] = pd.Series(np.where(close > b["pdh"], 1.0, np.where(close < b["pdl"], -1.0, lean)),
                        index=b.index).where(b["pdh"].notna())
    return v[list(INDICATORS)]


def _weights(enabled) -> pd.Series:
    return pd.Series({k: INDICATORS[k][1] for k in enabled})


def tf_score(v: pd.DataFrame, enabled) -> pd.Series:
    """Weighted mean vote per bar; NaN when fewer than 30% of the enabled weight can vote."""
    w = _weights(enabled)
    vv = v[list(enabled)]
    den = vv.notna().mul(w, axis=1).sum(axis=1)
    num = vv.mul(w, axis=1).sum(axis=1, skipna=True)
    return (num / den.where(den >= 0.3 * w.sum()))


def label(c: float, p: BiasParams) -> str:
    if c is None or np.isnan(c):
        return "NEUTRAL"
    return ("STRONG " if abs(c) >= p.strong else "") + ("BULLISH" if c > 0 else "BEARISH") if abs(c) >= p.mild else "NEUTRAL"


def trend_word(s: float, p: BiasParams) -> str:
    if s is None or np.isnan(s) or abs(s) < p.trend_thr:
        return "Neutral"
    return "Bullish" if s > 0 else "Bearish"


# ---------------------------------------------------------------- both timeframes
def analyse(spot1m: pd.DataFrame, fut1m: pd.DataFrame | None, params: BiasParams | None = None) -> pd.DataFrame:
    """One row per closed analysis bar (default 5m): its score and the confirmation timeframe's score (default 15m),
    bias, confidence, prediction, entry candidate. Column suffixes 5 / 15 are slot names (analysis / confirmation),
    whatever the timeframes are. An analysis bar only sees confirmation bars that had closed by its own close time."""
    p = params or BiasParams()
    b5, b15 = tf_bars(spot1m, fut1m, p.primary, p.ind), tf_bars(spot1m, fut1m, p.higher, p.ind)
    if b5.empty:
        return pd.DataFrame()
    v5, v15 = votes(b5, p.ind), (votes(b15, p.ind) if not b15.empty else pd.DataFrame(columns=list(INDICATORS)))
    s5 = tf_score(v5, p.enabled)
    s15_own = tf_score(v15, p.enabled) if not b15.empty else pd.Series(dtype=float)

    out = b5[["start", "close_ts", "day", "open", "high", "low", "close", "atr", "rsi", "ema9", "ema21", "ema50", "ema200",
              "macd_hist", "bb_up", "bb_lo", "fut_close", "fut_vwap", "pdh", "pdl"]].copy()
    out["s5"] = s5
    for k in INDICATORS:
        out[f"v5_{k}"] = v5[k]
    # attach the latest CLOSED 15m bar to each 5m bar (backward as-of on close time)
    if not b15.empty:
        h = pd.concat([b15[["close_ts", "rsi"]].rename(columns={"rsi": "rsi15"}), s15_own.rename("s15"),
                       v15.add_prefix("v15_")], axis=1).sort_values("close_ts")
        out = pd.merge_asof(out.sort_values("close_ts"), h, on="close_ts", direction="backward")
    else:
        out["s15"], out["rsi15"] = np.nan, np.nan
        for k in INDICATORS:
            out[f"v15_{k}"] = np.nan
    out = out.reset_index(drop=True)

    s5, s15 = out["s5"], out["s15"]
    comb = (p.w15 * s15 + (1 - p.w15) * s5).where(s15.notna(), s5)
    opposite = (np.sign(s15) * np.sign(s5) < 0) & (s15.abs() >= 0.15) & (s5.abs() >= 0.15)
    out["combined"] = comb
    out["conflict"] = opposite
    out["bias"] = [("NEUTRAL" if cf else label(c, p)) for c, cf in zip(comb, opposite)]
    dirn = np.sign(comb).where(~opposite, 0.0).fillna(0.0)

    # confidence: weighted agreement of the votes with the bias direction
    w = _weights(p.enabled)
    agree = against = total = 0.0
    for pre, tw in (("v5_", 1 - p.w15), ("v15_", p.w15)):
        V = out[[pre + k for k in p.enabled]].copy()
        V.columns = list(p.enabled)
        avail = V.notna().mul(w, axis=1)
        same = (np.sign(V).mul(dirn, axis=0) > 0) & (V.abs() >= VOTE_MIN)
        opp = (np.sign(V).mul(dirn, axis=0) < 0) & (V.abs() >= VOTE_MIN)
        total = total + tw * avail.sum(axis=1)
        agree = agree + tw * same.mul(w, axis=1).sum(axis=1)
        against = against + tw * opp.mul(w, axis=1).sum(axis=1)
    conf = (100 * ((agree - 0.5 * against) / total.where(total > 0)).clip(0, 1)).where(dirn != 0, 0.0)
    out["confidence"] = conf.where(out["bias"] != "NEUTRAL", 0.0).round(1)    # a NEUTRAL bias has no directional confidence
    conf = out["confidence"]
    out["atr_pct"] = 100 * out["atr"] / out["close"]

    d = dirn.astype(int)
    ok = (s15.abs() >= p.trend_thr) & (s5.abs() >= p.confirm_thr) & (np.sign(s15) == np.sign(s5)) \
        & (conf >= p.min_confidence) & (out["atr_pct"] >= p.min_atr_pct) & (d != 0)
    out["direction"] = d.where(ok, 0)
    out["predicted"] = np.where(comb.abs() >= p.predict_thr, np.where(comb > 0, "UP", "DOWN"), "NEUTRAL")
    out.loc[opposite | comb.isna(), "predicted"] = "NEUTRAL"
    return out


def classify(move: float, atr: float, flat_atr: float = 0.10) -> str:
    """Direction of a candle-to-candle move: FLAT when it is smaller than flat_atr x ATR."""
    if atr is None or pd.isna(atr) or abs(move) < flat_atr * atr:
        return "FLAT"
    return "UP" if move > 0 else "DOWN"


def classify_outcome(predicted: str, actual: str) -> str:
    """CORRECT / INCORRECT, or NEUTRAL when no direction was predicted or the next candle was flat."""
    if predicted == "NEUTRAL" or actual == "FLAT":
        return "NEUTRAL"
    return "CORRECT" if predicted == actual else "INCORRECT"


def evaluate_predictions(f: pd.DataFrame, p: BiasParams | None = None) -> pd.DataFrame:
    """Compare each bar's prediction with the NEXT 5m candle of the same day (the last bar of a day has none).
    Outcome: CORRECT / INCORRECT, or NEUTRAL when no direction was predicted or the candle barely moved."""
    p = p or BiasParams()
    f = f.copy()
    nxt = f.groupby("day")["close"].shift(-1)
    f["next_close"] = nxt
    move = nxt - f["close"]
    f["actual"] = [None if pd.isna(m) else classify(m, a, p.flat_atr) for m, a in zip(move, f["atr"])]
    out = [None if act is None else classify_outcome(pred, act) for pred, act in zip(f["predicted"], f["actual"])]
    f["outcome"] = out
    return f


def accuracy(f: pd.DataFrame, p: BiasParams | None = None) -> list[dict]:
    """Next-candle hit rate of the combined prediction and of each indicator, on the 5m and the 15m vote.
    An indicator 'predicts' its vote's sign when |vote| >= 0.1. NEUTRAL (no call or a flat candle) is counted
    separately and is not part of the accuracy. A 15m vote is scored against the same next 5m candle."""
    p = p or BiasParams()
    f = evaluate_predictions(f, p) if "outcome" not in f else f
    f = f[f["actual"].notna()]
    rows = []

    def row(key, label_, tf, pred):
        act = f["actual"]
        called = pred.isin(["UP", "DOWN"]) & act.isin(["UP", "DOWN"])
        n_ok, n_bad = int(((pred == act) & called).sum()), int(((pred != act) & called).sum())
        n = n_ok + n_bad
        rows.append({"key": key, "label": label_, "timeframe": tf, "correct": n_ok, "incorrect": n_bad,
                     "neutral": int(len(f) - n), "accuracy": round(100 * n_ok / n, 1) if n else None, "n": n})

    lab5, lab15 = f"{p.primary}m", f"{p.higher}m"
    row("combined", "Combined bias", f"{lab5}+{lab15}", f["predicted"])
    for k in p.enabled:
        for tf, col in ((lab5, f"v5_{k}"), (lab15, f"v15_{k}")):
            vv = f[col]
            row(k, INDICATORS[k][0], tf, pd.Series(np.where(vv >= VOTE_MIN, "UP", np.where(vv <= -VOTE_MIN, "DOWN", "NEUTRAL")),
                                                   index=f.index))
    return rows


# ---------------------------------------------------------------- explanation of one row
def _v(x, nd=2):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def explain(r: pd.Series, p: BiasParams | None = None) -> dict:
    """Everything the dashboard and the trade record need to say why the bias is what it is."""
    p = p or BiasParams()
    lab5, lab15 = f"{p.primary}m", f"{p.higher}m"
    d = int(np.sign(r["combined"])) if pd.notna(r["combined"]) and not r["conflict"] else 0
    rows, support, against = [], [], []
    for k in p.enabled:
        lab = INDICATORS[k][0]
        item = {"key": k, "label": lab, "weight": INDICATORS[k][1], "v5": _v(r.get(f"v5_{k}")), "v15": _v(r.get(f"v15_{k}"))}
        for tf, name in (("5", lab5), ("15", lab15)):
            x = item[f"v{tf}"]
            item[f"status{tf}"] = "unavailable" if x is None else "bullish" if x >= VOTE_MIN else "bearish" if x <= -VOTE_MIN else "neutral"
            if x is not None and d and abs(x) >= VOTE_MIN:
                (support if x * d > 0 else against).append(f"{lab} {name} ({x:+.2f})")
        rows.append(item)
    hold = []
    if r["direction"] == 0:
        s5, s15 = r["s5"], r["s15"]
        if pd.isna(s15):
            hold.append(f"{lab15} trend not available yet")
        elif r["conflict"]:
            hold.append(f"{lab5} ({s5:+.2f}) and {lab15} ({s15:+.2f}) disagree")
        elif abs(s15) < p.trend_thr:
            hold.append(f"{lab15} trend is neutral ({s15:+.2f}; needs ±{p.trend_thr:g})")
        elif pd.notna(s5) and abs(s5) < p.confirm_thr:
            hold.append(f"{lab5} does not confirm ({s5:+.2f}; needs ±{p.confirm_thr:g})")
        elif pd.notna(s5) and np.sign(s5) != np.sign(s15):
            hold.append(f"{lab5} and {lab15} point in opposite directions")
        if r["confidence"] < p.min_confidence:
            hold.append(f"confidence {r['confidence']:.0f}% is below your minimum {p.min_confidence:g}%")
        if r["atr_pct"] < p.min_atr_pct:
            hold.append(f"volatility too low ({lab5} ATR {r['atr_pct']:.3f}% of price; needs {p.min_atr_pct:g}%)")
    word = {1: "BUY CE candidate (bullish)", -1: "BUY PE candidate (bearish)"}.get(int(r["direction"]), "HOLD")
    summary = (f"{r['bias']}: {lab15} {trend_word(r['s15'], p).lower()} ({_v(r['s15'])}), {lab5} {trend_word(r['s5'], p).lower()} "
               f"({_v(r['s5'])}); {word}; indicator agreement {r['confidence']:.0f}%")
    return {
        "bar_close": pd.Timestamp(r["close_ts"]).isoformat(), "close": _v(r["close"]),
        "bias": r["bias"], "confidence": _v(r["confidence"], 1), "combined": _v(r["combined"]),
        "trend_5m": trend_word(r["s5"], p), "trend_15m": trend_word(r["s15"], p),
        "score_5m": _v(r["s5"]), "score_15m": _v(r["s15"]), "conflict": bool(r["conflict"]),
        "signal": {1: "BUY CE", -1: "BUY PE"}.get(int(r["direction"]), "HOLD"), "direction": int(r["direction"]),
        "prediction": r["predicted"], "atr": _v(r["atr"]), "atr_pct": _v(r["atr_pct"], 3),
        "rsi_5m": _v(r["rsi"], 1), "rsi_15m": _v(r.get("rsi15"), 1),
        "tf_primary": p.primary, "tf_confirm": p.higher,
        "values": {k: _v(r.get(k)) for k in ("ema9", "ema21", "ema50", "ema200", "macd_hist", "bb_up", "bb_lo", "fut_close",
                                             "fut_vwap", "pdh", "pdl", "open", "high", "low", "close")},
        "indicators": rows, "supports": support, "against": against, "hold_reasons": hold, "summary": summary,
        "note": "Confidence is the agreement between indicators, not a probability of winning.",
    }

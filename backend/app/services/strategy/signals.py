"""Signal engine: describes and scores each strategy crossover, and measures the score
against what actually happened afterwards.

Definitions (explicit, all tested):
* A signal is a strategy cross on a CLOSED bar whose close is inside the entry window.
  An unconfirmed cross of a confirmation strategy is reported as "No Trade".
* References use ATR(14) of the signal timeframe at the signal bar:
  entry = signal bar close; stop = entry -/+ 1 ATR; target = entry +/- 2 ATR (risk/reward 2.0).
* Outcome: from the minute the signal bar closes until 15:00, on 1-minute highs/lows.
  The target touched first = hit. The stop touched first, or neither by 15:00 = miss.
  A minute that touches both counts as a stop, because the order inside it is unknown.
* Score: ridge logistic regression on the features below, trained walk-forward: each year
  is scored only by a model trained on earlier years. Bands are judged by the hit rate
  those out-of-sample scores actually achieved, never presented as a raw probability.
* Option-chain OI, IV and Greeks are not used: Groww provides no historical option-chain
  snapshots, so they cannot be validated.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta

import numpy as np
import pandas as pd

from app.services.backtest import engine as backtest
from app.services.market_data import history as data_manager
from app.database import db
from app.services.strategy import strategies
from app.services.strategy import rules as st

VERSION = 3   # 3: calibration intervals, walk-forward Platt calibration, verdict (scores unchanged)
STOP_ATR, TARGET_ATR = 1.0, 2.0
MIN_TRAIN = 300
BANDS = [(0, 50, "No strong signal"), (50, 70, "Watch / Moderate signal"),
         (70, 85, "Strong signal"), (85, 101, "Very strong signal")]
FEATURES = [
    ("trend", "Trend strength", "slope of the slow EMA over 5 bars, in ATRs, signed by direction"),
    ("price_vs_slow", "Price vs slow EMA", "distance of close from the slow EMA, in ATRs, signed"),
    ("vwap", "VWAP position", "futures close minus futures session VWAP, in ATRs, signed"),
    ("rsi", "RSI", "(RSI(14) - 50) / 10, signed"),
    ("macd", "MACD", "MACD histogram in ATRs, signed"),
    ("volume", "Volume", "log of futures bar volume / average of the previous 20 bars"),
    ("volatility", "Volatility (ATR %)", "ATR as % of price"),
    ("regime", "Market regime", "+1 if the daily regime agrees with the direction, -1 if opposed"),
    ("high_vol", "High-volatility regime", "1 if daily ATR % is above its 1-year 80th percentile"),
    ("time", "Time of day", "fraction of the session elapsed"),
]


def band(score: float | None) -> str:
    if score is None or np.isnan(score):
        return "Not scored"
    return next(label for lo, hi, label in BANDS if lo <= score < hi)


# ---------------------------------------------------------------- regime (daily, no look-ahead)
def daily_regime(spot1m: pd.DataFrame) -> pd.DataFrame:
    """Regime for each day, from data up to the PREVIOUS day's close only."""
    d = spot1m.groupby(spot1m["ts"].dt.date).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    prev = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - prev).abs(), (d["low"] - prev).abs()], axis=1).max(axis=1)
    atr_pct = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / d["close"] * 100
    sma = d["close"].rolling(20, min_periods=20).mean()
    pct80 = atr_pct.rolling(250, min_periods=60).quantile(0.8)
    out = pd.DataFrame({"close": d["close"], "sma": sma, "sma_prev": sma.shift(5), "atr_pct": atr_pct, "p80": pct80}).shift(1)
    high_vol = out["atr_pct"] > out["p80"]
    bull = (out["close"] > out["sma"]) & (out["sma"] > out["sma_prev"])
    bear = (out["close"] < out["sma"]) & (out["sma"] < out["sma_prev"])
    out["regime"] = np.where(high_vol, "high volatility", np.where(bull, "bullish", np.where(bear, "bearish", "sideways")))
    out.loc[out["sma"].isna(), "regime"] = "unknown"
    out["high_vol"] = high_vol.astype(float)
    out["trend_sign"] = np.where(bull, 1.0, np.where(bear, -1.0, 0.0))
    return out


# ---------------------------------------------------------------- model
def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def fit(X: np.ndarray, y: np.ndarray, lam: float = 1.0) -> dict:
    """Ridge logistic regression by Newton steps; features standardised on the training set."""
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    sd[~np.isfinite(sd) | (sd == 0)] = 1.0
    mu[~np.isfinite(mu)] = 0.0
    Z = np.nan_to_num((X - mu) / sd)
    Z1 = np.c_[np.ones(len(Z)), Z]
    w = np.zeros(Z1.shape[1])
    pen = np.full(Z1.shape[1], lam)
    pen[0] = 0.0
    for _ in range(30):
        p = _sigmoid(Z1 @ w)
        g = Z1.T @ (y - p) - pen * w
        H = Z1.T @ (Z1 * (p * (1 - p))[:, None]) + np.diag(pen)
        step = np.linalg.solve(H, g)
        w += step
        if np.abs(step).max() < 1e-6:
            break
    return {"w": w, "mu": mu, "sd": sd}


def predict(model: dict, X: np.ndarray) -> np.ndarray:
    Z = np.nan_to_num((X - model["mu"]) / model["sd"])
    return _sigmoid(np.c_[np.ones(len(Z)), Z] @ model["w"])


def auc(score: np.ndarray, y: np.ndarray) -> float | None:
    pos, neg = score[y == 1], score[y == 0]
    if not len(pos) or not len(neg):
        return None
    ranks = pd.Series(np.r_[pos, neg]).rank().to_numpy()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


# ---------------------------------------------------------------- calibration (Phase 2)
# The raw score above is unchanged (prediction mode compares it with min_score). These helpers
# only measure it: what hit rate a score really corresponds to, and how uncertain that is.
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson interval for a hit rate of k out of n, in percent."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return round(max(0.0, mid - half) * 100, 1), round(min(1.0, mid + half) * 100, 1)


def _logit(score: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(score, dtype=float) / 100, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_calibrator(score: np.ndarray, y: np.ndarray) -> dict | None:
    """Platt scaling: a 1-feature logistic regression from logit(score) to the observed hit rate.
    Fitted only on out-of-sample scores, so it learns how the model's scores behave on unseen years."""
    if len(score) < 50 or y.min() == y.max():
        return None
    m = fit(_logit(score)[:, None], y.astype(float), lam=1.0)
    return {"w": m["w"].tolist(), "mu": m["mu"].tolist(), "sd": m["sd"].tolist(), "n": int(len(score))}


def apply_calibrator(cal: dict, score) -> np.ndarray:
    m = {"w": np.array(cal["w"]), "mu": np.array(cal["mu"]), "sd": np.array(cal["sd"])}
    return predict(m, _logit(np.atleast_1d(score))[:, None]) * 100


def auc_interval(score: np.ndarray, y: np.ndarray, reps: int = 400, seed: int = 7) -> tuple[float, float] | None:
    """95% bootstrap interval for the AUC (fixed seed, so a rebuild gives the same answer)."""
    if len(score) < 30 or y.min() == y.max():
        return None
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(reps):
        i = rng.integers(0, len(score), len(score))
        a = auc(score[i], y[i])
        if a is not None:
            vals.append(a)
    return (round(float(np.percentile(vals, 2.5)), 3), round(float(np.percentile(vals, 97.5)), 3)) if vals else None


def walk_forward_calibration(years: np.ndarray, score: np.ndarray, y: np.ndarray) -> dict:
    """Calibrate each out-of-sample year with a calibrator fitted on EARLIER out-of-sample years only,
    and compare it with the simplest honest forecast: the earlier years' average hit rate."""
    cal = np.full(len(score), np.nan)
    base = np.full(len(score), np.nan)
    folds = []
    for yr in sorted(set(years.tolist())):
        prior, test = years < yr, years == yr
        c = fit_calibrator(score[prior], y[prior])
        if c is None:
            continue
        cal[test] = apply_calibrator(c, score[test])
        base[test] = y[prior].mean() * 100
        p, b, yy = cal[test] / 100, base[test] / 100, y[test]
        folds.append({"year": int(yr), "n": int(test.sum()), "trained_on": int(prior.sum()),
                      "brier": _r(float(np.mean((p - yy) ** 2)), 4), "brier_base": _r(float(np.mean((b - yy) ** 2)), 4)})
    done = ~np.isnan(cal)
    out = {"folds": folds, "n": int(done.sum()), "brier": None, "brier_base": None, "skill": None}
    if done.any():
        bs = float(np.mean((cal[done] / 100 - y[done]) ** 2))
        bb = float(np.mean((base[done] / 100 - y[done]) ** 2))
        out.update(brier=_r(bs, 4), brier_base=_r(bb, 4), skill=_r((1 - bs / bb) * 100 if bb > 0 else None, 1))
    return out


def verdict(auc_ci: tuple[float, float] | None, wf: dict) -> dict:
    """Plain-language judgement of whether the score has a proven edge out of sample."""
    if auc_ci is None:
        return {"edge": False, "text": "Not enough out-of-sample signals to judge the score."}
    if auc_ci[0] <= 0.5:
        return {"edge": False, "text": f"No proven edge: the out-of-sample AUC range {auc_ci[0]:.2f}–{auc_ci[1]:.2f} includes 0.50 "
                                       "(a coin flip). Treat the score as context, not as a forecast."}
    if wf.get("skill") is None:
        return {"edge": False, "text": f"The score ranks signals better than chance (AUC {auc_ci[0]:.2f}–{auc_ci[1]:.2f}), but there "
                                       "aren't enough later years yet to test its calibrated hit rates."}
    if wf["skill"] <= 0:
        return {"edge": False, "text": f"Weak: the score ranks signals better than chance (AUC {auc_ci[0]:.2f}–{auc_ci[1]:.2f}), but its "
                                       "calibrated hit rates did not beat the plain historical average on later years."}
    return {"edge": True, "text": f"Modest edge: AUC {auc_ci[0]:.2f}–{auc_ci[1]:.2f}, and calibrated hit rates beat the historical "
                                  f"average by {wf['skill']:.1f}% (Brier skill) on later years."}


# ---------------------------------------------------------------- features + outcomes
def signal_bars(spot1m: pd.DataFrame, fut1m: pd.DataFrame | None, tf: int, key: str) -> pd.DataFrame:
    """Strategy bars plus the extra columns the features need. Used offline and live."""
    bars = strategies.prepare(spot1m, fut1m, tf, key)
    bars["slow_prev5"] = bars["slow"].shift(5)
    bars["vol_avg20"] = bars["fut_volume"].shift(1).rolling(20, min_periods=10).mean()
    return bars


def features(c, reg, d: int, atr: float, close_ts: datetime) -> tuple[dict, float]:
    """Feature values for one signal bar `c` (row of signal_bars) and its daily regime row."""
    vol_ratio = c["fut_volume"] / c["vol_avg20"] if pd.notna(c["vol_avg20"]) and c["vol_avg20"] > 0 else np.nan
    feats = {
        "trend": (c["slow"] - c["slow_prev5"]) / atr * d if pd.notna(c["slow_prev5"]) else np.nan,
        "price_vs_slow": (c["close"] - c["slow"]) / atr * d,
        "vwap": (c["fut_close"] - c["fut_vwap"]) / atr * d if pd.notna(c["fut_vwap"]) else np.nan,
        "rsi": (c["rsi"] - 50) / 10 * d if pd.notna(c["rsi"]) else np.nan,
        "macd": c["macd_hist"] / atr * d if pd.notna(c["macd_hist"]) else np.nan,
        "volume": float(np.log(vol_ratio)) if pd.notna(vol_ratio) and vol_ratio > 0 else np.nan,
        "volatility": atr / c["close"] * 100,
        "regime": (reg["trend_sign"] * d) if reg is not None else np.nan,
        "high_vol": reg["high_vol"] if reg is not None else np.nan,
        "time": ((close_ts - datetime.combine(close_ts.date(), st.SESSION_OPEN)).total_seconds() / 60) / 375,
    }
    return feats, vol_ratio


class Scorer:
    """Scores live signals with the model trained on all labelled history (Signals page)."""

    def __init__(self, analysis: dict):
        prm = (analysis.get("model") or {}).get("params")
        if not prm:
            raise LookupError("This Signals analysis has no trained model (too few signals). Rebuild it.")
        self.model = {"w": np.array(prm["w"]), "mu": np.array(prm["mu"]), "sd": np.array(prm["sd"])}
        self.calibration = analysis.get("calibration", [])
        self.calibrator = (analysis.get("model") or {}).get("calibrator")
        self.verdict = (analysis.get("model") or {}).get("verdict")
        self.built = analysis.get("generated_at")

    def score(self, feats: dict) -> float:
        x = np.array([[feats[k] for k, _, _ in FEATURES]], dtype=float)
        return float(predict(self.model, x)[0] * 100)

    def comparable(self, score: float) -> dict | None:
        c = next((c for c in self.calibration if c["from"] <= score < max(c["to"], 100.001)), None)
        if not c:
            return None
        return {"band": c["band"], "n": c["n"], "hit_rate": c["hit_rate"], "ci": c.get("ci"),
                "calibrated": _r(apply_calibrator(self.calibrator, score)[0]) if self.calibrator else None,
                "verdict": self.verdict}


def latest(strategy: str, tf: int, entry_start: str = "09:30", cutoff: str = "14:30") -> dict | None:
    """Most recent stored analysis for these settings, whatever data it was built on."""
    from sqlalchemy import text
    with db.engine().connect() as c:
        r = c.execute(text(
            "SELECT result FROM bt_runs WHERE params->>'kind'='signals' AND params->>'strategy'=:k "
            "AND (params->>'timeframe')::int=:tf AND (params->>'v')::int=:v "
            "ORDER BY (params->>'entry_start'=:a AND params->>'cutoff'=:b) DESC, created_at DESC LIMIT 1"),
            {"k": strategy, "tf": tf, "a": entry_start, "b": cutoff, "v": VERSION}).first()
    return r[0] if r else None


def _outcome(day_df: pd.DataFrame, from_ts: datetime, entry: float, direction: int, risk: float) -> tuple[str, str | None]:
    """('hit'|'miss'|'pending', time of the deciding touch)."""
    path = day_df[(day_df["ts"] >= from_ts) & (day_df["ts"].dt.time < st.SQUARE_OFF)]
    stop = entry - direction * STOP_ATR * risk
    target = entry + direction * TARGET_ATR * risk
    hi, lo = path["high"].to_numpy(), path["low"].to_numpy()
    if direction > 0:
        t_hit, s_hit = hi >= target, lo <= stop
    else:
        t_hit, s_hit = lo <= target, hi >= stop
    ti = int(np.argmax(t_hit)) if t_hit.any() else None
    si = int(np.argmax(s_hit)) if s_hit.any() else None
    complete = len(path) and path["ts"].iloc[-1].time() >= time(14, 59)
    if ti is not None and (si is None or ti < si):
        return "hit", path["ts"].iloc[ti].isoformat()
    if si is not None:
        return "miss", path["ts"].iloc[si].isoformat()
    return ("miss", None) if complete else ("pending", None)


def build(strategy: str = strategies.DEFAULT, tf: int = 15, entry_start: str = "09:30", cutoff: str = "14:30",
          progress=None) -> dict:
    say = progress or (lambda *_: None)
    s_cfg = strategies.STRATEGIES[strategy]
    first, last = data_manager.default_target()
    say(0.05, "Loading NIFTY spot and futures")
    spot = db.load_candles("NSE-NIFTY", datetime.combine(first - timedelta(days=60), time(0)),
                           datetime.combine(last + timedelta(days=1), time(0)))
    now = backtest._now()
    spot = spot[spot["ts"] + pd.Timedelta(minutes=1) <= now]
    if spot.empty:
        raise LookupError("No NIFTY data stored. Download it on the Data page first.")
    fut = data_manager.futures_1m(first - timedelta(days=60), last)
    say(0.2, "Computing indicators")
    bars = signal_bars(spot, fut, tf, strategy)
    asof = backtest._session_asof(spot)
    if asof:
        bars = bars[bars["close_ts"] <= asof].reset_index(drop=True)
    regime = daily_regime(spot)
    warm = strategies.warmup_sessions(strategy, tf)
    days = sorted(set(bars["day"]))
    first_day = days[warm] if len(days) > warm else None
    crosses = st.find_crosses(bars, "fast", "slow")
    start_t, cut_t = backtest._hm(entry_start), backtest._hm(cutoff)
    crosses = crosses[[(start_t <= t.time() <= cut_t) and t.time() < st.SQUARE_OFF for t in crosses["close_ts"]]]
    if first_day:
        crosses = crosses[crosses["day"] >= first_day]
    spot_by_day = {d: g for d, g in spot.groupby(spot["ts"].dt.date)}

    say(0.4, f"Measuring {len(crosses)} signals")
    rows = []
    for _, c in crosses.iterrows():
        d = int(c["direction"])
        atr = float(c["atr"]) if pd.notna(c["atr"]) and c["atr"] > 0 else np.nan
        reg = regime.loc[c["day"]] if c["day"] in regime.index else None
        if np.isnan(atr):
            continue
        close_ts = pd.Timestamp(c["close_ts"]).to_pydatetime()
        confirmed = bool(c["bull_ok"] if d > 0 else c["bear_ok"]) if s_cfg.confirm else True
        outcome, decided = _outcome(spot_by_day[c["day"]], close_ts, float(c["close"]), d, atr)
        feats, vol_ratio = features(c, reg, d, atr, close_ts)
        rows.append({"ts": close_ts, "day": c["day"], "direction": d, "close": float(c["close"]), "atr": atr,
                     "confirmed": confirmed, "outcome": outcome, "decided_at": decided,
                     "regime_label": reg["regime"] if reg is not None else "unknown",
                     "rsi_v": c["rsi"], "macd_v": c["macd_hist"], "fut_close": c["fut_close"], "fut_vwap": c["fut_vwap"],
                     "vol_ratio": vol_ratio, **feats})
    df = pd.DataFrame(rows)
    if df.empty:
        raise LookupError("No signals in the stored data for these settings.")
    keys = [k for k, _, _ in FEATURES]
    X = df[keys].to_numpy(dtype=float)
    y = (df["outcome"] == "hit").astype(float).to_numpy()
    labelled = (df["outcome"] != "pending") & df["confirmed"]

    say(0.7, "Walk-forward scoring")
    df["year"] = [d.year for d in df["day"]]
    df["score"] = np.nan
    df["oos"] = False
    years = sorted(df["year"].unique())
    fold_rows = []
    for yr in years:
        train = labelled & (df["year"] < yr)
        test = (df["year"] == yr) & df["confirmed"]
        if train.sum() < MIN_TRAIN or not test.any():
            continue
        m = fit(X[train.to_numpy()], y[train.to_numpy()])
        df.loc[test, "score"] = predict(m, X[test.to_numpy()]) * 100
        df.loc[test, "oos"] = True
        tl = test & labelled
        fold_rows.append({"year": int(yr), "train_signals": int(train.sum()), "test_signals": int(tl.sum()),
                          "hit_rate": round(float(y[tl.to_numpy()].mean() * 100), 1) if tl.any() else None,
                          "auc": _r(auc(df.loc[tl, "score"].to_numpy(), y[tl.to_numpy()]), 3)})
    final = fit(X[labelled.to_numpy()], y[labelled.to_numpy()]) if labelled.sum() >= MIN_TRAIN else None
    # Signals with no out-of-sample score yet (the newest, unlabelled ones) use the model trained on everything.
    fresh = df["confirmed"] & df["score"].isna() & (df["outcome"] == "pending")
    if final is not None and fresh.any():
        df.loc[fresh, "score"] = predict(final, X[fresh.to_numpy()]) * 100

    oos = df["oos"] & labelled
    s_oos, y_oos = df.loc[oos, "score"].to_numpy(), y[oos.to_numpy()]
    base = float(y_oos.mean()) if len(y_oos) else None
    calib = []
    for lo, hi, label in BANDS:
        mask = (s_oos >= lo) & (s_oos < hi)
        calib.append({"band": label, "from": lo, "to": min(hi, 100), "n": int(mask.sum()),
                      "mean_score": _r(s_oos[mask].mean()) if mask.any() else None,
                      "hit_rate": _r(y_oos[mask].mean() * 100) if mask.any() else None,
                      "ci": wilson(int(y_oos[mask].sum()), int(mask.sum()))})
    reliability = []
    if len(s_oos):
        edges = np.unique(np.percentile(s_oos, np.linspace(0, 100, 11)))
        for a, b in zip(edges[:-1], edges[1:]):
            mask = (s_oos >= a) & (s_oos <= b if b == edges[-1] else s_oos < b)
            if mask.sum():
                reliability.append({"from": _r(a), "to": _r(b), "n": int(mask.sum()),
                                    "mean_score": _r(s_oos[mask].mean()), "hit_rate": _r(y_oos[mask].mean() * 100),
                                    "ci": wilson(int(y_oos[mask].sum()), int(mask.sum()))})
    yr_oos = df.loc[oos, "year"].to_numpy()
    wf = walk_forward_calibration(yr_oos, s_oos, y_oos)
    auc_ci = auc_interval(s_oos, y_oos)
    calibrator = fit_calibrator(s_oos, y_oos)
    judged = verdict(auc_ci, wf)
    # Per-signal calibrated estimate: walk-forward for history (no look-ahead), final calibrator for new signals.
    df["calibrated"] = np.nan
    for yr in sorted(set(yr_oos.tolist())):
        prior = oos & (df["year"] < yr)
        c = fit_calibrator(df.loc[prior, "score"].to_numpy(), y[prior.to_numpy()])
        rows_yr = df["oos"] & (df["year"] == yr)
        if c is not None and rows_yr.any():
            df.loc[rows_yr, "calibrated"] = apply_calibrator(c, df.loc[rows_yr, "score"].to_numpy())
    if calibrator is not None and fresh.any():
        df.loc[fresh, "calibrated"] = apply_calibrator(calibrator, df.loc[fresh, "score"].to_numpy())

    def comparable(score):
        if score is None or np.isnan(score):
            return None
        c = next(c for c in calib if c["from"] <= score < max(c["to"], 100.001))
        return {"band": c["band"], "n": c["n"], "hit_rate": c["hit_rate"], "ci": c["ci"]}

    say(0.9, "Describing signals")
    out_rows = [_describe(r, tf, s_cfg, comparable) for r in df.tail(400).to_dict("records")]
    weights = None
    if final is not None:
        weights = [{"feature": label, "detail": detail, "weight": _r(w / 1, 3)}
                   for (k, label, detail), w in zip(FEATURES, final["w"][1:])]
    return {
        "strategy": strategy, "strategy_label": s_cfg.label, "timeframe": tf, "entry_start": entry_start, "cutoff": cutoff,
        "generated_at": datetime.now().isoformat(timespec="seconds"), "asof": spot["ts"].max().isoformat(),
        "counts": {"signals": int(len(df)), "labelled": int(labelled.sum()), "oos": int(oos.sum()),
                   "unconfirmed": int((~df["confirmed"]).sum()), "pending": int((df["outcome"] == "pending").sum())},
        "model": {"base_rate": _r(base * 100) if base is not None else None,
                  "brier": _r(float(np.mean((s_oos / 100 - y_oos) ** 2)), 4) if len(y_oos) else None,
                  "brier_base": _r(float(np.mean((base - y_oos) ** 2)), 4) if len(y_oos) else None,
                  "auc": _r(auc(s_oos, y_oos), 3), "auc_ci": auc_ci, "folds": fold_rows, "weights": weights,
                  "calibration_wf": wf, "calibrator": calibrator, "verdict": judged,
                  "stop_atr": STOP_ATR, "target_atr": TARGET_ATR,
                  "params": {"w": final["w"].tolist(), "mu": final["mu"].tolist(), "sd": final["sd"].tolist()} if final else None},
        "calibration": calib, "reliability": reliability,
        "signals": out_rows[::-1],
    }


def _r(v, n: int = 1):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), n)


def _describe(r: dict, tf: int, s_cfg, comparable) -> dict:
    d = r["direction"]
    entry, atr = r["close"], r["atr"]
    stop, target = entry - d * STOP_ATR * atr, entry + d * TARGET_ATR * atr

    def ind(name, value, supports):
        return {"name": name, "value": value, "supports": None if supports is None else bool(supports)}
    vr = r["vol_ratio"]
    indicators = [
        ind("EMA trend", f"slow EMA slope {r['trend']:+.2f} ATR" if pd.notna(r["trend"]) else "—",
            None if pd.isna(r["trend"]) else r["trend"] > 0),
        ind("VWAP", f"futures {r['fut_close']:.1f} vs VWAP {r['fut_vwap']:.1f}" if pd.notna(r["fut_vwap"]) else "no futures data",
            None if pd.isna(r["vwap"]) else r["vwap"] > 0),
        ind("RSI(14)", f"{r['rsi_v']:.1f}" if pd.notna(r["rsi_v"]) else "—", None if pd.isna(r["rsi"]) else r["rsi"] > 0),
        ind("MACD histogram", f"{r['macd_v']:+.2f}" if pd.notna(r["macd_v"]) else "—", None if pd.isna(r["macd"]) else r["macd"] > 0),
        ind("Volume", f"{vr:.2f}× 20-bar average" if pd.notna(vr) else "—", None if pd.isna(vr) else vr >= 1.2),
        ind("Volatility", f"ATR {r['volatility']:.2f}% of price", None),
        ind("Regime", r["regime_label"], None if r["regime_label"] in ("sideways", "unknown", "high volatility")
            else r["regime_label"] == ("bullish" if d > 0 else "bearish")),
    ]
    score = r["score"] if r["confirmed"] else None
    pro = [i["name"] for i in indicators if i["supports"] is True]
    con = [i["name"] for i in indicators if i["supports"] is False]
    word = "Bullish" if d > 0 else "Bearish"
    if not r["confirmed"]:
        call, reason = "No Trade", f"{word} {s_cfg.label} cross on {tf}m was not confirmed by {s_cfg.confirm.upper()}."
    else:
        call = word if (score is not None and score >= 50) else "Neutral"
        reason = (f"{word} {s_cfg.label} cross on {tf}m. Supported by {', '.join(pro) or 'nothing'}; "
                  f"against: {', '.join(con) or 'nothing'}. Regime: {r['regime_label']}.")
    cat = band(score) if score is not None else "Not scored"
    comp = comparable(score)
    strong = (score is not None and score >= 70 and len(pro) >= 3 and comp is not None and comp["n"] >= 30)
    return {
        "id": r["ts"].isoformat(), "ts": r["ts"].isoformat(), "day": r["day"].isoformat(), "direction": word,
        "call": call, "score": _r(score), "category": cat, "out_of_sample": bool(r["oos"]),
        "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
        "risk_reward": round(TARGET_ATR / STOP_ATR, 2), "atr": round(atr, 2),
        "expires": (r["ts"] + timedelta(minutes=tf)).isoformat(),
        "indicators": indicators, "reason": reason, "regime": r["regime_label"],
        "calibrated": _r(r.get("calibrated")) if r["confirmed"] else None,
        "comparable": comp, "outcome": r["outcome"] if r["confirmed"] else "not traded", "decided_at": r["decided_at"],
        "strong_alert": strong,
    }


def cache_key(strategy: str, tf: int, entry_start: str, cutoff: str) -> tuple[str, dict]:
    s = db.data_summary("NSE-NIFTY")
    params = {"kind": "signals", "dataset": "groww", "strategy": strategy, "timeframe": tf,
              "entry_start": entry_start, "cutoff": cutoff, "data_last": s["last"], "v": VERSION}
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24], params


def get(strategy: str, tf: int, entry_start: str = "09:30", cutoff: str = "14:30") -> dict | None:
    h, _ = cache_key(strategy, tf, entry_start, cutoff)
    run = db.get_run(h)
    return run["result"] if run else None


def build_and_store(strategy: str, tf: int, entry_start: str = "09:30", cutoff: str = "14:30", progress=None) -> dict:
    h, params = cache_key(strategy, tf, entry_start, cutoff)
    res = build(strategy, tf, entry_start, cutoff, progress)
    db.save_run(h, params, json.loads(json.dumps(res, default=str)))
    return {"hash": h}

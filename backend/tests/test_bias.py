"""strategy/bias.py: multi-timeframe bias, prediction and accuracy. Pure functions on synthetic candles."""
import numpy as np
import pandas as pd
import pytest

from app.services.strategy import bias


def candles(days=8, drift=0.0, seed=1, vol=6.0, start="2026-10-01", base=25000.0, futures=False, revert=0.0):
    """1-minute NIFTY candles 09:15-15:29 for consecutive weekdays (random walk with a drift per minute)."""
    rng = np.random.default_rng(seed)
    rows, px = [], base
    for d in pd.bdate_range(start, periods=days):
        for m in range(375):
            ts = d + pd.Timedelta(hours=9, minutes=15 + m)
            o = px
            px = px + drift + rng.normal(0, vol) - revert * (px - base)
            hi, lo = max(o, px) + abs(rng.normal(0, 1.5)), min(o, px) - abs(rng.normal(0, 1.5))
            rows.append((ts, o, hi, lo, px, float(rng.integers(500, 2000)) if futures else 0.0, 0.0))
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "oi"])


def test_analyse_is_causal_appending_candles_never_changes_earlier_rows():
    full = candles(days=9, seed=3, futures=True)
    fut = full.copy()
    fut["close"] += 12
    cut = pd.Timestamp("2026-10-09 11:20")                      # not a 15-minute boundary
    p = bias.BiasParams()
    a = bias.analyse(full[full.ts < cut], fut[fut.ts < cut], p)
    b = bias.analyse(full, fut, p)
    b = b[b["close_ts"] <= a["close_ts"].max()].reset_index(drop=True)
    assert len(a) == len(b) and len(a) > 400
    pd.testing.assert_frame_equal(a.drop(columns=["start"]), b.drop(columns=["start"]), check_dtype=False)


def test_changing_future_candles_does_not_change_the_current_bias():
    base = candles(days=8, seed=5)
    cut = pd.Timestamp("2026-10-08 12:00")
    other = base.copy()
    m = other.ts >= cut
    other.loc[m, ["open", "high", "low", "close"]] += 400      # a huge different future
    a = bias.analyse(base, None).query("close_ts <= @cut").reset_index(drop=True)
    b = bias.analyse(other, None).query("close_ts <= @cut").reset_index(drop=True)
    pd.testing.assert_frame_equal(a.drop(columns=["start"]), b.drop(columns=["start"]), check_dtype=False)


def test_each_5m_bar_only_sees_15m_bars_that_have_closed():
    f = bias.analyse(candles(days=6, seed=2), None)
    b15 = bias.tf_bars(candles(days=6, seed=2), None, 15)
    s15 = bias.tf_score(bias.votes(b15), bias.INDICATORS)
    last = f[f["close_ts"].dt.strftime("%H:%M") == "10:20"].iloc[-1]      # 5m bar closing 10:20: 15m bar closing 10:15 is the latest
    ref = s15[b15["close_ts"] == pd.Timestamp(last["close_ts"]).normalize() + pd.Timedelta(hours=10, minutes=15)].iloc[0]
    assert last["s15"] == pytest.approx(ref)
    at_1030 = f[f["close_ts"].dt.strftime("%H:%M") == "10:30"].iloc[-1]    # the 15m bar closing 10:30 closes with it
    ref2 = s15[b15["close_ts"] == pd.Timestamp(at_1030["close_ts"])].iloc[0]
    assert at_1030["s15"] == pytest.approx(ref2)


def test_steady_uptrend_gives_bullish_bias_and_ce_candidates_only():
    f = bias.analyse(candles(days=10, drift=0.6, seed=7, futures=True), candles(days=10, drift=0.6, seed=7, futures=True))
    late = f.iloc[len(f) // 2:]
    assert (late["bias"].isin(["BULLISH", "STRONG BULLISH"])).mean() > 0.8
    assert (late["direction"] > 0).sum() > 20 and (late["direction"] < 0).sum() == 0
    assert (late["predicted"] == "UP").mean() > 0.8


def test_steady_downtrend_gives_pe_candidates_only():
    f = bias.analyse(candles(days=10, drift=-0.6, seed=8), None)
    late = f.iloc[len(f) // 2:]
    assert (late["direction"] < 0).sum() > 20 and (late["direction"] > 0).sum() == 0
    assert (late["bias"].isin(["BEARISH", "STRONG BEARISH"])).mean() > 0.8


def test_sideways_market_trades_rarely():
    f = bias.analyse(candles(days=10, drift=0.0, seed=9, revert=0.15), None)    # mean-reverting: no lasting trend
    assert (f["direction"] != 0).mean() < 0.35        # most bars are HOLD without a trend


def test_conflicting_timeframes_are_neutral_and_never_a_candidate():
    f = bias.analyse(candles(days=8, seed=4), None)
    c = f[f["conflict"]]
    assert len(c) > 0
    assert (c["bias"] == "NEUTRAL").all() and (c["direction"] == 0).all() and (c["predicted"] == "NEUTRAL").all()


def test_the_confirmation_candle_is_exactly_the_three_closed_analysis_candles():
    """5m and 15m synchronisation: each 15m bar is the open of its first 5m bar, the extremes and the close of its last."""
    c = candles(days=4, seed=21)
    b5, b15 = bias.tf_bars(c, None, 5), bias.tf_bars(c, None, 15)
    assert len(b5) == 3 * len(b15)
    for i, r in enumerate(b15.itertuples()):
        g = b5.iloc[3 * i:3 * i + 3]
        assert (g["start"].iloc[0], g["close_ts"].iloc[-1]) == (r.start, r.close_ts)
        assert r.open == g["open"].iloc[0] and r.close == g["close"].iloc[-1]
        assert r.high == g["high"].max() and r.low == g["low"].min()


@pytest.mark.parametrize("tf,confirm", [(5, 15), (5, 30), (5, 60), (15, 30), (15, 60)])
def test_timeframes_are_configurable_and_labelled(tf, confirm):
    p = bias.BiasParams(primary=tf, higher=confirm)
    f = bias.analyse(candles(days=10, drift=0.4, seed=22), None, p)
    assert len(f) > 0 and f["s15"].notna().any()
    assert (f["close_ts"] - f["start"]).dropna().eq(pd.Timedelta(minutes=tf)).all()
    e = bias.explain(f.iloc[-1], p)
    assert (e["tf_primary"], e["tf_confirm"]) == (tf, confirm)
    assert f"{confirm}m" in e["summary"] and f"{tf}m" in e["summary"]
    acc = bias.accuracy(f, p)
    assert acc[0]["timeframe"] == f"{tf}m+{confirm}m" and {r["timeframe"] for r in acc[1:]} == {f"{tf}m", f"{confirm}m"}


def test_stored_values_include_the_raw_indicators():
    e = bias.explain(bias.analyse(candles(days=8, seed=23, futures=True), candles(days=8, seed=23, futures=True)).iloc[-1])
    assert {"ema9", "ema21", "ema50", "ema200", "macd_hist", "bb_up", "bb_lo", "fut_vwap", "pdh", "pdl"} <= set(e["values"])
    assert e["values"]["ema200"] is not None and e["rsi_5m"] is not None and e["atr"] is not None


@pytest.mark.parametrize("key", list(bias.INDICATORS))
def test_every_strategy_works_alone(key):
    """Each indicator on its own: it scores, predicts and can be evaluated (futures-based ones abstain without futures)."""
    c = candles(days=8, drift=0.3, seed=24, futures=True)
    f = bias.analyse(c, c, bias.BiasParams(enabled=(key,), min_confidence=0, trend_thr=0.05, confirm_thr=0.02))
    assert f["s5"].notna().any() or key == "rsi_divergence"
    assert set(f["predicted"]) <= {"UP", "DOWN", "NEUTRAL"}
    row = [r for r in bias.accuracy(f, bias.BiasParams(enabled=(key,))) if r["key"] == key and r["timeframe"] == "5m"][0]
    assert row["correct"] + row["incorrect"] == row["n"]


def test_label_thresholds():
    p = bias.BiasParams()
    assert [bias.label(x, p) for x in (0.6, 0.3, 0.05, -0.3, -0.6, float("nan"))] == \
           ["STRONG BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "STRONG BEARISH", "NEUTRAL"]


def test_confidence_is_a_percentage_and_zero_without_direction():
    f = bias.analyse(candles(days=8, drift=0.4, seed=11), None)
    assert f["confidence"].between(0, 100).all()
    assert (f.loc[f["bias"] == "NEUTRAL", "confidence"] == 0).all()
    assert (f.loc[f["bias"] != "NEUTRAL", "confidence"] > 0).any()


def test_disabling_an_indicator_removes_its_vote_from_the_score():
    c = candles(days=8, drift=0.3, seed=12)
    all_on = bias.analyse(c, None)
    only_ema = bias.analyse(c, None, bias.BiasParams(enabled=("ema_9_21",)))
    assert not np.allclose(all_on["s5"].fillna(0), only_ema["s5"].fillna(0))
    v = only_ema["v5_ema_9_21"]
    assert np.allclose(only_ema["s5"].dropna(), v.loc[only_ema["s5"].dropna().index])


def test_next_candle_outcome_compares_with_the_next_bar_of_the_same_day():
    f = bias.evaluate_predictions(bias.analyse(candles(days=6, drift=0.5, seed=13), None))
    last_of_day = f.groupby("day").tail(1)
    assert last_of_day["outcome"].isna().all()
    ok = f.dropna(subset=["next_close"])
    assert (ok["next_close"].values[:-1] != 0).all()
    called = ok[(ok["predicted"] != "NEUTRAL") & (ok["actual"].isin(["UP", "DOWN"]))]
    assert set(called["outcome"]) <= {"CORRECT", "INCORRECT"}
    assert ((called["predicted"] == called["actual"]) == (called["outcome"] == "CORRECT")).all()
    assert (ok.loc[ok["predicted"] == "NEUTRAL", "outcome"] == "NEUTRAL").all()


def test_accuracy_table_has_every_indicator_on_both_timeframes():
    rows = bias.accuracy(bias.analyse(candles(days=8, drift=0.2, seed=14, futures=True), candles(days=8, drift=0.2, seed=14, futures=True)))
    keys = {(r["key"], r["timeframe"]) for r in rows}
    assert ("combined", "5m+15m") in keys
    for k in bias.INDICATORS:
        assert (k, "5m") in keys and (k, "15m") in keys
    for r in rows:
        assert r["correct"] + r["incorrect"] == r["n"]
        assert r["accuracy"] is None or 0 <= r["accuracy"] <= 100


def test_explain_gives_reasons_and_never_calls_confidence_a_probability():
    f = bias.analyse(candles(days=8, drift=0.0, seed=15), None)
    e = bias.explain(f.iloc[-1])
    assert e["signal"] in ("BUY CE", "BUY PE", "HOLD") and len(e["indicators"]) == len(bias.INDICATORS)
    assert "not a probability" in e["note"]
    hold = f[f["direction"] == 0].iloc[-1]
    assert bias.explain(hold)["hold_reasons"]


def test_the_entry_threshold_is_inclusive_and_below_it_is_rejected_with_a_reason():
    """Confidence exactly at the minimum qualifies (>=); a hair above it does not, and the reason names the minimum."""
    c = candles(days=8, drift=0.35, seed=31, futures=True)
    f = bias.analyse(c, c, bias.BiasParams(min_confidence=0, min_atr_pct=0, trend_thr=0.05, confirm_thr=0.02))
    row = f[(f["direction"] != 0) & (f["confidence"] > 30)].iloc[-1]
    conf = float(row["confidence"])
    at = bias.analyse(c, c, bias.BiasParams(min_confidence=conf, min_atr_pct=0, trend_thr=0.05, confirm_thr=0.02))
    above = bias.analyse(c, c, bias.BiasParams(min_confidence=conf + 0.01, min_atr_pct=0, trend_thr=0.05, confirm_thr=0.02))
    i = f.index[f["close_ts"] == row["close_ts"]][0]
    assert at.loc[i, "direction"] == row["direction"] != 0
    assert above.loc[i, "direction"] == 0
    p = bias.BiasParams(min_confidence=conf + 0.01, min_atr_pct=0, trend_thr=0.05, confirm_thr=0.02)
    why = bias.explain(above.loc[i], p)["hold_reasons"]
    assert any("below your minimum" in w for w in why)

"""FVG, ADR, market structure (indicators.py) and the confluence strategy (strategy/confluence.py).
Pure functions on hand-built and synthetic candles: values are checked by hand, and every study is causal (appending or
changing later candles never changes an earlier row, so nothing repaints)."""
import numpy as np
import pandas as pd
import pytest

from app.services.strategy import bias, confluence, entries
from app.services.strategy import indicators as ind
from tests.test_bias import candles


def bars(rows, day="2026-10-05", atr=2.0):
    """rows: (open, high, low, close). One session of consecutive bars."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["day"] = pd.to_datetime(day).date()
    df["atr"] = atr
    return df


# ---------------------------------------------------------------- fair value gaps
def test_bullish_gap_is_detected_when_the_third_bar_closes_and_never_earlier():
    z = ind.fvg_zones(bars([(96, 100, 95, 99), (99, 112, 99, 111), (111, 115, 104, 114)]))
    assert list(z["fvg_new"]) == [0, 0, 1]                                    # bar 0 high 100 < bar 2 low 104
    assert z["fvg_bull_state"].iloc[2] == "unfilled" and z["fvg_bull_state"].iloc[1] is None
    assert (z["fvg_bull_lo"].iloc[2], z["fvg_bull_hi"].iloc[2]) == (100, 104)
    assert z["fvg_bull_age"].iloc[2] == 0 and z["fvg_bear_state"].iloc[2] is None


def test_bearish_gap_mirrors_the_bullish_one():
    z = ind.fvg_zones(bars([(110, 112, 108, 109), (109, 109, 96, 97), (97, 100, 94, 95)]))
    assert list(z["fvg_new"]) == [0, 0, -1]                                   # bar 2 high 100 < bar 0 low 108
    assert (z["fvg_bear_lo"].iloc[2], z["fvg_bear_hi"].iloc[2]) == (100, 108) and z["fvg_bear_state"].iloc[2] == "unfilled"


def test_gap_status_goes_unfilled_then_mitigated_with_a_retest_then_filled():
    rows = [(96, 100, 95, 99), (99, 112, 99, 111), (111, 115, 104, 114),       # gap 100-104 forms on bar 2
            (114, 118, 106, 117),                                              # bar 3 stays above: still unfilled
            (105, 109, 102, 108),                                              # bar 4 trades into the gap, holds, closes above it, bullish
            (108, 109, 101, 103),                                              # bar 5 back into the gap, closes inside, bearish: not a retest
            (103, 104, 99, 100)]                                               # bar 6 trades through the bottom: filled
    z = ind.fvg_zones(bars(rows))
    assert z["fvg_bull_state"].iloc[3] == "unfilled" and not z["fvg_bull_retest"].iloc[3]
    assert z["fvg_bull_state"].iloc[4] == "mitigated" and z["fvg_bull_retest"].iloc[4]            # retest confirmed on bar 4
    assert z["fvg_bull_state"].iloc[5] == "mitigated" and not z["fvg_bull_retest"].iloc[5]
    assert z["fvg_bull_state"].iloc[6] == "filled" and not z["fvg_bull_retest"].iloc[6] and z["fvg_bull_n"].iloc[6] == 0


def test_a_gap_smaller_than_the_minimum_is_ignored_and_zones_do_not_cross_sessions():
    small = ind.fvg_zones(bars([(96, 100, 95, 99), (99, 112, 99, 111), (111, 115, 100.1, 114)], atr=2.0), min_atr=0.1)
    assert small["fvg_new"].sum() == 0                                        # a 0.1 gap is below 0.1 x ATR 2
    two = pd.concat([bars([(96, 100, 95, 99), (99, 112, 99, 111), (111, 115, 104, 114)]),
                     bars([(114, 116, 113, 115), (115, 117, 114, 116)], day="2026-10-06")], ignore_index=True)
    z = ind.fvg_zones(two)
    assert z["fvg_bull_state"].iloc[2] == "unfilled" and z["fvg_bull_state"].iloc[3] is None   # a new session starts with no zones


def test_a_gap_expires_after_max_age_bars():
    rows = [(96, 100, 95, 99), (99, 112, 99, 111), (111, 115, 104, 114)] + [(114, 120, 110, 118)] * 6
    z = ind.fvg_zones(bars(rows), max_age=4)
    assert z["fvg_bull_state"].iloc[6] == "unfilled" and z["fvg_bull_age"].iloc[6] == 4
    assert z["fvg_bull_state"].iloc[7] is None and z["fvg_bull_n"].iloc[7] == 0


def test_fvg_is_causal_and_never_repaints():
    c = candles(days=6, seed=5, vol=6.0)
    b = bias.tf_bars(c, None, 5)
    cut = len(b) - 120
    a = ind.fvg_zones(b.iloc[:cut].reset_index(drop=True), 0.1, 24)
    full = ind.fvg_zones(b, 0.1, 24).iloc[:cut].reset_index(drop=True)
    assert a["fvg_new"].abs().sum() > 20
    pd.testing.assert_frame_equal(a, full, check_dtype=False)


# ---------------------------------------------------------------- ADR
def test_adr_averages_the_previous_sessions_only_and_range_used_grows_through_the_day():
    days = pd.bdate_range("2026-10-01", periods=7)
    rows = []
    for i, d in enumerate(days):                  # session i has a 10 + i point range
        rows += [(d.date(), 100.0, 100.0 + (10 + i), 100.0, 100.0)]
    # today (7th session) is built from two bars with a growing range
    df = pd.DataFrame(rows[:6], columns=["day", "open", "high", "low", "close"])
    today = pd.DataFrame([(days[6].date(), 100.0, 105.0, 100.0, 104.0), (days[6].date(), 104.0, 112.0, 98.0, 99.0)],
                         columns=["day", "open", "high", "low", "close"])
    df = pd.concat([df, today], ignore_index=True)
    a = ind.adr(df, (5, 10))
    assert a["adr5"].iloc[6] == pytest.approx(np.mean([11, 12, 13, 14, 15]))     # sessions 2-6, today excluded
    assert np.isnan(a["adr10"].iloc[6]) and np.isnan(a["adr5"].iloc[4])           # too few earlier sessions: unavailable
    assert a["range_today"].iloc[6] == 5 and a["range_today"].iloc[7] == 14
    assert a["adr_used5"].iloc[6] == pytest.approx(100 * 5 / 13) and a["adr_used5"].iloc[7] == pytest.approx(100 * 14 / 13)


def test_adr_is_causal():
    b = bias.tf_bars(candles(days=26, seed=2), None, 5)
    cut = len(b) - 100
    a = ind.adr(b.iloc[:cut].reset_index(drop=True))
    pd.testing.assert_frame_equal(a, ind.adr(b).iloc[:cut].reset_index(drop=True), check_dtype=False)
    assert a["adr20"].notna().any() and a["adr_used20"].dropna().between(0, 1000).all()


# ---------------------------------------------------------------- market structure
def zigzag(points, per=4):
    """Straight legs between turning points, one bar per step: high/low are the bar's own extremes."""
    px = [points[0]]
    for a, b in zip(points, points[1:]):
        px += list(np.linspace(a, b, per + 1)[1:])
    rows = [(p, p + 0.5, p - 0.5, p) for p in px]
    return bars(rows)


def test_higher_highs_and_higher_lows_are_known_only_after_the_swing_is_confirmed():
    s = ind.swing_structure(zigzag([100, 110, 104, 118, 108, 126, 115, 135]), k=3)
    assert s["struct"].iloc[-1] == 1.0                                         # HH and HL
    first = s["struct"].first_valid_index()
    assert first >= 3 + 3                                                      # not before two swings of each kind were confirmed
    # the swing high at bar 4 (110.5) is first visible at bar 4 + k, never before
    assert s["swing_hi"].iloc[4 + 2] != 110.5 and s["swing_hi"].iloc[4 + 3] == 110.5


def test_lower_highs_and_lower_lows_and_break_of_structure():
    s = ind.swing_structure(zigzag([140, 120, 132, 112, 124, 100, 112, 90]), k=3)
    assert s["struct"].iloc[-1] == -1.0
    b = zigzag([100, 120, 110, 140])                                           # the last leg closes above the 120.5 swing high
    t = ind.swing_structure(b, k=3)
    assert t["bos"].max() == 1 and t["bos_recent"].iloc[t["bos"].idxmax()] == 1
    assert (t["bos_recent"].iloc[: t["bos"].idxmax()] == 0).all()              # no break before it happened


def test_structure_is_causal():
    b = bias.tf_bars(candles(days=6, seed=8), None, 5)
    cut = len(b) - 90
    pd.testing.assert_frame_equal(ind.swing_structure(b.iloc[:cut].reset_index(drop=True)),
                                  ind.swing_structure(b).iloc[:cut].reset_index(drop=True), check_dtype=False)


# ---------------------------------------------------------------- VWAP events share the entries geometry
def _fut(spot):
    f = spot.copy()
    f["close"] += 12
    f["volume"] = 1000.0 + (f.index % 17) * 150
    return f


def test_vwap_retest_and_rejection_flags_follow_the_rules_and_never_overlap():
    spot = candles(days=14, seed=11, futures=True, vol=7.0)
    f = confluence.frame(spot, _fut(spot))
    assert f["vwap_retest_up"].any() and f["vwap_reject_up"].any() and f["vwap_reject_dn"].any()
    up = f[f["vwap_reject_up"]]
    assert (up["close"] > up["vwap_adj"]).all() and (up["close"] > up["open"]).all() and (up["low"] <= up["vwap_adj"] + 0.1 * up["atr"]).all()
    dn = f[f["vwap_reject_dn"]]
    assert (dn["close"] < dn["vwap_adj"]).all() and (dn["high"] >= dn["vwap_adj"] - 0.1 * dn["atr"]).all()
    assert not (f["vwap_reject_up"] & f["vwap_reject_dn"]).any()
    # the entries.py retest method still uses the shared geometry and keeps its definition
    d, far_up, far_dn, near = entries.vwap_geometry(entries.frame(spot, _fut(spot)))
    assert (d == f["vwap_dist"]).all()


# ---------------------------------------------------------------- the strategy
def test_confluence_is_causal_appending_or_changing_later_candles_never_changes_earlier_rows():
    spot = candles(days=30, drift=0.12, seed=3, futures=True, vol=6.0)
    fut = _fut(spot)
    cut = pd.Timestamp("2026-11-10 11:20")
    p = confluence.ConfluenceParams()
    a = confluence.analyse(spot[spot.ts < cut], fut[fut.ts < cut], p)
    b = confluence.analyse(spot, fut, p)
    b = b[b["close_ts"] <= a["close_ts"].max()].reset_index(drop=True)
    assert len(a) == len(b) > 1500 and (a["cf_direction"] != 0).sum() > 30
    pd.testing.assert_frame_equal(a.drop(columns=["start"]), b.drop(columns=["start"]), check_dtype=False)
    other = spot.copy()
    other.loc[other.ts >= cut, ["open", "high", "low", "close"]] += 400
    c = confluence.analyse(other, fut, p)
    c = c[c["close_ts"] <= a["close_ts"].max()].reset_index(drop=True)
    pd.testing.assert_frame_equal(a.drop(columns=["start"]), c.drop(columns=["start"]), check_dtype=False)


@pytest.fixture(scope="module")
def cf_frame():
    spot = candles(days=30, drift=0.12, seed=3, futures=True, vol=6.0)
    return spot, _fut(spot), confluence.analyse(spot, _fut(spot))


def test_votes_stay_in_range_and_the_score_is_the_weighted_agreement(cf_frame):
    _, _, a = cf_frame
    v = a[[f"cf_vote_{k}" for k in confluence.FACTORS]]
    assert v.abs().max().max() <= 1.0 and set(np.unique(v.stack().round(2))) <= {-1.0, -0.5, 0.0, 0.5, 1.0}
    assert a["cf_score"].between(0, 100).all()
    row = a[(a["cf_direction"] != 0)].iloc[0]
    d = row["cf_raw_dir"]
    votes = np.array([row[f"cf_vote_{k}"] for k in confluence.FACTORS], dtype=float)
    avail = ~np.isnan(votes)
    expected = 100 * np.clip(votes[avail] * d, 0, None).sum() / avail.sum()
    assert row["cf_score"] == pytest.approx(expected, abs=0.06)


def test_every_entry_passes_every_gate_and_rejections_name_the_gate_that_failed(cf_frame):
    spot, fut, a = cf_frame
    p = confluence.ConfluenceParams(require=("fvg",), min_score=75.0, adr_max_used=100.0)
    b = confluence.analyse(spot, fut, p)
    e = b[b["cf_direction"] != 0]
    assert len(e) > 0 and (e["cf_score"] >= 75).all() and e["cf_g_require"].all() and e["cf_g_htf"].all() and e["cf_g_adr"].all()
    assert (e[f"cf_vote_fvg"] * e["cf_raw_dir"] >= 1.0).all()                    # a required factor is fully confirmed (a retest)
    assert (e["trend15"] * e["cf_raw_dir"] >= 0).all()                           # the 15-minute trend is never against the trade
    used = e["adr_used10"].dropna()
    assert (used <= 100).all()
    # explain says why a candle with a direction was refused
    bad = b[(b["cf_raw_dir"] != 0) & (b["cf_direction"] == 0)].iloc[-1]
    ex = confluence.explain(bad, p, {"confidence": 0})
    assert ex["direction"] == 0 and ex["signal"] == "HOLD" and ex["hold_reasons"]


def test_disabling_a_factor_removes_it_from_the_score_and_the_adr_filter_blocks_an_exhausted_day(cf_frame):
    spot, fut, a = cf_frame
    no_fvg = confluence.analyse(spot, fut, confluence.ConfluenceParams(factors=("ema", "vwap", "structure")))
    assert (no_fvg["cf_raw_dir"] != a["cf_raw_dir"]).any()                       # the FVG vote was part of the decision before
    off = confluence.analyse(spot, fut, confluence.ConfluenceParams(adr_filter=False))
    tight = confluence.analyse(spot, fut, confluence.ConfluenceParams(adr_filter=True, adr_max_used=30.0))
    assert (tight["cf_direction"] != 0).sum() < (off["cf_direction"] != 0).sum()
    blocked = tight[(tight["cf_raw_dir"] != 0) & ~tight["cf_g_adr"]]
    assert len(blocked) > 0 and (blocked["adr_used10"] > 30).all() and (blocked["cf_direction"] == 0).all()


def test_explain_lists_each_factor_with_values_conditions_and_the_adr_table(cf_frame):
    spot, fut, _ = cf_frame
    p = confluence.ConfluenceParams()
    bf = bias.analyse(spot, fut)
    f = confluence.overlay(bf, spot, fut, p)
    r = f[f["cf_raw_dir"] != 0].iloc[-1]
    ex = confluence.explain(r, p, bias.explain(r))
    c = ex["confluence"]
    assert [x["key"] for x in c["factors"]] == ["ema", "vwap", "fvg", "structure"]
    assert all(x["condition"] and x["status"] in ("bullish", "bearish", "neutral", "unavailable") for x in c["factors"])
    assert [x["period"] for x in c["adr"]["rows"]] == [5, 10, 20] and c["adr"]["rows"][1]["used"] is not None
    assert ex["strategy"] == "confluence" and ex["entry_score"] == c["score"] and "probability" in c["note"]
    assert ex["bias_signal"] in ("BUY CE", "BUY PE", "HOLD")


def test_overlay_keeps_the_bias_prediction_and_only_replaces_the_entry_decision(cf_frame):
    spot, fut, _ = cf_frame
    bf = bias.analyse(spot, fut)
    o = confluence.overlay(bf, spot, fut, confluence.ConfluenceParams())
    assert len(o) == len(bf)
    for col in ("predicted", "bias", "confidence", "s5", "s15", "combined"):
        pd.testing.assert_series_equal(o[col], bf[col], check_dtype=False)
    assert (o["bias_direction"] == bf["direction"]).all() and (o["direction"] == o["cf_direction"]).all()


def test_missing_futures_leaves_the_vwap_vote_out_instead_of_guessing():
    spot = candles(days=30, drift=0.1, seed=4, futures=False)
    a = confluence.analyse(spot, None)
    assert a["cf_vote_vwap"].isna().all()
    assert a["cf_vote_ema"].notna().any()
    p = confluence.ConfluenceParams()
    r = a.iloc[-1]
    ex = confluence.explain(r, p, {"confidence": 0})
    vw = next(x for x in ex["confluence"]["factors"] if x["key"] == "vwap")
    assert vw["status"] == "unavailable" and "unavailable" in vw["condition"]


def test_research_signals_have_the_entries_format_and_the_event_cooldown(cf_frame):
    _, _, a = cf_frame
    s = confluence.research_signals(a)
    assert list(s.columns) == ["fvg_retest", "vwap_rejection", "confluence"]
    assert set(np.unique(s.values)) <= {-1, 0, 1} and (s != 0).sum().min() > 0
    for k in ("fvg_retest", "vwap_rejection"):
        idx = np.flatnonzero((s[k] != 0).to_numpy())
        for i, j in zip(idx, idx[1:]):
            assert a["day"].iloc[i] != a["day"].iloc[j] or j - i > entries.COOLDOWN_BARS
    c = s["confluence"]
    assert ((c != 0) <= (a["cf_direction"] != 0)).all()                          # only where the strategy says enter, once per episode


# ================================================================ the scored strategy
def test_fvg_retest_is_fresh_only_on_the_first_return_to_an_unmitigated_gap():
    rows = [(96, 100, 95, 99), (99, 112, 99, 111), (111, 115, 104, 114),          # gap 100-104
            (114, 118, 106, 117),
            (105, 109, 102, 108),                                                  # first return: enters, holds, closes out bullish -> fresh retest
            (110, 114, 105, 113),
            (108, 110, 102, 104),                                                  # second return: enters, closes at the top edge (no confirmation)
            (105, 110, 102, 109)]                                                  # third return: confirmed again, but the gap is already mitigated
    z = ind.fvg_zones(bars(rows))
    assert z["fvg_bull_retest"].iloc[4] and z["fvg_bull_fresh"].iloc[4]
    assert not z["fvg_bull_retest"].iloc[6]
    assert z["fvg_bull_retest"].iloc[7] and not z["fvg_bull_fresh"].iloc[7]       # a retest, but of a mitigated gap
    assert not z["fvg_bull_fresh"].iloc[:4].any() and not z["fvg_bear_fresh"].any()


def one_row_frame(**over):
    """700 identical bars (enough warm-up) whose last row is built to earn points on the long side."""
    base = dict(open=99.0, high=101.0, low=98.0, close=100.0, atr=10.0, ema20=95.0, ema50=90.0, ema200=80.0, trend15=1, struct=1.0, bos_recent=0,
                vwap_dist=5.0, vwap_adj=95.0, fut_vwap=95.0, fut_close=100.0, vwap_retest_up=False, vwap_retest_dn=False, vwap_reject_up=False,
                vwap_reject_dn=False, fvg_bull_retest=True, fvg_bull_fresh=True, fvg_bear_retest=False, fvg_bear_fresh=False, rsi=60.0, macd_hist=1.0,
                vol_ratio=1.2, adr_used10=50.0)
    base.update(over)
    return pd.DataFrame([base] * 700)


def pts_gates(p=None, **over):
    p = p or confluence.ScoredParams()
    f = one_row_frame(**over)
    pl, gl = confluence._side_points(f, p, 1)
    ps, gs = confluence._side_points(f, p, -1)
    return pl.iloc[-1], gl.iloc[-1], ps.iloc[-1], gs.iloc[-1]


def test_points_are_those_of_the_specification_and_sum_to_the_score():
    pl, gl, ps, gs = pts_gates()
    assert dict(pl) == {"trend": 25.0, "ema": 15.0, "vwap": 12.0, "fvg": 20.0, "momentum": 10.0, "volume": 5.0, "adr": 5.0}
    assert sum(v for v in pl) == 92.0 and gl.all()
    assert {k: v[1] for k, v in confluence.SC_COMPONENTS.items()} == {"trend": 25, "ema": 15, "vwap": 20, "fvg": 20, "momentum": 10, "volume": 5, "adr": 5}
    assert sum(v[1] for v in confluence.SC_COMPONENTS.values()) == 100
    assert ps["fvg"] == 0 and not gs["trend"] and not gs["fvg"]                  # the short side earns nothing from a bullish setup
    # a VWAP retest or rejection on the right side earns the full 20
    assert pts_gates(vwap_retest_up=True)[0]["vwap"] == 20.0
    assert pts_gates(vwap_reject_up=True)[0]["vwap"] == 20.0


def test_each_hard_gate_blocks_on_its_own_condition():
    cases = {"fvg": dict(fvg_bull_fresh=False), "trend": dict(trend15=0), "ema": dict(ema20=85.0), "vwap": dict(vwap_dist=0.5),
             "momentum": dict(rsi=40.0, macd_hist=-1.0), "adr": dict(adr_used10=130.0), "atr": dict(atr=0.01)}
    for gate, over in cases.items():
        _, g, _, _ = pts_gates(**over)
        assert not g[gate], gate
        assert g.drop(gate).drop("conflict", errors="ignore").sum() >= len(g) - 3     # the others are not what failed
    assert not pts_gates(fut_vwap=np.nan, fut_close=np.nan)[1]["vwap"]            # VWAP is required: missing futures data cannot pass
    assert pts_gates(adr_used10=np.nan)[1]["adr"] and pts_gates(adr_used10=np.nan)[0]["adr"] == 0      # ADR unknown: not checked, but earns nothing
    assert pts_gates(rsi=80.0)[0]["momentum"] == 5.0                              # an overbought RSI does not count as momentum, MACD still does
    assert pts_gates(vol_ratio=0.8)[0]["volume"] == 0 and pts_gates(vol_ratio=np.nan)[0]["volume"] == 0


def test_conflicting_signals_are_rejected():
    assert not pts_gates(struct=-1.0)[1]["conflict"]                                # opposite structure
    assert not pts_gates(fvg_bear_retest=True)[1]["conflict"]                       # an opposite gap retest on the same candle
    assert not pts_gates(rsi=40.0, macd_hist=-1.0)[1]["conflict"]                   # both momentum readings against
    assert pts_gates(rsi=40.0, macd_hist=1.0)[1]["conflict"]                        # only one against is not a conflict


def test_optional_context_timeframe_only_blocks_when_it_is_against():
    p = confluence.ScoredParams(ctx_tf=30)
    assert pts_gates(p, trend_ctx=1)[1]["ctx"] and pts_gates(p, trend_ctx=0)[1]["ctx"]
    assert not pts_gates(p, trend_ctx=-1)[1]["ctx"]
    assert pts_gates()[1]["ctx"]                                                    # off by default: no column, no gate


@pytest.fixture(scope="module")
def sc_frames():
    spot = candles(days=30, drift=0.12, seed=3, futures=True, vol=6.0)
    fut = _fut(spot)
    return spot, fut, {tf: confluence.analyse(spot, fut, confluence.ScoredParams(primary=tf, higher=h, min_score=50)) for tf, h in ((5, 15), (15, 30))}


def test_scored_analysis_is_causal_on_both_timeframe_pairs():
    spot = candles(days=30, drift=0.12, seed=3, futures=True, vol=6.0)
    fut = _fut(spot)
    cut = pd.Timestamp("2026-11-10 11:20")
    for tf, higher in ((5, 15), (15, 30)):
        p = confluence.ScoredParams(primary=tf, higher=higher, min_score=50)
        a = confluence.analyse(spot[spot.ts < cut], fut[fut.ts < cut], p)
        a = a[a["close_ts"] <= cut].reset_index(drop=True)                      # only bars that had closed (the engine never decides on a forming bar)
        b = confluence.analyse(spot, fut, p)
        b = b[b["close_ts"] <= cut].reset_index(drop=True)
        assert len(a) == len(b) > 400
        pd.testing.assert_frame_equal(a.drop(columns=["start"]), b.drop(columns=["start"]), check_dtype=False)
        other = spot.copy()
        other.loc[other.ts >= cut, ["open", "high", "low", "close"]] += 400
        c = confluence.analyse(other, fut, p)
        c = c[c["close_ts"] <= cut].reset_index(drop=True)
        pd.testing.assert_frame_equal(a.drop(columns=["start"]), c.drop(columns=["start"]), check_dtype=False)


def test_every_scored_entry_meets_the_score_and_every_gate_on_both_timeframes(sc_frames):
    for tf, a in sc_frames[2].items():
        pts = a[[f"sc_pts_{k}" for k in confluence.SC_COMPONENTS]]
        assert (pts.sum(axis=1).round(6) == a["sc_score"].round(6)).all() and a["sc_score"].between(0, 100).all()
        for k, (_, mx) in confluence.SC_COMPONENTS.items():
            assert (a[f"sc_pts_{k}"] <= mx).all(), (tf, k)
        e = a[a["sc_direction"] != 0]
        assert len(e) > 0, tf
        assert (e["sc_score"] >= 50).all() and (e["sc_direction"] == e["sc_cand"]).all()
        for g in ("trend", "ema", "vwap", "fvg", "momentum", "adr", "atr", "conflict", "ctx"):
            assert e[f"sc_g_{g}"].all(), (tf, g)
        side = e["sc_direction"]
        assert (e["trend15"] == side).all() and (e["vwap_dist"] * side > 0).all()                 # the confirmation trend and VWAP both point the same way
        assert (e["sc_pts_fvg"] == 20).all()
        fresh = np.where(side > 0, e["fvg_bull_fresh"], e["fvg_bear_fresh"])
        assert fresh.all()                                                                         # always the first return to an unmitigated gap
        used = e["adr_used10"].dropna()
        assert (used <= 100).all()


def test_a_higher_minimum_score_only_removes_entries_and_the_two_timeframes_are_separate(sc_frames):
    spot, fut, frames = sc_frames
    f5 = frames[5]
    strict = confluence.analyse(spot, fut, confluence.ScoredParams(min_score=90))
    assert (strict["sc_direction"] != 0).sum() <= (f5["sc_direction"] != 0).sum()
    assert set(f5.loc[strict["sc_direction"] != 0, "close_ts"]) <= set(f5.loc[f5["sc_direction"] != 0, "close_ts"])
    assert len(frames[15]) * 3 == len(f5)                                                          # a 15-minute entry frame has one third of the bars
    assert frames[15]["close_ts"].dt.minute.isin([0, 15, 30, 45]).all()


def test_scored_explain_lists_components_gates_reasons_and_the_decision(sc_frames):
    spot, fut, _ = sc_frames
    p = confluence.ScoredParams(min_score=50)
    o = confluence.overlay(bias.analyse(spot, fut), spot, fut, p)
    r = o[o["sc_direction"] != 0].iloc[-1]
    e = confluence.explain(r, p, bias.explain(r))
    s = e["scored"]
    assert e["strategy"] == "scored" and e["signal"] in ("BUY CE", "BUY PE") and e["entry_score"] == s["score"] and s["passed"] and s["rejections"] == []
    assert [c["key"] for c in s["components"]] == list(confluence.SC_COMPONENTS) and all(c["condition"] for c in s["components"])
    assert sum(c["points"] for c in s["components"]) == pytest.approx(s["score"]) and all(g["ok"] for g in s["gates"])
    assert "probability" in s["note"] and (s["entry_tf"], s["confirm_tf"]) == (5, 15)
    miss = o[(o["sc_direction"] == 0) & (o["sc_cand"] != 0)].iloc[-1]
    m = confluence.explain(miss, p, {"confidence": 0})
    assert m["direction"] == 0 and m["signal"] == "HOLD" and m["hold_reasons"] and not m["scored"]["passed"]
    assert any(not g["ok"] for g in m["scored"]["gates"]) and set(m["hold_reasons"]) <= {g["text"] for g in m["scored"]["gates"]}


def test_overlay_with_the_scored_strategy_keeps_the_bias_prediction(sc_frames):
    spot, fut, _ = sc_frames
    bf = bias.analyse(spot, fut)
    o = confluence.overlay(bf, spot, fut, confluence.ScoredParams(min_score=50))
    assert len(o) == len(bf)
    for col in ("predicted", "bias", "confidence", "s5", "s15", "combined"):
        pd.testing.assert_series_equal(o[col], bf[col], check_dtype=False)
    assert (o["direction"] == o["sc_direction"]).all() and (o["bias_direction"] == bf["direction"]).all()


def test_scored_research_signals_fire_once_per_entry_state(sc_frames):
    a = sc_frames[2][5]
    s = confluence.scored_research_signals(a)["scored"]
    d = a["sc_direction"]
    assert list(confluence.scored_research_signals(a).columns) == ["scored"] and ((s != 0) <= (d != 0)).all()
    assert (s[s != 0] == d[s != 0]).all() and (s != 0).sum() <= (d != 0).sum()


def test_params_for_selects_the_strategy_from_the_engine_configuration():
    from app.services.trading.engine_config import EngineConfig
    c = EngineConfig(signal_mode="bias", timeframe=15, bias_confirm_tf=30, entry_strategy="scored", sc_min_score=85, sc_ctx_tf=60, sc_adr_period=20)
    p = confluence.params_for(c.validate())
    assert isinstance(p, confluence.ScoredParams) and (p.primary, p.higher, p.min_score, p.ctx_tf, p.adr_period) == (15, 30, 85.0, 60, 20)
    assert isinstance(confluence.params_for(EngineConfig(signal_mode="bias", timeframe=5, entry_strategy="confluence").validate()), confluence.ConfluenceParams)
    assert confluence.params_for(EngineConfig(signal_mode="bias", timeframe=5).validate()) is None


def test_atr_stop_must_fall_inside_the_premium_range_for_the_scored_strategy():
    from app.services.trading import stops
    from app.services.trading.engine_config import EngineConfig
    cfg = EngineConfig(signal_mode="bias", timeframe=5, entry_strategy="scored", stop_mode="atr", stop_atr=1.0, target_rr=2.0).validate()
    ok = stops.stop_levels(cfg, "BUY", 100.0, 40.0, lambda: 0.5)                  # 0.5 x 40 = 20 points = 20% of the premium
    assert ok.error is None and ok.stop == pytest.approx(80.0, abs=0.1) and ok.target == pytest.approx(140.0, abs=0.1)     # 2R
    tight = stops.stop_levels(cfg, "BUY", 100.0, 4.0, lambda: 0.5)                # 2%: noise
    wide = stops.stop_levels(cfg, "BUY", 100.0, 150.0, lambda: 0.5)               # 75%: not a controlled risk
    assert tight.error and "needs 5% to 50%" in tight.error and tight.stop is None
    assert wide.error and "needs 5% to 50%" in wide.error
    plain = EngineConfig(signal_mode="bias", timeframe=5, stop_mode="atr").validate()
    assert stops.stop_levels(plain, "BUY", 100.0, 4.0, lambda: 0.5).error is None   # the other strategies keep their own behaviour


def test_strategy_stats_report_expectancy_profit_factor_and_drawdown_per_strategy():
    from app.services.trading import bias_report
    rows = [{"net": 300.0, "gross": 400.0, "entry_ts": "2026-11-02T10:00"}, {"net": -100.0, "gross": 0.0, "entry_ts": "2026-11-03T10:00"},
            {"net": -250.0, "gross": -150.0, "entry_ts": "2026-11-04T10:00"}, {"net": 200.0, "gross": 280.0, "entry_ts": "2026-11-05T10:00"}]
    s = bias_report.strategy_stats(rows)
    assert (s["trades"], s["wins"], s["losses"], s["win_rate"], s["net"], s["expectancy"]) == (4, 2, 2, 50.0, 150.0, 37.5)
    assert s["profit_factor"] == pytest.approx(500 / 350, abs=0.01) and s["max_drawdown"] == 350.0 and s["avg_win"] == 250.0 and s["avg_loss"] == -175.0
    assert bias_report.strategy_stats([])["expectancy"] is None
    assert bias_report.strategy_of({"analysis": {"strategy": "scored"}}) == "scored" and bias_report.strategy_of({"analysis": None}) == "bias"

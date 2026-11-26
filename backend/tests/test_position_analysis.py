"""Position trading: multi-timeframe bars, studies and the nine strategies. Pure (no database): synthetic 1-minute candles."""
from datetime import datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services.position import bars as pbars
from app.services.position import strategies as pstr
from app.services.position import studies
from app.services.strategy import indicators as ind


def make_spot(days=330, seed=7, drift=0.0004, start=datetime(2024, 1, 1), vol=0.0009):
    """Trending random walk of 375 one-minute candles a weekday, with futures volume."""
    rng = np.random.default_rng(seed)
    rows, price = [], 20000.0
    d = start
    n = 0
    while n < days:
        if d.weekday() < 5:
            regime = np.sin(n / 40.0)                                  # slow cycles so both directions occur
            for m in range(375):
                ret = rng.normal(drift * regime * 0.1, vol * 0.25)
                o = price
                price = max(1000.0, price * (1 + ret))
                hi = max(o, price) * (1 + abs(rng.normal(0, 0.00012)))
                lo = min(o, price) * (1 - abs(rng.normal(0, 0.00012)))
                rows.append((d.replace(hour=9, minute=15) + timedelta(minutes=m), o, hi, lo, price, float(rng.integers(500, 3000)) * (3 if rng.random() < 0.01 else 1)))
            n += 1
        d += timedelta(days=1)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    return df[["ts", "open", "high", "low", "close"]], df[["ts", "volume"]]


@pytest.fixture(scope="module")
def data():
    return make_spot()


def test_bars_have_the_nse_session_split_and_only_full_days_count_as_daily_bars(data):
    spot, fut = data
    tfs = pbars.build(spot, fut)
    day = tfs["D"].iloc[10]
    assert day["n"] == 375 and day["close_ts"].time() == time(15, 30)
    h4 = tfs["4h"][tfs["4h"]["day"] == day["day"]]
    assert list(h4["n"]) == [240, 135] and h4["start"].iloc[0].time() == time(9, 15) and h4["start"].iloc[1].time() == time(13, 15)    # 09:15-13:15, then the 2h15 remainder
    h1 = tfs["1h"][tfs["1h"]["day"] == day["day"]]
    assert list(h1["n"]) == [60] * 6 + [15]
    assert tfs["W"]["n"].max() == 5 * 375
    cut = pd.Timestamp(day["close_ts"]) - timedelta(minutes=30)
    part = pbars.build(spot[spot["ts"] < cut], fut)["D"]
    assert part["n"].iloc[-1] < 375 and day["day"] == tfs["D"]["day"].iloc[10]
    assert pbars.completed(part, cut, "D")["day"].max() < day["day"]       # the unfinished day is not a daily bar
    wk = pbars.build(spot[spot["ts"] < pd.Timestamp("2024-03-07 12:00")], fut)["W"]                  # a Thursday: the week is not over
    assert pbars.completed(wk, pd.Timestamp("2024-03-07 12:00"), "W")["start"].max() < pd.Timestamp("2024-03-04")


def test_no_indicator_value_ever_depends_on_a_later_candle(data):
    spot, fut = data
    full = pstr.prepare(spot, fut)
    cut_day = full["day"].iloc[-60]
    spot2 = spot[spot["ts"] < cut_day + timedelta(days=1)]
    part = pstr.prepare(spot2, fut)
    k = len(part) - 8                                                          # compare everything except the last days (their weekly bar differs)
    a = full.iloc[:k].drop(columns=["start", "last", "close_ts"]).reset_index(drop=True)
    b = part.iloc[:k].drop(columns=["start", "last", "close_ts"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9, atol=1e-9)
    sf, sp = pstr.signals(full).iloc[:k], pstr.signals(part).iloc[:k]
    pd.testing.assert_frame_equal(sf.reset_index(drop=True), sp.reset_index(drop=True))
    # and a repainting check: appending a candle never changes an earlier signal
    again = pstr.prepare(spot[spot["ts"] < cut_day + timedelta(days=4)], fut)
    pd.testing.assert_frame_equal(pstr.signals(again).iloc[:k].reset_index(drop=True), sp.reset_index(drop=True))


def test_swing_pivots_are_known_only_after_their_confirmation_bars():
    h = pd.Series([1, 2, 3, 9, 3, 2, 1, 2, 3, 4], dtype=float)
    bars = pd.DataFrame({"high": h, "low": h - 0.5, "close": h, "open": h})
    p = studies.pivots(bars, k=3)
    assert p["swing_hi"].iloc[:6].isna().all()                                  # the peak at index 3 is not known before index 6
    assert p["swing_hi"].iloc[6] == 9 and p["piv_hi_idx"].iloc[6] == 3


def test_adx_is_high_in_a_trend_and_low_in_a_range():
    n = 200
    up = pd.DataFrame({"high": np.linspace(100, 200, n) + 1, "low": np.linspace(100, 200, n) - 1, "close": np.linspace(100, 200, n)})
    rng = np.random.default_rng(1)
    flat = 100 + rng.normal(0, 1, n)
    ranged = pd.DataFrame({"high": flat + 1, "low": flat - 1, "close": flat})
    a_up, a_flat = ind.adx(up)["adx"].iloc[-1], ind.adx(ranged)["adx"].iloc[-1]
    assert a_up > 40 and a_flat < 25
    assert ind.adx(up)["plus_di"].iloc[-1] > ind.adx(up)["minus_di"].iloc[-1]


def test_warm_up_rows_have_no_ema_and_the_trend_needs_every_ema():
    spot, fut = make_spot(days=40)
    d = pstr.prepare(spot, fut)
    assert d["ema200"].isna().all() and d["ema20"].iloc[:19].isna().all() and not np.isnan(d["ema20"].iloc[19])
    assert (d["trend"] == 0).all()                                              # EMA 100 / 200 do not exist yet: no trend is claimed


def test_every_strategy_gives_only_minus_one_zero_or_one_and_they_fire_on_trending_data(data):
    spot, fut = data
    d = pstr.prepare(spot, fut)
    sig = pstr.signals(d)
    assert set(sig.columns) == set(pstr.STRATEGIES) and len(pstr.STRATEGIES) == 9
    assert set(np.unique(sig.to_numpy())) <= {-1, 0, 1}
    fired = {k: int((sig[k] != 0).sum()) for k in sig}
    assert sum(1 for v in fired.values() if v > 0) >= 6, fired                  # most strategies find something on 330 days of cycling trends
    assert (d["close_ts"].dt.time == time(15, 30)).all()                        # decisions are made at the daily close


def test_strategies_are_independent_and_configurable(data):
    spot, fut = data
    d = pstr.prepare(spot, fut)
    only = pstr.signals(d, {"adx_trend": {"adx_min": 25.0}})
    assert list(only.columns) == ["adx_trend"]
    strict = pstr.signals(d, {"adx_trend": {"adx_min": 60.0}})["adx_trend"]
    loose = pstr.signals(d, {"adx_trend": {"adx_min": 10.0}})["adx_trend"]
    assert (strict != 0).sum() <= (only["adx_trend"] != 0).sum() <= (loose != 0).sum()


def test_volume_breakout_needs_volume_data_and_never_guesses():
    spot, _ = make_spot(days=260, seed=11)
    d = pstr.prepare(spot, None)                                                # no futures volume at all
    assert (d["volume"] == 0).all() and d["vol_ratio"].isna().all()
    assert (pstr.signals(d, {"volume_breakout": {"vol_x": 1.5}})["volume_breakout"] == 0).all()


def test_a_fresh_signal_fires_once_when_a_condition_starts_not_on_every_bar():
    s = pstr._fresh(pd.Series([False, True, True, True, False, True]), pd.Series([False] * 6))
    assert list(s) == [0, 1, 0, 0, 0, 1]
    both = pstr._fresh(pd.Series([True, True]), pd.Series([True, True]))
    assert list(both) == [0, 0]                                                  # a conflict is no signal

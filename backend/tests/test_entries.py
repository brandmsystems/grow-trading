"""strategy/entries.py: entry methods are causal and well-formed. Pure functions on synthetic candles."""
import pandas as pd

from app.services.strategy import entries
from tests.test_bias import candles


def _fut(spot):
    f = spot.copy()
    f["close"] += 12
    f["volume"] = 1000.0 + (f.index % 17) * 150
    return f


def test_every_method_is_causal_appending_or_changing_later_candles_never_changes_earlier_signals():
    spot = candles(days=14, seed=11, futures=True, vol=7.0)
    fut = _fut(spot)
    cut = pd.Timestamp("2026-10-13 11:20")
    a = entries.frame(spot[spot.ts < cut], fut[fut.ts < cut])
    sa = entries.signals(a)
    b = entries.frame(spot, fut)
    sb = entries.signals(b)
    b = b[b["close_ts"] <= a["close_ts"].max()]
    sb = sb.loc[b.index].reset_index(drop=True)
    assert len(sa) == len(sb) > 500
    pd.testing.assert_frame_equal(sa, sb, check_dtype=False)
    other = spot.copy()
    other.loc[other.ts >= cut, ["open", "high", "low", "close"]] += 500    # a different future
    c = entries.frame(other, fut)
    sc = entries.signals(c).loc[c["close_ts"] <= a["close_ts"].max()].reset_index(drop=True)
    pd.testing.assert_frame_equal(sa, sc, check_dtype=False)


def test_signals_are_plus_minus_one_for_every_method_and_respect_the_cooldown():
    spot = candles(days=14, seed=4, futures=True, vol=7.0)
    f = entries.frame(spot, _fut(spot))
    s = entries.signals(f)
    assert list(s.columns) == list(entries.METHODS)
    assert set(s.stack().unique()) <= {-1, 0, 1}
    for k in s:
        idx = s.index[s[k] != 0]
        gaps = [(f.loc[j, "day"] == f.loc[i, "day"], j - i) for i, j in zip(idx[:-1], idx[1:])]
        assert all(not same or g > entries.COOLDOWN_BARS for same, g in gaps), k
    assert (s != 0).any().sum() >= 12            # most methods fire on a noisy series


def test_fresh_cross_fires_exactly_when_ema_order_flips():
    spot = candles(days=10, seed=9, vol=8.0)
    f = entries.frame(spot, None)
    s = entries.signals(f, cooldown=False)["cross_9_21"]
    d = (f["ema9"] > f["ema21"]).astype(int) * 2 - 1
    flips = d != d.shift(1)
    flips.iloc[0] = False
    assert ((s != 0) == flips).all()
    assert (s[flips] == d[flips]).all()


def test_opening_range_breakout_fires_once_per_day_and_direction_after_0930():
    spot = candles(days=12, seed=2, vol=9.0)
    f = entries.frame(spot, None)
    s = entries.signals(f, cooldown=False)["orb"]
    for _, g in s.groupby(f["day"]):
        assert (g == 1).sum() <= 1 and (g == -1).sum() <= 1
    first3 = f.groupby("day").cumcount() < 3
    assert (s[first3] == 0).all()

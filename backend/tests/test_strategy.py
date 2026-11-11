from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services.strategy import rules as st

D = date(2025, 3, 4)


def minute_bars(day=D, start="09:15", end="15:29", price=100.0):
    ts = pd.date_range(f"{day} {start}", f"{day} {end}", freq="1min")
    n = len(ts)
    close = price + np.arange(n, dtype=float)
    return pd.DataFrame({"ts": ts, "open": close - 0.5, "high": close + 1, "low": close - 1, "close": close})


# ------------------------------------------------------------- resampling
@pytest.mark.parametrize("tf,count,first_close,last_start,last_close", [
    (5, 75, "09:20", "15:25", "15:30"),
    (15, 25, "09:30", "15:15", "15:30"),
    (30, 13, "09:45", "15:15", "15:30"),   # last 30m bar is partial, capped at 15:30
])
def test_resample_alignment(tf, count, first_close, last_start, last_close):
    bars = st.resample(minute_bars(), tf)
    assert len(bars) == count
    assert bars["start"].iloc[0] == pd.Timestamp(f"{D} 09:15")
    assert bars["close_ts"].iloc[0] == pd.Timestamp(f"{D} {first_close}")
    assert bars["start"].iloc[-1] == pd.Timestamp(f"{D} {last_start}")
    assert bars["close_ts"].iloc[-1] == pd.Timestamp(f"{D} {last_close}")


def test_resample_ohlc_and_ignores_out_of_session():
    df = minute_bars()
    extra = pd.DataFrame({"ts": [pd.Timestamp(f"{D} 09:10"), pd.Timestamp(f"{D} 15:31")],
                          "open": [1, 1], "high": [1e9, 1e9], "low": [-1, -1], "close": [1, 1]})
    bars = st.resample(pd.concat([extra, df]), 15)
    b0 = bars.iloc[0]
    assert b0["open"] == 99.5 and b0["close"] == 114 and b0["high"] == 115 and b0["low"] == 99
    assert bars["high"].max() < 1e9


def test_resample_multi_day_does_not_cross_days():
    df = pd.concat([minute_bars(D), minute_bars(D + timedelta(days=1), price=500)])
    bars = st.resample(df, 30)
    assert len(bars) == 26
    assert set(bars["day"]) == {D, D + timedelta(days=1)}


# ------------------------------------------------------------- crosses
def _bars_from_diff(diffs, day=D, tf=15, closes=None):
    starts = [datetime.combine(day, time(9, 15)) + timedelta(minutes=tf * i) for i in range(len(diffs))]
    return pd.DataFrame({
        "start": pd.to_datetime(starts),
        "close_ts": pd.to_datetime([s + timedelta(minutes=tf) for s in starts]),
        "close": closes or [24000.0] * len(diffs),
        "ema9": [100 + d for d in diffs], "ema21": [100.0] * len(diffs),
        "day": [day] * len(diffs),
    })


def test_cross_detection_and_ties():
    c = st.find_crosses(_bars_from_diff([-1, -1, 1, 1, 0, -1]))
    assert list(c.index) == [2, 5] and list(c["direction"]) == [1, -1]


def test_tie_then_same_side_is_not_a_cross():
    assert st.find_crosses(_bars_from_diff([-1, 0, -1, 0, 0, -2])).empty


def test_tie_then_flip_crosses_on_the_flip_bar():
    c = st.find_crosses(_bars_from_diff([-1, 0, 0, 1]))
    assert list(c.index) == [3] and c["direction"].iloc[0] == 1


def test_first_bar_never_a_cross():
    assert st.find_crosses(_bars_from_diff([1, 1])).empty


# ------------------------------------------------------------- trade sequencing
def _diffs_with_crosses(n, flips):
    """Build a diff series that is -1 initially and flips sign at the given bar indices."""
    out, s = [], -1
    for i in range(n):
        if i in flips:
            s = -s
        out.append(s)
    return out


def close_time(i, tf=15):
    return (datetime.combine(D, time(9, 15)) + timedelta(minutes=tf * (i + 1))).time()


def test_window_reversal_and_square_off():
    # 15m bars: idx1 closes 09:45 (before start 10:00), idx4 10:30, idx6 11:00
    bars = _bars_from_diff(_diffs_with_crosses(25, {1, 4, 6}))
    legs, nt = st.generate_legs(bars, {D}, time(10, 0), time(14, 30))
    assert nt == {}
    assert [(l.direction, l.entry_ts.time(), l.exit_ts.time(), l.exit_reason, l.ordinal) for l in legs] == [
        (-1, time(10, 30), time(11, 0), "opposite_cross", 1),
        (1, time(11, 0), time(15, 0), "square_off", 2),
    ]
    assert legs[0].bars_held == 2


def test_cross_after_cutoff_exits_but_does_not_reverse():
    bars = _bars_from_diff(_diffs_with_crosses(25, {4, 10}))   # 10:30 and 12:00
    legs, _ = st.generate_legs(bars, {D}, time(9, 30), time(11, 30))
    assert len(legs) == 1
    assert legs[0].exit_ts.time() == time(12, 0) and legs[0].exit_reason == "opposite_cross"


def test_window_edges_are_inclusive():
    bars = _bars_from_diff(_diffs_with_crosses(25, {0 + 0, 0}))  # no-op
    bars = _bars_from_diff(_diffs_with_crosses(25, {0, 1}))      # idx0 can't cross; idx1 closes 09:45
    legs, _ = st.generate_legs(bars, {D}, time(9, 45) if False else time(9, 30), time(14, 30))
    # idx1 (09:45) flips back to -1 relative to idx0 (+1): a bearish cross inside window
    assert legs[0].entry_ts.time() == time(9, 45)
    bars = _bars_from_diff(_diffs_with_crosses(25, {1, 20}))    # idx20 closes 14:30 == cutoff
    legs, _ = st.generate_legs(bars, {D}, time(10, 0), time(14, 30))
    assert [l.entry_ts.time() for l in legs] == [time(14, 30)]
    bars = _bars_from_diff(_diffs_with_crosses(25, {2}))        # idx2 closes 10:00 == start
    legs, _ = st.generate_legs(bars, {D}, time(10, 0), time(14, 30))
    assert [l.entry_ts.time() for l in legs] == [time(10, 0)]


def test_signals_at_or_after_square_off_ignored():
    bars = _bars_from_diff(_diffs_with_crosses(25, {4, 22}))   # idx22 closes 15:00
    legs, _ = st.generate_legs(bars, {D}, time(9, 30), time(14, 30))
    assert len(legs) == 1 and legs[0].exit_reason == "square_off"


def test_no_trade_day_reason():
    bars = _bars_from_diff([-1] * 25)
    legs, nt = st.generate_legs(bars, {D}, time(9, 30), time(14, 30))
    assert legs == [] and D in nt


def test_entry_uses_signal_bar_close_and_close_price():
    closes = [24000.0 + i for i in range(25)]
    bars = _bars_from_diff(_diffs_with_crosses(25, {4}), closes=closes)
    legs, _ = st.generate_legs(bars, {D}, time(9, 30), time(14, 30))
    assert legs[0].signal_close == 24004.0
    assert legs[0].entry_ts == datetime.combine(D, time(10, 30))


# ------------------------------------------------------------- option selection
@pytest.mark.parametrize("spot,atm", [(24024.99, 24000), (24025, 24050), (24074.9, 24050), (24075, 24100)])
def test_atm_strike(spot, atm):
    assert st.atm_strike(spot) == atm


@pytest.mark.parametrize("mode,direction,expected", [
    ("ITM5_BUY", 1, (23750, "CE", "BUY")),
    ("ITM5_BUY", -1, (24250, "PE", "BUY")),
    ("ATM_BUY", 1, (24000, "CE", "BUY")),
    ("ATM_BUY", -1, (24000, "PE", "BUY")),
    ("ATM_SELL", 1, (24000, "PE", "SELL")),
    ("ATM_SELL", -1, (24000, "CE", "SELL")),
])
def test_option_for(mode, direction, expected):
    assert st.option_for(mode, direction, 24010) == expected


def test_pick_expiry():
    exps = [date(2025, 3, 4), date(2025, 3, 11)]
    assert st.pick_expiry(date(2025, 3, 3), exps) == date(2025, 3, 4)
    assert st.pick_expiry(date(2025, 3, 4), exps, True) == date(2025, 3, 11)
    assert st.pick_expiry(date(2025, 3, 4), exps, False) == date(2025, 3, 4)
    assert st.pick_expiry(date(2025, 3, 12), exps) is None


def test_price_at():
    df = minute_bars()
    df = df[df["ts"] != pd.Timestamp(f"{D} 10:30")]
    assert st.price_at(df, datetime.combine(D, time(10, 0)))[0] == df.loc[df["ts"] == f"{D} 10:00", "open"].iloc[0]
    px, ts = st.price_at(df, datetime.combine(D, time(10, 30)))
    assert ts == datetime.combine(D, time(10, 31))
    gap = df[(df["ts"] < f"{D} 11:00") | (df["ts"] > f"{D} 11:10")]
    assert st.price_at(gap, datetime.combine(D, time(11, 1)))[0] is None
    tail = df[df["ts"] <= f"{D} 14:50"]
    px, ts = st.price_at(tail, datetime.combine(D, time(15, 0)), fallback_prev=True)
    assert px == tail["close"].iloc[-1]

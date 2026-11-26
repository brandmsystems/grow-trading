"""Technical indicators on closed bars. Every value at bar i uses bars <= i only."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def wilder(x: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing: the first value is the simple mean of the first n inputs,
    then avg = (prev * (n - 1) + x) / n. Leading NaNs are skipped."""
    v = x.to_numpy(dtype=float)
    out = np.full(len(v), np.nan)
    idx = np.flatnonzero(~np.isnan(v))
    if len(idx) >= n:
        first = idx[0] + n - 1
        out[first] = np.nanmean(v[idx[0]:first + 1])
        prev = out[first]
        for i in range(first + 1, len(v)):
            if not np.isnan(v[i]):
                prev = (prev * (n - 1) + v[i]) / n
            out[i] = prev
    return pd.Series(out, index=x.index)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), n)
    loss = wilder(-delta.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's ATR. The previous close carries across days, so overnight gaps count."""
    prev = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev).abs(), (bars["low"] - prev).abs()], axis=1).max(axis=1)
    return wilder(tr, n)


def session_vwap(df1m: pd.DataFrame) -> pd.Series:
    """Cumulative VWAP from the day's first candle, per minute. NaN until volume trades."""
    tp = (df1m["high"] + df1m["low"] + df1m["close"]) / 3
    day = df1m["ts"].dt.date
    pv = (tp * df1m["volume"]).groupby(day).cumsum()
    vol = df1m["volume"].groupby(day).cumsum()
    return pv / vol.replace(0, np.nan)


# ---------------------------------------------------------------- price-action studies (closed bars, causal)
def fvg_zones(bars: pd.DataFrame, min_atr: float = 0.1, max_age: int = 24) -> pd.DataFrame:
    """Fair value gaps: a three-candle imbalance. Bullish when bar i's low is above bar i-2's high (zone = that gap),
    bearish when bar i's high is below bar i-2's low. The gap is known when bar i closes, never earlier, and
    only gaps of at least `min_atr` x ATR count. Zones live for one session (`day` column) and `max_age` bars.

    Status of a zone after each later bar: *unfilled* (price has not traded back into it), *mitigated* (price traded
    into it but not through it) and *filled* (traded through the far edge: the zone is finished). A **retest** is a
    bar that trades into an unfilled or mitigated zone, holds it (does not trade through) and closes back out of it in
    the gap's direction on a candle of that colour. Per bar the result holds, for each side, the zone in focus (the one
    retested on this bar, else the newest active one, else one filled on this bar): `fvg_{bull,bear}_{lo,hi,state,age,
    retest,fresh,n}` (`fresh`: the retest is the gap's first return, so it was unmitigated until this bar) plus `fvg_new` (+1/-1 on the bar that completed a gap). Every value uses bars <= i only."""
    n = len(bars)
    hi, lo = bars["high"].to_numpy(float), bars["low"].to_numpy(float)
    op, cl = bars["open"].to_numpy(float), bars["close"].to_numpy(float)
    a = (bars["atr"] if "atr" in bars else atr(bars)).to_numpy(float)
    day = bars["day"].to_numpy() if "day" in bars else bars["ts"].dt.date.to_numpy()
    cols = {f"fvg_{s}_{k}": np.full(n, np.nan if k in ("lo", "hi", "age") else None, dtype=object if k == "state" else float)
            for s in ("bull", "bear") for k in ("lo", "hi", "state", "age")}
    retest = {s: np.zeros(n, dtype=bool) for s in ("bull", "bear")}
    fresh = {s: np.zeros(n, dtype=bool) for s in ("bull", "bear")}
    count = {s: np.zeros(n, dtype=int) for s in ("bull", "bear")}
    new = np.zeros(n, dtype=int)
    active = {1: [], -1: []}               # zones: [lo, hi, born bar, touched]
    cur = None
    for i in range(n):
        if day[i] != cur:
            active, cur = {1: [], -1: []}, day[i]
        hit, filled_now, first = {1: None, -1: None}, {1: None, -1: None}, {1: False, -1: False}
        for side in (1, -1):
            keep = []
            for z in active[side]:
                if i - z[2] > max_age:
                    continue                                    # expired
                if side == 1:
                    through, entered = lo[i] <= z[0], lo[i] <= z[1]
                    confirm = cl[i] > z[1] and cl[i] > op[i]
                else:
                    through, entered = hi[i] >= z[1], hi[i] >= z[0]
                    confirm = cl[i] < z[0] and cl[i] < op[i]
                if through:
                    filled_now[side] = z
                    continue                                    # fully filled: finished
                if entered:
                    was_untouched = not z[3]
                    z[3] = True
                    if confirm:
                        hit[side], first[side] = z, was_untouched
                keep.append(z)
            active[side] = keep
        if i >= 2 and day[i - 2] == day[i] and not np.isnan(a[i]) and a[i] > 0:
            if lo[i] > hi[i - 2] and lo[i] - hi[i - 2] >= min_atr * a[i]:
                active[1].append([hi[i - 2], lo[i], i, False])
                new[i] = 1
            elif hi[i] < lo[i - 2] and lo[i - 2] - hi[i] >= min_atr * a[i]:
                active[-1].append([hi[i], lo[i - 2], i, False])
                new[i] = -1
        for side, name in ((1, "bull"), (-1, "bear")):
            z = hit[side] or (active[side][-1] if active[side] else None)
            state = None
            if z is not None:
                state = "mitigated" if z[3] else "unfilled"
            elif filled_now[side] is not None:
                z, state = filled_now[side], "filled"
            count[name][i] = len(active[side])
            if z is not None:
                cols[f"fvg_{name}_lo"][i], cols[f"fvg_{name}_hi"][i] = z[0], z[1]
                cols[f"fvg_{name}_state"][i], cols[f"fvg_{name}_age"][i] = state, i - z[2]
                retest[name][i] = hit[side] is not None
                fresh[name][i] = hit[side] is not None and first[side]
    out = pd.DataFrame(cols, index=bars.index)
    for s in ("bull", "bear"):
        out[f"fvg_{s}_retest"], out[f"fvg_{s}_n"] = retest[s], count[s]
        out[f"fvg_{s}_fresh"] = fresh[s]                     # the retest is the FIRST return to a gap that was unmitigated until now
    out["fvg_new"] = new
    return out


def adr(bars: pd.DataFrame, periods=(5, 10, 20)) -> pd.DataFrame:
    """Average Daily Range (high - low) of the previous N completed sessions, and how much of it today has used.
    `adr{N}` is the mean range of the N sessions BEFORE the bar's day (today is never in its own average);
    `range_today` is today's high minus low so far; `adr_used{N}` = range_today / adr{N} in %. NaN until N earlier
    sessions exist. Needs a `day` column."""
    day = bars["day"]
    daily = bars.groupby("day", sort=True).agg(hi=("high", "max"), lo=("low", "min"))
    rng = daily["hi"] - daily["lo"]
    out = pd.DataFrame(index=bars.index)
    out["range_today"] = bars.groupby("day")["high"].cummax() - bars.groupby("day")["low"].cummin()
    for n in periods:
        prior = rng.rolling(n, min_periods=n).mean().shift(1)
        out[f"adr{n}"] = day.map(prior).astype(float)
        out[f"adr_used{n}"] = 100 * out["range_today"] / out[f"adr{n}"].where(out[f"adr{n}"] > 0)
    return out


def swing_structure(bars: pd.DataFrame, k: int = 3, decay: int = 6) -> pd.DataFrame:
    """Market structure from swing pivots. A swing high/low at bar j has the highest high / lowest low of the 2k+1 bars
    around it, so it is only known at bar j+k and is recorded there (the same rule as the RSI divergence pivots).
    `swing_hi` / `swing_lo` are the latest confirmed swings, `struct` is +1 for higher highs and higher lows, -1 for
    lower highs and lower lows, else 0 (NaN until two swings of each kind exist). `bos` is +1/-1 on the bar whose close
    breaks the latest confirmed swing high/low (a break of structure); `bos_recent` keeps it for `decay` bars."""
    n = len(bars)
    hi, lo, cl = bars["high"].to_numpy(float), bars["low"].to_numpy(float), bars["close"].to_numpy(float)
    win = 2 * k + 1
    hp = (bars["high"].shift(k) == bars["high"].rolling(win).max()).to_numpy()
    lp = (bars["low"].shift(k) == bars["low"].rolling(win).min()).to_numpy()
    sh, sl = np.full(n, np.nan), np.full(n, np.nan)
    st_, bos = np.full(n, np.nan), np.zeros(n, dtype=int)
    highs, lows = [], []
    for i in range(n):
        if highs and cl[i] > highs[-1] and i and cl[i - 1] <= highs[-1]:
            bos[i] = 1                                   # judged against swings known before this bar
        elif lows and cl[i] < lows[-1] and i and cl[i - 1] >= lows[-1]:
            bos[i] = -1
        if i >= k:
            if hp[i]:
                highs.append(hi[i - k])
            if lp[i]:
                lows.append(lo[i - k])
        if highs:
            sh[i] = highs[-1]
        if lows:
            sl[i] = lows[-1]
        if len(highs) >= 2 and len(lows) >= 2:
            up, dn = highs[-1] > highs[-2] and lows[-1] > lows[-2], highs[-1] < highs[-2] and lows[-1] < lows[-2]
            st_[i] = 1.0 if up else -1.0 if dn else 0.0
    b = pd.Series(bos, index=bars.index)
    recent = b.where(b != 0).ffill(limit=decay - 1).fillna(0).astype(int)
    return pd.DataFrame({"swing_hi": sh, "swing_lo": sl, "struct": st_, "bos": b, "bos_recent": recent}, index=bars.index)


def adx(bars: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """Wilder's ADX with +DI / -DI (columns plus_di, minus_di, adx). Value at bar i uses bars <= i only."""
    up, down = bars["high"].diff(), -bars["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=bars.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=bars.index)
    prev = bars["close"].shift(1)
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev).abs(), (bars["low"] - prev).abs()], axis=1).max(axis=1)
    atr_ = wilder(tr, n)
    pdi = 100 * wilder(plus_dm, n) / atr_
    mdi = 100 * wilder(minus_dm, n) / atr_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"plus_di": pdi, "minus_di": mdi, "adx": wilder(dx.dropna(), n).reindex(bars.index)})

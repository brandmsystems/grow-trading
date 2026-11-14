"""9/21 EMA crossover: resampling, signals and trade sequencing (pure, no I/O).

Conventions (all explicit, all tested):
* 1-minute candles are stamped with their START time (IST wall clock).
* Resampled bars are aligned to 09:15. A bar covers [start, start+tf) and is
  identified by its CLOSE time = start + tf (the last bar is capped at 15:30).
* EMAs use pandas ewm(span, adjust=False) over the whole series, i.e. they carry
  across days; callers include warm-up days before the first traded day.
* A cross happens on bar i when sign(EMA9-EMA21) differs from the last non-zero
  sign before it. A bar where the EMAs are exactly equal is NOT a cross; it
  keeps the previous sign (ties never generate signals).
* A signal is known only when its bar closes, so the fill is at the OPEN of the
  1-minute candle that starts at the signal bar's close time (no look-ahead).
* Entry window: a cross whose bar close time is within [start, cutoff]
  (inclusive) may open a trade. Crosses outside it never open trades.
* Exits: an opposite cross closes the open trade at any time before 15:00
  (also after the cutoff). Inside the window the same cross also opens the
  reverse trade at the same fill time. Anything still open is squared off at
  the 15:00 1-minute open. Signals whose bar closes at/after 15:00 are ignored.
* Cross ordinal = 1-based rank of the cross among that day's in-window crosses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
SQUARE_OFF = time(15, 0)
FAST, SLOW = 9, 21


def resample(df1m: pd.DataFrame, tf_min: int) -> pd.DataFrame:
    """Resample 1m candles (column ts = start time) into tf-minute bars aligned to 09:15."""
    if df1m.empty:
        return pd.DataFrame(columns=["start", "close_ts", "open", "high", "low", "close", "day"])
    df = df1m.reset_index(drop=True)
    ts = pd.to_datetime(df["ts"])
    day = ts.dt.normalize()
    open_ts = day + pd.Timedelta(hours=9, minutes=15)
    mins = (ts - open_ts).dt.total_seconds() // 60
    df = df[(mins >= 0) & (ts.dt.time < SESSION_CLOSE)].copy()
    mins = mins.loc[df.index]
    df["start"] = open_ts.loc[df.index] + pd.to_timedelta((mins // tf_min) * tf_min, unit="m")
    g = df.groupby("start", sort=True)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
    }).reset_index()
    session_end = out["start"].dt.normalize() + pd.Timedelta(hours=15, minutes=30)
    close_ts = out["start"] + pd.Timedelta(minutes=tf_min)
    out["close_ts"] = close_ts.where(close_ts <= session_end, session_end)
    out["day"] = out["start"].dt.date
    return out


def add_emas(bars: pd.DataFrame) -> pd.DataFrame:
    bars = bars.copy()
    bars["ema9"] = bars["close"].ewm(span=FAST, adjust=False).mean()
    bars["ema21"] = bars["close"].ewm(span=SLOW, adjust=False).mean()
    return bars


def find_crosses(bars: pd.DataFrame, fast: str = "ema9", slow: str = "ema21") -> pd.DataFrame:
    """Return the cross bars with a `direction` column (+1 bullish, -1 bearish)."""
    diff = bars[fast] - bars[slow]
    sign = np.sign(diff).replace(0, np.nan).ffill()
    prev = sign.shift(1)
    is_cross = sign.notna() & prev.notna() & (sign != prev)
    out = bars.loc[is_cross].copy()
    out["direction"] = sign[is_cross].astype(int)
    return out


@dataclass
class Leg:
    """Direction-level trade (independent of execution mode)."""
    day: date
    direction: int                 # +1 long NIFTY view, -1 short view
    entry_ts: datetime             # fill time (= signal bar close)
    signal_close: float            # spot close of signal bar (used for strike)
    signal_bar_start: datetime
    ordinal: int
    exit_ts: datetime | None = None
    exit_reason: str | None = None
    bars_held: int = 0
    extra: dict = field(default_factory=dict)


def _t(ts) -> time:
    return pd.Timestamp(ts).time()


def generate_legs(bars: pd.DataFrame, trade_days: set[date], start: time, cutoff: time,
                  fast: str = "ema9", slow: str = "ema21", confirm: bool = False) -> tuple[list[Leg], dict[date, str]]:
    """Walk crosses day by day and build the trade sequence.

    `bars` must already contain EMAs (computed with warm-up history).
    With `confirm`, a cross opens a trade only if the bar's `bull_ok`/`bear_ok` column
    agrees; an unconfirmed cross still exits an open opposite trade.
    Returns (legs, no_trade_reasons) for days in `trade_days`.
    """
    crosses = find_crosses(bars, fast, slow)
    bar_close_index = {pd.Timestamp(t): i for i, t in enumerate(bars["close_ts"])}
    legs: list[Leg] = []
    no_trade: dict[date, str] = {}
    by_day = {d: g for d, g in crosses.groupby("day")} if not crosses.empty else {}
    for d in sorted(trade_days):
        day_crosses = by_day.get(d)
        open_leg: Leg | None = None
        ordinal = 0
        unconfirmed = 0
        day_legs: list[Leg] = []
        if day_crosses is not None:
            for _, cx in day_crosses.iterrows():
                close_t = _t(cx["close_ts"])
                if close_t >= SQUARE_OFF:
                    continue
                in_window = start <= close_t <= cutoff
                if open_leg is not None and cx["direction"] != open_leg.direction:
                    open_leg.exit_ts = pd.Timestamp(cx["close_ts"]).to_pydatetime()
                    open_leg.exit_reason = "opposite_cross"
                    open_leg = None
                if in_window:
                    ordinal += 1
                    ok = not confirm or bool(cx["bull_ok"] if cx["direction"] > 0 else cx["bear_ok"])
                    if not ok:
                        unconfirmed += 1
                    if open_leg is None and ok:
                        open_leg = Leg(day=d, direction=int(cx["direction"]),
                                       entry_ts=pd.Timestamp(cx["close_ts"]).to_pydatetime(),
                                       signal_close=float(cx["close"]),
                                       signal_bar_start=pd.Timestamp(cx["start"]).to_pydatetime(),
                                       ordinal=ordinal)
                        day_legs.append(open_leg)
        if open_leg is not None:
            open_leg.exit_ts = datetime.combine(d, SQUARE_OFF)
            open_leg.exit_reason = "square_off"
        for leg in day_legs:
            i0 = bar_close_index.get(pd.Timestamp(leg.entry_ts))
            i1 = bar_close_index.get(pd.Timestamp(leg.exit_ts))
            if i0 is not None and i1 is not None:
                leg.bars_held = i1 - i0
            else:  # square-off at 15:00 may not be a bar close for 30m bars
                tf = (bars["close_ts"].iloc[1] - bars["start"].iloc[1]) if len(bars) > 1 else timedelta(minutes=5)
                leg.bars_held = int((pd.Timestamp(leg.exit_ts) - pd.Timestamp(leg.entry_ts)) / tf)
        legs.extend(day_legs)
        if not day_legs:
            no_trade[d] = (f"{unconfirmed} crossover(s) in the window, none confirmed" if unconfirmed
                           else "No crossover inside the entry window")
    return legs, no_trade


# ---------------------------------------------------------------- option selection
STRIKE_STEP = 50
MODES = {
    # mode: (side, strike offset in steps toward ITM)
    "ITM5_BUY": ("BUY", 5),
    "ATM_BUY": ("BUY", 0),
    "ATM_SELL": ("SELL", 0),
}
MODE_LABELS = {"ITM5_BUY": "Deep ITM buy (ITM 5)", "ATM_BUY": "ATM buy", "ATM_SELL": "ATM sell"}


def atm_strike(spot: float, step: int = STRIKE_STEP) -> float:
    """Nearest strike; exact halves round UP (e.g. 24025 -> 24050)."""
    return float(np.floor(spot / step + 0.5) * step)


def option_for(mode: str, direction: int, spot: float, step: int = STRIKE_STEP) -> tuple[float, str, str]:
    """Return (strike, CE/PE, BUY/SELL) for a mode and signal direction.

    Bullish (+1): buy CE (ITM = lower strike) or sell PE.
    Bearish (-1): buy PE (ITM = higher strike) or sell CE.
    """
    side, itm_steps = MODES[mode]
    atm = atm_strike(spot, step)
    if side == "BUY":
        typ = "CE" if direction > 0 else "PE"
        strike = atm - itm_steps * step if typ == "CE" else atm + itm_steps * step
    else:
        typ = "PE" if direction > 0 else "CE"
        strike = atm
    return strike, typ, side


EXPIRY_RULES = {"nearest": "Nearest weekly", "next": "Next weekly", "monthly": "Nearest monthly"}


def pick_expiry(day: date, expiries: list[date], roll_on_expiry_day: bool = True, rule: str = "nearest") -> date | None:
    """Expiry on/after `day` by rule; on expiry day itself optionally roll to the next one.

    nearest: the first eligible expiry. next: the one after it.
    monthly: the first eligible expiry that is the last expiry of its calendar month.
    """
    exps = sorted(expiries)
    eligible = [e for e in exps if e > day or (e == day and not roll_on_expiry_day)]
    if rule == "monthly":
        last_of_month = {}
        for e in exps:
            last_of_month[(e.year, e.month)] = e
        eligible = [e for e in eligible if last_of_month[(e.year, e.month)] == e]
    idx = 1 if rule == "next" else 0
    return eligible[idx] if len(eligible) > idx else None


def price_at(df1m: pd.DataFrame, ts: datetime, max_wait_min: int = 3, fallback_prev: bool = False):
    """Open of the 1m candle starting at ts; else the next candle within max_wait_min.

    With fallback_prev, use the last close before ts (same day) if nothing follows.
    Returns (price, actual_ts) or (None, None).
    """
    if df1m.empty:
        return None, None
    ts = pd.Timestamp(ts)
    stamps = df1m["ts"]
    if stamps.is_monotonic_increasing:
        # Fast path, same answer: candles are stored and loaded oldest first, so the first candle
        # at or after ts is a binary search away, and the last candle before ts is the one just
        # before it (it is "same day" only if its date matches, as in the general path below).
        i = int(stamps.searchsorted(ts, side="left"))
        if i < len(stamps) and stamps.iloc[i] <= ts + pd.Timedelta(minutes=max_wait_min):
            r = df1m.iloc[i]
            return float(r["open"]), r["ts"].to_pydatetime()
        if fallback_prev and i > 0 and stamps.iloc[i - 1].date() == ts.date():
            r = df1m.iloc[i - 1]
            return float(r["close"]), (r["ts"] + pd.Timedelta(minutes=1)).to_pydatetime()
        return None, None
    after = df1m[(df1m["ts"] >= ts) & (df1m["ts"] <= ts + pd.Timedelta(minutes=max_wait_min))]
    if not after.empty:
        r = after.iloc[0]
        return float(r["open"]), r["ts"].to_pydatetime()
    if fallback_prev:
        before = df1m[(df1m["ts"] < ts) & (df1m["ts"].dt.date == ts.date())]
        if not before.empty:
            r = before.iloc[-1]
            return float(r["close"]), (r["ts"] + pd.Timedelta(minutes=1)).to_pydatetime()
    return None, None

"""Backtest orchestration: data -> signals -> per-mode option trades -> metrics."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, time, timedelta
from functools import lru_cache

import pandas as pd

import costs
import db
import metrics
import providers
import strategy as st

log = logging.getLogger("backtest")

WARMUP_DAYS = 3
WHIPSAW_BARS = 2
DEFAULTS = {
    "dataset": "synthetic",
    "start_date": None,
    "end_date": None,
    "timeframe": 15,
    "entry_start": "09:30",
    "cutoff": "14:30",
    "roll_on_expiry_day": True,
    "lot_size": 65,
    "lots": 1,
    "capital": 100000,
    "costs": costs.DEFAULT_COSTS.to_dict(),
}
START_CHOICES = ["09:30", "10:00", "10:30"]
CUTOFF_CHOICES = ["11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30"]
TIMEFRAMES = [5, 15, 30]
ENGINE_VERSION = 1   # bump to invalidate cached runs when logic changes


def _now() -> datetime:
    return datetime.now()


def data_stale(last: datetime | None) -> bool:
    """True when the market should have produced candles newer than `last`."""
    now = _now()
    day = now.date() if now.time() >= time(9, 16) else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    latest = min(now.replace(second=0, microsecond=0) - timedelta(minutes=1),
                 datetime.combine(day, time(15, 29)))
    return last is None or last < latest


def _session_asof(spot: pd.DataFrame) -> datetime | None:
    """If today's session is unfinished, the time the stored candles run up to."""
    if spot.empty:
        return None
    last = spot["ts"].max()
    if last.date() == _now().date() and last.time() < time(15, 29):
        return (last + pd.Timedelta(minutes=1)).to_pydatetime()
    return None


def normalise(params: dict) -> dict:
    p = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    p["costs"] = {**costs.DEFAULT_COSTS.to_dict(), **(params.get("costs") or {})}
    p["end_date"] = str(p["end_date"] or _now().date())
    p["start_date"] = str(p["start_date"] or (date.fromisoformat(p["end_date"]) - timedelta(days=90)))
    p["timeframe"] = int(p["timeframe"])
    if p["timeframe"] not in TIMEFRAMES:
        raise ValueError("timeframe must be 5, 15 or 30")
    if p["entry_start"] not in START_CHOICES or p["cutoff"] not in CUTOFF_CHOICES:
        raise ValueError("invalid entry window")
    if date.fromisoformat(p["start_date"]) > date.fromisoformat(p["end_date"]):
        raise ValueError("start date is after end date")
    p["roll_on_expiry_day"] = bool(p["roll_on_expiry_day"])
    for k in ("lot_size", "lots"):
        p[k] = int(p[k])
    p["capital"] = float(p["capital"])
    p["costs"] = {k: float(v) for k, v in p["costs"].items()}
    return p


def param_hash(p: dict) -> str:
    blob = json.dumps({**p, "_v": ENGINE_VERSION}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _hm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _day_range(symbol: str, day: date) -> pd.DataFrame:
    return db.load_candles(symbol, datetime.combine(day, time(0)), datetime.combine(day + timedelta(days=1), time(0)))


def ensure_data(params: dict, progress=None) -> dict:
    p = normalise(params)
    prov = providers.get(p["dataset"])
    s, e = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
    out = prov.ensure_spot(s - timedelta(days=10), e, progress)
    prov.ensure_expiries(s, e)
    db.clear_runs(p["dataset"])
    spot_bars.cache_clear()
    option_candles.cache_clear()
    return out


def run(params: dict, progress=None, use_cache: bool = True) -> dict:
    p = normalise(params)
    h = param_hash(p)
    if use_cache:
        cached = db.get_run(h)
        if cached and not cached["result"].get("partial_asof"):
            return cached["result"]
    prov = providers.get(p["dataset"])
    s, e = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
    say = progress or (lambda *_: None)

    say(0.02, "Loading spot candles")
    spot = db.load_candles(prov.spot_symbol, datetime.combine(s - timedelta(days=12), time(0)),
                           datetime.combine(e + timedelta(days=1), time(0)))
    spot = spot[spot["ts"] + pd.Timedelta(minutes=1) <= _now()]   # drop the minute still forming
    if spot.empty:
        raise LookupError("No spot data in this range. Download data first.")
    asof = _session_asof(spot)
    spot_days = sorted(set(spot["ts"].dt.date))
    first_tradeable = spot_days[WARMUP_DAYS] if len(spot_days) > WARMUP_DAYS else None
    trade_days = {d for d in spot_days if s <= d <= e and first_tradeable and d >= first_tradeable}

    no_trade: dict[date, str] = {}
    d = s
    while d <= e:
        if d.weekday() < 5 and d not in set(spot_days):
            no_trade[d] = "No spot data (market holiday or not downloaded)"
        elif d.weekday() < 5 and d not in trade_days and s <= d:
            no_trade[d] = f"EMA warm-up (needs {WARMUP_DAYS} prior sessions)"
        d += timedelta(days=1)

    say(0.06, "Computing signals")
    bars = st.add_emas(st.resample(spot, p["timeframe"]))
    if asof:   # the bar still forming must not produce a signal
        bars = bars[bars["close_ts"] <= asof].reset_index(drop=True)
    legs, nt = st.generate_legs(bars, trade_days, _hm(p["entry_start"]), _hm(p["cutoff"]))
    no_trade.update(nt)
    if asof:
        if asof.date() in no_trade:
            no_trade[asof.date()] = "No crossover inside the entry window so far today"
        legs = [l for l in legs if l.entry_ts < asof]   # fill candle hasn't happened yet
        for leg in legs:
            if leg.exit_ts > asof:   # still open: value it at the latest price
                leg.exit_ts, leg.exit_reason = asof, "open"
                leg.bars_held = int((asof - leg.entry_ts) / timedelta(minutes=p["timeframe"]))

    expiries = prov.ensure_expiries(s, e)
    qty = p["lot_size"] * p["lots"]
    cfg = costs.CostConfig(**p["costs"])
    spot_by_day = {d: g for d, g in spot.groupby(spot["ts"].dt.date)}
    opt_cache: dict[tuple[str, date], pd.DataFrame] = {}
    trades: dict[str, list[dict]] = {m: [] for m in st.MODES}
    skipped: list[dict] = []

    for i, leg in enumerate(legs):
        say(0.08 + 0.9 * i / max(1, len(legs)), f"Pricing trades {i + 1}/{len(legs)} ({leg.day:%d %b})")
        sday = spot_by_day[leg.day]
        spot_in, _ = st.price_at(sday, leg.entry_ts)
        spot_out, _ = st.price_at(sday, leg.exit_ts, fallback_prev=True)
        expiry = st.pick_expiry(leg.day, expiries, p["roll_on_expiry_day"])
        for mode in st.MODES:
            strike, typ, side = st.option_for(mode, leg.direction, leg.signal_close)
            base = {"mode": mode, "day": leg.day.isoformat(), "entry_ts": leg.entry_ts.isoformat(),
                    "direction": "Bullish" if leg.direction > 0 else "Bearish",
                    "strike": strike, "opt_type": typ}
            if expiry is None:
                skipped.append({**base, "reason": "No expiry available"})
                continue
            try:
                sym = prov.option_symbol(expiry, strike, typ)
                if sym is None:
                    skipped.append({**base, "reason": f"Contract not listed ({int(strike)} {typ} {expiry})"})
                    continue
                key = (sym, leg.day)
                if key not in opt_cache:
                    prov.ensure_option_day(sym, leg.day)
                    opt_cache[key] = _day_range(sym, leg.day)
                    if asof and leg.day == asof.date():
                        opt_cache[key] = opt_cache[key][opt_cache[key]["ts"] < asof]
                odf = opt_cache[key]
            except Exception as exc:  # network/API issues for one contract shouldn't kill the run
                log.warning("option data failed for %s: %s", base, exc)
                skipped.append({**base, "reason": f"Option data error: {exc}"})
                continue
            px_in, ts_in = st.price_at(odf, leg.entry_ts)
            px_out, ts_out = st.price_at(odf, leg.exit_ts, fallback_prev=True)
            if px_in is None or px_out is None:
                skipped.append({**base, "symbol": sym, "reason": "No option candle within 3 min of fill"})
                continue
            pnl = costs.round_trip(side, px_in, px_out, qty, cfg)
            whipsaw = leg.exit_reason == "opposite_cross" and leg.bars_held <= WHIPSAW_BARS
            trades[mode].append({
                **base,
                "id": f"{mode}-{len(trades[mode]) + 1}",
                "side": side, "symbol": sym, "expiry": expiry.isoformat(),
                "dte": (expiry - leg.day).days,
                "exit_ts": leg.exit_ts.isoformat(), "exit_reason": leg.exit_reason,
                "fill_entry_ts": ts_in.isoformat(), "fill_exit_ts": ts_out.isoformat(),
                "signal_close": round(leg.signal_close, 2),
                "spot_entry": spot_in, "spot_exit": spot_out,
                "opt_entry": round(px_in, 2), "opt_exit": round(px_out, 2),
                "qty": qty, "ordinal": leg.ordinal, "bars_held": leg.bars_held,
                "whipsaw": whipsaw, "outcome": "win" if pnl["net"] > 0 else "loss",
                **pnl,
            })

    result = {
        "params": p,
        "hash": h,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_label": prov.label,
        "partial_asof": asof.isoformat() if asof else None,
        "signals": len(legs),
        "trade_days": len(trade_days),
        "summary": {m: {"label": st.MODE_LABELS[m], **metrics.compute(trades[m], p["capital"])}
                    for m in st.MODES},
        "trades": trades,
        "no_trade_days": [{"day": d.isoformat(), "reason": r} for d, r in sorted(no_trade.items())],
        "skipped": skipped,
    }
    db.save_run(h, p, result)
    say(1.0, "Done")
    return result


# ---------------------------------------------------------------- chart payloads
@lru_cache(maxsize=64)
def spot_bars(dataset: str, day: date, tf: int) -> list[dict]:
    """Signal-timeframe bars for one day with EMAs computed over prior warm-up days."""
    prov = providers.get(dataset)
    df = db.load_candles(prov.spot_symbol, datetime.combine(day - timedelta(days=12), time(0)),
                         datetime.combine(day + timedelta(days=1), time(0)))
    df = df[df["ts"] + pd.Timedelta(minutes=1) <= _now()]
    bars = st.add_emas(st.resample(df, tf))
    asof = _session_asof(df)
    if asof:
        bars = bars[bars["close_ts"] <= asof]
    bars = bars[bars["day"] == day]
    return [{"t": r.start.isoformat(), "c_ts": r.close_ts.isoformat(), "o": r.open, "h": r.high,
             "l": r.low, "c": r.close, "e9": round(r.ema9, 2), "e21": round(r.ema21, 2)}
            for r in bars.itertuples(index=False)]


@lru_cache(maxsize=256)
def option_candles(symbol: str, day: date) -> list[dict]:
    df = _day_range(symbol, day)
    return [{"t": r.ts.isoformat(), "o": r.open, "h": r.high, "l": r.low, "c": r.close}
            for r in df.itertuples(index=False)]

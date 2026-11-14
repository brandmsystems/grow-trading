"""Backtest orchestration: data -> signals -> per-mode option trades -> metrics."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, time, timedelta
from functools import lru_cache

import pandas as pd

from app.utils.timeutil import parse_hm
from app.services.trading import charges as costs
from app.database import db
from app.services.backtest import metrics
from app.services.market_data import history as data_manager
from app.services.market_data import providers
from app.services.options import lot_sizes
from app.services.strategy import strategies
from app.services.strategy import rules as st

log = logging.getLogger("backtest")

WHIPSAW_BARS = 2
DEFAULTS = {
    "dataset": "groww",
    "strategy": strategies.DEFAULT,
    "expiry_rule": "nearest",
    "start_date": None,
    "end_date": None,
    "timeframe": 15,
    "entry_start": "09:30",
    "cutoff": "14:30",
    "roll_on_expiry_day": True,
    "lot_size": 0,          # 0 = each contract's NSE lot size (lot_sizes table); >0 = fixed
    "lots": 1,
    "capital": 100000,
    "costs": costs.DEFAULT_COSTS.to_dict(),
}
START_CHOICES = ["09:30", "10:00", "10:30"]
CUTOFF_CHOICES = ["11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30"]
TIMEFRAMES = [1, 5, 15, 30]
HISTORY_DAYS = 40    # calendar days loaded before the range so indicators have settled
ENGINE_VERSION = 3   # bump to invalidate cached runs when logic changes


def _now() -> datetime:
    return datetime.now()


def data_stale(last: datetime | None, tolerance_min: int = 15) -> bool:
    """True when the market should have produced candles more than `tolerance_min` newer than `last`."""
    now = _now()
    day = now.date() if now.time() >= time(9, 16) else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    latest = min(now.replace(second=0, microsecond=0) - timedelta(minutes=1),
                 datetime.combine(day, time(15, 29)))
    return last is None or last < latest - timedelta(minutes=tolerance_min)


def _session_asof(spot: pd.DataFrame) -> datetime | None:
    """If today's session is unfinished, the time the stored candles run up to."""
    if spot.empty:
        return None
    last = spot["ts"].max()
    if last.date() == _now().date() and last.time() < time(15, 29):
        return (last + pd.Timedelta(minutes=1)).to_pydatetime()
    return None


def normalise(params: dict) -> dict:
    """Fill defaults, coerce types and validate backtest parameters. The result is what gets
    hashed for the result cache, so two equivalent requests share one stored run."""
    p = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    p["costs"] = {**costs.DEFAULT_COSTS.to_dict(), **(params.get("costs") or {})}
    p["end_date"] = str(p["end_date"] or _now().date())
    p["start_date"] = str(p["start_date"] or (date.fromisoformat(p["end_date"]) - timedelta(days=90)))
    p["timeframe"] = int(p["timeframe"])
    if p["timeframe"] not in TIMEFRAMES:
        raise ValueError("timeframe must be 1, 5, 15 or 30")
    if p["strategy"] not in strategies.STRATEGIES:
        raise ValueError("unknown strategy")
    if p["expiry_rule"] not in st.EXPIRY_RULES:
        raise ValueError("unknown expiry rule")
    if p["entry_start"] not in START_CHOICES or p["cutoff"] not in CUTOFF_CHOICES:
        raise ValueError("invalid entry window")
    if date.fromisoformat(p["start_date"]) > date.fromisoformat(p["end_date"]):
        raise ValueError("start date is after end date")
    p["roll_on_expiry_day"] = bool(p["roll_on_expiry_day"])
    for k in ("lot_size", "lots"):
        p[k] = int(p[k])
    if p["lot_size"] < 0 or p["lots"] < 1:
        raise ValueError("lot size must be 0 (NSE history) or positive, and lots at least 1")
    p["capital"] = float(p["capital"])
    p["costs"] = {k: float(v) for k, v in p["costs"].items()}
    return p


def param_hash(p: dict) -> str:
    blob = json.dumps({**p, "_v": ENGINE_VERSION}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


_hm = parse_hm   # kept as a module name: other modules and tests call it here


def _day_range(symbol: str, day: date) -> pd.DataFrame:
    return db.load_candles(symbol, datetime.combine(day, time(0)), datetime.combine(day + timedelta(days=1), time(0)))


def ensure_data(params: dict, progress=None) -> dict:
    """Download what a backtest needs (spot, near-month futures for VWAP, expiries) and clear
    cached runs, since their results were computed on the older data."""
    p = normalise(params)
    prov = providers.get(p["dataset"])
    s, e = date.fromisoformat(p["start_date"]), date.fromisoformat(p["end_date"])
    if p["dataset"] == "groww":   # spot and near-month futures (VWAP and volume need futures)
        out = data_manager.download_all(s - timedelta(days=HISTORY_DAYS), e, progress=progress)
    else:
        out = prov.ensure_spot(s - timedelta(days=10), e, progress)
    prov.ensure_expiries(s, e)
    db.clear_runs(p["dataset"])
    spot_bars.cache_clear()
    option_candles.cache_clear()
    return out


def run(params: dict, progress=None, use_cache: bool = True, save: bool = True) -> dict:
    """Run one backtest: spot candles -> strategy bars -> crossover legs -> option trades per mode.

    Each leg is priced for every execution mode (ATM buy, ITM 5 buy, ATM sell) with the leg's
    expiry, the NSE lot size in force for that expiry and real option candles at the fill times
    (a closed trade with no option candle within 3 minutes of entry or exit is skipped, never
    estimated). Costs come from charges.round_trip. An unfinished session is cut at the last
    completed minute, so no bar or fill uses data from the future. Results are cached by
    parameter hash."""
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
    spot = db.load_candles(prov.spot_symbol, datetime.combine(s - timedelta(days=HISTORY_DAYS), time(0)),
                           datetime.combine(e + timedelta(days=1), time(0)))
    spot = spot[spot["ts"] + pd.Timedelta(minutes=1) <= _now()]   # drop the minute still forming
    if spot.empty:
        raise LookupError("No spot data in this range. Download data first.")
    asof = _session_asof(spot)
    key = p["strategy"]
    warmup = strategies.warmup_sessions(key, p["timeframe"])
    spot_days = sorted(set(spot["ts"].dt.date))
    first_tradeable = spot_days[warmup] if len(spot_days) > warmup else None
    trade_days = {d for d in spot_days if s <= d <= e and first_tradeable and d >= first_tradeable}

    no_trade: dict[date, str] = {}
    d = s
    while d <= e:
        if d.weekday() < 5 and d not in set(spot_days):
            no_trade[d] = "No spot data (market holiday or not downloaded)"
        elif d.weekday() < 5 and d not in trade_days and s <= d:
            no_trade[d] = f"Indicator warm-up (needs {warmup} prior sessions)"
        d += timedelta(days=1)

    say(0.06, "Computing signals")
    fut = None
    if strategies.STRATEGIES[key].confirm == "vwap":
        say(0.04, "Loading NIFTY futures (VWAP)")
        fut = data_manager.futures_1m(s - timedelta(days=HISTORY_DAYS), e)
        fut = fut[fut["ts"] + pd.Timedelta(minutes=1) <= _now()]
        if fut.empty:
            raise LookupError("No NIFTY futures data stored. Download data on the Data page first (it includes futures).")
    bars = strategies.prepare(spot, fut, p["timeframe"], key)
    if asof:   # the bar still forming must not produce a signal
        bars = bars[bars["close_ts"] <= asof].reset_index(drop=True)
    legs, nt = strategies.legs(bars, trade_days, _hm(p["entry_start"]), _hm(p["cutoff"]), key)
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
    cfg = costs.CostConfig(**p["costs"])
    spot_by_day = {d: g for d, g in spot.groupby(spot["ts"].dt.date)}
    contract_days: dict[str, dict[date, pd.DataFrame]] = {}
    empty = spot.iloc[0:0]

    def option_day(sym: str, day: date, expiry: date) -> pd.DataFrame:
        """A contract's candles for one day; each contract is loaded from the DB once."""
        cached = contract_days.get(sym, {})
        if day not in cached:
            prov.ensure_option_day(sym, day)
            last = min(max(expiry, day), day + timedelta(days=29))
            df = db.load_candles(sym, datetime.combine(day, time(0)), datetime.combine(last + timedelta(days=1), time(0)))
            groups = {d: g.reset_index(drop=True) for d, g in df.groupby(df["ts"].dt.date)} if not df.empty else {}
            cached = contract_days.setdefault(sym, {})
            cached.update(groups)
            cached.setdefault(day, empty)
        return cached[day]
    trades: dict[str, list[dict]] = {m: [] for m in st.MODES}
    skipped: list[dict] = []

    if p["dataset"] == "groww" and legs:
        _prefetch_options(prov, legs, expiries, p, say)

    for i, leg in enumerate(legs):
        say(0.5 + 0.49 * i / max(1, len(legs)), f"Pricing trades {i + 1}/{len(legs)} ({leg.day:%d %b})")
        sday = spot_by_day[leg.day]
        spot_in, _ = st.price_at(sday, leg.entry_ts)
        spot_out, _ = st.price_at(sday, leg.exit_ts, fallback_prev=True)
        expiry = st.pick_expiry(leg.day, expiries, p["roll_on_expiry_day"], p["expiry_rule"])
        for mode in st.MODES:
            strike, typ, side = st.option_for(mode, leg.direction, leg.signal_close)
            base = {"mode": mode, "day": leg.day.isoformat(), "entry_ts": leg.entry_ts.isoformat(),
                    "direction": "Bullish" if leg.direction > 0 else "Bearish",
                    "strike": strike, "opt_type": typ}
            if expiry is None:
                skipped.append({**base, "reason": "No expiry available"})
                continue
            if p["lot_size"]:
                lot, lot_src = p["lot_size"], "fixed"
            else:
                try:
                    lot, lot_src = lot_sizes.lot_size_for(expiry, expiries)
                except lot_sizes.LotSizeUnknown as exc:
                    skipped.append({**base, "reason": str(exc)})
                    continue
            qty = lot * p["lots"]
            try:
                sym = prov.option_symbol(expiry, strike, typ)
                if sym is None:
                    skipped.append({**base, "reason": f"Contract not listed ({int(strike)} {typ} {expiry})"})
                    continue
                odf = option_day(sym, leg.day, expiry)
                if asof and leg.day == asof.date():
                    odf = odf[odf["ts"] < asof]
            except Exception as exc:  # network/API issues for one contract shouldn't kill the run
                log.warning("option data failed for %s: %s", base, exc)
                skipped.append({**base, "reason": f"Option data error: {exc}"})
                continue
            px_in, ts_in = st.price_at(odf, leg.entry_ts)
            # Exits need a real candle too: no falling back to an earlier price.
            px_out, ts_out = st.price_at(odf, leg.exit_ts, fallback_prev=bool(asof and leg.exit_reason == "open"))
            if px_in is None or px_out is None:
                which = "entry" if px_in is None else "exit"
                skipped.append({**base, "symbol": sym, "reason": f"No option candle within 3 min of {which}"})
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
                "qty": qty, "lot_size": lot, "lot_source": lot_src, "ordinal": leg.ordinal, "bars_held": leg.bars_held,
                "whipsaw": whipsaw, "outcome": "win" if pnl["net"] > 0 else "loss",
                **pnl,
            })

    result = {
        "params": p,
        "hash": h,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "dataset_label": prov.label,
        "strategy": key,
        "strategy_label": strategies.STRATEGIES[key].label,
        "partial_asof": asof.isoformat() if asof else None,
        "signals": len(legs),
        "trade_days": len(trade_days),
        "summary": {m: {"label": st.MODE_LABELS[m], **metrics.compute(trades[m], p["capital"])}
                    for m in st.MODES},
        "trades": trades,
        "no_trade_days": [{"day": d.isoformat(), "reason": r} for d, r in sorted(no_trade.items())],
        "skipped": skipped,
    }
    if save:
        db.save_run(h, p, result)
    say(1.0, "Done")
    return result


def _prefetch_options(prov, legs, expiries, p, say, workers: int = 4) -> None:
    """Download every option contract the legs need, a few at a time, before pricing.

    Each request covers a contract from its first needed day to expiry (up to 30 days).
    Failures are ignored here; the pricing loop retries and skips with a reason.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    first: dict[str, date] = {}
    for leg in legs:
        expiry = st.pick_expiry(leg.day, expiries, p["roll_on_expiry_day"], p["expiry_rule"])
        if expiry is None:
            continue
        for mode in st.MODES:
            strike, typ, _ = st.option_for(mode, leg.direction, leg.signal_close)
            try:
                sym = prov.option_symbol(expiry, strike, typ)
            except Exception:
                continue
            if sym and (sym not in first or leg.day < first[sym]):
                first[sym] = leg.day
    todo = [(s_, d) for s_, d in first.items() if not db.fetched(s_, d)]
    if not todo:
        return
    done = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="optfetch") as ex:
        futs = [ex.submit(prov.ensure_option_day, s_, d) for s_, d in todo]
        for f in as_completed(futs):
            done += 1
            if done % 10 == 0 or done == len(todo):
                say(0.08 + 0.42 * done / len(todo), f"Downloading option candles {done}/{len(todo)}")
            try:
                f.result()
            except Exception as exc:
                log.warning("option prefetch failed: %s", exc)


# ---------------------------------------------------------------- chart payloads
@lru_cache(maxsize=64)
def spot_bars(dataset: str, day: date, tf: int, key: str = strategies.DEFAULT) -> list[dict]:
    """Signal-timeframe bars for one day with the strategy's EMAs (e9 = fast, e21 = slow)."""
    prov = providers.get(dataset)
    df = db.load_candles(prov.spot_symbol, datetime.combine(day - timedelta(days=HISTORY_DAYS), time(0)),
                         datetime.combine(day + timedelta(days=1), time(0)))
    df = df[df["ts"] + pd.Timedelta(minutes=1) <= _now()]
    bars = strategies.prepare(df, None, tf, key).rename(columns={"fast": "ema9", "slow": "ema21"})
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

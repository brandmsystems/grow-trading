"""Historical position backtest: the nine strategies, holds of 3, 5, 10 and 20 trading days, real stored option premiums.

Rules (fixed before any result was looked at; nothing is tuned):
* a strategy decides on a completed daily bar (closed 15:30); the order is filled on the **next trading day at 09:20** at the stored 1-minute
  option candle's open (never at the decision bar's price);
* BUY CE after a bullish signal, BUY PE after a bearish one; ATM strike of the decision close; the nearest expiry that leaves at least
  `ceil(1.5 x hold) + 2` calendar days beyond entry (so a weekly contract serves 3-, 5- and 10-day holds and a monthly one the 20-day hold);
* exits, checked on every stored 1-minute candle after entry: premium stop-loss -35% (a gap through it fills at the candle open), target +70%
  (2R; a gap through it fills at the open), the time exit at 15:15 on the hold's last trading day, and a forced exit at 15:15 the trading day before expiry;
  if one candle touches both the stop and the target the stop is assumed first;
* 1 lot of the NSE lot size valid for that expiry, slippage and the full charge stack (`charges.round_trip`);
* **a trade whose option has no stored candle at entry or at the exit day is not simulated and is counted by reason** (`unsimulatable`), never
  filled with a made-up price. Because the stored strikes cover ATM +-10 around each expiry's own date, a large move can leave the contract
  without candles; the count is part of the report so the result is not flattered by silently dropping bad trades.
* Splits are chronological (train 2022-23, validation 2024, out-of-sample 2025 to the end). No parameter is fitted, so these are hold-out
  periods, not walk-forward re-fits; a strategy counts as robust only if it is net positive in all three with at least 20 trades each.
No result here is a promise: past performance on a few dozen trades says little.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from app.services.position import strategies as pstr
from app.services.trading import charges as costs

HOLDS = (3, 5, 10, 20)
STOP_PCT, TARGET_PCT = 0.35, 0.70
ENTRY_AT, TIME_EXIT_AT = time(9, 20), time(15, 15)
MIN_PREMIUM = 5.0
PERIODS = (("train", date(2022, 1, 1), date(2023, 12, 31)), ("validation", date(2024, 1, 1), date(2024, 12, 31)), ("out_of_sample", date(2025, 1, 1), date(2099, 1, 1)))
MIN_TRADES_ROBUST = 20


def period_of(day: date) -> str:
    for name, a, b in PERIODS:
        if a <= day <= b:
            return name
    return "before_train"


def expiry_for(entry_day: date, expiries: list[date], hold: int) -> date | None:
    need = math.ceil(1.5 * hold) + 2
    return next((e for e in sorted(expiries) if (e - entry_day).days >= need), None)


@dataclass
class Trade:
    strategy: str
    hold: int
    direction: int
    decision_day: date
    entry_day: date
    expiry: date
    strike: float
    typ: str
    qty: int
    entry: float
    exit: float
    exit_ts: datetime
    exit_reason: str
    gross: float
    slippage: float
    charges: float
    net: float
    days_held: int
    period: str


def simulate(candles: pd.DataFrame, trading_days: list[date], entry_idx: int, hold: int, expiry: date, side: str = "BUY"):
    """Walk one option's stored candles from the entry day. Returns (fill dict, None) or (None, reason it cannot be simulated).
    `trading_days` are the spot trading days (the calendar); `entry_idx` the entry day's index in it."""
    entry_day = trading_days[entry_idx]
    day_col = candles["ts"].dt.date
    on_entry = candles[(day_col == entry_day) & (candles["ts"].dt.time >= ENTRY_AT)]
    if on_entry.empty:
        return None, "no option candle at entry"
    first = on_entry.iloc[0]
    if first["ts"] - datetime.combine(entry_day, ENTRY_AT) > timedelta(minutes=30):
        return None, "no option candle near the entry time"
    entry = float(first["open"])
    if entry < MIN_PREMIUM:
        return None, "premium below the minimum"
    stop, target = entry * (1 - STOP_PCT), entry * (1 + TARGET_PCT)
    # the last trading day of the hold: the H-th trading day after entry, or the trading day before expiry if that comes first
    last_idx = min(entry_idx + hold, len(trading_days) - 1)
    exp_idx = max((i for i, d in enumerate(trading_days) if d < expiry), default=last_idx)
    forced = exp_idx < last_idx
    last_idx = min(last_idx, exp_idx)
    if last_idx <= entry_idx:
        return None, "expiry too close"
    last_day = trading_days[last_idx]
    window = candles[(candles["ts"] >= first["ts"]) & (candles["ts"].dt.date <= last_day)]
    for r in window.iloc[1:].itertuples(index=False):
        if r.low <= stop:
            px = min(stop, float(r.open))
            return {"exit": px, "ts": r.ts, "reason": "stop_loss", "days": trading_days.index(r.ts.date()) - entry_idx, "entry": entry}, None
        if r.high >= target:
            px = max(target, float(r.open))
            return {"exit": px, "ts": r.ts, "reason": "target", "days": trading_days.index(r.ts.date()) - entry_idx, "entry": entry}, None
        if r.ts.date() == last_day and r.ts.time() >= TIME_EXIT_AT:
            return {"exit": float(r.close), "ts": r.ts, "reason": "expiry_exit" if forced else "time_exit", "days": last_idx - entry_idx, "entry": entry}, None
    late = window[(window["ts"].dt.date == last_day) & (window["ts"].dt.time >= time(15, 0))]
    if late.empty:
        return None, "no option candle on the exit day"
    r = late.iloc[-1]
    return {"exit": float(r["close"]), "ts": r["ts"], "reason": "expiry_exit" if forced else "time_exit", "days": last_idx - entry_idx, "entry": entry}, None


def trade_from(fill: dict, strategy: str, hold: int, direction: int, decision_day: date, entry_day: date, expiry: date, strike: float, typ: str, qty: int,
               cfg: costs.CostConfig = costs.DEFAULT_COSTS) -> Trade:
    rt = costs.round_trip("BUY", fill["entry"], fill["exit"], qty, cfg)
    return Trade(strategy, hold, direction, decision_day, entry_day, expiry, strike, typ, qty, fill["entry"], fill["exit"], fill["ts"], fill["reason"],
                 rt["gross"], rt["slippage"], rt["charges"]["total"] if isinstance(rt["charges"], dict) else rt["charges"], rt["net"], fill["days"], period_of(entry_day))


# ---------------------------------------------------------------- statistics
def stats(items: list[Trade]) -> dict:
    net = [t.net for t in sorted(items, key=lambda t: (t.entry_day, t.strategy))]
    wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
    peak = eq = dd = 0.0
    for x in net:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    gw, gl = sum(wins), -sum(losses)
    return {"trades": len(net), "win_rate": round(100 * len(wins) / len(net), 1) if net else None, "net": round(sum(net), 2), "gross": round(sum(t.gross for t in items), 2),
            "costs": round(sum(t.slippage + t.charges for t in items), 2), "expectancy": round(sum(net) / len(net), 2) if net else None,
            "profit_factor": round(gw / gl, 2) if gl > 0 else (None if not wins else float("inf")), "max_drawdown": round(dd, 2),
            "avg_days": round(sum(t.days_held for t in items) / len(items), 1) if items else None}


def report(trades: list[Trade], skipped: list[dict]) -> dict:
    """Per strategy and hold: overall, per period, per year and month, exit reasons, and how many trades could not be simulated."""
    out = {"cells": [], "pooled_by_hold": {}, "limits": []}
    groups = defaultdict(list)
    for t in trades:
        groups[(t.strategy, t.hold)].append(t)
    sk = defaultdict(lambda: defaultdict(int))
    for s in skipped:
        sk[(s["strategy"], s["hold"])][s["reason"]] += 1
    for key in sorted(set(groups) | set(sk)):
        items = groups.get(key, [])
        per = {n: stats([t for t in items if t.period == n]) for n, _, _ in PERIODS}
        robust = all(per[n]["trades"] >= MIN_TRADES_ROBUST and per[n]["net"] > 0 for n in per)
        by_year, by_month = defaultdict(float), defaultdict(float)
        for t in items:
            by_year[str(t.entry_day.year)] += t.net
            by_month[f"{t.entry_day:%Y-%m}"] += t.net
        reasons = defaultdict(int)
        for t in items:
            reasons[t.exit_reason] += 1
        out["cells"].append({"strategy": key[0], "hold": key[1], **stats(items), "periods": per, "robust": robust,
                             "by_year": {k: round(v, 2) for k, v in sorted(by_year.items())}, "by_month": {k: round(v, 2) for k, v in sorted(by_month.items())},
                             "exit_reasons": dict(reasons), "unsimulatable": dict(sk.get(key, {})), "unsimulatable_n": sum(sk.get(key, {}).values())})
    for h in HOLDS:
        out["pooled_by_hold"][str(h)] = stats([t for t in trades if t.hold == h])
    return out


# ---------------------------------------------------------------- the run (reads the database; never writes to it)
EXPORT = "position_research.json"


def run(start: date = date(2021, 11, 11), end: date | None = None, enabled: dict | None = None, holds=HOLDS, progress=None) -> tuple[list[Trade], list[dict], dict]:
    """Simulate every strategy x hold on the stored candles. Returns (trades, unsimulatable trades with reasons, meta)."""
    from app.database import db
    from app.services.market_data import history
    from app.services.options import lot_sizes
    say = progress or (lambda *_: None)
    end = end or date.today()
    spot = db.load_candles("NSE-NIFTY", datetime.combine(start, time(0)), datetime.combine(end + timedelta(days=1), time(0)))
    fut = history.futures_1m(start, end)
    d = pstr.prepare(spot, fut)
    sig = pstr.signals(d, enabled)
    counts = spot.groupby(spot["ts"].dt.date).size()
    days = [x for x in counts.index if counts[x] >= 300]
    didx = {x: i for i, x in enumerate(days)}
    expiries = db.load_expiries("groww")
    with db.engine().connect() as c:
        from sqlalchemy import text
        cmap = {(r[0], float(r[1]), r[2]): r[3] for r in c.execute(text("SELECT expiry, strike, opt_type, symbol FROM contracts WHERE dataset='groww'")).all()}
    trades, skipped = [], []
    busy: dict = {}
    cache: dict = {}
    total = int((sig != 0).to_numpy().sum()) * len(holds)
    done = 0
    for i in range(len(d)):
        for key in sig.columns:
            direction = int(sig[key].iloc[i])
            if not direction:
                continue
            dday = d["day"].iloc[i].date()
            for h in holds:
                done += 1
                if done % 50 == 0:
                    say(done / max(1, total), f"{key} {h}d")
                rec = {"strategy": key, "hold": h, "decision_day": dday.isoformat()}
                if dday not in didx or didx[dday] + 1 >= len(days):
                    skipped.append({**rec, "reason": "no next trading day yet"}); continue
                ei = didx[dday] + 1
                entry_day = days[ei]
                if busy.get((key, h), date.min) >= entry_day:
                    continue                                                 # this strategy already holds a position for this hold length
                if ei + h >= len(days) - 1 and entry_day + timedelta(days=int(1.5 * h) + 2) > end:
                    skipped.append({**rec, "reason": "the hold extends past the stored data"}); continue
                exp = expiry_for(entry_day, expiries, h)
                if exp is None:
                    skipped.append({**rec, "reason": "no suitable expiry"}); continue
                typ = "CE" if direction > 0 else "PE"
                strike = float(round(float(d["close"].iloc[i]) / 50) * 50)
                sym = cmap.get((exp, strike, typ)) or f"NSE-NIFTY-{exp:%d%b%y}-{int(strike)}-{typ}"
                last_day = days[min(ei + h, len(days) - 1)]
                ck = (sym, entry_day, last_day)
                if ck not in cache:
                    cache[ck] = db.load_candles(sym, datetime.combine(entry_day, time(9, 0)), datetime.combine(last_day + timedelta(days=1), time(0)))
                    if len(cache) > 400:
                        cache.pop(next(iter(cache)))
                cand = cache[ck]
                if cand.empty:
                    skipped.append({**rec, "reason": "no stored candles for the contract"}); continue
                fill, why = simulate(cand, days, ei, h, exp)
                if fill is None:
                    skipped.append({**rec, "reason": why}); continue
                try:
                    lot, _ = lot_sizes.lot_size_for(exp, expiries)
                except Exception:
                    skipped.append({**rec, "reason": "no NSE lot size recorded"}); continue
                t = trade_from(fill, key, h, direction, dday, entry_day, exp, strike, typ, lot)
                trades.append(t)
                busy[(key, h)] = fill["ts"].date()
    meta = {"generated_at": datetime.now().isoformat(timespec="seconds"), "data_from": str(days[0]) if days else None, "data_to": str(days[-1]) if days else None,
            "daily_bars": int(len(d)), "signals": int((sig != 0).to_numpy().sum()), "stop_pct": STOP_PCT, "target_pct": TARGET_PCT, "holds": list(holds),
            "periods": {n: [str(a), str(b)] for n, a, b in PERIODS}}
    return trades, skipped, meta


def evidence_from(rep: dict) -> dict:
    """Per strategy: 'positive' (some hold robust and net positive out of sample), 'insufficient' (fewer than 20 out-of-sample trades in total) or 'negative'."""
    by = defaultdict(list)
    for c in rep["cells"]:
        by[c["strategy"]].append(c)
    out = {}
    for k, cells in by.items():
        oos_n = sum(c["periods"]["out_of_sample"]["trades"] for c in cells)
        oos_net = sum(c["periods"]["out_of_sample"]["net"] for c in cells)
        best = max(cells, key=lambda c: c["periods"]["out_of_sample"]["net"])
        status = "positive" if any(c["robust"] for c in cells) else "insufficient" if oos_n < MIN_TRADES_ROBUST else "negative"
        out[k] = {"status": status, "trades": sum(c["trades"] for c in cells), "oos_trades": oos_n, "oos_net": round(oos_net, 2),
                  "note": f"{sum(c['trades'] for c in cells)} simulated trades over 4 holds; out-of-sample net ₹{oos_net:,.0f} over {oos_n} trades; "
                          f"best out-of-sample hold {best['hold']} days ₹{best['periods']['out_of_sample']['net']:,.0f}"}
    return out

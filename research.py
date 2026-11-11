"""Strategy comparison over the whole stored history, and walk-forward selection.

Each strategy x timeframe is run once over all stored data with the real option
pricing of backtest.run; only a compact summary is kept (per mode: metrics, yearly,
monthly and daily P&L). Option candles are downloaded on first use and cached.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import date

from sqlalchemy import text

import backtest
import db
import metrics
import strategies
import strategy as st

log = logging.getLogger("research")
BASELINE = ("ema_9_21", 15)


def grid() -> list[tuple[str, int]]:
    """Coarse timeframes first: they are quickest and most useful while 1m is still running."""
    return [(k, tf) for tf in sorted(backtest.TIMEFRAMES, reverse=True) for k in strategies.STRATEGIES]


def settings(entry_start: str = "09:30", cutoff: str = "14:30", **extra) -> dict:
    p = backtest.normalise({"entry_start": entry_start, "cutoff": cutoff, **extra})
    return {k: v for k, v in p.items() if k not in ("start_date", "end_date", "strategy", "timeframe")}


def settings_hash(s: dict) -> str:
    return hashlib.sha256(json.dumps({**s, "_v": backtest.ENGINE_VERSION}, sort_keys=True).encode()).hexdigest()[:16]


def full_range() -> tuple[date, date]:
    days = db.candle_days("NSE-NIFTY")
    if not days:
        raise LookupError("No NIFTY data stored. Download it on the Data page first.")
    return days[0], days[-1]


def compact(res: dict) -> dict:
    out = {"signals": res["signals"], "trade_days": res["trade_days"], "partial_asof": res.get("partial_asof"), "modes": {}}
    for mode, trades in res["trades"].items():
        m = metrics.compute(trades, res["params"]["capital"])
        m.pop("equity_curve")
        daily, yearly, monthly = defaultdict(float), defaultdict(lambda: [0.0, 0, 0]), defaultdict(float)
        for t in trades:
            daily[t["day"]] += t["net"]
            y = yearly[t["day"][:4]]
            y[0] += t["net"]; y[1] += 1; y[2] += t["net"] > 0
            monthly[t["day"][:7]] += t["net"]
        m["daily"] = [[d, round(v, 2)] for d, v in sorted(daily.items())]
        m["yearly"] = {k: {"net": round(v[0], 2), "trades": v[1], "win_rate": round(v[2] / v[1] * 100, 1) if v[1] else 0}
                       for k, v in sorted(yearly.items())}
        m["monthly"] = {k: round(v, 2) for k, v in sorted(monthly.items())}
        m["skipped"] = sum(1 for s in res["skipped"] if s["mode"] == mode)
        out["modes"][mode] = m
    return out


def run_grid(entry_start: str = "09:30", cutoff: str = "14:30", combos=None, force: bool = False, progress=None) -> dict:
    say = progress or (lambda *_: None)
    s = settings(entry_start, cutoff)
    h = settings_hash(s)
    first, last = full_range()
    todo = combos or grid()
    done = 0
    for i, (key, tf) in enumerate(todo):
        label = f"{strategies.STRATEGIES[key].label} · {tf}m"
        if not force:
            row = _row(key, tf, h)
            if row and row["end_date"] >= last and not row["summary"].get("partial_asof"):
                continue
        p = {**s, "strategy": key, "timeframe": tf, "start_date": first.isoformat(), "end_date": last.isoformat()}
        base = i / len(todo)
        res = backtest.run(p, use_cache=False, save=False,
                           progress=lambda f, m: say(base + f / len(todo), f"{label} ({i + 1}/{len(todo)}): {m}"))
        with db.engine().begin() as c:
            c.execute(text(
                "INSERT INTO strategy_results (strategy, timeframe, settings_hash, settings, start_date, end_date, summary) "
                "VALUES (:k,:tf,:h,CAST(:s AS JSONB),:a,:b,CAST(:r AS JSONB)) ON CONFLICT (strategy, timeframe, settings_hash) "
                "DO UPDATE SET settings=EXCLUDED.settings, start_date=EXCLUDED.start_date, end_date=EXCLUDED.end_date, "
                "summary=EXCLUDED.summary, created_at=now()"),
                {"k": key, "tf": tf, "h": h, "s": json.dumps(s), "a": first, "b": last, "r": json.dumps(compact(res), default=str)})
        done += 1
        log.info("research: %s done", label)
    say(1.0, "Comparison complete")
    return {"ran": done, "settings_hash": h}


def _row(key: str, tf: int, h: str) -> dict | None:
    with db.engine().connect() as c:
        r = c.execute(text("SELECT strategy, timeframe, start_date, end_date, summary, created_at FROM strategy_results "
                           "WHERE strategy=:k AND timeframe=:tf AND settings_hash=:h"), {"k": key, "tf": tf, "h": h}).mappings().first()
    return dict(r) if r else None


def results(entry_start: str = "09:30", cutoff: str = "14:30") -> dict:
    s = settings(entry_start, cutoff)
    h = settings_hash(s)
    with db.engine().connect() as c:
        rows = [dict(r) for r in c.execute(text(
            "SELECT strategy, timeframe, start_date, end_date, summary, created_at FROM strategy_results WHERE settings_hash=:h"),
            {"h": h}).mappings()]
    by = {(r["strategy"], r["timeframe"]): r for r in rows}
    cells = []
    for key, tf in grid():
        r = by.get((key, tf))
        cells.append({"strategy": key, "label": strategies.STRATEGIES[key].label, "timeframe": tf,
                      "start_date": r["start_date"].isoformat() if r else None,
                      "end_date": r["end_date"].isoformat() if r else None,
                      "updated": r["created_at"].isoformat() if r else None,
                      "summary": r["summary"] if r else None})
    return {"settings": s, "cells": cells,
            "walk_forward": {m: walk_forward(cells, m) for m in st.MODES}}


def walk_forward(cells: list[dict], mode: str) -> dict:
    """Each year, pick the configuration with the best net P&L on all EARLIER years,
    then record what it earned in that year. Nothing from the test year is used to choose."""
    yearly = {}
    for c in cells:
        if c["summary"]:
            daily = c["summary"]["modes"][mode]["daily"]
            by_year: dict[str, float] = defaultdict(float)
            for d, v in daily:
                by_year[d[:4]] += v
            yearly[(c["strategy"], c["timeframe"])] = by_year
    if not yearly:
        return {"rows": [], "total_oos": 0, "baseline_total": 0}
    years = sorted({y for v in yearly.values() for y in v})
    rows, total, base_total = [], 0.0, 0.0
    for i, y in enumerate(years):
        prior = years[:i]
        if not prior:
            continue
        insample = {k: sum(v.get(p, 0) for p in prior) for k, v in yearly.items()}
        pick = max(insample, key=insample.get)
        best = max(yearly, key=lambda k: yearly[k].get(y, 0))
        oos = yearly[pick].get(y, 0)
        base = yearly.get(BASELINE, {}).get(y, 0)
        total += oos
        base_total += base
        rows.append({"year": y, "trained_on": f"{prior[0]}–{prior[-1]}",
                     "pick": {"strategy": pick[0], "label": strategies.STRATEGIES[pick[0]].label, "timeframe": pick[1]},
                     "insample_net": round(insample[pick], 2), "oos_net": round(oos, 2), "baseline_net": round(base, 2),
                     "hindsight_best": {"label": strategies.STRATEGIES[best[0]].label, "timeframe": best[1],
                                        "net": round(yearly[best].get(y, 0), 2)}})
    return {"rows": rows, "total_oos": round(total, 2), "baseline_total": round(base_total, 2),
            "configs": len(yearly)}

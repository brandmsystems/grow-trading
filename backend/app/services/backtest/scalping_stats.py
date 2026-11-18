"""Statistics for the scalping analyzer: per-configuration metrics, grouping by year/month/regime, the
consistency verdict and the walk-forward selection. Pure functions over trade dicts (no database, no
clock), so they are unit tested directly. `scalping.py` re-exports them.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from app.services.backtest import metrics
from app.services.trading import charges as costs

CAPITAL = 100_000.0
MIN_TRADES = 200             # fewer trades than this is not enough evidence


_GROUP_KEY = {"year": lambda t: t["day"][:4], "month": lambda t: t["day"][:7], "regime": lambda t: t["regime"]}


def _group(trades: list[dict], field: str) -> dict:
    g = defaultdict(lambda: [0.0, 0, 0, 0.0])
    for t in trades:
        x = g[_GROUP_KEY[field](t)]
        x[0] += t["net"]; x[1] += 1; x[2] += t["net"] > 0; x[3] += t["gross"]
    return {k: {"net": round(v[0], 2), "gross": round(v[3], 2), "trades": v[1],
                "win_rate": round(v[2] / v[1] * 100, 1) if v[1] else 0.0} for k, v in sorted(g.items())}


def stats(trades: list[dict], capital: float = CAPITAL) -> dict:
    m = metrics.compute(trades, capital)
    m.pop("equity_curve")
    n = len(trades)
    m.update({
        "brokerage": round(sum(t["brokerage"] for t in trades), 2),
        "taxes": round(sum(t["taxes"] for t in trades), 2),
        "slippage": round(sum(t["slippage"] for t in trades), 2),
        "avg_hold_min": round(sum(t["hold_min"] for t in trades) / n, 2) if n else None,
        "risk_reward": m["payoff_ratio"],
        "exits": dict(sorted(Counter(t["reason"] for t in trades).items())),
    })
    return m


def _scaled(t: dict, lots: int, cfg: costs.CostConfig) -> dict:
    qty = t["lot_size"] * lots
    pnl = costs.round_trip("BUY", t["entry"], t["exit"], qty, cfg)
    ch = pnl["charges"]
    return {**t, "qty": qty, "lots": lots, "gross": pnl["gross"], "slippage": pnl["slippage"],
            "brokerage": ch["brokerage"], "taxes": round(ch["total"] - ch["brokerage"], 2),
            "charges": ch["total"], "friction": pnl["friction"], "net": pnl["net"]}


def evaluate(m: dict, yearly: dict, oos_net: float | None) -> dict:
    """Is a configuration consistently profitable after all costs? Every condition must hold."""
    years = [y for y, v in yearly.items() if v["trades"] >= 20]
    pos = [y for y in years if yearly[y]["net"] > 0]
    checks = {
        "net_positive": m["net_pnl"] > 0,
        "enough_trades": m["trades"] >= MIN_TRADES,
        "profit_factor_1_1": (m["profit_factor"] or 0) >= 1.1,
        "most_years_positive": bool(years) and len(pos) >= math.ceil(0.75 * len(years)),
        "out_of_sample_positive": oos_net is not None and oos_net > 0,   # held-out final 40% of the days
    }
    return {"consistent": all(checks.values()), "checks": checks, "years_positive": f"{len(pos)}/{len(years)}"}


def _score(c: dict) -> float:
    return c["net_pnl"] / max(c["max_drawdown"], 1000.0)


def _daily_equity(ts: list[dict]) -> list[list]:
    daily = defaultdict(float)
    for t in ts:
        daily[t["day"]] += t["net"]
    eq, out = 0.0, []
    for d in sorted(daily):
        eq += daily[d]
        out.append([d, round(eq, 2)])
    return out


def walk_forward(yearly_net: dict[str, dict[str, float]], cfgs: dict[str, dict]) -> dict:
    """Each year, pick the configuration with the best score on all EARLIER years (earlier net divided
    by the worst earlier year's loss, with at least MIN_TRADES earlier trades and positive earlier net).
    No pick means no trading that year. The test year's own results are never used to choose."""
    years = sorted({y for v in yearly_net.values() for y in v})
    rows, total = [], 0.0
    for i, y in enumerate(years):
        prior = years[:i]
        if not prior:
            continue
        best, best_s = None, None
        for k, v in yearly_net.items():
            n_prior = sum(cfgs[k]["yearly"].get(p, {}).get("trades", 0) for p in prior)
            net_prior = sum(v.get(p, 0.0) for p in prior)
            if n_prior < MIN_TRADES or net_prior <= 0:
                continue
            worst = min([v.get(p, 0.0) for p in prior] + [0.0])
            s = net_prior / max(-worst, 1000.0)
            if best_s is None or s > best_s:
                best, best_s = k, s
        oos = yearly_net[best].get(y, 0.0) if best else 0.0
        total += oos
        c = cfgs.get(best) if best else None
        rows.append({"year": y, "trained_on": f"{prior[0]}–{prior[-1]}",
                     "pick": best, "pick_label": f"{c['strategy_label']} · {c['contract_label']} · {c['exit_label']}" if c else None,
                     "oos_net": round(oos, 2), "oos_trades": c["yearly"].get(y, {}).get("trades", 0) if c else 0})
    return {"rows": rows, "total_oos": round(total, 2)}

"""Position sizing for option buys: whole lots limited by the risk budget and by the
cash/margin available, with the full charge stack included."""
from __future__ import annotations

from app.services.trading import charges as costs


def size_position(entry: float, stop: float, target: float, lot_size: int, capital: float,
                  risk_pct: float, available: float | None, cfg: costs.CostConfig = costs.DEFAULT_COSTS) -> dict:
    """Whole lots limited by the risk budget and by the cash/margin available for option buying."""
    lot_size = int(lot_size)
    risk_budget = capital * risk_pct / 100
    lot_risk = (entry - stop) * lot_size + costs.charges(entry, stop, lot_size, cfg)["total"]
    lot_cost = entry * lot_size + costs.charges(entry, entry, lot_size, cfg)["total"]
    investable = capital if available is None else min(capital, available)
    by_risk = int(risk_budget // lot_risk) if lot_risk > 0 else 0
    by_cash = int(investable // lot_cost) if lot_cost > 0 else 0
    lots = max(0, min(by_risk, by_cash))
    limit = "risk" if by_risk <= by_cash else ("margin" if available is not None and available < capital else "capital")
    qty = lots * lot_size
    out = {"lots": lots, "lot_size": lot_size, "qty": qty, "limited_by": limit,
           "risk_budget": round(risk_budget, 2), "risk_per_lot": round(lot_risk, 2), "cost_per_lot": round(lot_cost, 2),
           "lots_by_risk": by_risk, "lots_by_cash": by_cash, "capital": round(capital, 2),
           "available": None if available is None else round(available, 2)}
    if not lots:
        out["note"] = (f"One lot costs ₹{lot_cost:,.0f} but only ₹{investable:,.0f} is available."
                       if by_cash == 0 else
                       f"One lot risks ₹{lot_risk:,.0f}, more than the ₹{risk_budget:,.0f} risk budget "
                       f"({risk_pct:g}% of ₹{capital:,.0f}).")
        return out
    ch_t = costs.charges(entry, target, qty, cfg)
    ch_s = costs.charges(entry, stop, qty, cfg)
    out.update({
        "investment": round(entry * qty, 2),
        "charges_target": ch_t["total"], "charges_stop": ch_s["total"], "charges_detail": ch_t,
        "max_risk": round((entry - stop) * qty + ch_s["total"], 2),
        "target_profit": round((target - entry) * qty - ch_t["total"], 2),
        "stop_loss": round(-((entry - stop) * qty + ch_s["total"]), 2),
    })
    return out

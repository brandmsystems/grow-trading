"""Position sizing for options: whole lots limited by the risk budget, the capital or margin
available, and a maximum number of lots, with the full charge stack included.

risk_size() is the one implementation. The Live dashboard calls it through size_position()
(margin-limited, charges only); paper trading calls it with the slippage allowance as well.
"""
from __future__ import annotations

import math

from app.services.trading import charges as costs

PRESETS = {"conservative": 0.5, "low": 1.0, "moderate": 1.5, "high": 2.0}


def _loss_at(side: str, entry: float, exit_: float, qty: int, cfg, include_slippage: bool) -> dict:
    """Loss if the position closes at `exit_`: price move, slippage and charges, as positive ₹."""
    if include_slippage:
        rt = costs.round_trip(side, entry, exit_, qty, cfg)
        return {"loss": round(-rt["net"], 2), "slippage": rt["slippage"], "charges": rt["charges"]["total"],
                "charges_detail": rt["charges"]}
    buy, sell = (entry, exit_) if side == "BUY" else (exit_, entry)
    ch = costs.charges(buy, sell, qty, cfg)
    move = (entry - exit_) * qty if side == "BUY" else (exit_ - entry) * qty
    return {"loss": round(move + ch["total"], 2), "slippage": 0.0, "charges": ch["total"], "charges_detail": ch}


def _entry_charges(price: float, qty: int, cfg) -> float:
    """Charges on the buy order alone: brokerage, exchange, SEBI, stamp duty and GST."""
    val = price * qty
    exchange, sebi = val * cfg.exchange_pct, val * cfg.sebi_per_crore / 1e7
    return round(cfg.brokerage_per_order + exchange + sebi + val * cfg.stamp_buy_pct
                 + (cfg.brokerage_per_order + exchange + sebi) * cfg.gst_pct, 2)


def risk_size(side: str, entry: float | None, stop: float | None, lot_size: int | None, capital: float,
              risk_pct: float, available: float | None = None, max_lots: int | None = None,
              min_balance: float = 0.0, target: float | None = None,
              cfg: costs.CostConfig = costs.DEFAULT_COSTS, include_slippage: bool = True) -> dict:
    """Risk amount = capital x risk % / 100; risk per lot = loss from entry to stop for one lot
    (price move + charges [+ slippage]); lots = floor(risk amount / risk per lot), capped by the
    cash available (buys) and max_lots. decision is "TRADE" or "NO TRADE" with the reason."""
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError("side must be BUY or SELL")
    if not capital or capital <= 0:
        raise ValueError("capital must be positive")
    if not 0 < risk_pct <= 100:
        raise ValueError("risk % must be above 0 and at most 100")
    out = {"side": side, "capital": round(capital, 2), "risk_pct": risk_pct,
           "risk_amount": round(capital * risk_pct / 100, 2), "available": None if available is None else round(available, 2),
           "min_balance": round(min_balance, 2), "max_lots": max_lots, "entry": entry, "stop": stop, "target": target,
           "lot_size": lot_size, "include_slippage": include_slippage, "lots": 0, "qty": 0}
    if not entry or entry <= 0:
        return {**out, "decision": "NO TRADE", "reason": "Option premium unavailable: no position size can be calculated."}
    if stop is None or stop <= 0:
        return {**out, "decision": "NO TRADE", "reason": "Stop-loss unavailable: no position size can be calculated."}
    if not lot_size or int(lot_size) <= 0:
        return {**out, "decision": "NO TRADE", "reason": "Lot size unavailable: no position size can be calculated."}
    lot_size = int(lot_size)
    if (side == "BUY" and stop >= entry) or (side == "SELL" and stop <= entry):
        return {**out, "decision": "NO TRADE",
                "reason": f"The stop-loss must be {'below' if side == 'BUY' else 'above'} the entry premium."}

    per_lot = _loss_at(side, entry, stop, lot_size, cfg, include_slippage)
    risk_per_lot = per_lot["loss"]
    fill = costs.buy_fill(entry, cfg) if (include_slippage and side == "BUY") else entry
    cost_per_lot = round(fill * lot_size + costs.charges(fill, fill, lot_size, cfg)["total"], 2) if side == "BUY" else None
    base = capital if available is None else min(capital, available)
    investable = base - min_balance
    by_risk = int(out["risk_amount"] // risk_per_lot) if risk_per_lot > 0 else 0
    by_cash = (max(0, math.floor(investable / cost_per_lot)) if cost_per_lot else 0) if side == "BUY" else None
    caps = {"risk": by_risk}
    if by_cash is not None:
        caps["margin" if available is not None and available < capital else "capital"] = by_cash
    if max_lots:
        caps["max_lots"] = int(max_lots)
    lots = max(0, min(caps.values()))
    limited_by = min(caps, key=lambda k: (caps[k], ["risk", "capital", "margin", "max_lots"].index(k)))
    out.update({"stop_distance": round(abs(entry - stop), 2), "risk_per_lot": risk_per_lot,
                "slippage_per_lot": per_lot["slippage"], "charges_per_lot": per_lot["charges"],
                "cost_per_lot": cost_per_lot, "lots_by_risk": by_risk, "lots_by_cash": by_cash,
                "investable": round(investable, 2), "lots": lots, "qty": lots * lot_size, "limited_by": limited_by,
                "risk_reward": round(abs(target - entry) / abs(entry - stop), 2) if target else None})
    if side == "SELL":
        out["margin_note"] = "Margin for option selling isn't modelled; only the risk budget and maximum lots limit the size."
    if not lots:
        if by_risk == 0:
            why = (f"One lot risks ₹{risk_per_lot:,.0f} including charges{' and slippage' if include_slippage else ''}, "
                   f"more than the ₹{out['risk_amount']:,.0f} risk budget ({risk_pct:g}% of ₹{capital:,.0f}).")
        else:
            why = (f"One lot needs ₹{cost_per_lot:,.0f} but only ₹{max(investable, 0):,.0f} is available"
                   f"{f' after keeping ₹{min_balance:,.0f}' if min_balance else ''}.")
        return {**out, "decision": "NO TRADE", "reason": why}
    qty = lots * lot_size
    at_stop = _loss_at(side, entry, stop, qty, cfg, include_slippage)
    out.update({"decision": "TRADE", "reason": None,
                "investment": round((fill if side == "BUY" else entry) * qty, 2),
                "charges": at_stop["charges"], "charges_detail": at_stop["charges_detail"],
                "slippage": at_stop["slippage"], "max_loss": at_stop["loss"],
                "entry_charges": _entry_charges(fill, qty, cfg) if side == "BUY" else None,
                "balance_after": round(base - fill * qty - _entry_charges(fill, qty, cfg), 2) if side == "BUY" else None})
    if target:
        at_target = _loss_at(side, entry, target, qty, cfg, include_slippage)
        out.update({"target_profit": round(-at_target["loss"], 2), "charges_target": at_target["charges"],
                    "charges_target_detail": at_target["charges_detail"]})
    return out


def size_position(entry: float, stop: float, target: float, lot_size: int, capital: float,
                  risk_pct: float, available: float | None, cfg: costs.CostConfig = costs.DEFAULT_COSTS) -> dict:
    """Live dashboard: whole lots limited by the risk budget and the cash/margin available for option buying."""
    r = risk_size("BUY", entry, stop, lot_size, capital, risk_pct, available, target=target, cfg=cfg,
                  include_slippage=False)
    out = {"lots": r["lots"], "lot_size": int(lot_size), "qty": r["qty"], "limited_by": r["limited_by"],
           "risk_budget": r["risk_amount"], "risk_per_lot": r["risk_per_lot"], "cost_per_lot": r["cost_per_lot"],
           "lots_by_risk": r["lots_by_risk"], "lots_by_cash": r["lots_by_cash"], "capital": round(capital, 2),
           "available": None if available is None else round(available, 2)}
    if not r["lots"]:
        out["note"] = r["reason"]
        return out
    out.update({
        "investment": r["investment"],
        "charges_target": r["charges_target"], "charges_stop": r["charges"], "charges_detail": r["charges_target_detail"],
        "max_risk": r["max_loss"], "target_profit": r["target_profit"], "stop_loss": -r["max_loss"],
    })
    return out

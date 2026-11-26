"""Entry, stop-loss, targets, holding period, risk and warnings for one position-trading idea (pure).

The premium stop (-35%) and target (+70%, 2R) are the ones the backtest uses (`backtest.STOP_PCT`, `backtest.TARGET_PCT`). Target 2, the trailing stop
and the underlying invalidation level are *management aids* that the backtest does not simulate; the plan says so. Sizing is the existing
`options.sizing.risk_size` (risk % of capital, lots by the cost-inclusive loss at the stop)."""
from __future__ import annotations

import math
from datetime import date, timedelta

from app.services.options import sizing
from app.services.position import backtest as bt
from app.services.trading import charges as costs

TRAIL_PCT = 25.0            # after Target 1: stop moves to the entry, then trails this % below the best premium
DEFAULT_HOLD = 5


def add_trading_days(day: date, n: int, holidays: set[date] | None = None) -> date:
    """`n` weekdays after `day` (exchange holidays unknown unless given: the date is an estimate)."""
    d, k = day, 0
    while k < n:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in (holidays or set()):
            k += 1
    return d


def reward_risk(premium: float, stop: float, target: float, qty: int, cfg) -> dict:
    win = costs.round_trip("BUY", premium, target, qty, cfg)["net"]
    loss = costs.round_trip("BUY", premium, stop, qty, cfg)["net"]
    rr = win / abs(loss) if loss < 0 else None
    return {"net_at_target": round(win, 2), "net_at_stop": round(loss, 2), "ratio": None if rr is None else round(rr, 2)}


def build(*, direction: int, premium: float, est: dict | None, atr: float | None, close: float, swing: float | None, lot_size: int, capital: float, risk_pct: float,
          hold_days: int, expiry: date, decision_day: date, max_lots: int = 20, cfg=costs.DEFAULT_COSTS) -> dict:
    """The full plan. `est` is the Black-Scholes estimate dict from `bsm.estimate` (or None): delta / theta are used only when available."""
    delta = abs(est["delta"]) if est and est.get("available") else None
    warnings = []
    if delta is not None and atr:
        half = delta * 0.5 * atr
        lo, hi = max(0.05, premium - half), premium + half
        rng_note = f"the premium may open about ±{half:.1f} away (delta {delta:.2f} x half an ATR); estimate"
    else:
        lo, hi, rng_note = premium * 0.97, premium * 1.03, "delta unavailable: a plain ±3% band around the last premium"
    entry = premium
    stop = costs._round_tick_down(entry * (1 - bt.STOP_PCT))
    t1 = costs._round_tick_up(entry * (1 + bt.TARGET_PCT))
    t2 = costs._round_tick_up(entry * (1 + 2 * bt.TARGET_PCT))
    inval = None
    if atr and close:
        raw = (close - 2 * atr) if direction > 0 else (close + 2 * atr)
        if swing is not None and 0.75 * atr <= (close - swing) * direction <= 3 * atr:
            raw = swing
        inval = round(raw, 2)
    size = sizing.risk_size("BUY", entry, stop, lot_size, capital, risk_pct, available=capital, max_lots=max_lots, target=t1, cfg=cfg, include_slippage=True) if capital else None
    qty = size["qty"] if size and size.get("decision") == "TRADE" else lot_size
    rr = reward_risk(entry, stop, t1, qty, cfg)
    exit_day = add_trading_days(decision_day, 1 + hold_days)
    forced = None
    d = expiry - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    forced = d
    if forced < exit_day:
        warnings.append(f"expiry {expiry:%d %b}: the position must be closed by {forced:%d %b} (before the planned {exit_day:%d %b} time exit)")
        exit_day = forced
    if est and est.get("available") and est.get("theta_day"):
        warnings.append(f"theta: about ₹{abs(est['theta_day']) * qty:,.0f} a day for {qty} units ({abs(est['theta_pct_day'])}% of the premium); a weekend costs three days of it (estimate)")
    else:
        warnings.append("theta could not be estimated for this premium")
    if delta is not None and atr:
        warnings.append(f"overnight gap risk: a one-ATR ({atr:.0f} points) gap moves the premium by about ₹{delta * atr:.1f} ({100 * delta * atr / entry:.0f}% of it); the stop is not guaranteed through a gap (estimate)")
    warnings.append("scheduled events (RBI, budget, results, expiry) are not part of the score: check the calendar before entering")
    return {"entry": {"premium": round(entry, 2), "low": round(lo, 2), "high": round(hi, 2), "note": rng_note},
            "stop_premium": stop, "target1": t1, "target2": t2, "trailing": f"after Target 1 the stop moves to the entry premium, then trails {TRAIL_PCT:g}% below the best premium (not backtested)",
            "invalidation": inval, "invalidation_note": "if the NIFTY daily bar closes beyond this level the idea is invalid: review or close the position (not backtested)",
            "hold_days": hold_days, "planned_exit": exit_day.isoformat(), "expiry": expiry.isoformat(), "time_exit": f"close of day {hold_days} after entry (15:15) or the trading day before expiry",
            "risk_reward": rr, "sizing": size, "lots": size["lots"] if size and size.get("decision") == "TRADE" else 0, "qty": qty if size and size.get("decision") == "TRADE" else 0,
            "max_loss": size.get("max_loss") if size else None, "capital_required": size.get("investment") if size else None, "warnings": warnings,
            "backtested_rules": f"premium stop -{100 * bt.STOP_PCT:g}%, target +{100 * bt.TARGET_PCT:g}%, time exit, forced exit before expiry"}

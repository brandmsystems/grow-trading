"""Virtual paper account: running balance, available capital and the daily risk monitor.

Balance = starting capital + net P&L of the closed paper trades booked to the account.
Nothing here touches Groww orders; it is used only by paper trading.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import text

from app.database import db

DEFAULT_CAPITAL = 100000.0


def active(eng=None, create: bool = True) -> dict | None:
    eng = eng or db.engine()
    with eng.begin() as c:
        r = c.execute(text("SELECT id, capital, started_at FROM paper_accounts WHERE closed_at IS NULL "
                           "ORDER BY id DESC LIMIT 1")).mappings().first()
        if r is None and create:
            r = c.execute(text("INSERT INTO paper_accounts (capital, note) VALUES (:c, 'created automatically') "
                               "RETURNING id, capital, started_at"), {"c": DEFAULT_CAPITAL}).mappings().first()
    return dict(r) if r else None


def reset(capital: float, eng=None) -> dict:
    """Close the active account and open a new one. Old trades keep their account id."""
    if not capital or capital <= 0:
        raise ValueError("Virtual capital must be positive.")
    eng = eng or db.engine()
    with eng.begin() as c:
        c.execute(text("UPDATE paper_accounts SET closed_at=now() WHERE closed_at IS NULL"))
        r = c.execute(text("INSERT INTO paper_accounts (capital, note) VALUES (:c, 'reset by user') "
                           "RETURNING id, capital, started_at"), {"c": float(capital)}).mappings().first()
    return dict(r)


def _closed(acct_id: int, eng) -> list[dict]:
    with eng.connect() as c:
        return [dict(r) for r in c.execute(text(
            "SELECT id, day, exit_ts, net FROM live_trades WHERE trade_mode='paper' AND paper_account_id=:a "
            "AND status='CLOSED' AND net IS NOT NULL ORDER BY exit_ts, id"), {"a": acct_id}).mappings()]


def state(day: date, cfg=None, position: dict | None = None, mtm: float | None = None, eng=None, positions: list | None = None) -> dict:
    """Balance, available capital and today's risk figures.

    position: the open paper position (entry_price, qty, stop_premium, side) if any; positions: all open ones; mtm: their open P&L.
    cfg: the engine config (risk_pct, daily_risk_pct, max_daily_loss) or None for defaults.
    """
    eng = eng or db.engine()
    acct = active(eng)
    trades = _closed(acct["id"], eng)
    realised = sum(t["net"] for t in trades)
    before_today = sum(t["net"] for t in trades if t["day"] < day)
    today = [t for t in trades if t["day"] == day]
    realised_today = sum(t["net"] for t in today)
    balance = acct["capital"] + realised
    start_day = acct["capital"] + before_today
    # equity curve and drawdown over the account's closed trades
    eq, peak, max_dd = acct["capital"], acct["capital"], 0.0
    for t in trades:
        eq += t["net"]
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    streak = 0
    for t in reversed(trades):
        if t["net"] < 0:
            streak += 1
        else:
            break
    invested = open_risk = 0.0
    for position in (positions or ([position] if position else [])):     # one position, or every open position of a multi-position engine
        invested += position["entry_price"] * position["qty"] if position.get("side", "BUY") == "BUY" else 0.0
        if position.get("stop_premium") is not None:
            r = (position.get("risk") or {})
            open_risk += float(r.get("max_loss") or 0.0)
    risk_pct = getattr(cfg, "risk_pct", 1.0)
    daily_pct = getattr(cfg, "daily_risk_pct", 0.0)
    loss_cap = getattr(cfg, "max_daily_loss", 0.0)
    limits = [v for v in ((start_day * daily_pct / 100) if daily_pct else 0, loss_cap or 0) if v > 0]
    daily_limit = round(min(limits), 2) if limits else None
    pnl_today = realised_today + (mtm or 0.0)
    used = max(0.0, -pnl_today) + open_risk
    return {
        "account_id": acct["id"], "starting_capital": round(acct["capital"], 2),
        "started_at": acct["started_at"].isoformat() if isinstance(acct["started_at"], datetime) else acct["started_at"],
        "balance": round(balance, 2), "available": round(balance - invested, 2), "invested": round(invested, 2),
        "realised_total": round(realised, 2), "trades_total": len(trades),
        "day": day.isoformat(), "day_start_capital": round(start_day, 2),
        "realised_today": round(realised_today, 2), "mtm": None if mtm is None else round(mtm, 2),
        "pnl_today": round(pnl_today, 2), "daily_limit": daily_limit,
        "remaining_risk": None if daily_limit is None else round(max(0.0, daily_limit + min(0.0, pnl_today) - open_risk), 2),
        "risk_used_pct": None if not daily_limit else round(100 * used / daily_limit, 1),
        "open_risk": round(open_risk, 2), "consecutive_losses": streak, "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(100 * max_dd / acct["capital"], 2) if acct["capital"] else None,
        "risk_pct": risk_pct, "risk_amount": round((balance - invested) * risk_pct / 100, 2),
        "limit_reached": bool(daily_limit and pnl_today <= -daily_limit),
    }

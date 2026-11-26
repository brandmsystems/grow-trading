"""The separate virtual position-trading account and its multi-day paper positions. PAPER ONLY: no function here can place an order; nothing
imports `LiveBroker` or the live engine. Everything is read back from the database on each call, so a restart loses nothing (restart recovery).

* one account (`position_accounts`), its positions (`position_trades`), a unique `signal_key` per account so a signal is never entered twice;
* entries need a BUY / STRONG BUY opportunity and pass: free capital, maximum open positions, maximum portfolio risk (sum of the open positions'
  maximum losses as % of capital), the per-trade risk sizing (`options.sizing.risk_size`, costs included) and the duplicate rule;
* exits (`manage`): premium stop-loss (after Target 1 the stop moves to the entry and then trails), Target 2, the planned time exit (15:15), the forced
  exit the trading day before expiry; P&L = `charges.round_trip` (slippage, brokerage, taxes). A price older than `STALE_SEC` never triggers anything;
* nothing is forced: no opportunity, no position.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

from app.database import db
from app.services.options import sizing
from app.services.position import plan as pplan
from app.services.trading import charges as costs

DEFAULT_CAPITAL = 500_000.0
STALE_SEC = 900
TIME_EXIT_AT = time(15, 15)
_ENTRY_OK = ("BUY CE", "BUY PE", "STRONG BUY CE", "STRONG BUY PE")


def _eng(eng=None):
    return eng or db.engine()


def active(eng=None, create: bool = True) -> dict | None:
    eng = _eng(eng)
    with eng.begin() as c:
        r = c.execute(text("SELECT id, capital, started_at FROM position_accounts WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1")).mappings().first()
        if r is None and create:
            r = c.execute(text("INSERT INTO position_accounts (capital, note) VALUES (:c, 'created automatically') RETURNING id, capital, started_at"), {"c": DEFAULT_CAPITAL}).mappings().first()
    return dict(r) if r else None


def reset(capital: float, eng=None) -> dict:
    """Close the active account and open a new one (the old trades keep their account id; nothing is deleted)."""
    if not capital or capital <= 0:
        raise ValueError("Virtual capital must be positive.")
    eng = _eng(eng)
    with eng.begin() as c:
        c.execute(text("UPDATE position_accounts SET closed_at=now() WHERE closed_at IS NULL"))
        r = c.execute(text("INSERT INTO position_accounts (capital, note) VALUES (:c, 'reset by user') RETURNING id, capital, started_at"), {"c": float(capital)}).mappings().first()
    return dict(r)


def _rows(acct_id: int, eng) -> list[dict]:
    with eng.connect() as c:
        return [dict(r) for r in c.execute(text("SELECT * FROM position_trades WHERE account_id=:a ORDER BY id"), {"a": acct_id}).mappings()]


def _pnl(p: dict, price: float, cfg=costs.DEFAULT_COSTS) -> dict:
    return costs.round_trip("BUY", float(p["entry_price"]), float(price), int(p["qty"]), cfg)


def state(eng=None, risk_cfg: dict | None = None) -> dict:
    """Balance, free capital, exposure, open risk, realised and open P&L, drawdown."""
    eng = _eng(eng)
    acct = active(eng)
    rows = _rows(acct["id"], eng)
    closed = [r for r in rows if r["status"] == "CLOSED" and r["net"] is not None]
    open_ = [r for r in rows if r["status"] == "OPEN"]
    realised = sum(r["net"] for r in closed)
    invested = sum(r["entry_price"] * r["qty"] for r in open_)
    mtm = sum(_pnl(r, r["last_price"])["net"] for r in open_ if r["last_price"])
    open_risk = sum(float((r["risk"] or {}).get("max_loss") or 0) for r in open_)
    eq = peak = dd = acct["capital"]
    dd = 0.0
    for r in sorted(closed, key=lambda r: r["exit_ts"] or datetime.min):
        eq += r["net"]
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    balance = acct["capital"] + realised
    return {"account_id": acct["id"], "starting_capital": round(acct["capital"], 2), "balance": round(balance, 2), "invested": round(invested, 2),
            "available": round(balance - invested, 2), "realised": round(realised, 2), "open_pnl": round(mtm, 2), "equity": round(balance + mtm, 2),
            "open_positions": len(open_), "open_risk": round(open_risk, 2), "open_risk_pct": round(100 * open_risk / balance, 2) if balance else None,
            "exposure_pct": round(100 * invested / balance, 2) if balance else None, "closed_trades": len(closed), "max_drawdown": round(dd, 2),
            "started_at": acct["started_at"].isoformat() if hasattr(acct["started_at"], "isoformat") else acct["started_at"]}


def positions(eng=None, status: str | None = None) -> list[dict]:
    eng = _eng(eng)
    acct = active(eng)
    out = []
    for r in _rows(acct["id"], eng):
        if status and r["status"] != status:
            continue
        p = {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in r.items()}
        if r["status"] == "OPEN" and r["last_price"]:
            p["mtm"] = _pnl(r, r["last_price"])["net"]
        out.append(p)
    return out


def summary(eng=None) -> dict:
    """Completed trades: count, win rate, net, expectancy, profit factor, drawdown, per strategy."""
    from app.services.position.backtest import Trade, stats
    eng = _eng(eng)
    acct = active(eng)
    done = [r for r in _rows(acct["id"], eng) if r["status"] == "CLOSED" and r["net"] is not None]

    def mk(r):
        return Trade(r["strategy"], 0, 1 if r["direction"] == "Bullish" else -1, r["decision_day"], r["entry_ts"].date(), r["expiry"], r["strike"], r["opt_type"], r["qty"],
                     r["entry_price"], r["exit_price"], r["exit_ts"], r["exit_reason"], r["gross"] or 0, r["slippage"] or 0,
                     (r["charges"] or {}).get("total", 0) if isinstance(r["charges"], dict) else 0, r["net"], (r["exit_ts"].date() - r["entry_ts"].date()).days, "paper")
    items = [mk(r) for r in done]
    by = {}
    for k in sorted({i.strategy for i in items}):
        by[k] = stats([i for i in items if i.strategy == k])
    return {"overall": stats(items), "by_strategy": by}


# ---------------------------------------------------------------- entry
class Refused(ValueError):
    """The paper entry was not made; the message is the exact reason."""


def signal_key(strategy: str, decision_day: str, direction: int) -> str:
    return f"{strategy}|{decision_day}|{direction}"


def open_position(opp: dict, day: str, risk_cfg: dict, now: datetime, price: float | None = None, eng=None, auto: bool = False, allow_unvalidated: bool = False) -> dict:
    """Open one paper position from an analysed opportunity. Raises `Refused` with the reason; never forces a trade."""
    eng = _eng(eng)
    if opp.get("decision") not in _ENTRY_OK:
        raise Refused(f"the decision is {opp.get('decision')}: only BUY and STRONG BUY ideas can be opened")
    best, plan = opp.get("contract"), opp.get("plan")
    if not best or not plan:
        raise Refused("there is no usable option contract or plan for this idea")
    strat = opp["strategies"][0]
    if auto and not allow_unvalidated and not any(e["status"] == "positive" for e in opp.get("evidence", [])):
        raise Refused("automatic entry needs a strategy with a validated positive result; none has one (turn on 'allow unvalidated' to override, paper only)")
    key = signal_key(strat, day, opp["direction"])
    acct = active(eng)
    rows = _rows(acct["id"], eng)
    if any(r["signal_key"] == key for r in rows):
        raise Refused("this signal was already entered (duplicate entries are refused)")
    st = state(eng)
    if st["open_positions"] >= risk_cfg["max_open_positions"]:
        raise Refused(f"{st['open_positions']} positions are open (maximum {risk_cfg['max_open_positions']})")
    entry = float(price if price else best["premium"])
    basis = "live price" if price else "last traded premium of the decision day (the market was closed or no live price was available)"
    from app.services.position import backtest as bt
    stop = costs._round_tick_down(entry * (1 - bt.STOP_PCT))                 # the backtested levels, from the actual fill
    t1, t2 = costs._round_tick_up(entry * (1 + bt.TARGET_PCT)), costs._round_tick_up(entry * (1 + 2 * bt.TARGET_PCT))
    size = sizing.risk_size("BUY", entry, stop, best["lot_size"], st["available"], risk_cfg["risk_pct"], available=st["available"], max_lots=risk_cfg["max_lots"],
                            target=t1, include_slippage=True)
    if size.get("decision") != "TRADE":
        raise Refused("sizing: " + str(size.get("reason")))
    new_risk = float(size["max_loss"])
    cap = st["balance"]
    if st["open_risk"] + new_risk > cap * risk_cfg["max_portfolio_risk_pct"] / 100:
        raise Refused(f"portfolio risk would be ₹{st['open_risk'] + new_risk:,.0f} (₹{st['open_risk']:,.0f} open + ₹{new_risk:,.0f} new), above the limit of "
                      f"{risk_cfg['max_portfolio_risk_pct']:g}% of capital (₹{cap * risk_cfg['max_portfolio_risk_pct'] / 100:,.0f})")
    rec = {"a": acct["id"], "k": key, "s": strat, "d": "Bullish" if opp["direction"] > 0 else "Bearish", "t": best["typ"], "e": best["expiry"], "k2": best["strike"],
           "sym": best["symbol"], "ls": best["lot_size"], "lots": size["lots"], "q": size["qty"], "dd": date.fromisoformat(day), "sc": opp["score"], "ts": now, "ep": entry,
           "sp": stop, "t1": t1, "t2": t2, "inv": plan["invalidation"], "pe": plan["planned_exit"], "fe": None, "bp": entry, "lp": entry,
           "risk": json.dumps({**{k: size.get(k) for k in ("risk_amount", "risk_pct", "lots", "qty", "max_loss", "investment", "risk_per_lot")}, "capital": st["available"], "fill_basis": basis}),
           "an": json.dumps({"components": opp["components"], "contract": {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in best.items() if k != "estimate"},
                             "estimate": best.get("estimate"), "plan": plan, "strategies": opp["strategies"], "evidence": opp.get("evidence"), "why": opp["why"]}, default=str)}
    d = date.fromisoformat(plan["expiry"])
    fe = d - timedelta(days=1)
    while fe.weekday() >= 5:
        fe -= timedelta(days=1)
    rec["fe"] = fe
    with eng.begin() as c:
        tid = c.execute(text(
            "INSERT INTO position_trades (account_id, signal_key, strategy, direction, opt_type, expiry, strike, trading_symbol, lot_size, lots, qty, decision_day, score, entry_ts, "
            "entry_price, stop_premium, target1, target2, invalidation, planned_exit, forced_exit, best_premium, last_price, last_price_at, risk, analysis) VALUES "
            "(:a,:k,:s,:d,:t,:e,:k2,:sym,:ls,:lots,:q,:dd,:sc,:ts,:ep,:sp,:t1,:t2,:inv,:pe,:fe,:bp,:lp,:ts,CAST(:risk AS JSONB),CAST(:an AS JSONB)) RETURNING id"), rec).scalar_one()
    return {"id": tid, "entry_price": entry, "lots": size["lots"], "qty": size["qty"], "max_loss": new_risk, "fill_basis": basis}


# ---------------------------------------------------------------- management
def _close(p: dict, price: float, reason: str, now: datetime, eng) -> dict:
    rt = _pnl(p, price)
    with eng.begin() as c:
        c.execute(text("UPDATE position_trades SET status='CLOSED', exit_ts=:t, exit_price=:px, exit_reason=:r, gross=:g, slippage=:s, charges=CAST(:ch AS JSONB), net=:n, last_price=:px, "
                       "last_price_at=:t WHERE id=:i AND status='OPEN'"),
                  {"t": now, "px": price, "r": reason, "g": rt["gross"], "s": rt["slippage"], "ch": json.dumps(rt["charges"]), "n": rt["net"], "i": p["id"]})
    return {"id": p["id"], "reason": reason, "price": price, "net": rt["net"]}


def manage(now: datetime, price_fn, eng=None, trail_pct: float = pplan.TRAIL_PCT) -> list[dict]:
    """Apply the exit rules to every open position with the prices `price_fn(position) -> (price, as_of) | None` returns. A missing or stale price
    changes nothing. Returns what happened. Called by the scheduler during market hours and after the close; safe to call at any time."""
    eng = _eng(eng)
    acct = active(eng)
    events = []
    for p in _rows(acct["id"], eng):
        if p["status"] != "OPEN":
            continue
        got = None
        try:
            got = price_fn(p)
        except Exception:
            got = None
        if not got or got[0] is None:
            events.append({"id": p["id"], "note": "no price available: not managed this time"}); continue
        price, at = float(got[0]), got[1]
        if at is not None and (now - at).total_seconds() > STALE_SEC:
            events.append({"id": p["id"], "note": "the price is stale: not managed this time"}); continue
        best = max(float(p["best_premium"] or p["entry_price"]), price)
        stop, t1_hit = float(p["stop_premium"]), bool(p["t1_hit"])
        if not t1_hit and price >= float(p["target1"]):
            t1_hit, stop = True, max(stop, float(p["entry_price"]))
            events.append({"id": p["id"], "note": f"Target 1 reached at {price:.2f}: stop moved to the entry premium"})
        if t1_hit:
            stop = max(stop, costs._round_tick_down(best * (1 - trail_pct / 100)))
        with eng.begin() as c:
            c.execute(text("UPDATE position_trades SET best_premium=:b, last_price=:l, last_price_at=:t, stop_premium=:s, t1_hit=:h WHERE id=:i AND status='OPEN'"),
                      {"b": best, "l": price, "t": at or now, "s": stop, "h": t1_hit, "i": p["id"]})
        p = {**p, "stop_premium": stop}
        reason = None
        if price <= stop:
            reason = "trailing_stop" if t1_hit else "stop_loss"
        elif p["target2"] and price >= float(p["target2"]):
            reason = "target2"
        elif p["forced_exit"] and now.date() >= p["forced_exit"] and now.time() >= TIME_EXIT_AT:
            reason = "expiry_exit"
        elif p["planned_exit"] and now.date() >= p["planned_exit"] and now.time() >= TIME_EXIT_AT:
            reason = "time_exit"
        if reason:
            events.append(_close(p, price, reason, now, eng))
    return events


def live_price(p: dict):
    """(price, as-of) of one open position from Groww when it is reachable, else None. Read-only quote; never an order."""
    from app.services.market_data import live
    from app.utils.timeutil import now_naive
    m = live.GrowwMarket()
    c = m.contract(date.today(), p["expiry"], float(p["strike"]), p["opt_type"])
    if not c:
        return None
    return float(m.option_ltp(c)), now_naive()

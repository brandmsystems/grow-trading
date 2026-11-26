"""Option contract analysis for a position-trading idea: compare BUY CE and BUY PE, expiries and strikes using the premiums the market actually
traded on the decision day (stored 1-minute candles). Missing data is flagged, never invented:

* premium, day volume and open interest come from the stored candles of the decision day;
* bid-ask spread is not stored historically (it is checked live against Groww when connected);
* IV, delta and theta are Black-Scholes *estimates* from that premium (`bsm.py`), labelled as such.

`evaluate` is pure; `load` reads the database.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from app.services.position import bsm

STEP = 50
OFFSETS = (-100, -50, 0, 50, 100)            # points from ATM away from the money: negative = in the money, positive = out of the money
MIN_PREMIUM = 5.0
OI_FULL, VOL_FULL = 200_000, 100_000          # contracts (OI) and traded contracts (volume) for the full liquidity points


def atm(spot: float) -> float:
    return round(spot / STEP) * STEP


def _liquidity(oi, vol) -> tuple[float | None, str]:
    parts, notes = [], []
    if oi is not None and oi > 0:
        parts.append(2 * min(1.0, oi / OI_FULL)); notes.append(f"open interest {oi:,.0f}")
    else:
        notes.append("open interest not available")
    if vol is not None and vol > 0:
        parts.append(2 * min(1.0, vol / VOL_FULL)); notes.append(f"volume {vol:,.0f} on the day")
    else:
        notes.append("volume not available")
    return (sum(parts) if parts else None), ", ".join(notes)


MAX_SPREAD_PCT = 5.0


def evaluate(c: dict, atr: float | None, hold_days: int) -> dict:
    """Quality 0-10 and the facts behind it for one candidate {expiry, strike, typ, premium, volume, oi, dte, spot, lot_size, offset}."""
    notes, pts = [], 0.0
    liq, ln = _liquidity(c.get("oi"), c.get("volume"))
    pts += liq or 0.0
    notes.append(ln + ("" if liq is not None else " (0 points)"))
    est = bsm.estimate(c["premium"], c["spot"], c["strike"], max(c["dte"], 0.01), c["typ"])
    if c.get("iv") and c.get("delta") is not None:                     # Groww's own option-chain IV and delta (live): real data, not an estimate
        iv = float(c["iv"]) / 100 if float(c["iv"]) > 3 else float(c["iv"])          # Groww sends IV in percent (15.2); the model wants a fraction (0.152)
        g = bsm.greeks(c["spot"], c["strike"], max(c["dte"], 0.01) / 365.0, iv, c["typ"])
        est = {"available": True, "iv": iv, "delta": float(c["delta"]), "theta_day": g["theta_day"],
               "theta_pct_day": round(100 * g["theta_day"] / c["premium"], 2) if g["theta_day"] and c["premium"] else None,
               "note": "IV and delta from Groww's option chain; theta from Black-Scholes using that IV (a model value)"}
    spread_pct, spread = None, {"available": False, "why": "bid-ask spread is not stored historically; it is checked live against Groww when connected"}
    if c.get("bid") and c.get("ask") and c["ask"] >= c["bid"] > 0:
        spread_pct = 100 * (c["ask"] - c["bid"]) / ((c["ask"] + c["bid"]) / 2)
        spread = {"available": True, "bid": c["bid"], "ask": c["ask"], "pct": round(spread_pct, 2), "why": "live bid and ask from Groww"}
        notes.append(f"bid {c['bid']:.2f} / ask {c['ask']:.2f}: spread {spread_pct:.1f}%")
        pts += 1 if spread_pct <= 1.5 else 0.5 if spread_pct <= MAX_SPREAD_PCT else 0
    theta_pct = est.get("theta_pct_day") if est["available"] else None
    if theta_pct is not None:
        pts += 3 * min(1.0, max(0.0, (6.0 + theta_pct) / 4.0))               # theta_pct is negative: -2%/day or better earns 3, -6%/day or worse 0
        notes.append(f"estimated theta {theta_pct:.1f}% of the premium a day")
    else:
        notes.append("theta not available (0 points)")
    need = hold_days + 3
    pts += 2 if need <= c["dte"] <= need + 14 else 1 if c["dte"] >= need else 0
    notes.append(f"{c['dte']:.0f} days to expiry (a {hold_days}-day hold needs at least {need})")
    gap = None
    if est["available"] and atr:
        gap = abs(est["delta"]) * atr / c["premium"]
        pts += 1 if gap <= 0.25 else 0.5 if gap <= 0.4 else 0
        notes.append(f"a one-ATR overnight move changes the premium by about {100 * gap:.0f}% (estimate)")
    wide = spread_pct is not None and spread_pct > MAX_SPREAD_PCT
    ok = c["premium"] >= MIN_PREMIUM and c["dte"] >= max(2, hold_days // 2 + 1) and not wide
    return {**c, "quality": round(min(10.0, pts), 1), "estimate": est, "gap_pct": None if gap is None else round(100 * gap, 1), "usable": ok, "notes": notes,
            "reasons_unusable": ([] if c["premium"] >= MIN_PREMIUM else [f"premium {c['premium']:.2f} is below {MIN_PREMIUM:g}"])
            + ([] if c["dte"] >= max(2, hold_days // 2 + 1) else [f"only {c['dte']:.0f} days to expiry"])
            + ([f"bid-ask spread {spread_pct:.1f}% is above {MAX_SPREAD_PCT:g}%"] if wide else []), "spread": spread}


def rank(cands: list[dict]) -> list[dict]:
    return sorted(cands, key=lambda c: (not c["usable"], -c["quality"], c["dte"], abs(c["offset"])))


def explain_choice(best: dict, rest: list[dict]) -> list[str]:
    """Why `best` is preferred to the alternatives, in plain sentences."""
    name = lambda c: f"{c['expiry']:%d %b} {int(c['strike'])} {c['typ']}"
    out = [f"{name(best)}: quality {best['quality']:g} of 10 ({'; '.join(best['notes'])})."]
    for o in rest[:3]:
        why = []
        for k, label in (("quality", "quality"),):
            if o[k] < best[k]:
                why.append(f"lower {label} ({o[k]:g} against {best[k]:g})")
        if o["dte"] != best["dte"]:
            why.append(f"{o['dte']:.0f} against {best['dte']:.0f} days to expiry")
        if not o["usable"]:
            why.append("not usable: " + "; ".join(o["reasons_unusable"]))
        out.append(f"{name(o)} ranks lower: " + ("; ".join(why) or "similar, ranked after on tie-breaks (nearer expiry, closer to the money)") + ".")
    return out


# ---------------------------------------------------------------- database access
def _day_stats(symbol: str, day: date):
    """(last close, volume, last open interest) of one option on one day from stored 1-minute candles, or None."""
    from app.database import db
    df = db.load_candles(symbol, datetime.combine(day, time(9, 0)), datetime.combine(day + timedelta(days=1), time(0, 0)))
    if df.empty:
        return None
    last = df.iloc[-1]
    return float(last["close"]), float(df["volume"].sum()), (float(last["oi"]) if float(last["oi"]) > 0 else None)


_market = None


def _live_stats(expiry: date, strike: float, typ: str) -> dict | None:
    """A live read-only Groww quote of one contract (premium, volume, open interest, bid, ask, delta, IV), used when the decision day's candles are not stored yet
    (the option history is downloaded after a contract expires). None when Groww is unreachable. Never an order, never account data."""
    global _market
    try:
        from app.services.market_data import live
        _market = _market or live.GrowwMarket()
        c = _market.contract(date.today(), expiry, strike, typ)
        if not c:
            return None
        ltp = float(_market.option_ltp(c))
        q = _market.option_quote(c)
        return {"premium": ltp, "volume": q.get("volume"), "oi": q.get("oi"), "bid": q.get("bid"), "ask": q.get("ask"), "delta": q.get("delta"), "iv": q.get("iv"), "live": True}
    except Exception:
        return None


def load(day: date, spot: float, typ: str, hold_days: int, atr: float | None, expiries: list[date] | None = None, symbols: dict | None = None) -> list[dict]:
    """Evaluated candidates for one option type on decision day `day` (close `spot`): the nearest two expiries a `hold_days` hold fits, five strikes."""
    from app.database import db
    from app.services.options import lot_sizes
    expiries = expiries if expiries is not None else db.load_expiries("groww")
    need = hold_days + 3
    fit = [e for e in sorted(expiries) if (e - day).days >= need][:2]
    out = []
    for e in fit:
        for off in OFFSETS:
            strike = atm(spot) + (off if typ == "CE" else -off)       # CE: a lower strike is in the money, PE: a higher one
            sym = (symbols or {}).get((e, float(strike), typ)) or f"NSE-NIFTY-{e:%d%b%y}-{int(strike)}-{typ}"
            st = _day_stats(sym, day)
            extra = {}
            if st is None:
                live_ = _live_stats(e, float(strike), typ) if (date.today() - day).days <= 4 else None
                if live_ is None:
                    continue
                prem, vol, oi = live_["premium"], live_["volume"], live_["oi"]
                extra = {k: live_[k] for k in ("bid", "ask", "delta", "iv", "live")}
            else:
                prem, vol, oi = st
            try:
                lot, _ = lot_sizes.lot_size_for(e, list(expiries))
            except Exception:
                continue
            out.append(evaluate({"symbol": sym, "expiry": e, "strike": float(strike), "typ": typ, "premium": prem, "volume": vol, "oi": oi, "dte": float((e - day).days),
                                 "spot": spot, "lot_size": lot, "offset": off, **extra}, atr, hold_days))
    return rank(out)

"""Black-Scholes *estimates* from a real option premium (pure). Implied volatility, delta and theta are NOT market data: they are model values
derived from the premium the market actually showed, with an assumed risk-free rate and no dividends, and every caller labels them as
estimates. They are used for explanations and warnings (theta decay, overnight gap risk), never as a backtest input and never invented when
the premium is missing."""
from __future__ import annotations

import math

RATE = 0.065          # assumed risk-free rate (India 91-day T-bill order of magnitude); an assumption, shown with every estimate


def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def price(spot: float, strike: float, t: float, vol: float, typ: str, r: float = RATE) -> float:
    if t <= 0 or vol <= 0:
        return max(0.0, (spot - strike) if typ == "CE" else (strike - spot))
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if typ == "CE":
        return spot * _cdf(d1) - strike * math.exp(-r * t) * _cdf(d2)
    return strike * math.exp(-r * t) * _cdf(-d2) - spot * _cdf(-d1)


def implied_vol(premium: float, spot: float, strike: float, t: float, typ: str, r: float = RATE) -> float | None:
    """Volatility that reproduces `premium`, by bisection; None when the premium is below intrinsic value, there is no time left, or the
    premium cannot be matched (never a guess)."""
    if premium <= 0 or t <= 0 or spot <= 0 or strike <= 0:
        return None
    intrinsic = max(0.0, (spot - strike * math.exp(-r * t)) if typ == "CE" else (strike * math.exp(-r * t) - spot))
    if premium < intrinsic - 1e-6:
        return None
    lo, hi = 0.01, 3.0
    if price(spot, strike, t, hi, typ, r) < premium or price(spot, strike, t, lo, typ, r) > premium:
        return None
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if price(spot, strike, t, mid, typ, r) < premium:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), 5)


def greeks(spot: float, strike: float, t: float, vol: float, typ: str, r: float = RATE) -> dict:
    """{delta, theta_day} for a long option: theta_day is the premium lost in one calendar day, other things equal (a negative number)."""
    if t <= 0 or vol <= 0:
        return {"delta": None, "theta_day": None}
    sq = math.sqrt(t)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t) / (vol * sq)
    d2 = d1 - vol * sq
    delta = _cdf(d1) if typ == "CE" else _cdf(d1) - 1
    base = -spot * _pdf(d1) * vol / (2 * sq)
    theta_year = base - r * strike * math.exp(-r * t) * _cdf(d2) if typ == "CE" else base + r * strike * math.exp(-r * t) * _cdf(-d2)
    return {"delta": round(delta, 4), "theta_day": round(theta_year / 365, 4)}


def estimate(premium: float, spot: float, strike: float, days_to_expiry: float, typ: str) -> dict:
    """IV, delta and theta estimates for a real premium, or {"available": False, "why": ...}."""
    t = days_to_expiry / 365.0
    iv = implied_vol(premium, spot, strike, t, typ)
    if iv is None:
        return {"available": False, "why": "implied volatility could not be solved from this premium (below intrinsic value, expired, or out of range)"}
    g = greeks(spot, strike, t, iv, typ)
    return {"available": True, "iv": iv, "delta": g["delta"], "theta_day": g["theta_day"],
            "theta_pct_day": round(100 * g["theta_day"] / premium, 2) if premium else None,
            "note": f"model estimate from the premium (Black-Scholes, assumed rate {RATE:.1%}, no dividends); not market data"}

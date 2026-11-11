"""Option contract lookups in Groww responses."""
from __future__ import annotations

from app.utils.numbers import to_float as _f


def chain_row(chain: dict, strike: float, opt_type: str) -> dict | None:
    """The strike's CE/PE entry in a Groww option chain response (keys are strike strings)."""
    strikes = (chain or {}).get("strikes") or {}
    for k, v in strikes.items():
        if _f(k) == float(strike):
            row = (v or {}).get(opt_type)
            return row if isinstance(row, dict) else None
    return None

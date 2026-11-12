"""NIFTY lot size of a contract, from the NSE circulars stored in `lot_sizes`.

NSE changes lot sizes by contract: weekly and monthly expiries switch on different
dates, so the lot size depends on the contract's expiry and cycle, not the trade date.
A monthly contract is the last expiry of its calendar month.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache

from sqlalchemy import text

from app.database import db


class LotSizeUnknown(LookupError):
    pass


@lru_cache(maxsize=4)
def _table(underlying: str) -> tuple[tuple[str, date, int, str], ...]:
    with db.engine().connect() as c:
        rows = c.execute(text("SELECT cycle, first_expiry, lot_size, source FROM lot_sizes "
                              "WHERE underlying=:u ORDER BY first_expiry"), {"u": underlying}).fetchall()
    return tuple((r[0], r[1], int(r[2]), r[3]) for r in rows)


def clear_cache() -> None:
    _table.cache_clear()


def cycle_of(expiry: date, expiries: list[date]) -> str:
    """'monthly' if `expiry` is the last listed expiry of its month, else 'weekly'."""
    same_month = [e for e in expiries if (e.year, e.month) == (expiry.year, expiry.month)]
    return "monthly" if not same_month or expiry >= max(same_month) else "weekly"


def lot_size_for(expiry: date, expiries: list[date], underlying: str = "NIFTY") -> tuple[int, str]:
    """(lot size, source circular) for a contract. Raises LotSizeUnknown before the table starts."""
    cycle = cycle_of(expiry, expiries)
    match = None
    for cyc, first, size, source in _table(underlying):
        if cyc == cycle and first <= expiry:
            match = (size, source)
    if match is None:
        raise LotSizeUnknown(f"No NSE lot size recorded for the {cycle} {underlying} expiry {expiry}")
    return match


def history(underlying: str = "NIFTY") -> list[dict]:
    return [{"cycle": c, "first_expiry": f.isoformat(), "lot_size": s, "source": src}
            for c, f, s, src in _table(underlying)]

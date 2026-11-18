"""Small time helpers shared across services."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_naive() -> datetime:
    """Current local wall-clock time (the app runs on an IST machine and stores IST-naive datetimes).

    Modules expose this as `_now` so tests can monkeypatch the clock per module.
    """
    return datetime.now()


def parse_hm(s: str) -> time:
    """'09:30' -> time(9, 30)."""
    try:
        h, m = str(s).split(":")
        return time(int(h), int(m))
    except ValueError:
        raise ValueError(f"Time must look like 09:30, got {s!r}") from None

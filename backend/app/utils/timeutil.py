"""Small time helpers shared across services."""
from __future__ import annotations

from datetime import time


def parse_hm(s: str) -> time:
    """'09:30' -> time(9, 30)."""
    h, m = str(s).split(":")
    return time(int(h), int(m))

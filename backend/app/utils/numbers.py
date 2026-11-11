"""Number helpers shared across services."""
from __future__ import annotations

import math


def to_float(v) -> float | None:
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None

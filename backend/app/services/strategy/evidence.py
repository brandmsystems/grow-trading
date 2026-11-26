"""What the validation says about each strategy (static record of the documented results; no I/O).

The scanner's "historical out-of-sample performance" score component and its eligibility rule read this table. It is a record of what
was measured, not a forecast. The results come from `scripts/research_entries.py` (five years of NIFTY candles, real 1-minute option
premiums, NSE lot sizes, slippage and the full charge stack, train 2022-23 / validation 2024 / out-of-sample 2025 to Nov 2026, nothing
tuned after seeing a result). See docs/ENTRY_RESEARCH.md and docs/AUTO_TRADING.md.

status:
  positive      net positive after costs in training, validation and out-of-sample, with enough trades -> up to the full points
  insufficient  too few trades (or a short window) to say anything                                      -> a small share of the points
  negative      net negative after costs out of sample (or in every period)                              -> 0 points, not eligible by default

Update this table when a new validation is run; never from a single backtest that was tuned on its own result.
"""
from __future__ import annotations

POINTS = {"positive": 10, "insufficient": 3, "negative": 0}
LABELS = {"positive": "validated positive", "insufficient": "insufficient evidence", "negative": "negative validated result"}

_RESEARCH = ("Five years, real option premiums, full costs: 0 of 80 strategy x exit pairs were positive in all three periods "
             "(docs/ENTRY_RESEARCH.md); the pooled 5-minute result was -₹34.6 lakh over 18,710 trades.")

# explicit records first; anything not listed falls back to the research default (every registered strategy was tested in that research)
EVIDENCE: dict[str, dict] = {
    "bias": {"status": "negative", "trades": 138, "oos_net": None,
             "note": "Replay through the engine, 93 sessions in 2026: net -₹33,215 over 138 trades (docs/AUTO_TRADING.md); next-candle hit rate 50.9%."},
    "confluence": {"status": "negative", "trades": 2360, "oos_net": -190000,
                   "note": "Five years: 0 of 12 method and exit pairs positive; out-of-sample -₹1.9 to -2.5 lakh per exit rule (docs/AUTO_TRADING.md)."},
    "scored": {"status": "negative", "trades": 379, "oos_net": -56591,
               "note": "Five years, 5-minute entries: 379 trades, win 27.2%, net -₹97,628, out-of-sample -₹56,591, profit factor 0.51 (docs/AUTO_TRADING.md)."},
}


def evidence_for(key: str) -> dict:
    """The validation record of a registered strategy: {status, label, points, trades, oos_net, note}."""
    e = EVIDENCE.get(key) or {"status": "negative", "trades": None, "oos_net": None, "note": _RESEARCH}
    st = e["status"]
    return {"status": st, "label": LABELS[st], "points": POINTS[st], "trades": e.get("trades"), "oos_net": e.get("oos_net"), "note": e["note"]}


def eligible(key: str) -> bool:
    """Only a strategy with a validated positive result trades by default."""
    return evidence_for(key)["status"] == "positive"

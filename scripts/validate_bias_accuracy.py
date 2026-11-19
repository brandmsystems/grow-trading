"""Next-candle accuracy of the automated bias engine on stored real candles (read-only, no market calls, no writes).

    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\validate_bias_accuracy.py 2022-01-03 2026-11-18

The rules and thresholds are the fixed defaults (nothing is fitted to these candles), so every year is out of sample
for them. Prints the combined and per-indicator hit rates, by year, and what the spot price did after entry candidates.
"""
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np
import pandas as pd

from app.database import db
from app.services.market_data import history as dm
from app.services.market_data.providers import GrowwProvider
from app.services.strategy import bias

START = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2022, 1, 3)
END = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today() - timedelta(days=1)
warm = START - timedelta(days=60)
spot = db.load_candles(GrowwProvider.spot_symbol, datetime.combine(warm, time(0)), datetime.combine(END + timedelta(days=1), time(0)))
try:
    fut = dm.futures_1m(warm, END + timedelta(days=1))
except Exception as exc:
    print("no futures candles:", exc)
    fut = None
p = bias.BiasParams()
f = bias.analyse(spot, fut if fut is not None and len(fut) else None, p)
f = bias.evaluate_predictions(f[(f["day"] >= START) & (f["day"] <= END)].reset_index(drop=True), p)
f["year"] = pd.to_datetime(f["day"]).dt.year
print(f"{len(f)} candles on {f['day'].nunique()} days, {START} to {END}\n")

print("combined next-candle prediction by year (NEUTRAL excluded)")
for y, g in [("all", f)] + list(f.groupby("year")):
    g = g.dropna(subset=["actual"])
    called = g[(g.predicted != "NEUTRAL") & g.actual.isin(["UP", "DOWN"])]
    n = len(called)
    hit = (called.predicted == called.actual).mean() * 100 if n else float("nan")
    ci = 1.96 * np.sqrt(max(hit / 100 * (1 - hit / 100), 1e-9) / max(n, 1)) * 100
    up = (g.actual == "UP").sum() / max(1, g.actual.isin(["UP", "DOWN"]).sum()) * 100
    print(f"  {y}: {n:6d} calls of {len(g):6d} candles  hit {hit:5.1f}% (±{ci:.1f})  market UP share {up:4.1f}%")

print("\nper indicator")
for r in bias.accuracy(f, p):
    print(f"  {r['label']:22s} {r['timeframe']:8s} n={r['n']:6d} accuracy={r['accuracy']}")

print("\nentry candidates: spot move in the signal's direction after 1, 3 and 6 candles")
c = f.copy()
for h in (1, 3, 6):
    c[f"fwd{h}"] = (c.groupby("day")["close"].shift(-h) - c["close"]) * c["direction"]
cand = c[c.direction != 0]
print(f"  {len(cand)} candidates, {len(cand) / f['day'].nunique():.1f} a day (before the one-position and one-entry-per-signal rules)")
for h in (1, 3, 6):
    x = cand[f"fwd{h}"].dropna()
    print(f"  after {h * p.primary:3d} min: mean {x.mean():6.2f} points, positive {100 * (x > 0).mean():4.1f}%, mean ATR {cand.atr.mean():.1f}")

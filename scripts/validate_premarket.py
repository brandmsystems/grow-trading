"""How well would the pre-market score have called NIFTY's day? (read-only; uses Yahoo's daily history, stored NIFTY candles)

    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\validate_premarket.py

For every NIFTY session from 2022 to the last finished one it rebuilds the factors that HAVE history, with the same rules
and thresholds the page uses (premarket/scoring.py), from data known before 09:15 that day:
  * global: S&P 500, Nasdaq, Dow = the US session that ended before the open (Asian indices are mid-session at 09:15, Gift
    Nifty has no history: both left out, so this is the US half of the factor);
  * crude: Brent's last close before that morning; India VIX: its previous-day close and change;
  * structure: the daily trend/indicator score from stored NIFTY candles up to the previous close, plus the 3-session swing
    (the 15-minute part and the opening gap are left out).
FII/DII has no history here and scores 0. Target: NIFTY's close against the previous close (|move| < 0.15% = flat, not scored).
Thresholds were fixed before this ran and nothing was tuned. Prints tables; nothing is written.
"""
import math
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import numpy as np
import pandas as pd
import requests

from app.database import db
from app.services.market_data import history as data_manager
from app.services.premarket import scoring, sources
from app.services.strategy import bias

SYMS = {"sp500": "^GSPC", "nasdaq": "^IXIC", "dow": "^DJI", "brent": "BZ=F", "vix": "^INDIAVIX"}


def hist(sym: str) -> pd.Series:
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "6y", "interval": "1d"}, headers=sources.UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    s = pd.Series(res["indicators"]["quote"][0]["close"], index=[datetime.fromtimestamp(t).date() for t in res["timestamp"]], dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")]


def q(key, series: pd.Series, d: date):
    """Quote as of the morning of d: last close strictly before d against the one before it."""
    prior = series[series.index < d]
    if len(prior) < 8:
        return None
    c = prior.iloc[-8:].tolist()
    return {"key": key, "name": key, "price": c[-1], "prev_close": c[-2], "change_pct": (c[-1] / c[-2] - 1) * 100, "series": c,
            "asof": str(prior.index[-1]), "status": "last close", "source": "Yahoo Finance"}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0, 0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d * 100, (c + m) / d * 100)


def main():
    print("downloading Yahoo history...", flush=True)
    H = {k: hist(s) for k, s in SYMS.items()}
    start = datetime(2021, 11, 1)
    end = datetime.now()
    spot = db.load_candles("NSE-NIFTY", start, end)
    fut = data_manager.futures_1m(start.date(), end.date())
    days = bias.tf_bars(spot, fut, 375)
    days = days[days["day"] < end.date()].reset_index(drop=True)
    ds = bias.tf_score(bias.votes(days), bias.INDICATORS)
    h, lo = days["high"], days["low"]
    swing = pd.Series(np.where((h > h.shift(1)) & (h.shift(1) > h.shift(2)) & (lo > lo.shift(1)) & (lo.shift(1) > lo.shift(2)), 1.0,
                               np.where((h < h.shift(1)) & (h.shift(1) < h.shift(2)) & (lo < lo.shift(1)) & (lo.shift(1) < lo.shift(2)), -1.0, 0.0)))
    rows = []
    for i in range(210, len(days)):
        d = days["day"].iloc[i]
        if d < date(2022, 1, 1):
            continue
        qs = {k: q(k, H[k], d) for k in H}
        glob = scoring.global_factor({k: qs[k] for k in ("sp500", "nasdaq", "dow")})
        crude = scoring.crude_factor({"brent": qs["brent"]})
        vix = scoring.vix_factor({"vix": qs["vix"]})
        st = scoring.structure_factor({"day": str(days["day"].iloc[i - 1]), "open": 0, "high": 0, "low": 0, "close": 0, "rows": [], "asof": "", "freshness": "",
                                       "headline": "", "daily_score": None if pd.isna(ds.iloc[i - 1]) else float(ds.iloc[i - 1]), "m15_score": None,
                                       "swing": float(swing.iloc[i - 1]), "gap_vote": None})
        prev, cl, op = days["close"].iloc[i - 1], days["close"].iloc[i], days["open"].iloc[i]
        rows.append({"day": d, "year": d.year, "global": glob["score"], "crude": crude["score"], "vix": vix["score"], "structure": st["score"],
                     "total": glob["score"] + crude["score"] + vix["score"] + st["score"], "chg": (cl / prev - 1) * 100, "o2c": (cl / op - 1) * 100})
    t = pd.DataFrame(rows)
    t["dir"] = np.where(t.chg >= scoring.__dict__.get("FLAT", 0.15), 1, np.where(t.chg <= -0.15, -1, 0))
    print(f"\n{len(t)} sessions {t.day.min()} .. {t.day.max()}; up {100 * (t.dir == 1).mean():.1f}%, down {100 * (t.dir == -1).mean():.1f}%, flat {100 * (t.dir == 0).mean():.1f}%\n")

    def hit(sub, label):
        called = sub[(sub.dir != 0)]
        n, k = len(called), int(((np.sign(called["total"]) == called.dir)).sum())
        lo_, hi_ = wilson(k, n)
        print(f"{label:<42} calls {n:>4}  hit {100 * k / max(n, 1):5.1f}%  (95% {lo_:.1f}-{hi_:.1f})")

    print("== total score (US global + crude + VIX + daily structure; FII/DII and the rest have no history) ==")
    for thr in (2, 3):
        for name, sub in (("all", t), ("2022-23", t[t.year <= 2023]), ("2024", t[t.year == 2024]), ("2025-26", t[t.year >= 2025])):
            hit(sub[sub.total.abs() >= thr], f"|total| >= {thr}, {name}")
    print("\n== each factor on its own (only days it scored non-zero) ==")
    for f in ("global", "crude", "vix", "structure"):
        s = t[t[f] != 0]
        called = s[s.dir != 0]
        k = int((np.sign(called[f]) == called.dir).sum())
        lo_, hi_ = wilson(k, len(called))
        print(f"{f:<10} scored {len(s):>4} days, called {len(called):>4}, hit {100 * k / max(len(called), 1):5.1f}% (95% {lo_:.1f}-{hi_:.1f})")
    print("\n== mean NIFTY day move by total score ==")
    print(t.groupby("total").agg(days=("chg", "size"), mean_chg=("chg", "mean"), up_pct=("dir", lambda x: 100 * (x == 1).mean()), mean_o2c=("o2c", "mean")).round(3).to_string())
    print("\n(open-to-close is what a trade placed after the open could capture; the gap is already priced in)")


if __name__ == "__main__":
    main()

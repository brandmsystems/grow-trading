"""Replay the automated bias engine over finished sessions on stored REAL NIFTY candles and REAL option premiums
(paper broker: slippage and the full charge stack; fixed lots, no capital sizing in a replay).

    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\validate_bias_trades.py 2026-10-01 2026-11-12 ["{json overrides}"] [tag]

Candles are read from the real database. Every engine write (sessions, trades, predictions) goes to a scratch
database, groww_trading_bias_val_<tag>, which is dropped at the end, so nothing in your database changes. No Groww
order can be placed (PaperBroker). About 20 seconds per session. Prints one RESULT line of JSON.
"""
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pandas as pd
import psycopg2
from sqlalchemy import text

from app.config import settings as config
from app.database import db
from app.services.market_data.live import ReplayMarket
from app.services.trading import engine as le
from app.services.trading.brokers import PaperBroker

START, END = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])
OVER = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
TAG = sys.argv[4] if len(sys.argv) > 4 else "default"
SCRATCH = "groww_trading_bias_val_" + TAG

admin = psycopg2.connect(**{**config.PG, "dbname": "postgres"})
admin.autocommit = True
cur = admin.cursor()
cur.execute(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)")
cur.execute(f"CREATE DATABASE {SCRATCH}")
scratch = db.engine(SCRATCH)
db.init(scratch)
try:
    days = [d for d in db.candle_days("NSE-NIFTY") if START <= d <= END and d.weekday() < 5]
    print("sessions", len(days), flush=True)
    cfg = le.EngineConfig(**{"signal_mode": "bias", "trade_mode": "replay", "timeframe": 5, "max_daily_loss": 0, "lots": 1,
                             "max_trades_per_day": 20, "stop_mode": "pct", "stop_pct": 30, **OVER})
    market = ReplayMarket("groww", days[0] - timedelta(days=45), datetime.combine(days[0], time(9, 0)))
    eng = le.Engine(cfg, market, PaperBroker(market), eng=scratch)
    eng.start(threaded=False)
    for i, d in enumerate(days):
        market.clock, market.history_from, market._spot, market._fut = datetime.combine(d, time(9, 14)), d - timedelta(days=45), None, None
        while market.clock <= datetime.combine(d, time(15, 31)):
            eng.tick()
            market.clock += timedelta(seconds=10)
        if i % 5 == 4:
            print("done", d, flush=True)
    eng.stop(square_off=True, reason="validation finished")

    with scratch.connect() as c:
        t = pd.DataFrame(c.execute(text("SELECT * FROM live_trades ORDER BY id")).mappings().all())
        pr = pd.DataFrame(c.execute(text("SELECT predicted, actual FROM candle_bias WHERE outcome IS NOT NULL")).mappings().all())
    out = {"config": OVER, "sessions": len(days)}
    if len(pr):
        called = pr[(pr.predicted != "NEUTRAL") & pr.actual.isin(["UP", "DOWN"])]
        out["prediction"] = {"candles": len(pr), "calls": len(called),
                             "hit_pct": round(float((called.predicted == called.actual).mean() * 100), 1) if len(called) else None}
    if len(t):
        cl = t[t.status == "CLOSED"]
        net = cl["net"].astype(float)
        eq = net.cumsum()
        charges = sum((json.loads(x) if isinstance(x, str) else x)["total"] for x in cl["charges"] if x)
        out["trades"] = {
            "n": len(cl), "per_session": round(len(cl) / len(days), 2), "win_rate_pct": round(float((net > 0).mean() * 100), 1),
            "gross": round(float(cl["gross"].astype(float).sum()), 2), "slippage": round(float(cl["slippage"].astype(float).sum()), 2),
            "charges": round(float(charges), 2), "net": round(float(net.sum()), 2), "avg_net": round(float(net.mean()), 2),
            "max_drawdown": round(float((eq.cummax() - eq).max()), 2),
            "by_exit": {k: {"n": len(g), "net": round(float(g.net.astype(float).sum()), 2)} for k, g in cl.groupby("exit_reason")},
            "by_action": {k: {"n": len(g), "net": round(float(g.net.astype(float).sum()), 2)} for k, g in cl.groupby("action")},
        }
    print("RESULT " + json.dumps(out, default=str), flush=True)
finally:
    scratch.dispose()
    cur.execute(f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)")

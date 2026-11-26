"""Position-trading research: nine strategies x holds of 3, 5, 10 and 20 trading days on the stored NIFTY and option candles.

Read-only on the database. Writes data/exports/position_research.json (the report) and position_research_trades.csv.gz (every simulated trade).
    python scripts/research_position.py run      # simulate and write the files
    python scripts/research_position.py report   # print the stored report
"""
import gzip
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.position import backtest as bt  # noqa: E402

OUT = ROOT / "data" / "exports"


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    trades, skipped, meta = bt.run(progress=lambda f, m: print(f"\r{f:5.0%} {m:<30}", end="", flush=True))
    print()
    rep = bt.report(trades, skipped)
    rep["meta"] = meta
    rep["evidence"] = bt.evidence_from(rep)
    (OUT / bt.EXPORT).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    import pandas as pd
    pd.DataFrame([asdict(t) for t in trades]).to_csv(OUT / "position_research_trades.csv.gz", index=False, compression="gzip")
    print(f"{len(trades)} trades simulated, {len(skipped)} not simulatable -> {OUT / bt.EXPORT}")
    show(rep)


def show(rep):
    print(f"{'strategy':<18}{'hold':>5}{'trades':>8}{'win%':>7}{'net':>10}{'PF':>6}{'DD':>9}  train/val/oos net (trades)   skipped")
    for c in rep["cells"]:
        p = c["periods"]
        print(f"{c['strategy']:<18}{c['hold']:>5}{c['trades']:>8}{(c['win_rate'] or 0):>7}{c['net']:>10,.0f}{(c['profit_factor'] or 0):>6}{c['max_drawdown']:>9,.0f}  "
              + " / ".join(f"{p[n]['net']:,.0f} ({p[n]['trades']})" for n in ("train", "validation", "out_of_sample")) + f"   {c['unsimulatable_n']}")
    print("pooled by hold:", {h: (s["trades"], s["net"]) for h, s in rep["pooled_by_hold"].items()})
    print("robust cells:", [(c["strategy"], c["hold"]) for c in rep["cells"] if c["robust"]])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "report":
        show(json.loads((OUT / bt.EXPORT).read_text(encoding="utf-8")))
    else:
        run()

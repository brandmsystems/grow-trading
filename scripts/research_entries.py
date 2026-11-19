"""Five-year research of the entry methods on REAL NIFTY candles and REAL option premiums (read-only on the database).

    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py run [first_day] [last_day]
    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py report

`run` simulates every entry method (services/strategy/entries.py) x four fixed exit rules: signals from closed 5-minute
bars (15-minute trend from closed 15-minute bars), fill at the open of the first option candle at/after the signal
(within 2 minutes), ATM contract of the nearest weekly expiry (rolled on expiry day) with the NSE lot size of that
contract, slippage and the full Indian charge stack (trading/charges.py), one position at a time per method and exit
rule. A missing option candle skips the trade and is counted; nothing is filled in. Trades go to
data/exports/entry_research_trades.csv.gz. `report` prints the tables from that file (chronological train 2022-23,
validation 2024, out-of-sample 2025-26). Exit rules are fixed beforehand; none is tuned. Nothing is written to the DB.
"""
import json
import sys
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.database import db
from app.services.market_data import history as data_manager
from app.services.market_data import providers
from app.services.options import lot_sizes
from app.services.strategy import bias, entries
from app.services.strategy import rules as st
from app.services.strategy import signals as sig
from app.services.trading import charges as costs

OUT = ROOT / "data" / "exports" / "entry_research_trades.csv.gz"
WARM_SESSIONS = 12
FIRST_SIGNAL, LAST_SIGNAL = time(9, 20), time(15, 10)
FORCE_EXIT_MIN = 15 * 60 + 15              # nothing is held past 15:15
ENTRY_WAIT_MIN, EXIT_WAIT_MIN = 2, 3
WINDOWS = [("09:15-09:30", time(9, 15), time(9, 30)), ("09:30-10:30", time(9, 30), time(10, 30)),
           ("10:30-11:30", time(10, 30), time(11, 30)), ("11:30-12:30", time(11, 30), time(12, 30)),
           ("12:30-13:30", time(12, 30), time(13, 30)), ("13:30-14:30", time(13, 30), time(14, 30)),
           ("14:30-15:15", time(14, 30), time(15, 15))]
EXITS = [
    {"key": "sl20_tp40_h30", "stop": 20.0, "target": 40.0, "hold": 30},
    {"key": "sl25_tp50_h60", "stop": 25.0, "target": 50.0, "hold": 60},
    {"key": "trail_h60", "stop": 20.0, "target": None, "trail_act": 15.0, "trail": 12.0, "hold": 60},
    {"key": "time15", "stop": None, "target": None, "hold": 15},
]
SPLITS = [("train", date(2000, 1, 1), date(2023, 12, 31)), ("validation", date(2024, 1, 1), date(2024, 12, 31)),
          ("oos", date(2025, 1, 1), date(2100, 1, 1))]


def simulate(c: dict, ei: int, ex: dict):
    """(exit candle index, price, reason) for a long option entered at the open of candle ei."""
    m, o, h, l = c["m"], c["o"], c["h"], c["l"]
    entry = float(o[ei])
    end_m = min(m[ei] + ex["hold"], FORCE_EXIT_MIN)
    stop = costs._round_tick_down(entry * (1 - ex["stop"] / 100)) if ex.get("stop") else None
    target = costs._round_tick_up(entry * (1 + ex["target"] / 100)) if ex.get("target") else None
    peak = entry
    i = ei
    while i < len(m) and m[i] < end_m:
        if ex.get("trail") and peak >= entry * (1 + ex["trail_act"] / 100):
            tstop = costs._round_tick_down(peak * (1 - ex["trail"] / 100))
            stop = tstop if stop is None else max(stop, tstop)
        if i > ei:
            if stop is not None and o[i] <= stop:
                return i, float(o[i]), "stop_loss"
            if target is not None and o[i] >= target:
                return i, float(o[i]), "target"
        if stop is not None and l[i] <= stop:
            return i, float(stop), "stop_loss"
        if target is not None and h[i] >= target:
            return i, float(target), "target"
        peak = max(peak, float(h[i]))
        i += 1
    j = int(np.searchsorted(m, end_m))
    if j < len(m) and m[j] <= end_m + EXIT_WAIT_MIN:
        return j, float(o[j]), "time_exit"
    return None


def arrays(df: pd.DataFrame) -> dict:
    ts = df["ts"]
    return {"ts": ts.to_numpy(), "m": (ts.dt.hour * 60 + ts.dt.minute).to_numpy(), "o": df["open"].to_numpy(float),
            "h": df["high"].to_numpy(float), "l": df["low"].to_numpy(float)}


def run(first: date | None, last: date | None):
    prov = providers.get("groww")
    cfg = costs.DEFAULT_COSTS
    today = datetime.now().date()
    days_all = db.candle_days(prov.spot_symbol)
    last = last or max(d for d in days_all if d < today)
    first = first or days_all[0]
    print("loading candles", flush=True)
    spot = db.load_candles(prov.spot_symbol, datetime.combine(days_all[0], time(0)), datetime.combine(last + timedelta(days=1), time(0)))
    fut = data_manager.futures_1m(days_all[0], last)
    regime = sig.daily_regime(spot)["regime"].to_dict()
    spot_days = sorted(set(spot["ts"].dt.date))
    trade_days = {d for d in spot_days[WARM_SESSIONS:] if first <= d <= last}
    expiries = prov.ensure_expiries(days_all[0], last)

    print("signals", flush=True)
    f = entries.frame(spot, fut)
    s = entries.signals(f)
    ba = bias.analyse(spot, fut)                          # the automated bias engine, for the old-versus-new comparison
    d_ = ba["direction"].to_numpy()
    begin = np.where((d_ != 0) & (d_ != np.r_[0, d_[:-1]]), d_, 0)
    s["bias_engine"] = pd.Series(begin, index=ba.index).reindex(f.index).fillna(0).astype(int)
    sigs = []
    for k in s:
        idx = np.flatnonzero(s[k].to_numpy() != 0)
        for i in idx:
            r = f.iloc[i]
            t = pd.Timestamp(r["close_ts"]).to_pydatetime()
            if r["day"] in trade_days and FIRST_SIGNAL <= t.time() <= LAST_SIGNAL:
                sigs.append({"method": k, "day": r["day"], "ts": t, "direction": int(s[k].iloc[i]), "spot": float(r["close"])})
    print("signals:", len(sigs), {k: int((s[k] != 0).sum()) for k in s}, flush=True)

    with db.engine().connect() as cx:
        cmap = {(r[1], float(r[2]), r[3]): r[0] for r in cx.execute(text("SELECT symbol, expiry, strike, opt_type FROM contracts WHERE dataset='groww'"))}
    by_day = defaultdict(list)
    for x in sigs:
        by_day[x["day"]].append(x)
    trades, skipped, busy = [], defaultdict(lambda: defaultdict(int)), {}
    eng = db.engine()
    days = sorted(by_day)
    for di, d in enumerate(days):
        if di % 50 == 0:
            print(f"pricing {d} ({di + 1}/{len(days)}) trades so far {len(trades)}", flush=True)
        expiry = st.pick_expiry(d, expiries, True, "nearest")
        plan = {}
        for x in by_day[d]:
            if expiry is None:
                skipped[x["method"]]["no expiry"] += 1
                continue
            strike, typ, _ = st.option_for("ATM_BUY", x["direction"], x["spot"])
            try:
                lot, _ = lot_sizes.lot_size_for(expiry, expiries)
            except lot_sizes.LotSizeUnknown:
                skipped[x["method"]]["lot size unknown"] += 1
                continue
            plan[(x["method"], x["ts"])] = {"sym": cmap.get((expiry, float(strike), typ)) or f"NSE-NIFTY-{expiry:%d%b%y}-{int(strike)}-{typ}",
                                           "strike": strike, "typ": typ, "lot": lot}
        syms = sorted({p["sym"] for p in plan.values()})
        if not syms:
            continue
        with eng.connect() as cx:
            df = pd.read_sql(text("SELECT symbol, ts, open, high, low, close FROM candles_1m WHERE symbol = ANY(:s) AND ts >= :a AND ts < :b ORDER BY symbol, ts"),
                             cx, params={"s": syms, "a": datetime.combine(d, time(9, 15)), "b": datetime.combine(d, time(15, 30))})
        df["ts"] = pd.to_datetime(df["ts"])
        cand = {sym: arrays(g.reset_index(drop=True)) for sym, g in df.groupby("symbol")}
        for x in sorted(by_day[d], key=lambda y: y["ts"]):
            p = plan.get((x["method"], x["ts"]))
            if p is None:
                continue
            c = cand.get(p["sym"])
            sm = x["ts"].hour * 60 + x["ts"].minute
            ei = int(np.searchsorted(c["m"], sm)) if c is not None else 0
            if c is None or ei >= len(c["m"]) or c["m"][ei] > sm + ENTRY_WAIT_MIN:
                skipped[x["method"]]["no option candle at entry"] += 1
                continue
            entry = float(c["o"][ei])
            fill = pd.Timestamp(c["ts"][ei]).to_pydatetime()
            for ex in EXITS:
                ck = (x["method"], ex["key"])
                if busy.get(ck) and fill < busy[ck]:
                    skipped[x["method"]]["position still open"] += 1
                    continue
                res = simulate(c, ei, ex)
                if res is None:
                    skipped[x["method"]]["no option candle at exit"] += 1
                    continue
                xi, px, why = res
                xts = pd.Timestamp(c["ts"][xi]).to_pydatetime()
                busy[ck] = xts
                pnl = costs.round_trip("BUY", entry, px, p["lot"], cfg)
                trades.append({"method": x["method"], "exit_rule": ex["key"], "day": d.isoformat(), "signal_ts": x["ts"].isoformat(),
                               "entry_ts": fill.isoformat(), "exit_ts": xts.isoformat(), "direction": x["direction"], "opt_type": p["typ"],
                               "strike": p["strike"], "dte": (expiry - d).days, "lot": p["lot"], "spot": round(x["spot"], 2),
                               "entry": round(entry, 2), "exit": round(px, 2), "reason": why, "gross": pnl["gross"], "friction": pnl["friction"],
                               "net": pnl["net"], "regime": regime.get(d, "unknown")})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades).to_csv(OUT, index=False)
    (OUT.parent / "entry_research_skipped.json").write_text(json.dumps({k: dict(v) for k, v in skipped.items()}, indent=1))
    print("trades", len(trades), "->", OUT, flush=True)


# ---------------------------------------------------------------- report
def stats(g: pd.DataFrame) -> dict:
    if g.empty:
        return {"n": 0}
    net = g["net"].astype(float)
    eq = net.cumsum()
    w, l = net[net > 0], net[net <= 0]
    return {"n": int(len(g)), "win%": round(float((net > 0).mean() * 100), 1), "gross": round(float(g["gross"].sum())),
            "net": round(float(net.sum())), "avg": round(float(net.mean()), 1),
            "pf": round(float(w.sum() / -l.sum()), 2) if l.sum() < 0 else None,
            "avg_win": round(float(w.mean())) if len(w) else 0, "avg_loss": round(float(l.mean())) if len(l) else 0,
            "payoff": round(float(w.mean() / -l.mean()), 2) if len(w) and len(l) and l.mean() < 0 else None,
            "maxdd": round(float((eq.cummax() - eq).max()))}


def load() -> pd.DataFrame:
    t = pd.read_csv(OUT)
    t["day"] = pd.to_datetime(t["day"]).dt.date
    t["entry_ts"] = pd.to_datetime(t["entry_ts"])
    t["year"] = pd.to_datetime(t["day"]).dt.year
    t["split"] = [next(n for n, a, b in SPLITS if a <= d <= b) for d in t["day"]]
    mins = t["entry_ts"].dt.hour * 60 + t["entry_ts"].dt.minute
    t["window"] = [next((n for n, a, b in WINDOWS if a.hour * 60 + a.minute <= m < b.hour * 60 + b.minute), "other") for m in mins]
    return t


def report():
    t = load()
    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 500)
    print(f"{len(t)} trades, {t.day.min()} .. {t.day.max()}\n")
    rows = []
    for (m, e), g in t.groupby(["method", "exit_rule"]):
        r = {"method": m, "exit": e, **{k: v for k, v in stats(g).items() if k in ("n", "win%", "net", "pf")}}
        for sp in ("train", "validation", "oos"):
            s = stats(g[g.split == sp])
            r[sp + "_n"], r[sp + "_net"] = s.get("n", 0), s.get("net", 0)
        rows.append(r)
    tab = pd.DataFrame(rows)
    tab["robust"] = (tab.train_net > 0) & (tab.validation_net > 0) & (tab.oos_net > 0) & (tab[["train_n", "validation_n", "oos_n"]].min(axis=1) >= 30)
    print("== every method x exit rule (net of costs, 1 lot) ==")
    print(tab.sort_values(["method", "exit"]).to_string(index=False))
    print("\nmethod/exit pairs positive in train, validation AND out-of-sample (>=30 trades each):", int(tab.robust.sum()), "of", len(tab))
    print(tab[tab.robust].to_string(index=False))
    print("\nOut-of-sample only, best 10 by net:")
    print(tab.sort_values("oos_net", ascending=False).head(10)[["method", "exit", "oos_n", "oos_net", "train_net", "validation_net"]].to_string(index=False))
    print("\n== by exit rule, all methods pooled ==")
    for e, g in t.groupby("exit_rule"):
        print(e, stats(g), {sp: stats(g[g.split == sp]).get("net") for sp in ("train", "validation", "oos")})
    print("\n== by entry window, all pooled (net of costs) ==")
    for w, g in t.groupby("window"):
        print(w, {k: stats(g)[k] for k in ("n", "win%", "gross", "net", "avg")}, {sp: stats(g[g.split == sp]).get("net") for sp in ("train", "validation", "oos")})
    print("\n== CE versus PE ==")
    for o_, g in t.groupby("opt_type"):
        print(o_, {k: stats(g)[k] for k in ("n", "win%", "gross", "net", "avg")})
    print("\n== by regime ==")
    for o_, g in t.groupby("regime"):
        print(o_, {k: stats(g)[k] for k in ("n", "win%", "gross", "net", "avg")})
    print("\n== by days to expiry ==")
    for o_, g in t.assign(dte=t.dte.clip(upper=4)).groupby("dte"):
        print(o_, {k: stats(g)[k] for k in ("n", "win%", "gross", "net", "avg")})
    print("\n== by year ==")
    for o_, g in t.groupby("year"):
        print(o_, {k: stats(g)[k] for k in ("n", "win%", "gross", "net", "avg")})
    print("\n== by exit reason ==")
    for o_, g in t.groupby("reason"):
        print(o_, {k: stats(g)[k] for k in ("n", "gross", "net")})


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    if mode == "run":
        run(date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else None, date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None)
    else:
        report()

"""Five-year research of the entry methods on REAL NIFTY candles and REAL option premiums (read-only on the database).

    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py run [first_day] [last_day]
    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py report
    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py confluence [first_day] [last_day]   (FVG retest, VWAP rejection, confluence only)
    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py report confluence
    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py compare       (the scored strategy vs the seven existing strategies, 5m and 15m)
    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py optimize      (its stop and minimum score, chosen on the TRAINING period only)
    cd backend; ..\\.venv\\Scripts\\python ..\\scripts\\research_entries.py report scored

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
from app.services.strategy import bias, confluence, entries, strategies
from app.services.strategy import rules as st
from app.services.strategy import signals as sig
from app.services.trading import charges as costs

OUT = ROOT / "data" / "exports" / "entry_research_trades.csv.gz"
OUT_CF = ROOT / "data" / "exports" / "entry_research_confluence_trades.csv.gz"   # the confluence run never touches the earlier result
OUT_SC = ROOT / "data" / "exports" / "entry_research_scored_trades.csv.gz"      # scored strategy vs the seven existing ones
OUT_OPT = ROOT / "data" / "exports" / "entry_research_scored_chosen_trades.csv.gz"
ATR_DELTA = 0.5      # option delta assumed for the ATR stop in research (ATM); Greeks are not stored historically, the live engine uses the real one
GRID_MIN_SCORE, GRID_STOP_ATR = (70.0, 80.0, 90.0), (0.75, 1.0, 1.5)    # the only things tuned, fixed beforehand, chosen on the training period only
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
    stop = ex["stop_abs"] if "stop_abs" in ex else costs._round_tick_down(entry * (1 - ex["stop"] / 100)) if ex.get("stop") else None
    target = ex["target_abs"] if "target_abs" in ex else costs._round_tick_up(entry * (1 + ex["target"] / 100)) if ex.get("target") else None
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


def context(first: date | None, last: date | None) -> dict:
    """Everything pricing needs, loaded once: candles, futures, regimes, trading days, expiries, contract symbols."""
    prov = providers.get("groww")
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
    with db.engine().connect() as cx:
        cmap = {(r[1], float(r[2]), r[3]): r[0] for r in cx.execute(text("SELECT symbol, expiry, strike, opt_type FROM contracts WHERE dataset='groww'"))}
    return {"spot": spot, "fut": fut, "regime": regime, "trade_days": trade_days, "expiries": expiries, "cmap": cmap}


def frame_signals(f: pd.DataFrame, s: pd.DataFrame, ctx: dict) -> list[dict]:
    """Signal dicts for every non-zero column of `s` (aligned with frame `f`), inside the research entry window."""
    sigs = []
    for k in s:
        idx = np.flatnonzero(s[k].to_numpy() != 0)
        for i in idx:
            r = f.iloc[i]
            t = pd.Timestamp(r["close_ts"]).to_pydatetime()
            if r["day"] in ctx["trade_days"] and FIRST_SIGNAL <= t.time() <= LAST_SIGNAL:
                sigs.append({"method": k, "day": r["day"], "ts": t, "direction": int(s[k].iloc[i]), "spot": float(r["close"]),
                             "atr": float(r["atr"]) if pd.notna(r["atr"]) else None})
    return sigs


def price(sigs: list[dict], ctx: dict, exits: list[dict]):
    """Simulate every signal under every exit rule on real 1-minute option premiums: slippage and the full charge stack,
    NSE lot size of the contract's expiry, one position at a time per method and exit rule. Returns (trades, skipped)."""
    cfg = costs.DEFAULT_COSTS
    by_day = defaultdict(list)
    for x in sigs:
        by_day[x["day"]].append(x)
    trades, skipped, busy = [], defaultdict(lambda: defaultdict(int)), {}
    eng = db.engine()
    days = sorted(by_day)
    for di, d in enumerate(days):
        if di % 100 == 0:
            print(f"pricing {d} ({di + 1}/{len(days)}) trades so far {len(trades)}", flush=True)
        expiry = st.pick_expiry(d, ctx["expiries"], True, "nearest")
        plan = {}
        for x in by_day[d]:
            if expiry is None:
                skipped[x["method"]]["no expiry"] += 1
                continue
            strike, typ, _ = st.option_for("ATM_BUY", x["direction"], x["spot"])
            try:
                lot, _ = lot_sizes.lot_size_for(expiry, ctx["expiries"])
            except lot_sizes.LotSizeUnknown:
                skipped[x["method"]]["lot size unknown"] += 1
                continue
            plan[(x["method"], x["ts"])] = {"sym": ctx["cmap"].get((expiry, float(strike), typ)) or f"NSE-NIFTY-{expiry:%d%b%y}-{int(strike)}-{typ}",
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
            for ex in exits:
                ck = (x["method"], ex["key"])
                if busy.get(ck) and fill < busy[ck]:
                    skipped[x["method"]]["position still open"] += 1
                    continue
                run_ex = ex
                if ex.get("atr_rr"):           # the scored strategy's own risk: ATR stop with premium validation, 2R target
                    if not x.get("atr"):
                        skipped[x["method"]]["no ATR"] += 1
                        continue
                    stop = costs._round_tick_down(entry - ATR_DELTA * ex["stop_atr"] * x["atr"])
                    pct = 100 * (entry - stop) / entry
                    if stop <= 0 or not ex["min_pct"] <= pct <= ex["max_pct"]:
                        skipped[x["method"]]["stop outside the premium range"] += 1
                        continue
                    run_ex = {**ex, "stop_abs": stop, "target_abs": costs._round_tick_up(entry + ex["rr"] * (entry - stop))}
                res = simulate(c, ei, run_ex)
                if res is None:
                    skipped[x["method"]]["no option candle at exit"] += 1
                    continue
                xi, px, why = res
                xts = pd.Timestamp(c["ts"][xi]).to_pydatetime()
                busy[ck] = xts
                pnl = costs.round_trip("BUY", entry, px, p["lot"], cfg)
                risk = (entry - run_ex["stop_abs"]) * p["lot"] if "stop_abs" in run_ex else None       # ₹ risked on one lot (R)
                trades.append({"method": x["method"], "exit_rule": ex["key"], "day": d.isoformat(), "signal_ts": x["ts"].isoformat(),
                               "entry_ts": fill.isoformat(), "exit_ts": xts.isoformat(), "direction": x["direction"], "opt_type": p["typ"],
                               "strike": p["strike"], "dte": (expiry - d).days, "lot": p["lot"], "spot": round(x["spot"], 2),
                               "entry": round(entry, 2), "exit": round(px, 2), "reason": why, "gross": pnl["gross"], "friction": pnl["friction"],
                               "net": pnl["net"], "regime": ctx["regime"].get(d, "unknown"), "risk": round(risk, 2) if risk else None})
    return trades, skipped


def save(trades: list[dict], skipped, out_file: Path, skip_name: str):
    out_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades).to_csv(out_file, index=False)
    (out_file.parent / skip_name).write_text(json.dumps({k: dict(v) for k, v in skipped.items()}, indent=1))
    print("trades", len(trades), "->", out_file, flush=True)


def run(first: date | None, last: date | None, only_confluence: bool = False):
    ctx = context(first, last)
    spot, fut = ctx["spot"], ctx["fut"]
    print("signals", flush=True)
    if only_confluence:       # FVG retest, VWAP rejection and the confluence strategy (strategy/confluence.py): same fills and exits
        f = confluence.analyse(spot, fut)
        s = confluence.research_signals(f)
        out_file = OUT_CF
    else:
        f = entries.frame(spot, fut)
        s = entries.signals(f)
        ba = bias.analyse(spot, fut)                      # the automated bias engine, for the old-versus-new comparison
        d_ = ba["direction"].to_numpy()
        begin = np.where((d_ != 0) & (d_ != np.r_[0, d_[:-1]]), d_, 0)
        s["bias_engine"] = pd.Series(begin, index=ba.index).reindex(f.index).fillna(0).astype(int)
        out_file = OUT
    sigs = frame_signals(f, s, ctx)
    print("signals:", len(sigs), {k: int((s[k] != 0).sum()) for k in s}, flush=True)
    trades, skipped = price(sigs, ctx, EXITS)
    save(trades, skipped, out_file, "entry_research_confluence_skipped.json" if only_confluence else "entry_research_skipped.json")


# ---------------------------------------------------------------- the scored strategy against the seven existing strategies
TIMEFRAMES = {5: 15, 15: 30}                  # entry timeframe -> the timeframe that confirms its trend
ATR_RR = {"key": "atr_rr2", "atr_rr": True, "stop_atr": 1.0, "rr": 2.0, "hold": 375, "min_pct": 5.0, "max_pct": 50.0}


def strategy_signals(ctx: dict) -> list[dict]:
    """The seven existing strategies' entries (the same `strategies.prepare` / `legs` rules the backtester and the engine use)
    and the scored strategy's, for the 5-minute and the 15-minute entry timeframe separately."""
    spot, fut, sigs = ctx["spot"], ctx["fut"], []
    for tf, higher in TIMEFRAMES.items():
        for key in strategies.STRATEGIES:
            bars = strategies.prepare(spot, fut, tf, key)
            legs, _ = strategies.legs(bars, ctx["trade_days"], FIRST_SIGNAL, LAST_SIGNAL, key)
            atr = dict(zip(pd.to_datetime(bars["start"]), bars["atr"]))
            for L in legs:
                a = atr.get(pd.Timestamp(L.signal_bar_start))
                sigs.append({"method": f"{key}@{tf}m", "day": L.day, "ts": L.entry_ts, "direction": L.direction, "spot": L.signal_close,
                             "atr": float(a) if a is not None and pd.notna(a) else None})
        p = confluence.ScoredParams(primary=tf, higher=higher)
        f = confluence.analyse(spot, fut, p)
        sigs += frame_signals(f, confluence.scored_research_signals(f).rename(columns={"scored": f"scored@{tf}m"}), ctx)
    return sigs


def compare(first: date | None, last: date | None):
    ctx = context(first, last)
    print("signals", flush=True)
    sigs = strategy_signals(ctx)
    print("signals:", len(sigs), dict(pd.Series([x["method"] for x in sigs]).value_counts()), flush=True)
    trades, skipped = price(sigs, ctx, EXITS + [ATR_RR])
    save(trades, skipped, OUT_SC, "entry_research_scored_skipped.json")


def optimize(first: date | None, last: date | None):
    """Choose the scored strategy's stop distance and minimum score on the TRAINING period only (up to 2023), from a grid fixed
    beforehand, then price the chosen setting over every period. Validation and out-of-sample days are never used to choose."""
    ctx = context(first, last)
    train_end = SPLITS[0][2]
    train_days = {d for d in ctx["trade_days"] if d <= train_end}
    rows, chosen = [], {}
    for tf, higher in TIMEFRAMES.items():
        base = confluence.ScoredParams(primary=tf, higher=higher)
        f = confluence.frame(ctx["spot"], ctx["fut"], base)
        for ms in GRID_MIN_SCORE:
            p = confluence.ScoredParams(primary=tf, higher=higher, min_score=ms)
            fs = f.join(confluence.sc_decide(f, p))
            sigs = frame_signals(fs, confluence.scored_research_signals(fs).rename(columns={"scored": f"scored@{tf}m"}), {**ctx, "trade_days": train_days})
            for sa in GRID_STOP_ATR:
                tr, _ = price(sigs, ctx, [{**ATR_RR, "stop_atr": sa}])
                g = pd.DataFrame(tr)
                s_ = stats(g) if len(g) else {"n": 0}
                rows.append({"tf": tf, "min_score": ms, "stop_atr": sa, **{k: s_.get(k) for k in ("n", "net", "avg", "pf", "win%")}})
                print(rows[-1], flush=True)
    grid = pd.DataFrame(rows)
    for tf in TIMEFRAMES:
        ok = grid[(grid.tf == tf) & (grid.n >= 60)].sort_values("avg", ascending=False)
        chosen[tf] = {k: (None if pd.isna(v) else v) for k, v in ok.iloc[0].to_dict().items()} if len(ok) else None
    sigs_all, ex_all = [], []
    for tf, higher in TIMEFRAMES.items():
        c = chosen[tf]
        if not c:
            continue
        p = confluence.ScoredParams(primary=tf, higher=higher, min_score=float(c["min_score"]))
        f = confluence.analyse(ctx["spot"], ctx["fut"], p)
        sigs_all += frame_signals(f, confluence.scored_research_signals(f).rename(columns={"scored": f"scored_chosen@{tf}m"}), ctx)
        ex_all.append({**ATR_RR, "key": f"chosen_{tf}m", "stop_atr": float(c["stop_atr"])})
    tr = []
    for x_ex in ex_all:      # each timeframe's chosen stop applies to that timeframe's signals only
        tf_tag = x_ex["key"].split("_")[1]
        t_, _ = price([x for x in sigs_all if x["method"].endswith(f"@{tf_tag}")], ctx, [x_ex])
        tr += t_
    OUT_SC.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(tr).to_csv(OUT_OPT, index=False)
    (OUT_SC.parent / "entry_research_scored_grid.json").write_text(json.dumps({"grid": rows, "chosen": chosen, "train_end": str(train_end)}, indent=1, default=str))
    print("chosen on the training period only:", chosen, flush=True)
    print("trades", len(tr), "->", OUT_OPT, flush=True)


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


def load(path: Path = OUT) -> pd.DataFrame:
    t = pd.read_csv(path)
    t["day"] = pd.to_datetime(t["day"]).dt.date
    t["entry_ts"] = pd.to_datetime(t["entry_ts"])
    t["year"] = pd.to_datetime(t["day"]).dt.year
    t["split"] = [next(n for n, a, b in SPLITS if a <= d <= b) for d in t["day"]]
    mins = t["entry_ts"].dt.hour * 60 + t["entry_ts"].dt.minute
    t["window"] = [next((n for n, a, b in WINDOWS if a.hour * 60 + a.minute <= m < b.hour * 60 + b.minute), "other") for m in mins]
    return t


def report(path: Path = OUT):
    t = load(path)
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


def _row(g: pd.DataFrame) -> dict:
    s = stats(g.sort_values("entry_ts"))
    return {"n": s.get("n", 0), "win%": s.get("win%"), "net": s.get("net"), "exp": s.get("avg"), "pf": s.get("pf"), "maxdd": s.get("maxdd")}


def report_compare(path: Path = OUT_SC):
    """The scored strategy against the seven existing ones, 5-minute and 15-minute entries separately, on real premiums."""
    t = load(path)
    t["month"] = t["entry_ts"].dt.to_period("M").astype(str)
    t["trend"] = t["regime"].map(lambda r: "sideways" if r == "sideways" else "trending" if r in ("bullish", "bearish") else r)
    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 600)
    print(f"{len(t)} trades, {t.day.min()} .. {t.day.max()}; splits: train <= 2023, validation 2024, out-of-sample 2025 on. 1 lot per trade, all costs.\n")
    rows = []
    for (m, e), g in t.groupby(["method", "exit_rule"]):
        r = {"method": m, "exit": e, **_row(g)}
        for sp in ("train", "validation", "oos"):
            gs = g[g.split == sp]
            r[sp + "_n"], r[sp + "_net"], r[sp + "_exp"] = len(gs), round(float(gs["net"].sum())), round(float(gs["net"].mean()), 1) if len(gs) else None
        r["robust"] = r["train_net"] > 0 and r["validation_net"] > 0 and r["oos_net"] > 0 and min(r["train_n"], r["validation_n"], r["oos_n"]) >= 30
        rows.append(r)
    tab = pd.DataFrame(rows)
    for e in tab["exit"].unique():
        print(f"== exit rule {e}: every strategy, net of costs ==")
        print(tab[tab["exit"] == e].sort_values(["method"]).drop(columns=["exit"]).to_string(index=False))
        print()
    print("pairs positive in train, validation AND out-of-sample (>=30 trades each):", int(tab.robust.sum()), "of", len(tab))
    print(tab[tab.robust].to_string(index=False) if tab.robust.any() else "none\n")
    sc = t[t.method.str.startswith("scored")]
    for m, g in sc[sc.exit_rule == ATR_RR["key"]].groupby("method"):
        print(f"\n=== {m} with its own risk (ATR stop validated against the premium, 2R target) ===")
        print("overall", _row(g))
        print("by split", {sp: _row(g[g.split == sp]) for sp in ("train", "validation", "oos")})
        print("by year (walk-forward, nothing fitted):")
        print(pd.DataFrame({y: _row(gy) for y, gy in g.groupby("year")}).T.to_string())
        print("trending versus sideways:")
        print(pd.DataFrame({k: _row(gk) for k, gk in g.groupby("trend")}).T.to_string())
        print("by regime:")
        print(pd.DataFrame({k: _row(gk) for k, gk in g.groupby("regime")}).T.to_string())
        mo = g.groupby("month")["net"].agg(["count", "sum"]).round(0)
        print("by month: months", len(mo), "| positive", int((mo["sum"] > 0).sum()), "| negative", int((mo["sum"] <= 0).sum()),
              "| best", mo["sum"].idxmax(), float(mo["sum"].max()), "| worst", mo["sum"].idxmin(), float(mo["sum"].min()))
        print(mo.T.to_string())
        print("exit reasons:", {k: {"n": int(len(v)), "net": round(float(v["net"].sum()))} for k, v in g.groupby("reason")})
        if g["risk"].notna().any():
            r_ = (g["net"] / g["risk"]).replace([np.inf, -np.inf], np.nan).dropna()
            print(f"net R multiple per trade: mean {r_.mean():.3f}, median {r_.median():.3f} (R = the ATR stop distance x lot)")
    print("\n=== the seven existing strategies pooled, same exit, by trend and year ===")
    old = t[~t.method.str.startswith("scored") & (t.exit_rule == ATR_RR["key"])]
    for tf in ("5m", "15m"):
        g = old[old.method.str.endswith("@" + tf)]
        print(tf, "all seven:", _row(g))
        print(pd.DataFrame({y: _row(gy) for y, gy in g.groupby("year")}).T.to_string())


def report_optimize():
    """The train-only grid, what it chose, and how the choice and the specified defaults did on every period."""
    gj = json.loads((OUT_SC.parent / "entry_research_scored_grid.json").read_text())
    print("grid (training period only, up to", gj["train_end"], "):")
    print(pd.DataFrame(gj["grid"]).to_string(index=False))
    print("\nchosen on training only:", gj["chosen"])
    t = load(OUT_OPT) if OUT_OPT.exists() else pd.DataFrame()
    d = load(OUT_SC)
    d = d[d.method.str.startswith("scored") & (d.exit_rule == ATR_RR["key"])]
    for tf in TIMEFRAMES:
        print(f"\n--- {tf}-minute entries ---")
        g = d[d.method == f"scored@{tf}m"]
        print("specified defaults (min score 80, stop 1.0 ATR):", {sp: _row(g[g.split == sp]) for sp in ("train", "validation", "oos")})
        if len(t):
            c = t[t.method.str.endswith(f"@{tf}m")]
            print("chosen on training:", {sp: _row(c[c.split == sp]) for sp in ("train", "validation", "oos")})


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "report"
    first = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 and mode in ("run", "confluence", "compare", "optimize") else None
    last = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 and mode in ("run", "confluence", "compare", "optimize") else None
    if mode in ("run", "confluence"):
        run(first, last, only_confluence=mode == "confluence")
    elif mode == "compare":
        compare(first, last)
    elif mode == "optimize":
        optimize(first, last)
    elif mode == "report" and len(sys.argv) > 2 and sys.argv[2] == "scored":
        report_compare()
        print("\n" + "=" * 100 + "\n")
        report_optimize()
    else:
        report(OUT_CF if len(sys.argv) > 2 and sys.argv[2] == "confluence" else OUT)

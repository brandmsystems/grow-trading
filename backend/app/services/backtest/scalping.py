"""5-minute NIFTY options scalping analyzer (13 Nov 2026).

A separate study next to the existing backtester. It changes no existing strategy: the signal
definitions (EMA 9/21, 5/20, 20/50, 9/21 + VWAP / RSI / MACD) come from strategies.prepare, and
prices, lot sizes and charges from the same modules the backtester uses.

How a trade is simulated (no look-ahead, no repainting, no duplicate entries):
* Signals: crossovers of the strategy's fast/slow EMA on COMPLETED 5-minute NIFTY spot bars,
  confirmed by the strategy's filter on that same bar. A bar closing at T is only known at T.
* Entry: the open of the first 1-minute option candle at or after T (within ENTRY_WAIT_MIN),
  i.e. the next tradable option price after the signal. Buy-side slippage is added on top.
* Contract: ATM or ITM 5 (5 strikes in the money), CE for bullish, PE for bearish signals, the
  nearest weekly expiry (rolled on expiry day), with the NSE lot size of that contract.
* Exit, one of:
    - "time": the open of the option candle HOLD_MIN minutes after the entry fill;
    - "sl_target": stop at entry x (1 - stop%) and target at entry x (1 + target%), checked on each
      1-minute option candle from the entry candle on (levels rounded to the 0.05 tick against us);
      the time exit applies if neither is hit.
      If one candle touches both, the stop is assumed first (conservative). A candle opening
      beyond a level fills at that open (gap).
* One position at a time per configuration: a signal while a trade is still open is skipped.
* Costs: slippage (0.5% + 0.5 point per fill), brokerage, STT, exchange, SEBI, stamp duty and GST
  (trading/charges.py). Missing option candles skip the trade with a reason; nothing is filled in.
* Today's unfinished session is never used.

Results are kept per configuration: strategy x contract (ATM / ITM 5) x exit rule. Rupee results
are for 1 lot per trade; the stop/target configurations are also sized by risk % of capital.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.database import db
from app.services.market_data import history as data_manager
from app.services.market_data import providers
from app.services.options import lot_sizes
from app.services.strategy import rules as st
from app.services.strategy import signals as sig
from app.services.strategy import strategies
from app.services.trading import charges as costs
from app.services.backtest.scalping_stats import (   # noqa: F401  (re-exported: scalping.<name> is the public path)
    CAPITAL, MIN_TRADES, _daily_equity, _group, _scaled, _score, evaluate, stats, walk_forward)

log = logging.getLogger("scalping")

VERSION = 1
TF = 5
HOLD_MIN = 5
ENTRY_WAIT_MIN = 2           # the option must trade within 2 minutes of the signal, else no trade
EXIT_WAIT_MIN = 3            # time exit: first candle within 3 minutes of the exit time
STRATEGY_KEYS = ["ema_9_21", "ema_5_20", "ema_9_21_vwap", "ema_9_21_rsi", "ema_9_21_macd", "ema_20_50"]
CONTRACTS = ["ATM_BUY", "ITM5_BUY"]
STOPS = [5.0, 10.0, 15.0]    # % of the entry premium
TARGETS = [5.0, 10.0, 20.0]
RISKS = [0.5, 1.0, 2.0]      # % of capital risked per trade (stop/target exits only)
ENTRY_START, CUTOFF = time(9, 30), time(14, 30)


def exits() -> list[dict]:
    out = [{"key": f"time{HOLD_MIN}", "kind": "time", "label": f"Fixed {HOLD_MIN}-min hold"}]
    for s in STOPS:
        for t in TARGETS:
            out.append({"key": f"sl{s:g}_tp{t:g}", "kind": "sl_target", "stop": s, "target": t,
                        "label": f"SL {s:g}% / TP {t:g}% (max {HOLD_MIN} min)"})
    return out


def config_key(strategy: str, contract: str, exit_key: str) -> str:
    return f"{strategy}|{contract}|{exit_key}"


def settings() -> dict:
    return {"version": VERSION, "timeframe": TF, "hold_min": HOLD_MIN, "entry_window": [ENTRY_START.strftime("%H:%M"), CUTOFF.strftime("%H:%M")],
            "entry_wait_min": ENTRY_WAIT_MIN, "strategies": STRATEGY_KEYS, "contracts": CONTRACTS,
            "stops": STOPS, "targets": TARGETS, "risks": RISKS, "capital": CAPITAL,
            "expiry": "nearest weekly, rolled on expiry day", "costs": costs.DEFAULT_COSTS.to_dict(),
            "min_trades": MIN_TRADES}


# ---------------------------------------------------------------- signals
def find_signals(bars: pd.DataFrame, key: str, trade_days: set[date]) -> list[dict]:
    """Confirmed crossovers on completed bars inside the entry window. One per bar at most."""
    s = strategies.STRATEGIES[key]
    cx = st.find_crosses(bars, "fast", "slow")
    out = []
    for r in cx.itertuples(index=False):
        close_ts = pd.Timestamp(r.close_ts).to_pydatetime()
        if r.day not in trade_days or not (ENTRY_START <= close_ts.time() <= CUTOFF):
            continue
        d = int(r.direction)
        if s.confirm and not bool(r.bull_ok if d > 0 else r.bear_ok):
            continue
        out.append({"day": r.day, "ts": close_ts, "direction": d, "spot": float(r.close)})
    return out


# ---------------------------------------------------------------- one trade
def simulate(c: dict, entry_i: int, ex: dict) -> tuple[int, float, str] | None:
    """Exit (candle index, raw price, reason) for a long option entered at the open of candle entry_i.
    `c` holds numpy arrays: m (minute of day), o, h, l. None if no exit candle exists."""
    m, o, h, l = c["m"], c["o"], c["h"], c["l"]
    entry = o[entry_i]
    end_m = m[entry_i] + HOLD_MIN
    if ex["kind"] == "sl_target":
        stop = costs._round_tick_down(entry * (1 - ex["stop"] / 100))      # levels on the 0.05 tick,
        target = costs._round_tick_up(entry * (1 + ex["target"] / 100))    # rounded against us
        i = entry_i
        while i < len(m) and m[i] < end_m:
            if i > entry_i and o[i] <= stop:
                return i, float(o[i]), "stop_loss"
            if i > entry_i and o[i] >= target:
                return i, float(o[i]), "target"
            if l[i] <= stop:                       # both touched in one candle: stop first
                return i, float(stop), "stop_loss"
            if h[i] >= target:
                return i, float(target), "target"
            i += 1
    j = int(np.searchsorted(m, end_m))
    if j < len(m) and m[j] <= end_m + EXIT_WAIT_MIN:
        return j, float(o[j]), "time_exit"
    return None


def _arrays(df: pd.DataFrame) -> dict:
    ts = df["ts"]
    return {"ts": ts.to_numpy(), "m": (ts.dt.hour * 60 + ts.dt.minute).to_numpy(),
            "o": df["open"].to_numpy(float), "h": df["high"].to_numpy(float), "l": df["low"].to_numpy(float)}


def size_lots(entry: float, stop_pct: float, lot: int, risk_pct: float, cfg: costs.CostConfig) -> int:
    """Whole lots whose loss at the stop (with slippage and charges) fits risk % of capital,
    limited by the capital itself."""
    stop = entry * (1 - stop_pct / 100)
    one = -costs.round_trip("BUY", entry, stop, lot, cfg)["net"]
    if one <= 0:
        return 0
    by_risk = int(CAPITAL * risk_pct / 100 // one)
    by_cash = int(CAPITAL // (costs.buy_fill(entry, cfg) * lot))
    return max(0, min(by_risk, by_cash))


def price_day(d: date, day_signals: list[tuple[str, dict]], candles: dict, plan: dict, ex_list: list[dict],
              busy_until: dict, skipped, trades: dict, cfg: costs.CostConfig, regime: str = "unknown") -> None:
    """Price one day's signals for every contract and exit rule. One position at a time per
    configuration: a signal filled before that configuration's previous exit is skipped."""
    for key, s in sorted(day_signals, key=lambda x: x[1]["ts"]):
        for mode in CONTRACTS:
            p = plan.get((key, mode, s["ts"]))
            if p is None:
                continue
            c = candles.get(p["sym"])
            sm = s["ts"].hour * 60 + s["ts"].minute
            ei = int(np.searchsorted(c["m"], sm)) if c is not None else 0
            if c is None or ei >= len(c["m"]) or c["m"][ei] > sm + ENTRY_WAIT_MIN:
                skipped[f"{key}|{mode}"]["no option candle at entry"] += 1
                continue
            entry = float(c["o"][ei])
            fill_ts = pd.Timestamp(c["ts"][ei]).to_pydatetime()
            for ex in ex_list:
                ck = config_key(key, mode, ex["key"])
                if busy_until.get(ck) and fill_ts < busy_until[ck]:
                    skipped[ck]["position still open"] += 1
                    continue
                res = simulate(c, ei, ex)
                if res is None:
                    skipped[ck]["no option candle at exit"] += 1
                    continue
                xi, px, why = res
                exit_ts = pd.Timestamp(c["ts"][xi]).to_pydatetime()
                busy_until[ck] = exit_ts
                pnl = costs.round_trip("BUY", entry, px, p["lot"], cfg)
                ch = pnl["charges"]
                trades[ck].append({
                    "day": d.isoformat(), "signal_ts": s["ts"].isoformat(), "entry_ts": fill_ts.isoformat(),
                    "exit_ts": exit_ts.isoformat(), "hold_min": round((exit_ts - fill_ts).total_seconds() / 60, 1),
                    "direction": "Bullish" if s["direction"] > 0 else "Bearish", "opt_type": p["typ"],
                    "symbol": p["sym"], "strike": p["strike"], "expiry": p["expiry"].isoformat(),
                    "lot_size": p["lot"], "qty": p["lot"], "spot": round(s["spot"], 2),
                    "entry": round(entry, 2), "exit": round(px, 2), "entry_fill": pnl["entry_fill"],
                    "exit_fill": pnl["exit_fill"], "reason": why, "gross": pnl["gross"],
                    "slippage": pnl["slippage"], "brokerage": ch["brokerage"],
                    "taxes": round(ch["total"] - ch["brokerage"], 2), "charges": ch["total"],
                    "friction": pnl["friction"], "net": pnl["net"], "regime": regime,
                })


# ---------------------------------------------------------------- the run
def run(progress=None, start: date | None = None, end: date | None = None, store: bool = True,
        dataset: str = "groww") -> dict:
    """Simulate every scalping configuration over the stored history and summarise it.

    Signals come from completed 5-minute spot bars (today's unfinished session excluded); each
    strategy x contract x exit rule is simulated on real 1-minute option candles by `simulate`,
    one position at a time. With `store`, the run and its trades are saved for the page."""
    say = progress or (lambda *_: None)
    prov = providers.get(dataset)
    cfg = costs.DEFAULT_COSTS
    today = datetime.now().date()
    days_all = db.candle_days(prov.spot_symbol)
    if not days_all:
        raise LookupError("No NIFTY data stored. Download it on the Data page first.")
    last = end or max(d for d in days_all if d < today)        # never today's unfinished session
    first = max(days_all[0], start) if start else days_all[0]
    load_from = days_all[0] if not start else first - timedelta(days=60)    # indicator warm-up before `start`
    say(0.01, "Loading NIFTY spot candles")
    spot = db.load_candles(prov.spot_symbol, datetime.combine(load_from, time(0)), datetime.combine(last + timedelta(days=1), time(0)))
    say(0.04, "Loading NIFTY futures (VWAP)")
    fut = data_manager.futures_1m(load_from, last)
    regime = sig.daily_regime(spot)["regime"].to_dict()
    expiries = prov.ensure_expiries(first, last)
    with db.engine().connect() as cx:
        contract_map = {(r[1], float(r[2]), r[3]): r[0] for r in cx.execute(text(
            "SELECT symbol, expiry, strike, opt_type FROM contracts WHERE dataset=:d"), {"d": dataset})}
    spot_days = sorted(set(spot["ts"].dt.date))

    # 1. signals of every strategy
    sigs: dict[str, list[dict]] = {}
    for i, key in enumerate(STRATEGY_KEYS):
        say(0.05 + 0.1 * i / len(STRATEGY_KEYS), f"Signals: {strategies.STRATEGIES[key].label}")
        warm = strategies.warmup_sessions(key, TF)
        trade_days = {d for d in spot_days[warm:] if first <= d <= last}
        bars = strategies.prepare(spot, fut if strategies.STRATEGIES[key].confirm == "vwap" else None, TF, key)
        sigs[key] = find_signals(bars, key, trade_days)

    # 2. contracts each signal needs, grouped by day
    need: dict[date, set[str]] = defaultdict(set)
    plan: dict[tuple, dict] = {}
    skipped = defaultdict(lambda: defaultdict(int))
    for key, lst in sigs.items():
        for s in lst:
            expiry = st.pick_expiry(s["day"], expiries, True, "nearest")
            for mode in CONTRACTS:
                if expiry is None:
                    skipped[f"{key}|{mode}"]["no expiry"] += 1
                    continue
                strike, typ, _ = st.option_for(mode, s["direction"], s["spot"])
                try:
                    lot, _src = lot_sizes.lot_size_for(expiry, expiries)
                except lot_sizes.LotSizeUnknown:
                    skipped[f"{key}|{mode}"]["lot size unknown"] += 1
                    continue
                if dataset == "groww":    # stored history only (Data page); nothing is downloaded here
                    sym = contract_map.get((expiry, float(strike), typ)) or f"NSE-NIFTY-{expiry:%d%b%y}-{int(strike)}-{typ}"
                else:                     # synthetic test data is generated on demand
                    sym = prov.option_symbol(expiry, strike, typ)
                    prov.ensure_option_day(sym, s["day"])
                plan[(key, mode, s["ts"])] = {"sym": sym, "strike": strike, "typ": typ, "expiry": expiry, "lot": lot}
                need[s["day"]].add(sym)

    # 3. price every configuration, day by day (each day's option candles loaded once)
    ex_list = exits()
    trades: dict[str, list[dict]] = defaultdict(list)
    busy_until: dict[str, datetime] = {}
    by_day = defaultdict(list)
    for key, lst in sigs.items():
        for s in lst:
            by_day[s["day"]].append((key, s))
    days = sorted(by_day)
    eng = db.engine()
    for di, d in enumerate(days):
        if di % 20 == 0:
            say(0.15 + 0.8 * di / max(1, len(days)), f"Pricing trades: {d:%d %b %Y} ({di + 1}/{len(days)} days)")
        syms = sorted(need.get(d, ()))
        if not syms:
            continue
        with eng.connect() as cx:
            df = pd.read_sql(text("SELECT symbol, ts, open, high, low, close FROM candles_1m WHERE symbol = ANY(:s) "
                                  "AND ts >= :a AND ts < :b ORDER BY symbol, ts"), cx,
                             params={"s": syms, "a": datetime.combine(d, time(9, 15)), "b": datetime.combine(d, time(15, 30))})
        df["ts"] = pd.to_datetime(df["ts"])
        candles = {sym: _arrays(g.reset_index(drop=True)) for sym, g in df.groupby("symbol")}
        price_day(d, by_day[d], candles, plan, ex_list, busy_until, skipped, trades, cfg, regime.get(d, "unknown"))

    say(0.96, "Summarising")
    summary = summarise(trades, skipped, ex_list, cfg)
    summary.update({"settings": settings(), "start_date": first.isoformat(), "end_date": last.isoformat(),
                    "signals": {k: len(v) for k, v in sigs.items()}, "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "existing": existing_comparison()})
    if not store:
        return {"summary": summary, "trades": trades}
    run_id = save(summary, trades, first, last)
    say(1.0, "Done")
    return {"run_id": run_id, "configs": len(summary["configs"])}


# ---------------------------------------------------------------- summaries
def summarise(trades: dict[str, list[dict]], skipped, ex_list: list[dict], cfg: costs.CostConfig) -> dict:
    """Per-configuration statistics (overall, in/out of sample, yearly, by regime, by risk %), the
    consistency verdict, walk-forward selection and the comparison with the existing strategies.
    Win rate is reported but never used to rank or select."""
    ex_by = {e["key"]: e for e in ex_list}
    configs = []
    yearly_net: dict[str, dict[str, float]] = {}
    for key in STRATEGY_KEYS:
        for mode in CONTRACTS:
            for ex in ex_list:
                ck = config_key(key, mode, ex["key"])
                ts = trades.get(ck, [])
                m = stats(ts)
                yearly = _group(ts, "year")
                yearly_net[ck] = {y: v["net"] for y, v in yearly.items()}
                row = {"key": ck, "strategy": key, "strategy_label": strategies.STRATEGIES[key].label,
                       "contract": mode, "contract_label": st.MODE_LABELS[mode], "exit": ex["key"],
                       "exit_label": ex["label"], "exit_kind": ex["kind"], "stop": ex.get("stop"), "target": ex.get("target"),
                       **m, "ce": stats([t for t in ts if t["opt_type"] == "CE"]),
                       "pe": stats([t for t in ts if t["opt_type"] == "PE"]),
                       "yearly": yearly, "monthly": _group(ts, "month"), "regimes": _group(ts, "regime"),
                       "skipped": dict(skipped.get(ck, {})) | dict(skipped.get(f"{key}|{mode}", {})),
                       "equity": _daily_equity(ts)}
                if ex["kind"] == "sl_target":
                    row["risk"] = {}
                    for r in RISKS:
                        sized, zero = [], 0
                        for t in ts:
                            lots = size_lots(t["entry"], ex["stop"], t["lot_size"], r, cfg)
                            if lots < 1:
                                zero += 1
                                continue
                            sized.append(_scaled(t, lots, cfg))
                        rm = stats(sized)
                        row["risk"][f"{r:g}"] = {k: rm[k] for k in ("trades", "net_pnl", "gross_pnl", "win_rate", "profit_factor",
                                                                    "max_drawdown", "max_drawdown_pct", "brokerage", "taxes", "slippage")}
                        row["risk"][f"{r:g}"]["avg_lots"] = round(sum(t["lots"] for t in sized) / len(sized), 2) if sized else 0
                        row["risk"][f"{r:g}"]["too_small"] = zero
                configs.append(row)
    wf = walk_forward(yearly_net, {c["key"]: c for c in configs})
    all_days = sorted({t["day"] for ts in trades.values() for t in ts})
    split = all_days[int(len(all_days) * 0.6)] if all_days else None
    for c in configs:
        ts = trades.get(c["key"], [])
        ins = [t for t in ts if t["day"] < split] if split else []
        oos = [t for t in ts if t["day"] >= split] if split else []
        c["in_sample"] = {k: stats(ins)[k] for k in ("trades", "net_pnl", "profit_factor", "max_drawdown")} if ins else None
        c["out_of_sample"] = {k: stats(oos)[k] for k in ("trades", "net_pnl", "profit_factor", "max_drawdown")} if oos else None
        c["oos_net"] = c["out_of_sample"]["net_pnl"] if oos else None
        c["verdict"] = evaluate(c, c["yearly"], c["oos_net"])
        c["score"] = _score(c)
    # Ranking: in-sample score only (net / max drawdown, enough trades); the out-of-sample period then
    # decides whether the leader is acceptable. Win rate plays no part.
    def is_score(c):
        i = c["in_sample"]
        return i["net_pnl"] / max(i["max_drawdown"], 1000.0) if i else float("-inf")
    eligible = [c for c in configs if c["in_sample"] and c["in_sample"]["trades"] >= MIN_TRADES * 0.6]
    ranked = sorted(eligible, key=is_score, reverse=True)
    for c in configs:
        c["in_sample_score"] = round(is_score(c), 3) if c["in_sample"] else None
    best = next((c for c in ranked if c["in_sample"]["net_pnl"] > 0 and (c["oos_net"] or 0) > 0), None)
    consistent = [c["key"] for c in configs if c["verdict"]["consistent"]]
    return {"configs": configs, "walk_forward": wf, "ranking": [c["key"] for c in ranked],
            "best": best["key"] if best else None, "top_in_sample": ranked[0]["key"] if ranked else None,
            "split_day": split, "consistent": consistent, "exits": ex_list, "selection_rule": SELECTION_RULE}


SELECTION_RULE = ("Configurations are ranked on the first 60% of the trading days (in-sample) by net P&L after all costs "
                  "divided by maximum drawdown, among those with enough trades. Win rate is not used. The best configuration "
                  "is the highest-ranked one that is also net positive on the held-out final 40% (out-of-sample); if none is, "
                  "there is no best configuration. The walk-forward table repeats the choice year by year using earlier years "
                  f"only. 'Consistently profitable' needs all of: net positive, {MIN_TRADES}+ trades, profit factor of at least "
                  "1.1, positive in at least 75% of its years and positive out of sample.")


def existing_comparison() -> list[dict]:
    """The existing strategies' full-history results (Compare page) for the same contracts."""
    from app.services.backtest import research
    try:
        cells = research.results()["cells"]
    except Exception as exc:
        log.warning("existing comparison unavailable: %s", exc)
        return []
    out = []
    for c in cells:
        if not c["summary"]:
            continue
        for mode in CONTRACTS:
            m = c["summary"]["modes"].get(mode)
            if m:
                out.append({"strategy": c["strategy"], "label": c["label"], "timeframe": c["timeframe"], "contract": mode,
                            "trades": m["trades"], "net_pnl": m["net_pnl"], "win_rate": m["win_rate"],
                            "profit_factor": m["profit_factor"], "max_drawdown": m["max_drawdown"],
                            "years_positive": f"{sum(1 for v in m['yearly'].values() if v['net'] > 0)}/{len(m['yearly'])}"})
    return out


# ---------------------------------------------------------------- storage
def save(summary: dict, trades: dict[str, list[dict]], first: date, last: date) -> int:
    with db.engine().begin() as c:
        rid = c.execute(text("INSERT INTO scalp_runs (settings, start_date, end_date, summary) VALUES "
                             "(CAST(:s AS JSONB), :a, :b, CAST(:m AS JSONB)) RETURNING id"),
                        {"s": json.dumps(settings()), "a": first, "b": last, "m": json.dumps(summary, default=str)}).scalar_one()
        for k, ts in trades.items():
            c.execute(text("INSERT INTO scalp_trades (run_id, config, trades) VALUES (:r, :k, CAST(:t AS JSONB))"),
                      {"r": rid, "k": k, "t": json.dumps(ts, default=str)})
    return rid


def latest() -> dict | None:
    with db.engine().connect() as c:
        r = c.execute(text("SELECT id, start_date, end_date, summary, created_at FROM scalp_runs ORDER BY id DESC LIMIT 1")).mappings().first()
    if not r:
        return None
    return {"run_id": r["id"], "start_date": r["start_date"].isoformat(), "end_date": r["end_date"].isoformat(),
            "created_at": r["created_at"].isoformat(), **r["summary"]}


def config_trades(run_id: int, key: str) -> list[dict]:
    with db.engine().connect() as c:
        r = c.execute(text("SELECT trades FROM scalp_trades WHERE run_id=:r AND config=:k"), {"r": run_id, "k": key}).first()
    return r[0] if r else []


# ---------------------------------------------------------------- paper trading a tested configuration
TIME_EXIT_PROTECTIVE_STOP = 30.0    # % of premium: the paper risk rules need a stop even for "time" exits


def parse_key(key: str) -> tuple[str, str, dict]:
    """(strategy, contract, exit rule) of a configuration key; ValueError if it is not one we test."""
    try:
        strategy, contract, exit_key = key.split("|")
    except ValueError:
        raise ValueError("Unknown scalping configuration") from None
    ex = next((e for e in exits() if e["key"] == exit_key), None)
    if strategy not in STRATEGY_KEYS or contract not in CONTRACTS or ex is None:
        raise ValueError("Unknown scalping configuration")
    return strategy, contract, ex


def engine_config(key: str, trade_mode: str = "paper", overrides: dict | None = None) -> dict:
    """Engine settings that trade `key` the way the analyzer tested it. Paper or replay only:
    real-money scalping is never started from here. `overrides` may change the paper risk
    settings (risk %, daily limits, lot cap), never the strategy, contract or exit rule."""
    if trade_mode not in ("paper", "replay"):
        raise ValueError("Scalping runs in paper or replay mode only; real-money scalping is not enabled.")
    strategy, contract, ex = parse_key(key)
    cfg = {"trade_mode": trade_mode, "signal_mode": "scalp", "scalp_config": key, "strategy": strategy,
           "exec_mode": contract, "timeframe": TF, "hold_min": HOLD_MIN,
           "entry_start": ENTRY_START.strftime("%H:%M"), "cutoff": CUTOFF.strftime("%H:%M"),
           "stop_mode": "pct", "scalp_exit": ex["kind"],
           "stop_pct": ex["stop"] if ex["kind"] == "sl_target" else TIME_EXIT_PROTECTIVE_STOP,
           "target_pct": ex["target"] if ex["kind"] == "sl_target" else 10.0}
    allowed = ("risk_pct", "daily_risk_pct", "max_lots", "max_daily_loss", "max_trades_per_day", "min_balance")
    for k, v in (overrides or {}).items():
        if k in allowed and v not in (None, ""):
            cfg[k] = v
    return cfg


def paper_trades(key: str | None = None, mode: str | None = None, limit: int = 500,
                 include_synthetic: bool = False) -> list[dict]:
    """Engine trades opened in scalp mode (newest first), optionally for one configuration.
    Synthetic (test-data) trades are left out unless asked for."""
    q = "SELECT * FROM live_trades WHERE signal_mode='scalp'"
    if not include_synthetic:
        q += " AND trading_symbol NOT LIKE 'SYNTH:%'"
    p: dict = {"n": limit}
    if key:
        q += " AND scalp_config=:k"; p["k"] = key
    if mode:
        q += " AND trade_mode=:m"; p["m"] = mode
    q += " ORDER BY id DESC LIMIT :n"
    with db.engine().connect() as c:
        rows = [dict(r) for r in c.execute(text(q), p).mappings()]
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, (datetime, date)):
                r[k] = v.isoformat()
    return rows

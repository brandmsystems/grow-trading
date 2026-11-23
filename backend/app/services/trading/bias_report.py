"""Reports for the automated bias engine: stored predictions, accuracy per indicator and timeframe, trade
summary and the full reasoning behind one trade. Paper and replay rows only (live trades are never served,
see services/privacy.py). No Flask imports."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import text

from app.database import db
from app.services import privacy
from app.services.strategy import bias


def _iso(v):
    return v.isoformat() if isinstance(v, (datetime, date)) else v


def _mode(mode: str | None) -> str:
    return mode if mode in ("paper", "replay") else "paper"


def predictions(day: str | None, mode: str | None = "paper", limit: int = 120, session: int | None = None) -> list[dict]:
    """Stored candle analyses with the prediction and, once known, the actual next-candle result (newest first)."""
    m = _mode(mode)
    where, args = ["trade_mode=:m"], {"m": m, "n": max(1, min(int(limit), 1000))}
    if day:
        where.append("day=:d")
        args["d"] = date.fromisoformat(day)
    if m == "replay" and session:
        where.append("scope=:s")
        args["s"] = int(session)
    with db.engine().connect() as c:
        rows = c.execute(text(
            "SELECT day, bar_close, nifty_close, bias, confidence, score_5m, score_15m, signal, predicted, next_close, "
            f"actual, outcome FROM candle_bias WHERE {' AND '.join(where)} ORDER BY bar_close DESC LIMIT :n"), args).mappings().all()
    return [{k: _iso(v) for k, v in r.items()} for r in rows]


def accuracy(mode: str | None = "paper", day_from: str | None = None, day_to: str | None = None) -> dict:
    """Next-candle hit rate of the combined prediction and of each indicator on the 5m and 15m vote, from the stored
    predictions whose next candle has closed. NEUTRAL (no call, or a flat candle) is counted but is not an error."""
    m = _mode(mode)
    where, args = ["trade_mode=:m", "actual IS NOT NULL"], {"m": m}
    if day_from:
        where.append("day>=:a")
        args["a"] = date.fromisoformat(day_from)
    if day_to:
        where.append("day<=:b")
        args["b"] = date.fromisoformat(day_to)
    with db.engine().connect() as c:
        rows = c.execute(text(f"SELECT predicted, actual, votes FROM candle_bias WHERE {' AND '.join(where)}"), args).mappings().all()
        last = c.execute(text("SELECT analysis->>'tf_primary' AS a, analysis->>'tf_confirm' AS b FROM candle_bias "
                              "WHERE trade_mode=:m AND analysis ? 'tf_primary' ORDER BY bar_close DESC LIMIT 1"), {"m": m}).first()
    tfs = (int(last[0]), int(last[1])) if last else (5, 15)
    return {"candles": len(rows), "rows": _tally(rows, tfs), "timeframes": list(tfs)}


def _tally(rows, tfs: tuple[int, int] = (5, 15)) -> list[dict]:
    """Rows of {predicted, actual, votes: {"5m": {...}, "15m": {...}}} (the vote groups are the analysis and confirmation
    timeframe slots, stored under the names "5m"/"15m"); the output labels use the real timeframes `tfs`."""
    keys = list(bias.INDICATORS)
    lab = {"5m": f"{tfs[0]}m", "15m": f"{tfs[1]}m"}
    tally = {("combined", f"{lab['5m']}+{lab['15m']}"): [0, 0, 0]}
    tally.update({(k, lab[tf]): [0, 0, 0] for k in keys for tf in ("5m", "15m")})

    def add(key, call, actual):
        t = tally[key]
        if call in ("UP", "DOWN") and actual in ("UP", "DOWN"):
            t[0 if call == actual else 1] += 1
        else:
            t[2] += 1
    for r in rows:
        add(("combined", f"{lab['5m']}+{lab['15m']}"), r["predicted"], r["actual"])
        for tf in ("5m", "15m"):
            for k in keys:
                v = ((r["votes"] or {}).get(tf) or {}).get(k)
                call = "NEUTRAL" if v is None or abs(v) < bias.VOTE_MIN else "UP" if v > 0 else "DOWN"
                add((k, lab[tf]), call, r["actual"])
    out = []
    for (k, tf), (ok, bad, neu) in tally.items():
        n = ok + bad
        out.append({"key": k, "label": "Combined bias" if k == "combined" else bias.INDICATORS[k][0], "timeframe": tf,
                    "correct": ok, "incorrect": bad, "neutral": neu, "n": n,
                    "accuracy": round(100 * ok / n, 1) if n else None})
    return out


def history_accuracy(start: date, end: date, primary: int = 5, higher: int = 15) -> dict:
    """The same accuracy table recomputed over stored candles (the analysis is causal, so this is what the engine
    would have predicted). Used to judge the indicators before trusting them; makes no market calls."""
    from app.services.market_data.providers import GrowwProvider
    sym = GrowwProvider.spot_symbol
    warm = start - timedelta(days=45)
    spot = db.load_candles(sym, datetime.combine(warm, time(0)), datetime.combine(end + timedelta(days=1), time(0)))
    if spot.empty:
        return {"candles": 0, "rows": [], "note": "No stored NIFTY candles for that period."}
    from app.services.market_data import history as data_manager
    try:
        fut = data_manager.futures_1m(warm, end + timedelta(days=1))
    except Exception:
        fut = None
    p = bias.BiasParams(primary=primary, higher=higher)
    f = bias.analyse(spot, fut if fut is not None and not fut.empty else None, p)
    f = f[(f["day"] >= start) & (f["day"] <= end)]
    f = bias.evaluate_predictions(f, p)
    rows = [{"predicted": r.predicted, "actual": r.actual,
             "votes": {"5m": {k: getattr(r, f"v5_{k}") for k in bias.INDICATORS},
                       "15m": {k: getattr(r, f"v15_{k}") for k in bias.INDICATORS}}}
            for r in f.dropna(subset=["actual"]).itertuples()]
    for r in rows:      # NaN votes cannot call a direction
        for tf in r["votes"]:
            r["votes"][tf] = {k: (None if pd.isna(v) else float(v)) for k, v in r["votes"][tf].items()}
    return {"candles": len(rows), "rows": _tally(rows, (primary, higher)), "timeframes": [primary, higher],
            "from": start.isoformat(), "to": end.isoformat()}


def _trade_rows(mode: str, day: str | None, limit: int = 300, session: int | None = None) -> list[dict]:
    where, args = ["trade_mode=:m", "signal_mode='bias'"], {"m": mode, "n": limit}
    if day:
        where.append("day=:d")
        args["d"] = date.fromisoformat(day)
    if mode == "replay" and session:
        where.append("session_id=:s")
        args["s"] = int(session)
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(text(
            f"SELECT * FROM live_trades WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT :n"), args).mappings()]


def trades(mode: str | None, day: str | None, limit: int = 300, session: int | None = None) -> list[dict]:
    m = _mode(mode)
    out = []
    for r in _trade_rows(m, day, max(1, min(int(limit), 1000)), session):
        r = privacy.public_trade(r)
        for k, v in list(r.items()):
            r[k] = _iso(v)
        a = r.get("analysis") or {}
        r["supporting"] = a.get("supports") or []
        r["strategy"] = strategy_of(r)
        r.pop("analysis", None)       # the list stays small; the full reasoning is one click away (trade_detail)
        out.append(r)
    return out


def strategy_of(r: dict) -> str:
    """Which entry strategy opened a trade: the one recorded in its analysis, `bias` for trades that predate the choice."""
    return (r.get("analysis") or {}).get("strategy") or "bias"


def strategy_stats(items: list[dict]) -> dict:
    """Per-strategy performance on closed trades: sample size, win rate, net expectancy per trade, profit factor, maximum drawdown."""
    net = [float(r["net"] or 0) for r in sorted(items, key=lambda r: str(r.get("entry_ts") or r.get("signal_ts") or ""))]
    wins, losses = [x for x in net if x > 0], [x for x in net if x <= 0]
    peak = eq = dd = 0.0
    for x in net:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    n = len(net)
    return {"trades": n, "wins": len(wins), "losses": len(losses), "win_rate": round(100 * len(wins) / n, 1) if n else None,
            "net": round(sum(net), 2), "gross": round(sum(float(r["gross"] or 0) for r in items), 2),
            "expectancy": round(sum(net) / n, 2) if n else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "max_drawdown": round(dd, 2), "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None}


def summary(mode: str | None, day: str | None, session: int | None = None) -> dict:
    """Wins, losses, win rate and net P&L; by instrument, exit reason, confidence band and supporting indicator."""
    m = _mode(mode)
    rows = [r for r in _trade_rows(m, day, 1000, session)]
    closed = [r for r in rows if r["status"] == "CLOSED"]

    def agg(items):
        n = len(items)
        w = sum(1 for r in items if (r["net"] or 0) > 0)
        return {"trades": n, "wins": w, "losses": n - w, "win_rate": round(100 * w / n, 1) if n else None,
                "net": round(sum(r["net"] or 0 for r in items), 2), "gross": round(sum(r["gross"] or 0 for r in items), 2)}
    by_instr, by_exit, by_conf, by_ind = {}, {}, {}, {}
    for r in closed:
        by_instr.setdefault(r.get("action") or f"{r['side']} {r['opt_type']}", []).append(r)
        by_exit.setdefault(r.get("exit_reason") or "—", []).append(r)
        cf = r.get("confidence")
        band = "unknown" if cf is None else "55-70%" if cf < 70 else "70-85%" if cf < 85 else "85-100%"
        by_conf.setdefault(band, []).append(r)
        for s in (r.get("analysis") or {}).get("supports") or []:
            by_ind.setdefault(s.rsplit(" (", 1)[0], []).append(r)
    by_strategy: dict[str, list] = {}
    for r in closed:
        by_strategy.setdefault(strategy_of(r), []).append(r)
    open_n = sum(1 for r in rows if r["status"] == "OPEN")
    return {**agg(closed), "open": open_n, "mode": m,
            "target_hits": len(by_exit.get("profit_target", [])),
            "by_instrument": {k: agg(v) for k, v in by_instr.items()},
            "by_exit": {k: agg(v) for k, v in by_exit.items()},
            "by_confidence": {k: agg(v) for k, v in sorted(by_conf.items())},
            "by_indicator": {k: agg(v) for k, v in sorted(by_ind.items())},
            "by_strategy": {k: strategy_stats(v) for k, v in sorted(by_strategy.items())},
            "note": "An indicator is credited with every trade it supported at entry (several indicators share each trade), "
                    "so these rows are descriptive, not independent evidence."}


def trade_detail(tid: int) -> dict | None:
    """Everything behind one paper trade: the analysis at entry, contract checks, risk calculation, stop changes, exit."""
    with db.engine().connect() as c:
        r = c.execute(text("SELECT * FROM live_trades WHERE id=:i AND trade_mode IN ('paper','replay')"), {"i": tid}).mappings().first()
        if not r:
            return None
        stops = [dict(x) for x in c.execute(text(
            "SELECT ts, old_stop, new_stop, old_max_loss, new_max_loss, source, note FROM paper_stop_changes "
            "WHERE trade_id=:i ORDER BY id"), {"i": tid}).mappings()]
    row = privacy.public_trade(dict(r))
    row = {k: _iso(v) for k, v in row.items()}
    for s in stops:
        s["ts"] = _iso(s["ts"])
    return {"trade": row, "stop_changes": stops}

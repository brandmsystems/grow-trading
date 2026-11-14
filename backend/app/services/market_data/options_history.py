"""Historical NIFTY option candles: plan, resumable download and coverage.

Scope: for every completed session with stored spot data, the CE and PE contracts
within STRIKE_RANGE strikes of that day's at-the-money strike (using the day's spot
low and high), for every expiry a backtest could pick that day (nearest, next and
nearest monthly; with and without rolling on expiry day).

Only candles Groww returns are stored. A contract Groww has no candles for is recorded
in fetch_log with 0 rows and reported as such; nothing is estimated or filled in.
Downloads are resumable: every (contract, day) already requested is skipped.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import text

from app.database import db
from app.services.market_data import history as data_manager
from app.services.market_data import providers
from app.services.strategy import rules as st

log = logging.getLogger("options_history")

RUN_SYMBOL = "NIFTY-OPTIONS"     # data_downloads.symbol for option download runs
STRIKE_RANGE = 10                # strikes either side of ATM
WINDOW_DAYS = 29                 # one Groww request covers up to 30 days of 1-minute candles


def _now() -> datetime:
    return datetime.now()


def spot_ranges(start: date, end: date) -> dict[date, tuple[float, float]]:
    """Each stored session's spot (low, high)."""
    with db.engine().connect() as c:
        rows = c.execute(text(
            "SELECT ts::date, min(low), max(high) FROM candles_1m WHERE symbol=:s AND ts >= :a AND ts < :b "
            "GROUP BY 1 ORDER BY 1"),
            {"s": data_manager.SYMBOL, "a": start, "b": end + timedelta(days=1)}).fetchall()
    return {r[0]: (float(r[1]), float(r[2])) for r in rows}


def expiries_for(day: date, expiries: list[date]) -> set[date]:
    out = set()
    for rule in st.EXPIRY_RULES:
        for roll in (True, False):
            e = st.pick_expiry(day, expiries, roll, rule)
            if e:
                out.add(e)
    return out


def strikes_for(low: float, high: float, n: int = STRIKE_RANGE, step: int = st.STRIKE_STEP) -> list[float]:
    lo, hi = st.atm_strike(low, step) - n * step, st.atm_strike(high, step) + n * step
    return [float(k) for k in range(int(lo), int(hi) + step, step)]


def plan(start: date, end: date, expiries: list[date], ranges: dict[date, tuple[float, float]],
         n: int = STRIKE_RANGE) -> dict[tuple[date, float, str], list[date]]:
    """(expiry, strike, CE/PE) -> sorted days it is needed."""
    need: dict[tuple[date, float, str], set[date]] = defaultdict(set)
    for day, (low, high) in ranges.items():
        if not (start <= day <= end):
            continue
        for e in expiries_for(day, expiries):
            for k in strikes_for(low, high, n):
                for typ in ("CE", "PE"):
                    need[(e, k, typ)].add(day)
    return {key: sorted(days) for key, days in need.items()}


def windows(days: list[date], expiry: date) -> list[date]:
    """Request start days so that every needed day falls inside one request window."""
    starts: list[date] = []
    for d in days:
        if not starts or d > min(starts[-1] + timedelta(days=WINDOW_DAYS), expiry):
            starts.append(d)
    return starts


def _fetched(symbols: list[str]) -> set[tuple[str, date]]:
    if not symbols:
        return set()
    with db.engine().connect() as c:
        rows = c.execute(text("SELECT symbol, day FROM fetch_log WHERE symbol = ANY(:s)"), {"s": symbols}).fetchall()
    return {(r[0], r[1]) for r in rows}


def todo(start: date, end: date, n: int = STRIKE_RANGE, prov=None) -> tuple[list[tuple[str, date]], int]:
    """Requests still needed as (contract symbol, first day), and the number of contracts in scope."""
    prov = prov or providers.GrowwProvider()
    today = _now().date()
    end = min(end, today - timedelta(days=1))          # completed sessions only
    expiries = prov.ensure_expiries(start, end)
    need = plan(start, end, expiries, spot_ranges(start, end), n)
    by_expiry: dict[date, list[tuple[float, str, list[date]]]] = defaultdict(list)
    for (e, k, typ), days in need.items():
        by_expiry[e].append((k, typ, days))
    jobs: list[tuple[str, date]] = []
    for e in sorted(by_expiry):
        rows = [(prov.option_symbol(e, k, typ), days) for k, typ, days in by_expiry[e]]
        done = _fetched([s for s, _ in rows])
        for sym, days in rows:   # only days never requested; stored days are reused
            jobs += [(sym, w) for w in windows([d for d in days if (sym, d) not in done], e)]
    return jobs, len(need)


def download(start: date, end: date, progress=None, n: int = STRIKE_RANGE, prov=None, workers: int = 3) -> dict:
    """Fetch every planned contract window not yet requested. Safe to stop and re-run."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    say = progress or (lambda *_: None)
    prov = prov or providers.GrowwProvider()
    data_manager._stop.clear()
    say(0.0, "Planning option contracts")
    jobs, contracts = todo(start, end, n, prov)
    with db.engine().begin() as c:
        run_id = c.execute(text("INSERT INTO data_downloads (symbol, start_date, end_date, chunks_total) "
                                "VALUES (:s,:a,:b,:n) RETURNING id"),
                           {"s": RUN_SYMBOL, "a": start, "b": end, "n": len(jobs)}).scalar_one()
    done = failed = 0
    errors: list[str] = []
    status = "done"
    pending = iter(jobs)
    try:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="optdl") as ex:
            running = {}
            while True:
                while len(running) < workers * 2 and not data_manager._stop.is_set():
                    job = next(pending, None)
                    if job is None:
                        break
                    running[ex.submit(prov.ensure_option_day, *job)] = job
                if not running:
                    break
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for f in finished:
                    sym, day = running.pop(f)
                    try:
                        f.result()
                    except Exception as exc:
                        if data_manager._fatal(exc):
                            raise
                        failed += 1
                        errors.append(f"{sym} {day}: {exc}")
                        log.warning("option window %s %s failed: %s", sym, day, exc)
                    done += 1
                    if done % 25 == 0 or done == len(jobs):
                        say(done / max(1, len(jobs)), f"Option contracts {done:,}/{len(jobs):,} ({sym})")
                        data_manager._update(run_id, chunks_done=done, rows_rejected=failed)
            if data_manager._stop.is_set() and done < len(jobs):
                status = "stopped"
    except Exception as exc:
        data_manager._update(run_id, status="failed", chunks_done=done, rows_rejected=failed,
                             error=data_manager._explain(exc), finished_at=_now())
        raise data_manager.DownloadError(data_manager._explain(exc)) from exc
    err = f"{failed} request(s) failed; re-run to retry them. First: {errors[0]}" if failed else None
    data_manager._update(run_id, status=status, chunks_done=done, rows_rejected=failed, error=err, finished_at=_now())
    say(1.0, "Option download " + status)
    return {"id": run_id, "status": status, "contracts_in_scope": contracts, "requests": len(jobs),
            "done": done, "failed": failed}


def coverage(start: date | None = None, end: date | None = None, n: int = STRIKE_RANGE) -> dict:
    """Planned vs downloaded, per month, from stored expiries, contracts and fetch_log. No API calls."""
    d_start, d_end = data_manager.default_target()
    start, end = start or d_start, min(end or d_end, _now().date() - timedelta(days=1))
    expiries = db.load_expiries("groww")
    need = plan(start, end, expiries, spot_ranges(start, end), n)
    with db.engine().connect() as c:
        known = {(r[1], float(r[2]), r[3]): r[0] for r in c.execute(text(
            "SELECT symbol, expiry, strike, opt_type FROM contracts WHERE dataset='groww' AND expiry BETWEEN :a AND :b"),
            {"a": start, "b": end + timedelta(days=60)})}
        log_rows = c.execute(text(
            "SELECT symbol, day, rows FROM fetch_log WHERE symbol LIKE 'NSE-NIFTY-%' AND symbol NOT LIKE '%-FUT' "
            "AND day BETWEEN :a AND :b"), {"a": start, "b": end}).fetchall()
        last_run = c.execute(text("SELECT * FROM data_downloads WHERE symbol=:s ORDER BY id DESC LIMIT 1"),
                             {"s": RUN_SYMBOL}).mappings().first()
        last_ok = c.execute(text("SELECT max(finished_at) FROM data_downloads WHERE symbol=:s AND status='done'"),
                            {"s": RUN_SYMBOL}).scalar()
    fetched: dict[str, dict[date, int]] = defaultdict(dict)
    for sym, day, rows in log_rows:
        fetched[sym][day] = rows
    months: dict[str, dict] = {}
    totals = defaultdict(int)
    for (e, k, typ), days in need.items():
        sym = known.get((e, k, typ)) or f"NSE-NIFTY-{e:%d%b%y}-{int(k)}-{typ}"
        got = fetched.get(sym, {})
        m = months.setdefault(f"{days[0]:%Y-%m}", defaultdict(int))
        m["contracts"] += 1
        m["contract_days"] += len(days)
        have = [d for d in days if d in got]
        m["downloaded_days"] += len(have)
        m["empty_days"] += sum(1 for d in have if got[d] == 0)
        m["candles"] += sum(got[d] for d in have)
        if have and len(have) == len(days):
            m["complete_contracts"] += 1
    for m in months.values():
        for k, v in m.items():
            totals[k] += v
    rows = [{"month": k, **v, "pct": round(100 * v["downloaded_days"] / max(1, v["contract_days"]), 1)}
            for k, v in sorted(months.items())]
    serial = lambda r: {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in dict(r).items()} if r else None
    return {
        "scope": {"from": start.isoformat(), "to": end.isoformat(), "strikes_each_side": n,
                  "expiry_rules": list(st.EXPIRY_RULES), "types": ["CE", "PE"]},
        "summary": {**totals, "pct": round(100 * totals["downloaded_days"] / max(1, totals["contract_days"]), 1),
                    "expiries": len({e for e, _, _ in need})},
        "months": rows,
        "last_run": serial(last_run),
        "last_success": last_ok.isoformat() if last_ok else None,
    }

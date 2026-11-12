"""Data providers: real Groww data, and a synthetic dataset used only by automated tests.

Both write into the same Postgres tables but under different symbol namespaces,
so synthetic data can never be mistaken for (or mixed with) real market data.
The web app refuses the synthetic dataset.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import time as _time
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.database import db

log = logging.getLogger("providers")
IST = ZoneInfo("Asia/Kolkata")


def _first_list(resp) -> list:
    """Groww responses wrap lists in a dict; find the list regardless of key name."""
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("candles", "expiries", "contracts", "data"):
            if isinstance(resp.get(k), list):
                return resp[k]
        for v in resp.values():
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = _first_list(v)
                if inner:
                    return inner
    return []


def parse_candles(resp, dedupe: bool = True) -> pd.DataFrame:
    """Normalise Groww candle rows [ts, o, h, l, c, v, (oi)] to an IST-naive DataFrame."""
    rows = _first_list(resp)
    out = []
    for r in rows:
        if isinstance(r, dict):
            ts = r.get("timestamp") or r.get("ts") or r.get("time")
            vals = [r.get(k) for k in ("open", "high", "low", "close", "volume", "open_interest")]
        else:
            ts, vals = r[0], list(r[1:7]) + [None] * (6 - len(r[1:7]))
        if ts is None or vals[0] is None:
            continue
        if isinstance(ts, (int, float)):
            secs = ts / 1000 if ts > 1e11 else ts
            dt = datetime.fromtimestamp(secs, IST).replace(tzinfo=None)
        else:
            dt = pd.Timestamp(ts)
            if dt.tzinfo is not None:
                dt = dt.tz_convert(IST).tz_localize(None)
            dt = dt.to_pydatetime()
        out.append((dt, *[float(v) if v is not None else 0.0 for v in vals]))
    df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
        if dedupe:
            df = df.drop_duplicates("ts")
        df = df.sort_values("ts").reset_index(drop=True)
    return df


OPT_RE = re.compile(r"-(\d+(?:\.\d+)?)-(CE|PE)$", re.I)
EXPIRY_RE = re.compile(r"-(\d{2}[A-Za-z]{3}\d{2})-")


class Provider:
    dataset = "base"
    label = "base"
    spot_symbol = ""

    def ensure_spot(self, start: date, end: date, progress=None) -> dict:
        raise NotImplementedError

    def ensure_expiries(self, start: date, end: date) -> list[date]:
        raise NotImplementedError

    def option_symbol(self, expiry: date, strike: float, typ: str) -> str | None:
        raise NotImplementedError

    def ensure_option_day(self, symbol: str, day: date) -> None:
        raise NotImplementedError


# ====================================================================== Groww
class GrowwProvider(Provider):
    dataset = "groww"
    label = "Groww (real market data)"
    spot_symbol = "NSE-NIFTY"
    EXCHANGE = "NSE"
    REQ_GAP = 0.12          # seconds between API calls (stay well under rate limits)

    def __init__(self):
        from app.services.groww import client as groww_client
        self._gc = groww_client
        self._last = 0.0

    def _call(self, fn, **kw):
        from app.services.market_data import history as data_manager
        for attempt in range(1, 4):
            wait = self.REQ_GAP - (_time.monotonic() - self._last)
            if wait > 0:
                _time.sleep(wait)
            try:
                return self._gc.call(fn, timeout=20, **kw)
            except Exception as exc:
                # Permission and bad-request errors won't change on retry.
                if data_manager._fatal(exc) or "400" in str(exc) or attempt == 3:
                    raise
                log.warning("%s failed (attempt %d): %s", fn, attempt, exc)
                _time.sleep(2 ** attempt)
            finally:
                self._last = _time.monotonic()

    def _candles(self, segment: str, symbol: str, a: datetime, b: datetime, dedupe: bool = True) -> pd.DataFrame:
        resp = self._call("get_historical_candles", exchange=self.EXCHANGE, segment=segment,
                          groww_symbol=symbol, start_time=a.strftime("%Y-%m-%d %H:%M:%S"),
                          end_time=b.strftime("%Y-%m-%d %H:%M:%S"), candle_interval="1minute")
        return parse_candles(resp, dedupe=dedupe)

    def ensure_spot(self, start: date, end: date, progress=None) -> dict:
        from app.services.market_data import history as data_manager
        return data_manager.download(start, end, fetch=lambda seg, sym, a, b: self._candles(seg, sym, a, b, dedupe=False),
                                     progress=progress, symbol=self.spot_symbol)

    def ensure_expiries(self, start: date, end: date) -> list[date]:
        have = set(db.load_expiries(self.dataset))
        months = set()
        d = date(start.year, start.month, 1)
        last = min(end + timedelta(days=45), date(date.today().year, 12, 31))   # Groww rejects future years
        while d <= last:
            months.add((d.year, d.month))
            d = (d + timedelta(days=32)).replace(day=1)
        covered = {(e.year, e.month) for e in have}
        for y, m in sorted(months - covered):
            resp = self._call("get_expiries", exchange=self.EXCHANGE, underlying_symbol="NIFTY",
                              year=y, month=m)
            exps = [pd.Timestamp(x).date() for x in _first_list(resp)]
            db.save_expiries(self.dataset, exps)
        return db.load_expiries(self.dataset)

    def option_symbol(self, expiry: date, strike: float, typ: str) -> str | None:
        if not db.has_contracts(self.dataset, expiry):
            resp = self._call("get_contracts", exchange=self.EXCHANGE, underlying_symbol="NIFTY",
                              expiry_date=expiry.isoformat())
            rows = []
            for sym in _first_list(resp):
                s = sym if isinstance(sym, str) else (sym.get("groww_symbol") or sym.get("trading_symbol") or "")
                m = OPT_RE.search(s)
                if m:
                    rows.append((s, expiry, float(m.group(1)), m.group(2).upper()))
            db.save_contracts(self.dataset, rows)
        # Groww's list for an expired expiry can miss strikes that did trade; their candles
        # are still served under the standard name. If none exist, the trade is skipped.
        return (db.find_contract(self.dataset, expiry, strike, typ)
                or f"NSE-NIFTY-{expiry:%d%b%y}-{int(strike)}-{typ}")

    def ensure_option_day(self, symbol: str, day: date) -> None:
        """Fetch the contract from `day` to its expiry (up to 30 days) in one request.

        A weekly contract is usually needed on several days, so this is one call per
        contract instead of one per day. Only regular-session candles are stored.
        """
        if db.fetched(symbol, day):
            return
        m = EXPIRY_RE.search(symbol)
        expiry = datetime.strptime(m.group(1), "%d%b%y").date() if m else day
        today = date.today()
        last = min(max(expiry, day), day + timedelta(days=29), today)
        df = self._candles("FNO", symbol, datetime.combine(day, time(9, 15)), datetime.combine(last, time(15, 30)))
        if not df.empty:
            df = df[df["ts"].dt.time.between(time(9, 15), time(15, 29)) & (df["ts"] + pd.Timedelta(minutes=1) <= datetime.now())]
        db.upsert_candles(symbol, df)
        counts = df.groupby(df["ts"].dt.date).size().to_dict() if not df.empty else {}
        d = day
        while d <= last:
            if (d.weekday() < 5 or d in counts) and d < today:   # weekend special sessions too
                db.mark_fetched(symbol, d, int(counts.get(d, 0)))
            d += timedelta(days=1)


# ====================================================================== Synthetic
def _bs_price(spot: float, strike: float, t_years: float, vol: float, typ: str, r: float = 0.065) -> float:
    if t_years <= 0:
        return max(0.0, spot - strike) if typ == "CE" else max(0.0, strike - spot)
    sq = vol * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * t_years) / sq
    d2 = d1 - sq
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    if typ == "CE":
        return spot * n(d1) - strike * math.exp(-r * t_years) * n(d2)
    return strike * math.exp(-r * t_years) * n(-d2) - spot * n(-d1)


def _now() -> datetime:
    return datetime.now()


class SyntheticProvider(Provider):
    """Deterministic fake NIFTY data for UI demos and tests. NOT market data."""
    dataset = "synthetic"
    label = "Synthetic demo data (not real)"
    spot_symbol = "SYNTH:NIFTY"

    def _rng(self, *parts) -> np.random.Generator:
        seed = int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)
        return np.random.default_rng(seed)

    def _spot_day(self, day: date, prev_close: float) -> pd.DataFrame:
        rng = self._rng("spot", day)
        n = 375
        # ~0.9% daily stdev, intraday trend regimes so crossovers both work and whipsaw
        drift = rng.normal(0, 0.00001)
        regime = np.repeat(rng.normal(0, 0.00004, 8), math.ceil(n / 8))[:n]
        rets = rng.normal(drift + regime, 0.00035, n)
        gap = rng.normal(0, 0.002)
        closes = prev_close * (1 + gap) * np.exp(np.cumsum(rets))
        opens = np.concatenate([[prev_close * (1 + gap)], closes[:-1]])
        spread = np.abs(rng.normal(0, 0.0004, n)) * closes
        highs = np.maximum(opens, closes) + spread
        lows = np.minimum(opens, closes) - spread
        ts = pd.date_range(datetime.combine(day, time(9, 15)), periods=n, freq="1min")
        return pd.DataFrame({"ts": ts, "open": opens.round(2), "high": highs.round(2),
                             "low": lows.round(2), "close": closes.round(2),
                             "volume": 0.0, "oi": 0.0})

    ANCHOR = date(2024, 1, 1)
    ANCHOR_LEVEL = 22000.0

    def ensure_spot(self, start: date, end: date, progress=None) -> dict:
        """Generate a deterministic random walk from ANCHOR so any range is reproducible.

        Days before `start - 10d` are generated (to carry the price level) but not stored.
        """
        from sqlalchemy import text
        with db.engine().connect() as c:
            stored = c.execute(text(
                "SELECT DISTINCT ON (ts::date) ts::date AS d, close, ts AS last_ts FROM candles_1m "
                "WHERE symbol=:s ORDER BY ts::date, ts DESC"), {"s": self.spot_symbol}).fetchall()
        # Only finished sessions count; a day stored part-way through is regenerated.
        last_close = {r[0]: r[1] for r in stored if r[2].time() >= time(15, 29)}
        now = _now()
        end = min(end, now.date())
        store_from = start - timedelta(days=10)
        level, d, rows = self.ANCHOR_LEVEL, self.ANCHOR, 0
        total = max(1, (end - self.ANCHOR).days)
        while d <= end:
            if d.weekday() < 5:
                if d in last_close:
                    level = float(last_close[d])
                else:
                    df = self._spot_day(d, level)
                    level = float(df["close"].iloc[-1])
                    if d == now.date():   # never store minutes that haven't happened yet
                        df = df[df["ts"] + pd.Timedelta(minutes=1) <= now]
                    if d >= store_from and not df.empty:
                        db.upsert_candles(self.spot_symbol, df)
                        rows += len(df)
            if progress and d.day == 1:
                progress((d - self.ANCHOR).days / total, f"Generating synthetic {d:%b %Y}")
            d += timedelta(days=1)
        return {"rows": rows}

    def ensure_expiries(self, start: date, end: date) -> list[date]:
        d = start - timedelta(days=10)
        exps = []
        while d <= end + timedelta(days=21):
            if d.weekday() == 1:  # weekly Tuesday expiry
                exps.append(d)
            d += timedelta(days=1)
        db.save_expiries(self.dataset, exps)
        return db.load_expiries(self.dataset)

    def option_symbol(self, expiry: date, strike: float, typ: str) -> str | None:
        sym = f"SYNTH:NIFTY-{expiry:%d%b%y}-{int(strike)}-{typ}"
        db.save_contracts(self.dataset, [(sym, expiry, strike, typ)])
        return sym

    def ensure_option_day(self, symbol: str, day: date) -> None:
        if db.fetched(symbol, day):
            return
        m = re.match(r"SYNTH:NIFTY-(\d{2}\w{3}\d{2})-(\d+)-(CE|PE)$", symbol)
        expiry = datetime.strptime(m.group(1), "%d%b%y").date()
        strike, typ = float(m.group(2)), m.group(3)
        spot = db.load_candles(self.spot_symbol, datetime.combine(day, time(0)),
                               datetime.combine(day + timedelta(days=1), time(0)))
        rng = self._rng("iv", day)
        vol = 0.11 + 0.06 * rng.random()
        expiry_dt = datetime.combine(expiry, time(15, 30))
        rows = []
        for r in spot.itertuples(index=False):
            t = max((expiry_dt - r.ts).total_seconds(), 60) / (365 * 24 * 3600)
            px = [max(0.05, round(_bs_price(v, strike, t, vol, typ) / 0.05) * 0.05)
                  for v in (r.open, r.high, r.low, r.close)]
            hi, lo = max(px), min(px)
            rows.append((r.ts, px[0], hi, lo, px[3], 0.0, 0.0))
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
        db.upsert_candles(symbol, df)
        if day < _now().date():   # today's session is still growing
            db.mark_fetched(symbol, day, len(df))


def get(dataset: str) -> Provider:
    if dataset == "synthetic":
        return SyntheticProvider()
    if dataset == "groww":
        return GrowwProvider()
    raise ValueError(f"unknown dataset {dataset}")

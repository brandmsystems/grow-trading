"""Live market data for the engine: clock, NIFTY 1m candles (completed only), LTPs,
expiries and option contracts.

GrowwMarket talks to Groww. ReplayMarket replays stored candles on a simulated clock
(tests and dry runs). Order execution lives in app.services.trading.brokers.
"""
from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd

from app.config import settings as config
from app.database import db
from app.utils.timeutil import IST
from app.services.market_data import providers

log = logging.getLogger("live.market")
INSTRUMENTS_FILE = config.BASE_DIR / "data" / "historical" / "instruments.csv"


@dataclass(frozen=True)
class Contract:
    trading_symbol: str     # used for orders / LTP  e.g. NIFTY26D0124000CE
    groww_symbol: str       # used for historical candles e.g. NSE-NIFTY-01Dec26-24000-CE
    expiry: date
    strike: float
    opt_type: str
    lot_size: int


def _completed(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Keep only 1m candles that have fully closed (start + 1 min <= now)."""
    if df.empty:
        return df
    return df[df["ts"] + pd.Timedelta(minutes=1) <= pd.Timestamp(now)].reset_index(drop=True)


# ====================================================================== Groww
class GrowwMarket:
    HISTORY_DAYS = 40      # enough for the slowest indicator to settle
    spot_symbol = "NSE-NIFTY"

    def __init__(self):
        from app.services.groww import client as groww_client
        self._gc = groww_client
        self._prov = providers.GrowwProvider()
        self._lock = threading.Lock()
        self._hist: tuple[date, pd.DataFrame] | None = None
        self._exp: tuple[date, list[date]] | None = None
        self._instr: tuple[date, pd.DataFrame] | None = None
        self._fut: tuple[date, str | None, pd.DataFrame] | None = None

    def now(self) -> datetime:
        return datetime.now(IST).replace(tzinfo=None, microsecond=0)

    def sleep(self, seconds: float) -> None:
        _time.sleep(seconds)

    # -------------------------------------------------- candles
    def _history(self, day: date) -> pd.DataFrame:
        """Prior sessions (for EMA warm-up), downloaded once per day and kept in Postgres."""
        if self._hist and self._hist[0] == day:
            return self._hist[1]
        start = day - timedelta(days=self.HISTORY_DAYS)
        self._prov.ensure_spot(start, day - timedelta(days=1))
        try:   # keep near-month futures as current as spot (VWAP, volume, Data page)
            from app.services.market_data import history as data_manager
            data_manager.download_futures(start, day - timedelta(days=1))
        except Exception as exc:
            log.warning("futures refresh failed: %s", exc)
        df = db.load_candles(self._prov.spot_symbol, datetime.combine(start, time(0)),
                             datetime.combine(day, time(0)))
        self._hist = (day, df)
        return df

    def spot_1m(self, day: date) -> pd.DataFrame:
        """Warm-up history + today's completed 1m candles."""
        hist = self._history(day)
        now = self.now()
        today = self._prov._candles("CASH", self._prov.spot_symbol,
                                    datetime.combine(day, time(9, 15)), min(now, datetime.combine(day, time(15, 30))))
        today = _completed(today, now)
        if not today.empty:
            db.upsert_candles(self._prov.spot_symbol, today)
        return pd.concat([hist, today], ignore_index=True)

    def futures_1m(self, day: date) -> pd.DataFrame:
        """Near-month NIFTY futures: stored history + today's completed candles (VWAP, volume)."""
        from app.services.market_data import history as data_manager
        if not (self._fut and self._fut[0] == day):
            exps = data_manager.monthly_expiries(day - timedelta(days=45), day + timedelta(days=45))
            front = next((e for e in exps if e > day), None)
            data_manager.download_futures(day - timedelta(days=self.HISTORY_DAYS), day - timedelta(days=1))
            hist = data_manager.futures_1m(day - timedelta(days=self.HISTORY_DAYS), day - timedelta(days=1))
            self._fut = (day, data_manager.fut_symbol(front) if front else None, hist)
        _, sym, hist = self._fut
        if not sym:
            return hist
        now = self.now()
        today = self._prov._candles("FNO", sym, datetime.combine(day, time(9, 15)), min(now, datetime.combine(day, time(15, 30))))
        today = _completed(today, now)
        if not today.empty:
            today = today[today["ts"].dt.time.between(time(9, 15), time(15, 29))]
            db.upsert_candles(sym, today)
        return pd.concat([hist, today], ignore_index=True)

    # -------------------------------------------------- quotes
    def _ltp(self, key: str, segment: str) -> float:
        resp = self._gc.call("get_ltp", exchange_trading_symbols=key, segment=segment, timeout=5)
        if isinstance(resp, dict):
            v = resp.get(key)
            if v is None and len(resp) == 1:
                v = next(iter(resp.values()))
            if isinstance(v, dict):
                v = v.get("ltp") or v.get("last_price")
            if v is not None:
                return float(v)
        raise RuntimeError(f"No LTP for {key}: {resp}")

    def spot_ltp(self) -> float:
        return self._ltp("NSE_NIFTY", "CASH")

    def option_ltp(self, c: Contract) -> float:
        return self._ltp(f"NSE_{c.trading_symbol}", "FNO")

    # -------------------------------------------------- contracts
    def expiries(self, day: date) -> list[date]:
        if self._exp and self._exp[0] == day:
            return self._exp[1]
        out = set()
        for d in (day, (day.replace(day=1) + timedelta(days=32))):
            resp = self._gc.call("get_expiries", exchange="NSE", underlying_symbol="NIFTY",
                                 year=d.year, month=d.month, timeout=10)
            out.update(pd.Timestamp(x).date() for x in providers._first_list(resp))
        exps = sorted(e for e in out if e >= day)
        if not exps:  # fall back to the instrument master
            df = self._instruments(day)
            exps = sorted({e for e in pd.to_datetime(df["expiry_date"]).dt.date if e >= day})
        self._exp = (day, exps)
        return exps

    def _instruments(self, day: date) -> pd.DataFrame:
        if self._instr and self._instr[0] == day:
            return self._instr[1]
        INSTRUMENTS_FILE.parent.mkdir(exist_ok=True)
        fresh = INSTRUMENTS_FILE.exists() and date.fromtimestamp(INSTRUMENTS_FILE.stat().st_mtime) == day
        if not fresh:
            import requests
            r = requests.get("https://growwapi-assets.groww.in/instruments/instrument.csv", timeout=60)
            r.raise_for_status()
            INSTRUMENTS_FILE.write_bytes(r.content)
        df = pd.read_csv(INSTRUMENTS_FILE, low_memory=False)
        df = df[(df["underlying_symbol"] == "NIFTY") & (df["segment"] == "FNO")
                & (df["instrument_type"].isin(["CE", "PE"])) & (df["exchange"] == "NSE")].copy()
        df["expiry"] = pd.to_datetime(df["expiry_date"]).dt.date
        self._instr = (day, df)
        return df

    def option_delta(self, c: Contract) -> float | None:
        """The contract's delta from Groww's option chain (cached 30 s per expiry)."""
        from app.services.options.contracts import chain_row
        from app.utils.numbers import to_float
        key = c.expiry
        cached = getattr(self, "_chain_cache", {}).get(key)
        if not cached or (_time.monotonic() - cached[0]) > 30:
            chain = self._gc.call("get_option_chain", exchange="NSE", underlying="NIFTY",
                                  expiry_date=c.expiry.isoformat(), timeout=10)
            self._chain_cache = {**getattr(self, "_chain_cache", {}), key: (_time.monotonic(), chain)}
            cached = self._chain_cache[key]
        row = chain_row(cached[1], c.strike, c.opt_type)
        return to_float(((row or {}).get("greeks") or {}).get("delta"))

    def option_quote(self, c: Contract) -> dict:
        """What Groww reports about the contract right now: open interest, volume, delta, and the best bid and
        ask when the quote has them. A field Groww does not send is None (the engine only checks what is known)."""
        from app.services.options.contracts import chain_row
        from app.utils.numbers import to_float
        out = {"oi": None, "volume": None, "delta": None, "iv": None, "bid": None, "ask": None}
        try:
            self.option_delta(c)          # refreshes the 30 s chain cache
            row = chain_row(self._chain_cache[c.expiry][1], c.strike, c.opt_type) or {}
            g = row.get("greeks") or {}
            out.update(oi=to_float(row.get("open_interest")), volume=to_float(row.get("volume")),
                       delta=to_float(g.get("delta")), iv=to_float(g.get("iv")))
        except Exception as exc:
            log.warning("option chain quote failed: %s", exc)
        try:
            q = self._gc.call("get_quote", trading_symbol=c.trading_symbol, exchange="NSE", segment="FNO", timeout=5) or {}
            out["bid"], out["ask"] = to_float(q.get("bid_price")), to_float(q.get("offer_price"))
            if out["oi"] is None:
                out["oi"] = to_float(q.get("open_interest"))
        except Exception as exc:
            log.warning("option quote failed: %s", exc)
        return out

    def contract(self, day: date, expiry: date, strike: float, opt_type: str) -> Contract | None:
        df = self._instruments(day)
        m = df[(df["expiry"] == expiry) & (df["strike_price"].astype(float) == float(strike))
               & (df["instrument_type"] == opt_type)]
        if m.empty:
            return None
        r = m.iloc[0]
        return Contract(str(r["trading_symbol"]), str(r["groww_symbol"]), expiry, float(strike),
                        opt_type, int(r["lot_size"]))


# ====================================================================== brokers
# ====================================================================== replay (tests / dry runs)
class ReplayMarket:
    """Replays stored candles on a simulated clock. Option LTP = open of the current minute."""

    def __init__(self, dataset: str, history_from: date, start: datetime):
        self.prov = providers.get(dataset)
        self.history_from = history_from
        self.clock = start
        self._spot: pd.DataFrame | None = None
        self._fut: pd.DataFrame | None = None
        self._opt: dict[str, pd.DataFrame] = {}
        self.spot_symbol = self.prov.spot_symbol

    def now(self) -> datetime:
        return self.clock

    def sleep(self, seconds: float) -> None:
        self.clock += timedelta(seconds=seconds)

    def _all_spot(self) -> pd.DataFrame:
        if self._spot is None:
            self._spot = db.load_candles(self.prov.spot_symbol, datetime.combine(self.history_from, time(0)),
                                         datetime.combine(self.clock.date() + timedelta(days=30), time(0)))
        return self._spot

    def spot_1m(self, day: date) -> pd.DataFrame:
        df = self._all_spot()
        return _completed(df[df["ts"] < datetime.combine(day + timedelta(days=1), time(0))], self.clock)

    def futures_1m(self, day: date) -> pd.DataFrame:
        if self._fut is None:
            from app.services.market_data import history as data_manager
            self._fut = (data_manager.futures_1m(self.history_from, self.clock.date() + timedelta(days=1))
                         if self.prov.dataset == "groww" else pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "oi"]))
        df = self._fut
        if df.empty:
            return df
        return _completed(df[df["ts"] < datetime.combine(day + timedelta(days=1), time(0))], self.clock)

    def _minute_open(self, df: pd.DataFrame) -> float:
        m = pd.Timestamp(self.clock).floor("min")
        row = df[df["ts"] >= m].head(1)
        if row.empty:
            row = df[df["ts"] < m].tail(1)
            return float(row["close"].iloc[0])
        return float(row["open"].iloc[0])

    def spot_ltp(self) -> float:
        day = self.clock.date()
        if getattr(self, "_spot_day", (None,))[0] != day:
            df = self._all_spot()
            self._spot_day = (day, df[df["ts"].dt.date == day])
        return self._minute_open(self._spot_day[1])

    def option_ltp(self, c: Contract) -> float:
        sym, day = c.groww_symbol, self.clock.date()
        key = f"{sym}|{day}"
        if key not in self._opt:
            self.prov.ensure_option_day(sym, day)
            self._opt[key] = db.load_candles(sym, datetime.combine(day, time(0)),
                                             datetime.combine(day + timedelta(days=1), time(0)))
        return self._minute_open(self._opt[key])

    def option_quote(self, c: Contract) -> dict:
        """Replay: open interest and volume of the stored option candle for the current minute. There are no
        stored bids, asks or Greeks, so those are None and are not checked."""
        out = {"oi": None, "volume": None, "delta": None, "iv": None, "bid": None, "ask": None}
        try:
            self.option_ltp(c)
            df = self._opt[f"{c.groww_symbol}|{self.clock.date()}"]
            row = df[df["ts"] <= pd.Timestamp(self.clock).floor("min")].tail(1)
            if not row.empty:
                oi, vol = float(row["oi"].iloc[0]), float(row["volume"].iloc[0])
                out["oi"], out["volume"] = (oi or None), (vol or None)
        except Exception:
            pass
        return out

    def expiries(self, day: date) -> list[date]:
        return self.prov.ensure_expiries(day, day + timedelta(days=14))

    def contract(self, day: date, expiry: date, strike: float, opt_type: str) -> Contract | None:
        sym = self.prov.option_symbol(expiry, strike, opt_type)
        if not sym:
            return None
        # The replayed contract's own NSE lot size, as in the backtest.
        from app.services.options import lot_sizes
        lot, _ = lot_sizes.lot_size_for(expiry, self.prov.ensure_expiries(expiry, expiry))
        return Contract(sym, sym, expiry, strike, opt_type, lot)

"""Market-data and order-execution adapters for the live/paper engine.

Market:  clock, NIFTY 1m candles (completed only), LTPs, expiries, contracts.
Broker:  executes an order and returns the fill price.

GrowwMarket / LiveBroker talk to Groww; PaperBroker simulates fills at LTP.
ReplayMarket replays stored candles on a simulated clock (tests / dry runs).
"""
from __future__ import annotations

import logging
import random
import string
import threading
import time as _time
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import config
import db
import providers

log = logging.getLogger("live.market")
IST = ZoneInfo("Asia/Kolkata")
INSTRUMENTS_FILE = config.BASE_DIR / "data" / "instruments.csv"


@dataclass(frozen=True)
class Contract:
    trading_symbol: str     # used for orders / LTP  e.g. NIFTY26D0124000CE
    groww_symbol: str       # used for historical candles e.g. NSE-NIFTY-01Dec26-24000-CE
    expiry: date
    strike: float
    opt_type: str
    lot_size: int


class OrderError(RuntimeError):
    """Order rejected / failed: no position change happened."""


class OrderUnknown(RuntimeError):
    """Order outcome could not be confirmed: the engine must halt for manual review."""


def _completed(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Keep only 1m candles that have fully closed (start + 1 min <= now)."""
    if df.empty:
        return df
    return df[df["ts"] + pd.Timedelta(minutes=1) <= pd.Timestamp(now)].reset_index(drop=True)


# ====================================================================== Groww
class GrowwMarket:
    HISTORY_DAYS = 12

    def __init__(self):
        import groww_client
        self._gc = groww_client
        self._prov = providers.GrowwProvider()
        self._lock = threading.Lock()
        self._hist: tuple[date, pd.DataFrame] | None = None
        self._exp: tuple[date, list[date]] | None = None
        self._instr: tuple[date, pd.DataFrame] | None = None

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
class PaperBroker:
    """Fills instantly at the current LTP. Slippage/charges are applied by the engine."""
    name = "paper"
    models_slippage = True

    def __init__(self, market):
        self.market = market

    def execute(self, c: Contract, txn: str, qty: int, ref: str) -> dict:
        px = self.market.option_ltp(c)
        return {"price": round(px, 2), "order_id": f"PAPER-{ref}", "status": "EXECUTED",
                "ts": self.market.now()}


class LiveBroker:
    """Places MIS market orders on Groww and waits for confirmation."""
    name = "live"
    models_slippage = False     # actual fills already contain slippage
    DONE = {"EXECUTED", "COMPLETED", "FILLED"}
    DEAD = {"REJECTED", "FAILED", "CANCELLED", "CANCELLATION_REQUESTED"}
    CONFIRM_TIMEOUT = 30

    def __init__(self, market):
        import groww_client
        self._gc = groww_client
        self.market = market

    @staticmethod
    def _ref() -> str:
        return "EMA" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))

    def execute(self, c: Contract, txn: str, qty: int, ref: str | None = None) -> dict:
        ref = ref or self._ref()
        try:
            resp = self._gc.call("place_order", validity="DAY", exchange="NSE", order_type="MARKET",
                                 product="MIS", quantity=int(qty), segment="FNO",
                                 trading_symbol=c.trading_symbol, transaction_type=txn,
                                 order_reference_id=ref, price=0.0, timeout=10)
        except Exception as exc:
            # A timeout here is ambiguous (the order may exist) -> check by reference.
            if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
                return self._confirm(None, ref, qty)
            raise OrderError(f"Order rejected: {exc}") from exc
        oid = (resp or {}).get("groww_order_id")
        if (resp or {}).get("order_status", "").upper() in self.DEAD:
            raise OrderError(f"Order {oid} {resp.get('order_status')}: {resp.get('remark', '')}")
        return self._confirm(oid, ref, qty)

    def _confirm(self, oid: str | None, ref: str, qty: int) -> dict:
        deadline = _time.monotonic() + self.CONFIRM_TIMEOUT
        last = None
        while _time.monotonic() < deadline:
            try:
                if oid:
                    st = self._gc.call("get_order_status", segment="FNO", groww_order_id=oid, timeout=5)
                else:
                    st = self._gc.call("get_order_status_by_reference", segment="FNO",
                                       order_reference_id=ref, timeout=5)
                    oid = st.get("groww_order_id") or oid
                last = st
                status = str(st.get("order_status", "")).upper()
                if status in self.DONE and int(st.get("filled_quantity") or qty) >= qty:
                    price = st.get("average_fill_price")
                    if not price and oid:
                        det = self._gc.call("get_order_detail", segment="FNO", groww_order_id=oid, timeout=5)
                        price = det.get("average_fill_price")
                    if not price:
                        raise OrderUnknown(f"Order {oid} executed but fill price unavailable")
                    return {"price": round(float(price), 2), "order_id": oid, "status": status,
                            "ts": self.market.now()}
                if status in self.DEAD:
                    raise OrderError(f"Order {oid} {status}: {st.get('remark', '')}")
            except (OrderError, OrderUnknown):
                raise
            except Exception as exc:
                log.warning("order status check failed: %s", exc)
            _time.sleep(0.7)
        raise OrderUnknown(f"Order {oid or ref} not confirmed within {self.CONFIRM_TIMEOUT}s "
                           f"(last status: {last}). Check the Groww app.")


# ====================================================================== replay (tests / dry runs)
class ReplayMarket:
    """Replays stored candles on a simulated clock. Option LTP = open of the current minute."""

    def __init__(self, dataset: str, history_from: date, start: datetime):
        self.prov = providers.get(dataset)
        self.history_from = history_from
        self.clock = start
        self._spot: pd.DataFrame | None = None
        self._opt: dict[str, pd.DataFrame] = {}

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

    def _minute_open(self, df: pd.DataFrame) -> float:
        m = pd.Timestamp(self.clock).floor("min")
        row = df[df["ts"] >= m].head(1)
        if row.empty:
            row = df[df["ts"] < m].tail(1)
            return float(row["close"].iloc[0])
        return float(row["open"].iloc[0])

    def spot_ltp(self) -> float:
        df = self._all_spot()
        return self._minute_open(df[df["ts"].dt.date == self.clock.date()])

    def option_ltp(self, c: Contract) -> float:
        sym, day = c.groww_symbol, self.clock.date()
        key = f"{sym}|{day}"
        if key not in self._opt:
            self.prov.ensure_option_day(sym, day)
            self._opt[key] = db.load_candles(sym, datetime.combine(day, time(0)),
                                             datetime.combine(day + timedelta(days=1), time(0)))
        return self._minute_open(self._opt[key])

    def expiries(self, day: date) -> list[date]:
        return self.prov.ensure_expiries(day, day + timedelta(days=14))

    def contract(self, day: date, expiry: date, strike: float, opt_type: str) -> Contract | None:
        sym = self.prov.option_symbol(expiry, strike, opt_type)
        return Contract(sym, sym, expiry, strike, opt_type, 65) if sym else None

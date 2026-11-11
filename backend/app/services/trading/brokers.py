"""Order execution: PaperBroker simulates fills at the option LTP; LiveBroker places real
MIS market orders on Groww and waits for confirmation.

Every broker returns {"price", "order_id", "status", "ts"} or raises:
  OrderError   - rejected or failed; no position change happened.
  OrderUnknown - outcome could not be confirmed; the engine must halt for manual review.
"""
from __future__ import annotations

import logging
import random
import string
import time as _time

from app.services.market_data.live import Contract

log = logging.getLogger("live.broker")


class OrderError(RuntimeError):
    """Order rejected / failed: no position change happened."""


class OrderUnknown(RuntimeError):
    """Order outcome could not be confirmed: the engine must halt for manual review."""


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
        from app.services.groww import client as groww_client
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

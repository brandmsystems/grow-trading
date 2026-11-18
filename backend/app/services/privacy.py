"""Personal financial data of REAL-MONEY (live) trading never leaves the backend.

The app shows market data, strategy signals, paper trading and backtests. It does not show what happens in
your real Groww account: funds and margin, positions, fills and order ids, P&L, charges, or the trades the
live engine took. These helpers remove those details from everything that goes to the browser (REST and
WebSocket). The database keeps the full records; nothing is deleted.

Deliberately NOT hidden, because live-trading safety depends on it:
* that a live position is open (`live_position_open`), so you know to close it;
* the proposed order that waits for your confirmation (side, contract, quantity), because you cannot
  confirm what you cannot see;
* halts and errors ("square off manually in the Groww app").
"""
from __future__ import annotations

import re

HIDDEN_EVENT = "Live order activity (details are not shown)"

# Engine log lines that carry fills, quantities, prices or P&L of real orders.
_FILL_EVENT = re.compile(
    r"^(ENTERED|EXITED|Resumed open|You confirmed|Stop-loss changed|Premium .* reached|Risk:|Daily loss limit hit)"
    r"|→ (BUY|SELL) ")

# Alert payload fields that describe an actual fill or its result.
_FILL_FIELDS = ("entry_price", "exit_price", "net", "qty", "entry_ts", "exit_ts", "order_id", "pnl", "charges")


# Order identifiers are never needed by the UI (paper ones are simulated, live ones are real Groww ids).
_ORDER_FIELDS = ("entry_order_id", "exit_order_id")


def public_trade(row: dict) -> dict:
    """A trade row as served to the browser: no order identifiers."""
    return {k: v for k, v in row.items() if k not in _ORDER_FIELDS}


def is_live(status: dict) -> bool:
    return ((status.get("config") or {}).get("trade_mode")) == "live"


def redact_live_status(status: dict) -> dict:
    """The engine status for the browser. Unchanged unless the engine runs in live (real-money) mode."""
    if not is_live(status):
        return status
    out = dict(status)
    out["live_position_open"] = out.get("position") is not None
    out["position"] = None
    out["realised_today"] = 0.0
    out["live_details_hidden"] = True
    out["events"] = [{**e, "message": HIDDEN_EVENT} if _FILL_EVENT.search(e.get("message", "")) else e
                     for e in out.get("events") or []]
    return out


def redact_live_alert(alert: dict) -> dict:
    """An alert as shown to the browser: live-mode alerts lose their fill details."""
    if alert.get("mode") != "live":
        return alert
    return {k: v for k, v in alert.items() if k not in _FILL_FIELDS}

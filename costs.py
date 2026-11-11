"""Slippage and the Indian index-options charge stack.

All rates are parameters (see DEFAULT_COSTS) so they can be updated when
exchange/regulatory rates change.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

TICK = 0.05


@dataclass(frozen=True)
class CostConfig:
    slippage_pct: float = 0.005          # 0.5% of premium
    slippage_pts: float = 0.5            # plus fixed points per fill
    brokerage_per_order: float = 20.0    # flat per executed order
    stt_sell_pct: float = 0.0015         # STT on sell-side premium (options)
    exchange_pct: float = 0.0003503      # NSE options transaction charge on premium turnover
    sebi_per_crore: float = 10.0         # SEBI turnover fee
    stamp_buy_pct: float = 0.00003       # stamp duty on buy-side premium
    gst_pct: float = 0.18                # GST on brokerage + exchange + SEBI

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_COSTS = CostConfig()


def _round_tick_up(p: float) -> float:
    return round(math.ceil(round(p / TICK, 6)) * TICK, 2)


def _round_tick_down(p: float) -> float:
    return round(math.floor(round(p / TICK, 6)) * TICK, 2)


def buy_fill(price: float, cfg: CostConfig = DEFAULT_COSTS) -> float:
    """Price paid when buying: worse by pct + points, rounded up to the tick."""
    return _round_tick_up(price * (1 + cfg.slippage_pct) + cfg.slippage_pts)


def sell_fill(price: float, cfg: CostConfig = DEFAULT_COSTS) -> float:
    """Price received when selling: worse by pct + points, rounded down, floored at 0.05."""
    return max(TICK, _round_tick_down(price * (1 - cfg.slippage_pct) - cfg.slippage_pts))


def charges(buy_price: float, sell_price: float, qty: int, cfg: CostConfig = DEFAULT_COSTS) -> dict:
    """Charges for one round trip (one buy order + one sell order)."""
    buy_val = buy_price * qty
    sell_val = sell_price * qty
    turnover = buy_val + sell_val
    brokerage = 2 * cfg.brokerage_per_order
    stt = sell_val * cfg.stt_sell_pct
    exchange = turnover * cfg.exchange_pct
    sebi = turnover * cfg.sebi_per_crore / 1e7
    stamp = buy_val * cfg.stamp_buy_pct
    gst = (brokerage + exchange + sebi) * cfg.gst_pct
    out = {"brokerage": brokerage, "stt": stt, "exchange": exchange, "sebi": sebi,
           "stamp": stamp, "gst": gst}
    out = {k: round(v, 2) for k, v in out.items()}
    out["total"] = round(sum(out.values()), 2)
    return out


def round_trip(side: str, raw_entry: float, raw_exit: float, qty: int,
               cfg: CostConfig = DEFAULT_COSTS) -> dict:
    """Full PnL breakdown for a trade.

    side: "BUY" (long option: buy at entry, sell at exit) or
          "SELL" (short option: sell at entry, buy back at exit).
    """
    if side == "BUY":
        entry_fill, exit_fill = buy_fill(raw_entry, cfg), sell_fill(raw_exit, cfg)
        gross = (raw_exit - raw_entry) * qty
        after_slip = (exit_fill - entry_fill) * qty
        ch = charges(entry_fill, exit_fill, qty, cfg)
    elif side == "SELL":
        entry_fill, exit_fill = sell_fill(raw_entry, cfg), buy_fill(raw_exit, cfg)
        gross = (raw_entry - raw_exit) * qty
        after_slip = (entry_fill - exit_fill) * qty
        ch = charges(exit_fill, entry_fill, qty, cfg)
    else:
        raise ValueError(side)
    slippage = round(gross - after_slip, 2)
    gross = round(gross, 2)
    net = round(gross - slippage - ch["total"], 2)
    return {"entry_fill": entry_fill, "exit_fill": exit_fill, "gross": gross,
            "slippage": slippage, "charges": ch, "friction": round(slippage + ch["total"], 2),
            "net": net}

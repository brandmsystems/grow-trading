"""Paper/scalp stop-loss and target premiums, and the NIFTY levels they correspond to.

Pure functions (no engine state, no I/O) so the rules can be unit tested on their own.
Buys stop below the premium and target above it; sells are the mirror image.
"""
from __future__ import annotations

from typing import Callable, NamedTuple

from app.services.strategy import signals
from app.services.trading import charges as costs
from app.services.trading.engine_config import EngineConfig


class StopLevels(NamedTuple):
    stop: float | None
    target: float | None
    how: str                 # human-readable method, shown in the risk calculation
    error: str | None        # set when no stop can be calculated (the trade is then refused)
    delta: float | None      # |option delta| used (ATR mode only)
    invalid: bool = False    # the stop was calculated but is outside the range the strategy allows (a refusal, not a missing input)


def stop_levels(cfg: EngineConfig, side: str, premium: float, atr: float | None,
                get_delta: Callable[[], float | None]) -> StopLevels:
    """Stop and target premiums for an entry at `premium`.

    `get_delta` is only called in ATR mode; it may raise or return a falsy value when the option's delta
    is unavailable, which refuses the trade rather than guessing a stop.
    """
    sgn = 1 if side == "BUY" else -1
    round_stop = costs._round_tick_down if side == "BUY" else costs._round_tick_up
    zero_error = "The stop-loss works out at or below zero; no position size can be calculated."

    if cfg.signal_mode == "scalp":
        stop = premium * (1 - sgn * cfg.stop_pct / 100)
        target = premium * (1 + sgn * cfg.target_pct / 100) if cfg.scalp_exit == "sl_target" else None
        how = (f"scalp: stop {cfg.stop_pct:g}% of the premium"
               + (f", target {cfg.target_pct:g}%" if target else f" (protective), exit after {cfg.hold_min} min"))
        stop = round_stop(stop)
        if stop <= 0:
            return StopLevels(None, None, how, zero_error, None)
        if target:
            target = (costs._round_tick_up if side == "BUY" else costs._round_tick_down)(target)
        return StopLevels(stop, target, how, None, None)

    delta_used = None
    if cfg.stop_mode == "pct":
        stop = premium * (1 - sgn * cfg.stop_pct / 100)
        target = premium * (1 + sgn * 2 * cfg.stop_pct / 100)
        how = f"{cfg.stop_pct:g}% of the premium (target 2× that distance)"
    elif cfg.stop_mode == "points":
        stop = premium - sgn * cfg.stop_points
        target = premium + sgn * 2 * cfg.stop_points
        how = f"{cfg.stop_points:g} premium points (target 2× that distance)"
    else:
        if not atr:
            return StopLevels(None, None, "", "NIFTY ATR unavailable, so no stop-loss can be calculated.", None)
        try:
            delta = get_delta()
        except Exception as exc:
            return StopLevels(None, None, "", f"Option delta unavailable ({exc}), so no stop-loss can be calculated.", None)
        if not delta:
            return StopLevels(None, None, "", "Option delta unavailable, so no stop-loss can be calculated.", None)
        delta_used = abs(delta)
        move = delta_used * atr
        stop = premium - sgn * cfg.stop_atr * move
        target = premium + sgn * signals.TARGET_ATR * move
        how = (f"delta {delta_used:.2f} × {cfg.stop_atr:g} × NIFTY ATR {atr:.2f} "
               f"(target {signals.TARGET_ATR:g}× ATR)")
    if cfg.signal_mode == "bias":
        target = premium + sgn * cfg.target_rr * abs(premium - stop)
        how += f"; target {cfg.target_rr:g}× the stop distance"
    stop = round_stop(stop)
    if stop <= 0:
        return StopLevels(None, None, how, zero_error, delta_used)
    if cfg.signal_mode == "bias" and cfg.entry_strategy == "scored" and premium > 0:
        pct = 100 * abs(premium - stop) / premium          # option premium validation: a controlled, meaningful stop distance
        if not cfg.sc_stop_min_pct <= pct <= cfg.sc_stop_max_pct:
            return StopLevels(None, None, how, f"The stop is {pct:.1f}% of the premium ({premium:.2f}); the scored strategy needs "
                              f"{cfg.sc_stop_min_pct:g}% to {cfg.sc_stop_max_pct:g}%.", delta_used, True)
    return StopLevels(stop, round(target, 2), how, None, delta_used)


def position_levels(p: dict) -> dict:
    """Stop/target of an open position with their risk, plus the NIFTY levels they correspond to (chart lines)."""
    if p.get("stop_premium") is None:
        return {}
    r = p.get("risk") or {}
    sgn = 1 if p["side"] == "BUY" else -1
    delta, ref = r.get("delta"), r.get("nifty_ref")
    d = 1 if p["direction"] > 0 else -1

    def to_nifty(prem):
        if not (delta and ref) or prem is None:
            return None
        return round(ref - d * sgn * (p["entry_price"] - prem) / delta, 2)

    cap = r.get("capital") or 0
    ml = r.get("max_loss")
    return {"stop_premium": p["stop_premium"], "target_premium": p.get("target_premium"),
            "max_loss": ml, "max_loss_pct": round(100 * ml / cap, 2) if cap and ml is not None else None,
            "risk_amount": r.get("risk_amount"), "risk_reward": r.get("risk_reward"),
            "nifty_stop": to_nifty(p["stop_premium"]), "nifty_target": to_nifty(p.get("target_premium")),
            "stop_method": r.get("stop_method")}

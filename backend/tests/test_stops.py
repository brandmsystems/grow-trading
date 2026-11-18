"""stops.py: the paper/scalp stop-loss and target rules as pure functions."""
import pytest

from app.services.strategy import signals
from app.services.trading import stops
from app.services.trading.engine_config import EngineConfig


def cfg(**kw):
    return EngineConfig(**{"trade_mode": "paper", **kw}).validate()


def no_delta():
    pytest.fail("delta must not be fetched outside ATR mode")


def test_pct_mode_buy_and_sell_mirror_each_other():
    buy = stops.stop_levels(cfg(stop_mode="pct", stop_pct=30), "BUY", 100.0, None, no_delta)
    sell = stops.stop_levels(cfg(stop_mode="pct", stop_pct=30), "SELL", 100.0, None, no_delta)
    assert (buy.stop, buy.target, buy.error, buy.delta) == (70.0, 160.0, None, None)
    assert (sell.stop, sell.target) == (130.0, 40.0)
    assert "30%" in buy.how


def test_points_mode():
    lv = stops.stop_levels(cfg(stop_mode="points", stop_points=20), "BUY", 120.0, None, no_delta)
    assert (lv.stop, lv.target) == (100.0, 160.0)


def test_stop_rounds_to_the_tick_in_the_unfavourable_direction():
    # 100 - 33.3% = 66.7 -> a buy stop rounds DOWN to a 0.05 tick, a sell stop UP
    assert stops.stop_levels(cfg(stop_mode="pct", stop_pct=33.3), "BUY", 100.0, None, no_delta).stop == 66.7
    assert stops.stop_levels(cfg(stop_mode="pct", stop_pct=33.33), "BUY", 100.0, None, no_delta).stop == 66.65
    assert stops.stop_levels(cfg(stop_mode="pct", stop_pct=33.33), "SELL", 100.0, None, no_delta).stop == 133.35


def test_atr_mode_uses_delta_times_atr_and_reports_the_delta():
    lv = stops.stop_levels(cfg(stop_mode="atr", stop_atr=1.0), "BUY", 100.0, 40.0, lambda: -0.5)
    assert lv.delta == 0.5                                   # absolute value
    assert lv.stop == 80.0                                   # 100 - 1 x 0.5 x 40
    assert lv.target == pytest.approx(100 + signals.TARGET_ATR * 20)
    assert "delta 0.50" in lv.how


@pytest.mark.parametrize("atr,get_delta,fragment", [
    (None, lambda: 0.5, "ATR unavailable"),
    (40.0, lambda: None, "delta unavailable"),
    (40.0, lambda: 0, "delta unavailable"),
])
def test_atr_mode_refuses_when_inputs_are_missing(atr, get_delta, fragment):
    lv = stops.stop_levels(cfg(stop_mode="atr"), "BUY", 100.0, atr, get_delta)
    assert lv.stop is None and lv.target is None and fragment in lv.error


def test_atr_mode_refuses_when_delta_lookup_raises():
    def boom():
        raise ConnectionError("groww down")
    lv = stops.stop_levels(cfg(stop_mode="atr"), "BUY", 100.0, 40.0, boom)
    assert lv.stop is None and "groww down" in lv.error


def test_a_stop_at_or_below_zero_is_refused():
    lv = stops.stop_levels(cfg(stop_mode="points", stop_points=150), "BUY", 100.0, None, no_delta)
    assert lv.stop is None and "at or below zero" in lv.error


def test_scalp_levels():
    c = cfg(trade_mode="paper", signal_mode="scalp", timeframe=5, scalp_exit="sl_target", stop_pct=10, target_pct=20)
    lv = stops.stop_levels(c, "BUY", 100.0, None, no_delta)
    assert (lv.stop, lv.target) == (90.0, 120.0)
    timed = cfg(signal_mode="scalp", timeframe=5, scalp_exit="time", stop_pct=10, hold_min=5)
    lv = stops.stop_levels(timed, "BUY", 100.0, None, no_delta)
    assert lv.stop == 90.0 and lv.target is None and "protective" in lv.how


def test_position_levels_map_premium_levels_back_to_nifty():
    p = {"side": "BUY", "direction": 1, "entry_price": 100.0, "stop_premium": 80.0, "target_premium": 140.0,
         "risk": {"delta": 0.5, "nifty_ref": 25000.0, "capital": 100000, "max_loss": 1500.0, "risk_amount": 1000.0,
                  "risk_reward": 2.0, "stop_method": "x"}}
    lv = stops.position_levels(p)
    assert lv["nifty_stop"] == 24960.0 and lv["nifty_target"] == 25080.0     # premium move / delta
    assert lv["max_loss_pct"] == 1.5 and lv["risk_reward"] == 2.0
    assert stops.position_levels({**p, "stop_premium": None}) == {}
    no_delta_p = {**p, "risk": {**p["risk"], "delta": None}}
    assert stops.position_levels(no_delta_p)["nifty_stop"] is None


def test_engine_config_rejects_bad_times_with_a_clear_message():
    with pytest.raises(ValueError, match="09:30"):
        EngineConfig(entry_start="9h30").validate()
    with pytest.raises(ValueError, match="before cutoff"):
        EngineConfig(entry_start="14:30", cutoff="09:30").validate()
    with pytest.raises(ValueError, match="paper mode only"):
        EngineConfig(trade_mode="live", signal_mode="scalp", timeframe=5).validate()

"""Position trading: the historical option simulator, statistics, score, contract analysis, plan, Black-Scholes estimates and settings. Pure (no database)."""
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services.position import backtest as bt
from app.services.position import bsm
from app.services.position import contracts as pc
from app.services.position import plan as pp
from app.services.position import score as ps
from app.services.position import settings as pset
from app.services.trading import charges as costs

DAYS = [date(2026, 3, 2) + timedelta(days=i) for i in range(40) if (date(2026, 3, 2) + timedelta(days=i)).weekday() < 5]
EXPIRY = date(2026, 3, 26)


def candles(prices_by_day: dict[int, list[tuple]], start_minute=time(9, 15)):
    """Option candles: {day index: [(minute offset from 09:15, o, h, l, c), ...]}."""
    rows = []
    for di, items in prices_by_day.items():
        for m, o, h, l, c in items:
            rows.append((datetime.combine(DAYS[di], start_minute) + timedelta(minutes=m), o, h, l, c, 100.0, 5000.0))
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume", "oi"])


def flat(day, price, minutes=range(0, 375, 5)):
    return [(m, price, price + 0.5, price - 0.5, price) for m in minutes]


# ---------------------------------------------------------------- the simulator
def test_a_stop_is_hit_on_a_candle_low_and_a_gap_through_it_fills_at_the_open():
    base = {0: flat(0, 100), 1: flat(1, 100)}
    base[1] = [(m, 100, 100.5, 99.5, 100) for m in range(0, 200, 5)] + [(205, 100, 100.2, 60.0, 62.0)] + [(210, 62, 62.5, 61, 62)]
    fill, why = bt.simulate(candles(base), DAYS, 0, 3, EXPIRY)
    assert why is None and fill["reason"] == "stop_loss" and fill["exit"] == pytest.approx(100 * (1 - bt.STOP_PCT)) and fill["entry"] == 100.0
    gap = {0: flat(0, 100), 1: [(m, 100, 100.5, 99.5, 100) for m in range(0, 200, 5)] + [(205, 50.0, 55, 49, 52)]}
    fill, _ = bt.simulate(candles(gap), DAYS, 0, 3, EXPIRY)
    assert fill["reason"] == "stop_loss" and fill["exit"] == 50.0                          # the candle opened below the stop: filled at the open, not at the stop


def test_a_target_is_hit_on_a_candle_high_and_the_stop_wins_when_one_candle_touches_both():
    up = {0: flat(0, 100), 1: [(m, 100, 100.5, 99.5, 100) for m in range(0, 100, 5)] + [(100, 100, 175.0, 99, 170)]}
    fill, _ = bt.simulate(candles(up), DAYS, 0, 3, EXPIRY)
    assert fill["reason"] == "target" and fill["exit"] == pytest.approx(100 * (1 + bt.TARGET_PCT))
    both = {0: flat(0, 100), 1: [(m, 100, 100.5, 99.5, 100) for m in range(0, 100, 5)] + [(100, 100, 180.0, 60.0, 100)]}
    fill, _ = bt.simulate(candles(both), DAYS, 0, 3, EXPIRY)
    assert fill["reason"] == "stop_loss"                                                    # both touched on one candle: the stop is assumed first


def test_the_time_exit_is_the_close_of_the_last_hold_day_and_the_hold_counts_trading_days():
    quiet = {i: flat(i, 100 + i * 0.2) for i in range(0, 8)}
    fill, why = bt.simulate(candles(quiet), DAYS, 0, 3, EXPIRY)
    assert why is None and fill["reason"] == "time_exit" and fill["days"] == 3 and fill["ts"].date() == DAYS[3] and fill["ts"].time() >= time(15, 0)
    assert fill["exit"] == pytest.approx(100.6, abs=0.01)


def test_an_expiring_contract_is_closed_the_trading_day_before_expiry_even_if_the_hold_is_longer():
    near = DAYS[3]                                             # expiry on the 4th trading day
    quiet = {i: flat(i, 100) for i in range(0, 8)}
    fill, why = bt.simulate(candles(quiet), DAYS, 0, 10, near)
    assert why is None and fill["reason"] == "expiry_exit" and fill["ts"].date() == DAYS[2] and fill["days"] == 2


def test_a_trade_that_cannot_be_priced_is_reported_with_the_reason_never_filled_with_a_made_up_price():
    assert bt.simulate(candles({1: flat(1, 100)}), DAYS, 0, 3, EXPIRY)[1] == "no option candle at entry"
    late = {0: [(60, 100, 100, 100, 100)]}                                                  # the first candle is 10:15, an hour after the entry time
    assert bt.simulate(candles(late), DAYS, 0, 3, EXPIRY)[1] == "no option candle near the entry time"
    assert bt.simulate(candles({0: flat(0, 3.0), 1: flat(1, 3.0)}), DAYS, 0, 3, EXPIRY)[1] == "premium below the minimum"
    gone = {0: flat(0, 100), 1: flat(1, 100)}                                               # candles stop before the exit day
    fill, why = bt.simulate(candles(gone), DAYS, 0, 3, EXPIRY)
    assert fill is None and why == "no option candle on the exit day"


def test_expiry_choice_leaves_room_for_the_hold():
    exps = [date(2026, 3, 5), date(2026, 3, 12), date(2026, 3, 26), date(2026, 4, 30)]
    assert bt.expiry_for(date(2026, 3, 2), exps, 3) == date(2026, 3, 12)                    # ceil(4.5)+2 = 7 days beyond entry
    assert bt.expiry_for(date(2026, 3, 2), exps, 20) == date(2026, 4, 30)                   # a 20-day hold needs the monthly
    assert bt.expiry_for(date(2026, 4, 28), exps, 3) is None


def test_trade_pnl_uses_the_full_cost_stack_and_the_statistics_are_right():
    fill = {"entry": 100.0, "exit": 170.0, "ts": datetime(2026, 3, 4, 11, 0), "reason": "target", "days": 2}
    t = bt.trade_from(fill, "adx_trend", 3, 1, DAYS[0], DAYS[1], EXPIRY, 25000.0, "CE", 65)
    rt = costs.round_trip("BUY", 100.0, 170.0, 65)
    assert t.net == rt["net"] and t.gross == rt["gross"] == 4550.0 and t.net < t.gross and t.charges > 0 and t.slippage > 0
    mk = lambda net, d: bt.Trade("s", 3, 1, d, d, EXPIRY, 1, "CE", 1, 1, 1, datetime.combine(d, time(12)), "x", net, 0, 0, net, 1, "train")
    items = [mk(100, DAYS[0]), mk(-40, DAYS[1]), mk(-80, DAYS[2]), mk(60, DAYS[3])]
    s = bt.stats(items)
    assert s["trades"] == 4 and s["win_rate"] == 50.0 and s["net"] == 40 and s["profit_factor"] == pytest.approx(160 / 120, abs=0.01) and s["max_drawdown"] == 120
    assert bt.stats([])["win_rate"] is None


def test_a_strategy_is_robust_only_when_positive_in_all_three_periods_with_enough_trades():
    def trades(period_nets):
        out = []
        d0 = {"train": date(2023, 5, 1), "validation": date(2024, 5, 1), "out_of_sample": date(2025, 5, 1)}
        for per, nets in period_nets.items():
            for i, n in enumerate(nets):
                out.append(bt.Trade("s", 5, 1, d0[per], d0[per] + timedelta(days=i), EXPIRY, 1, "CE", 1, 1, 1, datetime.combine(d0[per], time(12)), "x", n, 0, 0, n, 1, per))
        return out
    good = {p: [50.0] * 25 for p in ("train", "validation", "out_of_sample")}
    rep = bt.report(trades(good), [])
    assert rep["cells"][0]["robust"] is True and bt.evidence_from(rep)["s"]["status"] == "positive"
    thin = {**good, "validation": [50.0] * 5}
    assert bt.report(trades(thin), [])["cells"][0]["robust"] is False                        # fewer than 20 validation trades is not evidence
    bad = {**good, "out_of_sample": [-10.0] * 25}
    r2 = bt.report(trades(bad), [])
    assert r2["cells"][0]["robust"] is False and bt.evidence_from(r2)["s"]["status"] == "negative"
    few = {p: [5.0] * 3 for p in good}
    assert bt.evidence_from(bt.report(trades(few), []))["s"]["status"] == "insufficient"
    rep3 = bt.report(trades(good), [{"strategy": "s", "hold": 5, "reason": "no option candle at entry"}] * 3)
    assert rep3["cells"][0]["unsimulatable"] == {"no option candle at entry": 3} and rep3["cells"][0]["unsimulatable_n"] == 3
    assert bt.period_of(date(2023, 12, 29)) == "train" and bt.period_of(date(2024, 1, 2)) == "validation" and bt.period_of(date(2025, 1, 2)) == "out_of_sample"


# ---------------------------------------------------------------- Black-Scholes estimates
def test_implied_volatility_recovers_the_volatility_a_premium_was_built_from_and_refuses_impossible_premiums():
    for typ in ("CE", "PE"):
        p = bsm.price(25000, 25200, 12 / 365, 0.16, typ)
        assert bsm.implied_vol(p, 25000, 25200, 12 / 365, typ) == pytest.approx(0.16, abs=1e-3)
    assert bsm.implied_vol(5.0, 25000, 24000, 10 / 365, "CE") is None                       # below intrinsic value: no volatility explains it
    assert bsm.implied_vol(100, 25000, 25000, 0, "CE") is None and bsm.implied_vol(0, 25000, 25000, 0.03, "CE") is None
    e = bsm.estimate(bsm.price(25000, 25000, 10 / 365, 0.14, "CE"), 25000, 25000, 10, "CE")
    assert e["available"] and e["theta_day"] < 0 and 0.45 < e["delta"] < 0.6 and "not market data" in e["note"]
    assert bsm.estimate(1.0, 25000, 20000, 10, "CE")["available"] is False


# ---------------------------------------------------------------- score
def row(**o):
    base = {"trend_w": 2, "trend": 2, "trend_4h": 2, "rsi": 60.0, "macd_hist": 5.0, "adx": 30.0, "plus_di": 30.0, "minus_di": 10.0, "vol_ratio": 1.6, "close": 25000.0, "atr": 200.0,
            "atr_pct": 0.8, "swing_hi": np.nan, "swing_lo": 24500.0, "hh": np.nan, "ll": 24400.0}
    base.update(o)
    return pd.Series(base)


def test_candle_components_add_to_85_and_a_perfect_setup_with_a_contract_and_levels_reaches_100():
    comps = ps.components(row(), 1)
    assert sum(c["max"] for c in comps) == 85 and ps.total(comps) == 85.0
    assert [c["key"] for c in comps] == ["weekly", "daily", "h4", "momentum", "volume", "sr", "volatility"]
    assert sum(m for _, _, m in ps.COMPONENTS) == 100 and ps.LATE_MAX == 15


def test_a_trade_against_the_trends_scores_low_and_missing_values_score_zero_and_are_flagged():
    against = ps.total(ps.components(row(), -1))
    assert against < 35
    miss = {c["key"]: c for c in ps.components(row(trend_w=np.nan, trend_4h=np.nan, vol_ratio=np.nan, atr=np.nan, atr_pct=np.nan), 1)}
    for k in ("weekly", "h4", "volume", "sr", "volatility"):
        assert not miss[k]["available"] and miss[k]["points"] == 0 and "not available" in miss[k]["note"]


def test_decisions_follow_the_thresholds_and_a_failed_gate_is_always_no_trade():
    assert ps.decide(1, 80, [])[0] == "STRONG BUY CE" and ps.decide(-1, 80, [])[0] == "STRONG BUY PE"
    assert ps.decide(1, 62, [])[0] == "BUY CE" and ps.decide(-1, 62, [])[0] == "BUY PE"
    assert ps.decide(1, 55, [])[0] == "HOLD" and ps.decide(0, 90, [])[0] == "HOLD"
    assert ps.decide(1, 95, ["no usable contract"])[0] == "NO TRADE"
    assert ps.decide(1, 65, [], buy=70)[0] == "HOLD"                                        # the minimum score is configurable
    assert ps.decide(1, 72, [], buy=80)[0] == "HOLD" and ps.decide(1, 82, [], buy=80)[0] == "STRONG BUY CE"


# ---------------------------------------------------------------- contracts and plan
def cand(**o):
    c = {"symbol": "s", "expiry": date(2026, 12, 10), "strike": 25000.0, "typ": "CE", "premium": 200.0, "volume": 120000.0, "oi": 250000.0, "dte": 14.0, "spot": 25000.0, "lot_size": 65, "offset": 0}
    c.update(o)
    return c


def test_contract_quality_rewards_liquidity_and_flags_missing_data_and_never_invents_a_spread():
    good = pc.evaluate(cand(), 200.0, 5)
    assert good["usable"] and good["quality"] > 6 and good["spread"]["available"] is False and "not stored" in good["spread"]["why"]
    blind = pc.evaluate(cand(volume=None, oi=None), 200.0, 5)
    assert "open interest not available" in " ".join(blind["notes"]) and blind["quality"] < good["quality"]
    cheap = pc.evaluate(cand(premium=3.0), 200.0, 5)
    assert not cheap["usable"] and "below" in cheap["reasons_unusable"][0]
    short = pc.evaluate(cand(dte=1.0), 200.0, 10)
    assert not short["usable"] and "1 days to expiry" in short["reasons_unusable"][-1]


def test_ranking_prefers_usable_contracts_and_the_explanation_names_why_the_others_rank_lower():
    a = pc.evaluate(cand(), 200.0, 5)
    b = pc.evaluate(cand(strike=25100.0, oi=20000.0, volume=1000.0, offset=100), 200.0, 5)
    c = pc.evaluate(cand(strike=24900.0, premium=3.0, offset=-100), 200.0, 5)
    ranked = pc.rank([c, b, a])
    assert ranked[0] is a and ranked[-1] is c
    text = pc.explain_choice(ranked[0], ranked[1:])
    assert "ranks lower" in text[1] and "lower quality" in text[1] and "not usable" in text[2]
    assert pc.atm(25024) == 25000 and pc.atm(25026) == 25050


def test_the_plan_uses_the_backtested_stop_and_target_sizes_by_risk_and_warns_about_expiry_and_gaps():
    est = bsm.estimate(200.0, 25000, 25000, 14, "CE")
    p = pp.build(direction=1, premium=200.0, est=est, atr=210.0, close=25000.0, swing=24600.0, lot_size=65, capital=500000.0, risk_pct=1.0, hold_days=5,
                 expiry=date(2026, 12, 10), decision_day=date(2026, 11, 26))
    assert p["stop_premium"] == pytest.approx(130.0, abs=0.1) and p["target1"] == pytest.approx(340.0, abs=0.1) and p["target2"] == pytest.approx(480.0, abs=0.1)
    assert p["entry"]["low"] < 200 < p["entry"]["high"] and p["invalidation"] == 24600.0
    assert p["lots"] >= 1 and p["max_loss"] <= 5000 + 1 and p["qty"] == p["lots"] * 65 and p["capital_required"] > 0
    assert p["risk_reward"]["ratio"] and 1.0 < p["risk_reward"]["ratio"] < 2.0              # costs push it under the gross 2.0
    assert any("overnight gap" in w for w in p["warnings"]) and any("theta" in w for w in p["warnings"]) and "not backtested" in p["trailing"]
    soon = pp.build(direction=-1, premium=120.0, est=None, atr=200.0, close=25000.0, swing=None, lot_size=65, capital=500000.0, risk_pct=1.0, hold_days=10,
                    expiry=date(2026, 12, 4), decision_day=date(2026, 11, 26))
    assert soon["planned_exit"] == "2026-12-03" and any("must be closed by 03 Dec" in w for w in soon["warnings"]) and any("could not be estimated" in w for w in soon["warnings"])
    assert soon["invalidation"] == 25400.0                                                   # no swing: two ATR beyond the close
    assert pp.add_trading_days(date(2026, 11, 26), 3) == date(2026, 12, 1)


# ---------------------------------------------------------------- settings
def test_settings_validate_refuses_bad_values_as_a_whole_and_keeps_defaults_for_the_rest():
    d = pset.defaults()
    assert len(d["strategies"]) == 9 and d["auto_enter"] is False and d["risk"]["max_open_positions"] == 3
    clean, errs = pset.validate({"risk": {"risk_pct": 2.0}, "strategies": {"adx_trend": {"enabled": False, "params": {"adx_min": 30}}}})
    assert not errs and clean["risk"]["risk_pct"] == 2.0 and clean["strategies"]["adx_trend"]["enabled"] is False and clean["strategies"]["adx_trend"]["params"]["adx_min"] == 30.0
    for bad in ({"risk": {"risk_pct": 50}}, {"risk": {"max_open_positions": 2.5}}, {"risk": {"nope": 1}}, {"strategies": {"magic": {}}}, {"strategies": {"adx_trend": {"params": {"x": 1}}}},
                {"strategies": {"adx_trend": {"params": {"adx_min": -1}}}}, {"auto_enter": "yes"}, {"zzz": 1}):
        assert pset.validate(bad)[1], bad
    assert pset.enabled_strategies(clean).keys() == set(d["strategies"]) - {"adx_trend"}


def test_live_groww_quotes_add_a_real_spread_and_real_iv_and_delta_and_a_wide_spread_makes_a_contract_unusable():
    live = pc.evaluate(cand(bid=199.0, ask=201.0, iv=0.15, delta=0.52, live=True), 200.0, 5)
    assert live["spread"]["available"] and live["spread"]["pct"] == pytest.approx(1.0, abs=0.05) and live["usable"]
    assert live["estimate"]["delta"] == 0.52 and live["estimate"]["iv"] == 0.15 and "from Groww" in live["estimate"]["note"] and live["estimate"]["theta_day"] < 0
    wide = pc.evaluate(cand(bid=180.0, ask=220.0, iv=0.15, delta=0.52), 200.0, 5)
    assert not wide["usable"] and any("spread" in r and "above 5%" in r for r in wide["reasons_unusable"]) and wide["quality"] < live["quality"] + 1
    assert pc.evaluate(cand(), 200.0, 5)["spread"]["available"] is False                    # no bid/ask: said so, nothing invented


def test_groww_iv_sent_in_percent_is_converted_before_it_reaches_the_model():
    e = pc.evaluate(cand(bid=199.0, ask=201.0, iv=15.2, delta=0.52), 200.0, 5)["estimate"]
    assert e["iv"] == pytest.approx(0.152) and -8 < e["theta_pct_day"] < 0                  # a sane theta, not -110% a day

"""Live dashboard insight: high/low, signal explanations, today's plan, candle patterns and chart data.
None of them may change the strategy's signal, look at the forming bar, or repaint."""
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from app.services.market_data import feed as lf
from app.services.strategy import insight, patterns, signals
from app.services.strategy import rules as st
from tests.test_live_feed import DAY, FakeApi, at, first_buy_time, make_feed, spot_path


@pytest.fixture(autouse=True)
def no_alert_store(monkeypatch):
    monkeypatch.setattr(lf, "record_signal", lambda *a: None)


def bars_of(rows, day=date(2026, 11, 11), tf=5):
    """Signal bars from (o, h, l, c) tuples, one per tf minutes from 09:15."""
    start = datetime.combine(day, time(9, 15))
    out = []
    for i, (o, h, l, c) in enumerate(rows):
        s = start + timedelta(minutes=tf * i)
        out.append({"start": pd.Timestamp(s), "close_ts": pd.Timestamp(s + timedelta(minutes=tf)), "day": day,
                    "open": o, "high": h, "low": l, "close": c})
    return pd.DataFrame(out)


FLAT = [(100, 101, 99, 100.5), (100.5, 101.5, 99.5, 100), (100, 101, 99, 100.6), (100.6, 101.4, 99.6, 100.1)] * 3


# ---------------------------------------------------------------- 1. high / low
def test_quote_high_low_distances():
    leg = first_buy_time()
    f, _ = make_feed(leg.entry_ts + timedelta(seconds=30), FakeApi(spot=25060.0))
    q = f.dashboard(tf=5)["quote"]
    assert (q["high"], q["low"], q["prev_close"]) == (25100, 24950, 25000)        # Groww's quote, as returned
    assert q["from_high"] == 25060 - 25100 and q["from_low"] == 25060 - 24950
    assert q["range_pct"] == pytest.approx((25060 - 24950) / (25100 - 24950) * 100, abs=0.1)
    assert q["state"] == "live" and q["as_of"]


def test_quote_unavailable_is_flagged():
    f, _ = make_feed(at("11:00:30"), FakeApi(fail={"get_quote"}))
    q = f.dashboard(tf=5)["quote"]
    assert q["state"] == "unavailable" and "timed out" in q["error"] and "from_high" not in q


# ---------------------------------------------------------------- 2. explanations
def test_buy_explanation_uses_actual_values():
    leg = first_buy_time()
    f, _ = make_feed(leg.entry_ts + timedelta(seconds=30))
    d = f.dashboard(tf=5)
    assert d["signal"]["action"] == "BUY CE"
    e = d["explain"]
    bar = [b for b in d["chart"]["bars"] if b["t"] == (leg.entry_ts - timedelta(minutes=5)).isoformat()][0]
    ema = e["checks"][0]
    assert ema["values"]["ema9"] == bar["e9"] and ema["values"]["ema21"] == bar["e21"]
    assert "crossed above" in ema["text"] and f"{bar['e9']:,.2f}" in ema["text"]
    rsi = next(c for c in e["checks"] if c["key"] == "rsi")
    assert rsi["values"]["rsi"] == bar["rsi"] and f"{bar['rsi']:.1f}" in rsi["text"]
    macd = next(c for c in e["checks"] if c["key"] == "macd")
    assert macd["status"] == ("supports" if bar["macd_hist"] > 0 else "against")
    assert next(c for c in e["checks"] if c["key"] == "vwap")["status"] == "unavailable"   # no futures in the fake
    assert "inside the window" in e["why"] and "rather than HOLD" in e["why"]
    assert "Not scored" in e["confidence"]["text"]          # no model for an injected market


def test_hold_explanation_states_what_is_needed():
    f, _ = make_feed(at("09:50:30"))
    d = f.dashboard(tf=5)
    assert d["signal"]["action"] == "HOLD"
    e = d["explain"]
    assert e["summary"].startswith("HOLD") and "A new entry needs EMA 9 to close" in e["why"]
    assert e["confidence"] is None


def test_checks_classify_by_value():
    r = pd.Series({"fut_close": 101.0, "fut_vwap": 100.0, "rsi": 47.0, "macd_hist": -0.5, "fut_volume": 1300.0, "vol_avg20": 1000.0})
    reg = pd.Series({"regime": "bullish", "trend_sign": 1.0, "sma": 99.0, "close": 100.0})
    c = {x["key"]: x["status"] for x in insight.checks(r, 1, reg)}
    assert c == {"vwap": "supports", "rsi": "neutral", "macd": "against", "volume": "supports", "trend": "supports"}
    c = {x["key"]: x["status"] for x in insight.checks(r, -1, reg)}
    assert c["vwap"] == "against" and c["macd"] == "supports" and c["trend"] == "against"


def test_explanation_with_model_reports_band_and_hit_rate():
    leg = first_buy_time()
    f, _ = make_feed(leg.entry_ts + timedelta(seconds=30))
    d = f.dashboard(tf=5)

    class FakeScorer:
        def score(self, feats):
            assert set(feats) == {k for k, _, _ in signals.FEATURES}
            return 74.0

        def comparable(self, s):
            return {"band": "Strong signal", "n": 120, "hit_rate": 41.5}
    bars = f.bars(DAY, 5)[0]
    e = insight.explain(d["signal"], bars[bars["close_ts"] <= pd.Timestamp(leg.entry_ts)], DAY, 5, None, FakeScorer())
    assert e["confidence"]["score"] == 74.0 and "41.5%" in e["confidence"]["text"] and "not a probability" in e["confidence"]["text"]


def test_explanation_never_changes_the_signal():
    leg = first_buy_time()
    f, _ = make_feed(leg.entry_ts + timedelta(seconds=30))
    d = f.dashboard(tf=5)
    bars = st.add_emas(st.resample(spot_path(leg.entry_ts + timedelta(seconds=30)), 5))
    assert d["signal"]["action"] == lf.signal_state(bars, DAY, leg.entry_ts + timedelta(seconds=30), "09:30", "14:30")["action"]


# ---------------------------------------------------------------- 4. today's plan
def test_pivots():
    p = insight.pivots(110, 90, 100)
    assert p == {"P": 100, "R1": 110, "S1": 90, "R2": 120, "S2": 80}


def test_plan_levels_and_opening_range():
    leg = first_buy_time()
    now = leg.entry_ts + timedelta(seconds=30)
    f, _ = make_feed(now)
    d = f.dashboard(tf=5)
    p = d["plan"]
    names = {l["name"] for l in p["levels"]}
    assert {"Pivot", "Pivot R1", "Pivot S1", "Previous day high", "Previous day low", "Opening range high"} <= names
    today = spot_path(now)
    first = today[(today["ts"].dt.date == DAY) & (today["ts"] < pd.Timestamp(datetime.combine(DAY, time(9, 30))))]
    assert p["opening_range"] == {"high": round(first["high"].max(), 2), "low": round(first["low"].min(), 2)}
    assert p["bullish_level"] == p["opening_range"]["high"] and p["bearish_level"] == p["opening_range"]["low"]
    assert all("calculated" in l["source"] or "candles" in l["source"] for l in p["levels"])
    assert {s["key"] for s in p["scenarios"]} == {"bullish", "bearish", "sideways"}
    assert sum(s["active"] for s in p["scenarios"]) == 1
    assert p["changes"][0]["reason"] == "Session plan created." and p["created_at"]


def test_plan_before_opening_range_uses_previous_day():
    f, _ = make_feed(at("09:25:30"))
    p = f.dashboard(tf=5)["plan"]
    assert p["opening_range"] is None and p["bullish_level"] == next(l["price"] for l in p["levels"] if l["name"] == "Previous day high")


def test_plan_change_reason():
    base = {"preferred": "none", "bullish_level": 10.0, "bearish_level": 5.0, "opening_range": None, "votes": {"bull": 2, "bear": 1}}
    assert insight.plan_change_reason(None, base) == "Session plan created."
    assert insight.plan_change_reason(base, dict(base)) is None
    new = {**base, "preferred": "bullish", "votes": {"bull": 3, "bear": 0}}
    assert "Preferred direction none → bullish" in insight.plan_change_reason(base, new)
    formed = {**base, "bullish_level": 12.0, "opening_range": {"high": 12.0, "low": 4.0}, "bearish_level": 4.0}
    assert "opening range formed" in insight.plan_change_reason(base, formed).lower()


def test_plan_updates_are_recorded_once_per_change():
    f, m = make_feed(at("09:25:30"))
    f.dashboard(tf=5)
    f.dashboard(tf=5)                                   # nothing changed
    m.clock = at("10:05:30")
    p = f.dashboard(tf=5)["plan"]
    assert p["changes"][0]["reason"] == "Session plan created." and len(p["changes"]) >= 2
    assert len({c["reason"] for c in p["changes"]}) == len(p["changes"])


# ---------------------------------------------------------------- 5. candle patterns
def test_bullish_and_bearish_engulfing():
    b = bars_of(FLAT[:6] + [(101, 101.2, 98, 98.5), (98.2, 102.5, 98, 102.2), (102, 102.3, 101.5, 102.1)])
    p = [x for x in patterns.detect(b) if x["name"] == "Bullish engulfing" and x["o"] == 98.2]
    assert p and p[0]["o"] == 98.2 and p[0]["c"] == 102.2 and p[0]["status"] == "not confirmed"   # next close 102.1 < 102.2
    b = bars_of(FLAT[:6] + [(98, 101.5, 97.8, 101.2), (101.4, 101.6, 97, 97.5)])
    p = [x for x in patterns.detect(b) if x["name"] == "Bearish engulfing" and x["o"] == 101.4]
    assert p and p[0]["bias"] == "bearish" and p[0]["status"] == "awaiting confirmation"


def test_hammer_shooting_star_doji():
    down = [(105, 105.5, 104, 104.2), (104.2, 104.5, 103, 103.2), (103.2, 103.4, 102, 102.1), (102.1, 102.3, 101, 101.2)]
    b = bars_of(down + [(100.0, 101.25, 98.0, 101.0), (101.0, 102.4, 100.9, 102.2)])   # body 1.0, lower wick 2.0
    hammer = [x for x in patterns.detect(b) if x["name"] == "Hammer"]
    assert hammer and hammer[0]["status"] == "confirmed"
    up = [(100, 101, 99.8, 100.9), (100.9, 102, 100.8, 101.9), (101.9, 103, 101.8, 102.9), (102.9, 104, 102.8, 103.9)]
    b = bars_of(up + [(105.0, 107.0, 103.9, 104.0)])   # body 1.0, upper wick 2.0
    assert any(x["name"] == "Shooting star" for x in patterns.detect(b))
    b = bars_of(FLAT[:4] + [(100.0, 102.0, 98.0, 100.1)])
    d = [x for x in patterns.detect(b) if x["name"] == "Doji"]
    assert d and d[-1]["bias"] == "neutral" and "no effect" in patterns.effect(d[-1], "BUY CE").lower()


def test_morning_evening_star_strong_and_breakout():
    pre = FLAT[:6]
    b = bars_of(pre + [(103, 103.2, 99, 99.2), (99.1, 99.5, 98.6, 99.0), (99.2, 102.6, 99.1, 102.4)])
    assert any(x["name"] == "Morning star" for x in patterns.detect(b))
    b = bars_of(pre + [(99, 103.2, 98.8, 103.0), (103.1, 103.5, 102.8, 103.2), (103.0, 103.1, 99.5, 99.8)])
    assert any(x["name"] == "Evening star" for x in patterns.detect(b))
    b = bars_of(FLAT * 2 + [(100.5, 106.2, 100.4, 106.0)])
    names = {x["name"] for x in patterns.detect(b)}
    assert {"Strong bullish candle", "Breakout"} <= names
    b = bars_of(FLAT * 2 + [(100.0, 100.1, 94.0, 94.2)])
    assert {"Strong bearish candle", "Breakdown"} <= {x["name"] for x in patterns.detect(b)}


def test_patterns_use_closed_bars_only_and_never_repaint():
    rows = FLAT[:6] + [(101, 101.2, 98, 98.5), (98.2, 102.5, 98, 102.2), (102, 103, 101.9, 102.9), (102.9, 103.5, 102.5, 103.2)]
    b = bars_of(rows)
    full = patterns.detect(b)
    for k in range(3, len(b)):
        part = patterns.detect(b.iloc[:k])
        # every pattern found on a prefix is still found, at the same bar, with the same OHLC
        for p in part:
            assert any(q["name"] == p["name"] and q["ts"] == p["ts"] and q["c"] == p["c"] for q in full)
    # the bar still forming (close_ts after now) is never analysed
    now = b["close_ts"].iloc[-2] + timedelta(seconds=30)
    assert all(pd.Timestamp(p["close_ts"]) <= now for p in patterns.detect(b, now))


def test_pattern_effect_never_overrides():
    p = {"bias": "bearish"}
    assert "Conflicts with BUY CE" in patterns.effect(p, "BUY CE") and "keeps its signal" in patterns.effect(p, "BUY CE")
    assert "Agrees" in patterns.effect({"bias": "bullish"}, "BUY CE")
    assert "needs an EMA 9/21 crossover" in patterns.effect({"bias": "bullish"}, "HOLD")


# ---------------------------------------------------------------- chart data
def test_chart_bars_markers_and_one_minute():
    leg = first_buy_time()
    now = leg.entry_ts + timedelta(minutes=20)
    f, _ = make_feed(now)
    d = f.dashboard(tf=5)
    b = d["chart"]["bars"][-1]
    assert {"e9", "e21", "rsi", "macd", "macd_signal", "macd_hist", "vwap", "v"} <= set(b)
    assert all(pd.Timestamp(x["t"]) + timedelta(minutes=5) <= pd.Timestamp(now) for x in d["chart"]["bars"])   # closed only
    assert d["markers"][0] == {"ts": leg.entry_ts.isoformat(), "kind": "entry", "action": "BUY CE"}
    one = make_feed(now)[0].dashboard(tf=1)
    assert one["timeframe"] == 1 and len(one["chart"]["bars"]) > len(d["chart"]["bars"])


def test_patterns_in_dashboard_have_effect_and_ohlc():
    leg = first_buy_time()
    f, _ = make_feed(leg.entry_ts + timedelta(minutes=30))
    pats = f.dashboard(tf=5)["patterns"]
    assert pats and all({"name", "ts", "bias", "o", "h", "l", "c", "status", "effect", "confirmation"} <= set(p) for p in pats)


def test_missing_candles_and_api_disconnection():
    f, _ = make_feed(at("11:00:30"))
    f.market.spot_1m = lambda day: (_ for _ in ()).throw(RuntimeError("Groww candles timed out"))
    d = f.dashboard(tf=5)
    assert d["chart"]["bars"] == [] and d["signal"]["action"] == "HOLD" and "timed out" in d["bars_error"]

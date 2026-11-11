"""Live dashboard feed: signal state, contract selection, quote verification, sizing, data checks.

No network: Groww is replaced by a fake API and market that return Groww-shaped responses.
"""
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

import costs
import live_feed as lf
import strategy as st
from live_market import Contract

DAY = date(2026, 11, 11)          # a Wednesday
PREV = date(2026, 11, 10)
EXPIRY = date(2026, 11, 17)


# ---------------------------------------------------------------- helpers
def bars_from_gaps(gaps: list[float], day: date = DAY, tf: int = 5) -> pd.DataFrame:
    """Bars whose EMA9 - EMA21 follows `gaps` (only the sign matters to the strategy)."""
    starts = [datetime.combine(day, time(9, 15)) + timedelta(minutes=tf * i) for i in range(len(gaps))]
    close = [25000.0 + i for i in range(len(gaps))]
    return pd.DataFrame({"start": starts, "close_ts": [s + timedelta(minutes=tf) for s in starts],
                         "open": close, "high": close, "low": close, "close": close, "day": [day] * len(gaps),
                         "ema9": [25000 + g for g in gaps], "ema21": [25000.0] * len(gaps)})


def gaps_with(cross_at: dict[str, int], n: int = 75, start: int = -1) -> list[float]:
    """Sign path for a day of 5m bars; cross_at maps bar close 'HH:MM' -> new sign."""
    sign, out = start, []
    for i in range(n):
        close = (datetime.combine(DAY, time(9, 15)) + timedelta(minutes=5 * (i + 1))).strftime("%H:%M")
        sign = cross_at.get(close, sign)
        out.append(sign * 5.0)
    return out


def at(hhmm: str, d: date = DAY) -> datetime:
    return datetime.combine(d, time(*map(int, hhmm.split(":"))))


# ---------------------------------------------------------------- signal_state
def test_no_cross_is_hold_without_alert():
    s = lf.signal_state(bars_from_gaps(gaps_with({})), DAY, at("11:00"), "09:30", "14:30")
    assert s["action"] == "HOLD" and s["alert"] is False


def test_bullish_cross_in_window_is_buy_ce_until_reversal():
    b = bars_from_gaps(gaps_with({"10:00": 1, "11:00": -1}))
    s = lf.signal_state(b, DAY, at("10:30"), "09:30", "14:30")
    assert s["action"] == "BUY CE" and s["since"] == "2026-11-11T10:00:00" and s["alert"]
    s = lf.signal_state(b, DAY, at("11:00"), "09:30", "14:30")
    assert s["action"] == "BUY PE" and s["since"] == "2026-11-11T11:00:00"     # reversal inside window


def test_signal_uses_completed_bars_only():
    b = bars_from_gaps(gaps_with({"10:00": 1}))
    assert lf.signal_state(b, DAY, at("09:59"), "09:30", "14:30")["action"] == "HOLD"
    assert lf.signal_state(b, DAY, at("10:00"), "09:30", "14:30")["action"] == "BUY CE"


def test_opposite_cross_after_cutoff_exits_to_hold():
    b = bars_from_gaps(gaps_with({"10:00": 1, "14:45": -1}))
    s = lf.signal_state(b, DAY, at("14:50"), "09:30", "14:30")
    assert s["action"] == "HOLD" and "closed the CE trade" in s["reason"] and s["alert"]


def test_square_off_at_15_is_hold():
    b = bars_from_gaps(gaps_with({"10:00": 1}))
    assert lf.signal_state(b, DAY, at("14:59"), "09:30", "14:30")["action"] == "BUY CE"
    s = lf.signal_state(b, DAY, at("15:05"), "09:30", "14:30")
    assert s["action"] == "HOLD" and "15:00" in s["reason"]


def test_cross_before_window_is_not_traded():
    s = lf.signal_state(bars_from_gaps(gaps_with({"09:25": 1})), DAY, at("09:40"), "09:30", "14:30")
    assert s["action"] == "HOLD" and "before the 09:30" in s["reason"] and s["alert"]


def test_signal_state_agrees_with_generate_legs():
    b = bars_from_gaps(gaps_with({"09:50": 1, "10:40": -1, "12:00": 1, "14:40": -1}))
    legs, _ = st.generate_legs(b, {DAY}, time(9, 30), time(14, 30))
    for leg in legs:
        s = lf.signal_state(b, DAY, leg.entry_ts + timedelta(minutes=1), "09:30", "14:30")
        assert s["action"] == ("BUY CE" if leg.direction > 0 else "BUY PE")
        assert s["since"] == pd.Timestamp(leg.entry_ts).isoformat()


# ---------------------------------------------------------------- sizing
def test_size_limited_by_risk():
    z = lf.size_position(200, 180, 240, 65, capital=100000, risk_pct=5, available=None)
    lot_risk = 20 * 65 + costs.charges(200, 180, 65)["total"]
    assert z["lots"] == int(5000 // lot_risk) == 3 and z["qty"] == 195 and z["limited_by"] == "risk"
    assert z["investment"] == 200 * 195
    assert z["max_risk"] == round(20 * 195 + costs.charges(200, 180, 195)["total"], 2) <= 5000
    assert z["target_profit"] == round(40 * 195 - costs.charges(200, 240, 195)["total"], 2)
    assert z["stop_loss"] == -z["max_risk"]


def test_size_limited_by_margin_and_whole_lots():
    z = lf.size_position(200, 180, 240, 65, capital=100000, risk_pct=50, available=30000)
    assert z["lots"] == 2 and z["limited_by"] == "margin"          # 2 x 13,000 + charges fits 30,000
    assert z["qty"] % 65 == 0


def test_size_zero_lots_explains_why():
    z = lf.size_position(200, 180, 240, 65, capital=100000, risk_pct=1, available=None)
    assert z["lots"] == 0 and "risk budget" in z["note"] and "investment" not in z
    z = lf.size_position(200, 180, 240, 65, capital=100000, risk_pct=50, available=5000)
    assert z["lots"] == 0 and "available" in z["note"]


# ---------------------------------------------------------------- data checks
def _m1(prices, end="11:00"):
    e = at(end)
    ts = [e - timedelta(minutes=len(prices) - i) for i in range(len(prices))]
    return pd.DataFrame({"ts": pd.to_datetime(ts), "open": prices, "high": prices, "low": prices, "close": prices})


def test_data_checks():
    moving = _m1([25000, 25003, 24998, 25005, 25010])
    assert lf.data_checks(moving, {"price": 25012}, at("11:00:20")) == []
    frozen = _m1([25000, 25130, 25130, 25130, 25130])
    assert any("frozen" in w for w in lf.data_checks(frozen, {"price": 25130}, at("11:00:20")))
    assert any("differ" in w for w in lf.data_checks(moving, {"price": 25582}, at("11:00:20")))


# ---------------------------------------------------------------- fake Groww
def spot_path(now: datetime, cross: str = "10:00") -> pd.DataFrame:
    """Prior day drifting down, today flat then rising from `cross`: a bullish 5m cross near it."""
    rows = []
    for d, f in ((PREV, lambda i: 25300 - i * 0.6), (DAY, None)):
        t = datetime.combine(d, time(9, 15))
        i = 0
        while t.time() < time(15, 30) and (d != DAY or t + timedelta(minutes=1) <= now):
            if f:
                p = f(i)
            else:
                k = (t - at(cross)).total_seconds() / 60
                p = 25000 - i * 0.2 if k < -30 else 24994 + max(0.0, k + 30) * 1.5
            rows.append((t, p, p + 2, p - 2, p + 0.5))
            t += timedelta(minutes=1); i += 1
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"]).assign(ts=lambda d: pd.to_datetime(d["ts"]))


class FakeMarket:
    def __init__(self, now):
        self.clock = now

    def now(self):
        return self.clock

    def spot_1m(self, day):
        return spot_path(self.clock)

    def expiries(self, day):
        return [date(2026, 11, 11), EXPIRY, date(2026, 11, 23)]

    def contract(self, day, expiry, strike, typ):
        sym = f"NIFTY26N17{int(strike)}{typ}"
        return Contract(sym, f"NSE-NIFTY-17Nov26-{int(strike)}-{typ}", expiry, float(strike), typ, 65)


class FakeApi:
    def __init__(self, spot=25060.0, premium=212.4, fail=()):
        self.spot, self.premium, self.fail, self.calls = spot, premium, set(fail), []

    def __call__(self, fn, **kw):
        self.calls.append((fn, kw))
        if fn in self.fail:
            raise RuntimeError(f"{fn} timed out")
        if fn == "get_quote" and kw["segment"] == "CASH":
            return {"last_price": self.spot, "day_change": 60.0, "day_change_perc": 0.24,
                    "ohlc": {"open": 25000, "high": 25100, "low": 24950, "close": 25000}}
        if fn == "get_quote":
            if "quote_fno" in self.fail:
                raise RuntimeError("quote failed")
            return {"last_price": self.premium, "depth": {"sell": [{"price": self.premium + 0.4}, {"price": self.premium + 0.6}]}}
        if fn == "get_option_chain":
            strikes = {}
            for k in range(24500, 25600, 50):
                strikes[str(k)] = {t: {"trading_symbol": f"NIFTY26N17{k}{t}", "ltp": 200.0,
                                       "greeks": {"delta": 0.5 if t == "CE" else -0.5, "iv": 15.0}}
                                   for t in ("CE", "PE")}
            return {"underlying_ltp": self.spot, "strikes": strikes}
        if fn == "get_available_margin_details":
            return {"fno_margin_details": {"option_buy_balance_available": 60000.0}}
        raise AssertionError(fn)


@pytest.fixture
def no_alert_store(monkeypatch):
    stored = []
    monkeypatch.setattr(lf, "record_signal", lambda *a: stored.append(a))
    return stored


def make_feed(now, api=None):
    m = FakeMarket(now)
    return lf.Feed(market=m, api=api or FakeApi(), clock=m.now), m


def first_buy_time():
    """First bar close at which the fake path gives a BUY (found, not assumed)."""
    b = st.add_emas(st.resample(spot_path(at("15:29")), 5))
    legs, _ = st.generate_legs(b, {DAY}, time(9, 30), time(14, 30))
    return legs[0]


def test_dashboard_recommends_verified_contract(no_alert_store):
    leg = first_buy_time()
    assert leg.direction == 1
    now = leg.entry_ts + timedelta(seconds=30)
    api = FakeApi()
    f, _ = make_feed(now, api)
    d = f.dashboard(tf=5, capital=None, risk_pct=2)
    assert d["quote"]["state"] == "live" and d["warnings"] == []
    s = d["signal"]
    assert s["action"] == "BUY CE"
    r = s["rec"]
    assert r["verified"] and not r.get("error")
    assert r["strike"] == st.atm_strike(25060.0) == 25050 and r["opt_type"] == "CE"
    assert r["expiry"] == EXPIRY.isoformat()                      # expiry day itself is rolled
    assert r["symbol"] == "NIFTY26N1725050CE" and r["lot_size"] == 65
    assert r["premium"] == 212.4 and r["premium"] != d["quote"]["price"]
    assert r["entry"] == 212.8                                    # best offer
    assert r["stop"] < r["entry"] < r["target"]
    z = r["sizing"]
    assert z["available"] == 60000 and z["capital"] == 60000 and z["qty"] == z["lots"] * 65
    assert z["max_risk"] <= z["risk_budget"]
    assert no_alert_store and no_alert_store[-1][4]["action"] == "BUY CE"
    # chart: completed bars only, EMAs on every bar, forming bar after them
    ch = d["chart"]
    assert ch["day"] == DAY.isoformat() and all(pd.Timestamp(b["t"]) + timedelta(minutes=5) <= pd.Timestamp(now) for b in ch["bars"])
    assert ch["forming"]["c"] == 25060.0


def test_itm5_and_pe_strikes():
    assert st.option_for("ITM5_BUY", 1, 25060)[:2] == (24800.0, "CE")
    assert st.option_for("ITM5_BUY", -1, 25060)[:2] == (25300.0, "PE")


def test_unverified_option_quote_gives_no_size(no_alert_store):
    now = first_buy_time().entry_ts + timedelta(seconds=30)
    f, _ = make_feed(now, FakeApi(fail={"quote_fno"}))
    r = f.dashboard(tf=5)["signal"]["rec"]
    assert not r["verified"] and "could not be verified" in r["error"] and "sizing" not in r


def test_premium_equal_to_index_is_rejected(no_alert_store):
    now = first_buy_time().entry_ts + timedelta(seconds=30)
    f, _ = make_feed(now, FakeApi(premium=25060.0))
    r = f.dashboard(tf=5)["signal"]["rec"]
    assert "sizing" not in r and "index price" in r["error"]


def test_chain_symbol_must_match_instrument_master(no_alert_store, monkeypatch):
    now = first_buy_time().entry_ts + timedelta(seconds=30)
    f, m = make_feed(now)
    monkeypatch.setattr(m, "contract", lambda *a: Contract("OTHER", "x", EXPIRY, 25050.0, "CE", 65))
    r = f.dashboard(tf=5)["signal"]["rec"]
    assert not r["verified"] and "does not match" in r["error"]


def test_quote_failure_marks_delayed_then_backs_off(no_alert_store):
    now = first_buy_time().entry_ts + timedelta(seconds=30)
    api = FakeApi()
    f, m = make_feed(now, api)
    assert f.dashboard(tf=5)["quote"]["state"] == "live"
    api.fail.add("get_quote")
    m.clock = now + timedelta(seconds=20)
    f._c["quote"].fetched -= 10                         # TTL expired
    d = f.dashboard(tf=5)
    assert d["quote"]["state"] == "delayed" and d["quote"]["price"] == 25060.0 and d["quote"]["error"]
    assert d["signal"]["rec"]["verified"] is False         # never recommend on a delayed quote
    n = sum(1 for c in api.calls if c[0] == "get_quote")
    f.dashboard(tf=5)                                      # inside the backoff window: no new request
    assert sum(1 for c in api.calls if c[0] == "get_quote") == n


def test_unavailable_quote_with_no_history():
    f, _ = make_feed(at("10:30"), FakeApi(fail={"get_quote"}))
    q = f.quote(True)
    assert q["state"] == "unavailable" and q.get("price") is None


def test_market_closed_never_recommends(no_alert_store):
    f, _ = make_feed(datetime(2026, 11, 14, 11, 0))      # Saturday
    d = f.dashboard(tf=5)
    assert d["market"]["state"] == "closed" and d["quote"]["state"] == "closed"
    assert d["signal"]["action"] == "HOLD" and "rec" not in d["signal"]
    assert not [c for c in f.api.calls if c[0] == "get_option_chain"]


def test_frozen_candles_block_recommendation(no_alert_store, monkeypatch):
    now = first_buy_time().entry_ts + timedelta(seconds=30)
    f, m = make_feed(now)
    base = spot_path(now)
    frozen = base.copy()
    frozen.loc[frozen.index[-5:], ["open", "high", "low", "close"]] = 25060.0
    monkeypatch.setattr(m, "spot_1m", lambda day: frozen)
    d = f.dashboard(tf=5)
    assert d["warnings"] and d["chart"]["forming"] is None
    if d["signal"]["action"] != "HOLD":
        assert d["signal"]["rec"]["verified"] is False


def test_signal_alert_is_stored_once():
    """Real DB round trip (throwaway database): a repeated poll never alerts the same signal twice."""
    import psycopg2
    from sqlalchemy import text
    import config
    import db
    name = "groww_trading_test_feed"
    try:
        conn = psycopg2.connect(**{**config.PG, "dbname": "postgres"})
    except Exception:
        pytest.skip("PostgreSQL not available")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {name}")
    old = db._engine
    db._engine = db.engine(name)
    try:
        db.init()
        sig = {"action": "BUY CE", "since": "2026-11-11T10:00:00", "reason": "test", "direction": "Bullish", "nifty": 1.0}
        for _ in range(3):
            lf.record_signal(DAY, 5, "09:30", "14:30", sig, at("10:00"))
        lf.record_signal(DAY, 5, "09:30", "14:30", {**sig, "action": "HOLD", "since": "2026-11-11T14:45:00"}, at("14:45"))
        import live_manager
        alerts = live_manager.recent_alerts(("signal", "paper"))
        assert [a["action"] for a in alerts] == ["HOLD", "BUY CE"] and alerts[0]["mode"] == "signal"
    finally:
        db._engine.dispose()
        db._engine = old
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.close()

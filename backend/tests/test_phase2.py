"""Phase 2: score calibration (out-of-sample only, no look-ahead) and the live option chain.

No network and no database: Groww is replaced by a fake API and market.
"""
from datetime import date, datetime

import numpy as np
import pytest

from app.services.market_data import feed as lf
from app.services.strategy import insight, signals

DAY = date(2026, 11, 12)
EXPIRY = date(2026, 11, 17)


# ---------------------------------------------------------------- calibration helpers
def test_wilson_interval_known_values():
    assert signals.wilson(0, 0) is None
    lo, hi = signals.wilson(50, 100)
    assert lo == pytest.approx(40.4, abs=0.1) and hi == pytest.approx(59.6, abs=0.1)
    lo, hi = signals.wilson(0, 10)
    assert lo == 0.0 and 0 < hi < 35          # never a negative or zero-width range
    lo, hi = signals.wilson(10, 10)
    assert hi == 100.0 and lo > 65


def _data(n_per_year=400, years=(2022, 2023, 2024, 2025), informative=True, seed=1):
    rng = np.random.default_rng(seed)
    yrs, sc, y = [], [], []
    for yr in years:
        s = rng.uniform(5, 60, n_per_year)
        p = s / 100 if informative else np.full(n_per_year, 0.3)
        yrs += [yr] * n_per_year
        sc += list(s)
        y += list((rng.uniform(size=n_per_year) < p).astype(float))
    return np.array(yrs), np.array(sc), np.array(y)


def test_calibrator_is_monotonic_and_bounded():
    _, s, y = _data()
    cal = signals.fit_calibrator(s, y)
    out = signals.apply_calibrator(cal, np.array([1.0, 10, 30, 50, 90]))
    assert np.all(np.diff(out) >= 0) and out.min() >= 0 and out.max() <= 100
    assert signals.fit_calibrator(s[:10], y[:10]) is None            # too few signals
    assert signals.fit_calibrator(s, np.zeros_like(y)) is None        # one outcome only


def test_walk_forward_calibration_has_no_look_ahead():
    yrs, s, y = _data()
    a = signals.walk_forward_calibration(yrs, s, y)
    assert [f["year"] for f in a["folds"]] == [2023, 2024, 2025]      # the first year has nothing earlier to learn from
    assert a["folds"][0]["trained_on"] == 400 and a["folds"][2]["trained_on"] == 1200
    # Changing the LAST year's outcomes must not change any earlier year's result.
    y2 = y.copy()
    y2[yrs == 2025] = 1 - y2[yrs == 2025]
    b = signals.walk_forward_calibration(yrs, s, y2)
    assert a["folds"][:2] == b["folds"][:2] and a["folds"][2] != b["folds"][2]


def test_informative_score_beats_the_average_and_noise_does_not():
    yrs, s, y = _data(informative=True)
    good = signals.walk_forward_calibration(yrs, s, y)
    assert good["skill"] > 0
    ci = signals.auc_interval(s[yrs > 2022], y[yrs > 2022])
    assert ci[0] > 0.5 and signals.verdict(ci, good)["edge"] is True

    yrs, s, y = _data(informative=False)
    bad = signals.walk_forward_calibration(yrs, s, y)
    ci = signals.auc_interval(s[yrs > 2022], y[yrs > 2022])
    v = signals.verdict(ci, bad)
    assert v["edge"] is False and ("No proven edge" in v["text"] or "Weak" in v["text"])


def test_auc_interval_is_reproducible():
    _, s, y = _data()
    assert signals.auc_interval(s, y) == signals.auc_interval(s, y)
    assert signals.auc_interval(s[:5], y[:5]) is None


def test_verdict_without_later_years():
    v = signals.verdict((0.6, 0.8), {"skill": None})
    assert v["edge"] is False and "enough later years" in v["text"]
    assert signals.verdict(None, {})["edge"] is False


def _analysis(calibrator=True):
    return {"generated_at": "2026-11-12T18:00:00",
            "model": {"params": {"w": [0.0] + [0.1] * len(signals.FEATURES), "mu": [0.0] * len(signals.FEATURES),
                                 "sd": [1.0] * len(signals.FEATURES)},
                      "calibrator": {"w": [-1.0, 0.5], "mu": [0.0], "sd": [1.0], "n": 500} if calibrator else None,
                      "verdict": {"edge": False, "text": "No proven edge: test."} if calibrator else None},
            "calibration": [{"band": "No strong signal", "from": 0, "to": 50, "n": 500, "hit_rate": 25.0, "ci": [21.4, 29.0]},
                            {"band": "Watch / Moderate signal", "from": 50, "to": 70, "n": 30, "hit_rate": 40.0, "ci": [24.6, 57.7]}]}


def test_scorer_score_is_unchanged_by_calibration():
    feats = {k: 0.5 for k, _, _ in signals.FEATURES}
    a, b = signals.Scorer(_analysis(True)), signals.Scorer(_analysis(False))
    assert a.score(feats) == b.score(feats)                           # prediction mode compares this raw score
    ca, cb = a.comparable(30.0), b.comparable(30.0)
    assert ca["hit_rate"] == cb["hit_rate"] == 25.0 and ca["ci"] == [21.4, 29.0]
    assert ca["calibrated"] is not None and 0 <= ca["calibrated"] <= 100 and ca["verdict"]["edge"] is False
    assert cb["calibrated"] is None and cb["verdict"] is None         # an older analysis still works


def test_live_confidence_text_shows_range_estimate_and_verdict(monkeypatch):
    class S:
        def score(self, feats):
            return 30.0

        def comparable(self, s):
            return {"band": "No strong signal", "n": 500, "hit_rate": 25.0, "ci": [21.4, 29.0], "calibrated": 26.3,
                    "verdict": {"edge": False, "text": "No proven edge: test."}}
    import pandas as pd
    from datetime import timedelta
    from tests.test_live_feed import first_buy_time, make_feed, spot_path   # reuse the feed test's fake market
    leg = first_buy_time()
    f, _ = make_feed(leg.entry_ts + timedelta(seconds=30))
    monkeypatch.setattr(lf, "record_signal", lambda *a: None)
    d = f.dashboard(tf=5)
    bars = f.bars(leg.entry_ts.date(), 5)[0]
    e = insight.explain(d["signal"], bars[bars["close_ts"] <= pd.Timestamp(leg.entry_ts)], leg.entry_ts.date(), 5, None, S())
    t = e["confidence"]["text"]
    assert "21.4–29.0%" in t and "26%" in t and "No proven edge" in t
    assert e["confidence"]["calibrated"] == 26.3 and e["confidence"]["edge"] is False


# ---------------------------------------------------------------- option chain
class Market:
    def __init__(self, now):
        self.clock = now

    def now(self):
        return self.clock

    def expiries(self, day):
        return [date(2026, 11, 11), EXPIRY, date(2026, 11, 23)]


class Api:
    """Groww-shaped responses. Quotes carry Groww's scaled oi_day_change (x0.65) to prove it isn't used."""
    def __init__(self, spot=25299.35, fail=()):
        self.spot, self.fail, self.calls = spot, set(fail), []

    def __call__(self, fn, **kw):
        self.calls.append((fn, kw))
        if fn in self.fail:
            raise RuntimeError(f"{fn} failed")
        if fn == "get_quote" and kw["segment"] == "CASH":
            return {"last_price": self.spot, "day_change": 44.3, "day_change_perc": 0.18,
                    "ohlc": {"open": 25213.5, "high": 25384.8, "low": 25142.95, "close": 25255.05}}
        if fn == "get_quote":
            if "fno_quote" in self.fail:
                raise RuntimeError("quote failed")
            return {"last_price": 179.1, "day_change": -4.6, "day_change_perc": -2.5, "ohlc": {"close": 183.7},
                    "open_interest": 109298.0, "previous_open_interest": 80335.0,
                    "oi_day_change": 18825.95, "oi_day_change_percentage": 36.05}
        if fn == "get_option_chain":
            assert kw["expiry_date"] in ("2026-11-17", "2026-11-23")
            strikes = {str(k): {t: {"trading_symbol": f"NIFTY26N17{k}{t}", "ltp": 100.0 + (k - 25000) / 10 * (1 if t == "PE" else -1),
                                    "open_interest": 1000 + k % 7, "volume": 5000,
                                    "greeks": {"delta": 0.5 if t == "CE" else -0.5, "iv": 15.5, "gamma": 0.001, "theta": -18.0, "vega": 11.0}}
                                for t in ("CE", "PE")} for k in range(24000, 26550, 50)}
            return {"underlying_ltp": self.spot, "strikes": strikes}
        raise AssertionError(fn)


def chain_feed(now, api=None):
    m = Market(now)
    return lf.Feed(market=m, api=api or Api(), clock=m.now)


def test_chain_centres_on_atm_and_keeps_spot_separate():
    api = Api()
    d = chain_feed(datetime(2026, 11, 12, 11, 0), api).option_chain(width=10)
    assert d["expiry"] == "2026-11-17" and d["expiries"] == ["2026-11-17", "2026-11-23"]   # past expiry dropped
    assert d["atm"] == 25300 and len(d["rows"]) == 21 and [r["strike"] for r in d["rows"] if r["atm"]] == [25300]
    assert d["rows"][0]["strike"] == 24800 and d["rows"][-1]["strike"] == 25800
    assert d["spot"]["price"] == 25299.35 and d["underlying_ltp"] == 25299.35
    atm = next(r for r in d["rows"] if r["atm"])
    assert atm["ce"]["ltp"] != d["spot"]["price"] and atm["ce"]["iv"] == 15.5 and atm["pe"]["delta"] == -0.5
    assert d["days_to_expiry"] == 5 and d["market"] == "open"


def test_chain_oi_change_is_oi_minus_previous_oi():
    d = chain_feed(datetime(2026, 11, 12, 11, 0)).option_chain(width=10)
    ce = next(r for r in d["rows"] if r["atm"])["ce"]
    assert ce["prev_oi"] == 80335 and ce["oi_change"] == 28963 and ce["oi_change_pct"] == 36.05
    assert ce["prev_close"] == 183.7 and ce["change"] == -4.6


def test_chain_quotes_only_near_atm_and_nothing_invented():
    api = Api()
    d = chain_feed(datetime(2026, 11, 12, 11, 0), api).option_chain(width=10)
    fno = [kw["trading_symbol"] for fn, kw in api.calls if fn == "get_quote" and kw["segment"] == "FNO"]
    assert len(fno) == 2 * (2 * lf.CHAIN_QUOTE_WIDTH + 1)
    far = d["rows"][0]
    assert far["ce"]["ltp"] is not None and far["ce"]["change"] is None and far["ce"]["oi_change"] is None


def test_chain_quotes_failing_still_returns_the_chain():
    d = chain_feed(datetime(2026, 11, 12, 11, 0), Api(fail={"fno_quote"})).option_chain()
    assert d["quotes_error"] and all(r["ce"]["change"] is None for r in d["rows"]) and d["rows"][0]["ce"]["ltp"] is not None


def test_chain_errors_are_reported_not_filled():
    with pytest.raises(RuntimeError, match="Option chain unavailable"):
        chain_feed(datetime(2026, 11, 12, 11, 0), Api(fail={"get_option_chain"})).option_chain()
    with pytest.raises(ValueError, match="not a listed"):
        chain_feed(datetime(2026, 11, 12, 11, 0)).option_chain(date(2026, 11, 24))


def test_chain_other_expiry_and_width_limits():
    d = chain_feed(datetime(2026, 11, 12, 11, 0)).option_chain(EXPIRY.replace(day=23), width=99)
    assert d["expiry"] == "2026-11-23" and d["width"] == 20 and len(d["rows"]) == 41


def test_chain_quotes_are_cached():
    api = Api()
    f = chain_feed(datetime(2026, 11, 12, 11, 0), api)
    f.option_chain()
    n = len(api.calls)
    f.option_chain()
    assert sum(1 for fn, kw in api.calls[n:] if fn == "get_quote" and kw["segment"] == "FNO") == 0

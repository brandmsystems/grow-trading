import pytest

import costs
import metrics


def test_buy_sell_fill():
    assert costs.buy_fill(100) == 101.0           # 100.5 + 0.5
    assert costs.sell_fill(100) == 99.0           # 99.5 - 0.5
    assert costs.buy_fill(10.01) == 10.6          # 10.56005 rounded UP to tick
    assert costs.sell_fill(10.01) == 9.45         # 9.45995 rounded DOWN to tick
    assert costs.sell_fill(0.3) == 0.05           # floored at one tick


def test_charges_hand_calculated():
    c = costs.charges(100, 120, 65)
    # buy 6500, sell 7800, turnover 14300
    assert c["brokerage"] == 40
    assert c["stt"] == pytest.approx(11.70)       # 7800 * 0.15%
    assert c["exchange"] == pytest.approx(5.01)   # 14300 * 0.03503%
    assert c["sebi"] == pytest.approx(0.01)
    assert c["stamp"] == pytest.approx(0.20, abs=0.011)
    assert c["gst"] == pytest.approx(8.10)        # 18% of (40 + 5.009 + 0.014)
    assert c["total"] == pytest.approx(sum(v for k, v in c.items() if k != "total"))


def test_round_trip_buy():
    r = costs.round_trip("BUY", 100, 120, 65)
    assert r["entry_fill"] == 101.0 and r["exit_fill"] == pytest.approx(118.9)  # 119.4-0.5
    assert r["gross"] == 1300
    assert r["slippage"] == pytest.approx(1300 - (118.9 - 101.0) * 65)
    assert r["net"] == pytest.approx(r["gross"] - r["slippage"] - r["charges"]["total"])
    assert r["friction"] == pytest.approx(r["slippage"] + r["charges"]["total"])


def test_round_trip_sell_profits_when_premium_falls():
    r = costs.round_trip("SELL", 120, 100, 65)
    assert r["gross"] == 1300
    assert r["entry_fill"] == pytest.approx(118.9) and r["exit_fill"] == 101.0
    # STT is charged on the SELL leg value (entry for a short)
    assert r["charges"]["stt"] == pytest.approx(118.9 * 65 * 0.0015, abs=0.01)
    assert r["net"] < r["gross"]


def test_metrics():
    trades = [{"net": n, "gross": n + 10, "friction": 10} for n in (100, -50, 200, -100)]
    m = metrics.compute(trades, capital=1000)
    assert m["trades"] == 4 and m["win_rate"] == 50
    assert m["net_pnl"] == 150 and m["gross_pnl"] == 190 and m["friction"] == 40
    assert m["profit_factor"] == 2 and m["payoff_ratio"] == 2
    assert m["expectancy"] == 37.5
    assert m["max_drawdown"] == 100 and m["max_drawdown_pct"] == 8.0
    assert m["equity_curve"] == [1100, 1050, 1250, 1150]


def test_metrics_edge_cases():
    assert metrics.compute([])["trades"] == 0
    m = metrics.compute([{"net": 10, "gross": 12, "friction": 2}])
    assert m["profit_factor"] is None and m["max_drawdown"] == 0

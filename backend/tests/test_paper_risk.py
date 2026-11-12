"""Paper-trading risk management: the calculator, the virtual account and the engine's
pre-trade checks, premium stop-loss and daily limit. Live and replay are not affected."""
from datetime import date, datetime, time, timedelta

import psycopg2
import pytest
from sqlalchemy import text

import app.main as app_module
from app.config import settings as config
from app.database import db
from app.services.backtest import engine as backtest
from app.services.market_data.live import ReplayMarket
from app.services.options import sizing
from app.services.trading import charges as costs
from app.services.trading import engine as le
from app.services.trading import paper_account
from app.services.trading.brokers import PaperBroker

TEST_DB = "groww_trading_test_paper"
START, END = date(2025, 6, 2), date(2025, 6, 20)
PARAMS = {"dataset": "synthetic", "start_date": START.isoformat(), "end_date": END.isoformat(),
          "timeframe": 15, "entry_start": "09:30", "cutoff": "14:30"}


@pytest.fixture(scope="module", autouse=True)
def test_db():
    conn = psycopg2.connect(**{**config.PG, "dbname": "postgres"})
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {TEST_DB}")
    old = db._engine
    db._engine = db.engine(TEST_DB)
    db.init()
    backtest.ensure_data(PARAMS)
    yield
    db._engine.dispose()
    db._engine = old
    with conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
    conn.close()


@pytest.fixture(autouse=True)
def clean():
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, live_alerts, paper_accounts RESTART IDENTITY CASCADE"))


# ---------------------------------------------------------------- calculator
@pytest.mark.parametrize("pct", [0.5, 1.0, 1.5, 2.0, 0.75])
def test_risk_amount_and_lots_for_each_setting(pct):
    r = sizing.risk_size("BUY", 100, 90, 65, 200000, pct, available=200000)
    assert r["risk_amount"] == 200000 * pct / 100
    per_lot = -costs.round_trip("BUY", 100, 90, 65)["net"]          # move + slippage + charges at the stop
    assert r["risk_per_lot"] == pytest.approx(per_lot)
    assert r["lots"] == int(r["risk_amount"] // per_lot) and r["qty"] == r["lots"] * 65
    if r["lots"]:
        assert r["max_loss"] <= r["risk_amount"] and r["decision"] == "TRADE"


@pytest.mark.parametrize("capital", [50000, 100000, 500000])
@pytest.mark.parametrize("entry, stop", [(60, 50), (150, 120), (240, 228)])
@pytest.mark.parametrize("lot", [25, 50, 65, 75])           # NIFTY lot sizes since 2021
def test_sizing_invariants(capital, entry, stop, lot):
    r = sizing.risk_size("BUY", entry, stop, lot, capital, 2, available=capital, max_lots=20)
    assert r["qty"] % lot == 0 and r["lots"] <= 20
    if r["decision"] == "TRADE":
        assert r["max_loss"] <= r["risk_amount"] + 0.01
        assert r["investment"] + r["entry_charges"] <= capital
        assert r["max_loss"] == pytest.approx(-costs.round_trip("BUY", entry, stop, r["qty"])["net"])
        assert r["slippage"] > 0 and r["charges"] > 0                 # costs are part of the risk
    else:
        assert r["lots"] == 0 and r["reason"]


def test_one_lot_over_budget_is_no_trade():
    r = sizing.risk_size("BUY", 120, 100, 65, 100000, 1)
    assert r["decision"] == "NO TRADE" and r["lots"] == 0 and "risk budget" in r["reason"]


def test_insufficient_capital_and_min_balance():
    r = sizing.risk_size("BUY", 300, 295, 75, 20000, 50, available=20000)
    assert r["decision"] == "NO TRADE" and "available" in r["reason"]
    ok = sizing.risk_size("BUY", 100, 95, 65, 100000, 5, available=100000)
    kept = sizing.risk_size("BUY", 100, 95, 65, 100000, 5, available=100000, min_balance=95000)
    assert ok["lots"] > kept["lots"] and kept["lots_by_cash"] == 0 and "after keeping" in kept["reason"]


def test_max_lots_cap_and_missing_inputs():
    r = sizing.risk_size("BUY", 80, 70, 75, 500000, 2, max_lots=3)
    assert r["lots"] == 3 and r["limited_by"] == "max_lots"
    assert sizing.risk_size("BUY", None, 70, 75, 500000, 2)["decision"] == "NO TRADE"
    assert "Stop-loss unavailable" in sizing.risk_size("BUY", 80, None, 75, 500000, 2)["reason"]
    assert "below" in sizing.risk_size("BUY", 80, 85, 75, 500000, 2)["reason"]
    assert "above" in sizing.risk_size("SELL", 80, 75, 75, 500000, 2)["reason"]
    with pytest.raises(ValueError):
        sizing.risk_size("BUY", 80, 70, 75, 500000, 0)


def test_dashboard_size_position_unchanged():
    """The Live dashboard keeps its formula (charges, no slippage) through the shared core."""
    z = sizing.size_position(200, 180, 240, 65, capital=100000, risk_pct=5, available=None)
    assert z["risk_per_lot"] == round(20 * 65 + costs.charges(200, 180, 65)["total"], 2) and z["lots"] == 3


def test_risk_calc_api():
    c = app_module.app.test_client()
    d = c.post("/api/paper/risk-calc", json={"capital": 100000, "risk_pct": 2, "entry": 120, "stop_pct": 12.5,
                                             "lot_size": 65, "max_lots": 10}).get_json()["data"]
    assert d["stop"] == 105 and d["decision"] == "TRADE" and d["lots"] == 1
    assert c.post("/api/paper/risk-calc", json={"capital": 100000, "risk_pct": 0}).status_code == 400


# ---------------------------------------------------------------- engine
class DeltaReplay(ReplayMarket):
    def option_delta(self, c):
        return 0.5


def run(cfg, days, market_cls=ReplayMarket):
    market = market_cls("synthetic", START - timedelta(days=12), datetime.combine(days[0], time(9, 0)))
    eng = le.Engine(le.EngineConfig(**{"trade_mode": "paper", "timeframe": 15, "max_trades_per_day": 100,
                                       "max_daily_loss": 0, **cfg}), market, PaperBroker(market))
    eng.start(threaded=False)
    for d in days:
        market.clock = datetime.combine(d, time(9, 14))
        while market.clock <= datetime.combine(d, time(15, 31)):
            eng.tick()
            market.clock += timedelta(seconds=10)
    return eng


def trades():
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(text("SELECT * FROM live_trades ORDER BY id")).mappings()]


def holds():
    with db.engine().connect() as c:
        return [r[0] for r in c.execute(text("SELECT payload FROM live_alerts WHERE action='HOLD' ORDER BY id"))]


DAYS = [START + timedelta(days=i) for i in range(7, 12) if (START + timedelta(days=i)).weekday() < 5]


def test_every_paper_trade_stores_its_risk_calculation():
    paper_account.reset(300000)
    run({"risk_pct": 1.0, "stop_mode": "pct", "stop_pct": 20, "daily_risk_pct": 0}, DAYS)
    ts = trades()
    assert ts, "need paper trades"
    for t in ts:
        r = t["risk"]
        assert r["decision"] == "TRADE" and t["qty"] == r["qty"] == r["lots"] * r["lot_size"] == r["lots"] * 75
        assert r["risk_amount"] == pytest.approx(r["capital"] * 0.01, abs=0.01) and r["max_loss"] <= r["risk_amount"]
        assert t["stop_premium"] == r["stop"] == costs._round_tick_down(r["entry"] * 0.8)
        assert t["paper_account_id"] == 1 and set(r["checks"]) >= {"daily_loss_limit", "open_positions", "available_balance"}
    # the running balance is capital plus closed net P&L
    st = paper_account.state(DAYS[-1] + timedelta(days=1))
    assert st["balance"] == pytest.approx(300000 + sum(t["net"] for t in ts if t["status"] == "CLOSED"), abs=0.01)


def test_premium_stop_loss_exits():
    paper_account.reset(300000)
    run({"risk_pct": 2.0, "stop_mode": "pct", "stop_pct": 3, "daily_risk_pct": 0}, DAYS)
    stops = [t for t in trades() if t["exit_reason"] == "stop_loss"]
    assert stops, "a 3% premium stop should be hit"
    for t in stops:
        assert t["exit_price"] <= t["stop_premium"]


def test_atr_stop_uses_delta_and_atr():
    paper_account.reset(300000)
    eng = run({"risk_pct": 2.0, "stop_mode": "atr", "daily_risk_pct": 0}, DAYS[:2], DeltaReplay)
    ts = trades()
    assert ts and all("delta 0.50" in t["risk"]["stop_method"] for t in ts)
    assert eng.last_atr and eng.last_atr > 0


def test_atr_stop_without_delta_is_no_trade():
    paper_account.reset(300000)
    run({"risk_pct": 2.0, "stop_mode": "atr"}, DAYS[:2])       # ReplayMarket has no option delta
    assert not trades()
    assert any("no stop-loss can be calculated" in h["reason"] for h in holds())


def test_one_lot_over_budget_records_no_trade_reason():
    paper_account.reset(100000)
    run({"risk_pct": 0.05, "stop_mode": "pct", "stop_pct": 30}, DAYS[:2])
    assert not trades()
    h = [x for x in holds() if x["reason"].startswith("risk check")]
    assert h and "risk budget" in h[0]["reason"] and h[0]["risk"]["decision"] == "NO TRADE"


def test_entry_refused_when_max_loss_exceeds_remaining_daily_risk():
    paper_account.reset(100000)
    eng = run({"risk_pct": 2.0, "stop_mode": "pct", "stop_pct": 3, "daily_risk_pct": 0.5}, DAYS)
    assert paper_account.state(DAYS[0], eng.cfg)["daily_limit"] == 500     # 0.5% of ₹1,00,000
    assert not trades()                                                      # one lot risks more than ₹500
    h = [x for x in holds() if "left in today's loss limit" in x["reason"]]
    assert h and not h[0]["risk"]["checks"]["remaining_daily_risk"]


def test_daily_loss_limit_reached_halts_new_entries():
    acct = paper_account.reset(100000)
    with db.engine().begin() as c:     # a ₹600 realised loss already booked today
        c.execute(text("INSERT INTO live_trades (trade_mode, day, exec_mode, direction, side, trading_symbol, qty, "
                       "entry_ts, exit_ts, net, status, paper_account_id) VALUES ('paper', :d, 'ATM_BUY', 'Bullish', "
                       "'BUY', 'X', 75, :e, :x, -600, 'CLOSED', :a)"),
                  {"d": DAYS[0], "e": datetime.combine(DAYS[0], time(9, 20)), "x": datetime.combine(DAYS[0], time(9, 25)),
                   "a": acct["id"]})
    eng = run({"risk_pct": 2.0, "stop_mode": "pct", "stop_pct": 20, "daily_risk_pct": 0.5}, DAYS[:1])
    assert eng.state == "halted" and "Daily loss limit" in eng.halt_reason
    assert len(trades()) == 1                                                 # no new entries
    st = paper_account.state(DAYS[0], eng.cfg)
    assert st["limit_reached"] and st["remaining_risk"] == 0 and st["consecutive_losses"] == 1
    # Your chosen rule: trading resumes at the next session, not later the same day.
    eng.market.clock = datetime.combine(DAYS[1], time(9, 20))
    eng.tick()
    assert eng.state == "running" and eng.halt_reason is None


def test_open_position_limit():
    from app.services.strategy import rules as st
    paper_account.reset(300000)
    eng = run({"risk_pct": 2.0, "stop_mode": "pct", "stop_pct": 20}, DAYS[:1])
    eng.market.clock = datetime.combine(DAYS[0], time(11, 0))
    exp = st.pick_expiry(DAYS[0], eng.market.expiries(DAYS[0]), True)
    atm = st.atm_strike(eng.market.spot_ltp())
    c = eng.market.contract(DAYS[0], exp, atm, "CE")
    leg = st.Leg(day=DAYS[0], direction=1, entry_ts=eng.market.clock, signal_close=atm,
                 signal_bar_start=eng.market.clock, ordinal=0)
    before = eng._paper_risk(leg, c, "BUY")
    assert before["checks"]["open_positions"]
    with db.engine().begin() as cx:     # another paper position is open (e.g. from another session)
        cx.execute(text("INSERT INTO live_trades (trade_mode, day, exec_mode, direction, side, trading_symbol, qty, status) "
                        "VALUES ('paper', :d, 'ATM_BUY', 'Bullish', 'BUY', 'X', 75, 'OPEN')"), {"d": DAYS[0]})
    after = eng._paper_risk(leg, c, "BUY")
    assert after["decision"] == "NO TRADE" and "already open" in after["reason"] and not after["checks"]["open_positions"]
    eng2 = run({"risk_pct": 2.0, "stop_mode": "pct", "stop_pct": 20, "max_open_positions": 2}, DAYS[1:2])
    assert eng2.cfg.max_open_positions == 2


def test_replay_and_live_sizing_unchanged():
    run({"trade_mode": "replay", "lots": 2}, DAYS[:2])
    ts = trades()
    assert ts and all(t["qty"] == 150 and t["risk"] is None and t["stop_premium"] is None for t in ts)


def test_account_api_and_reset():
    c = app_module.app.test_client()
    d = c.get("/api/paper/account").get_json()["data"]
    assert d["balance"] == d["starting_capital"] and d["presets"] == {"conservative": 0.5, "low": 1.0, "moderate": 1.5, "high": 2.0}
    assert c.post("/api/paper/account", json={"capital": 50000}).status_code == 400
    r = c.post("/api/paper/account", json={"capital": 50000, "confirm": "RESET"}).get_json()["data"]
    assert r["capital"] == 50000 and c.get("/api/paper/account").get_json()["data"]["balance"] == 50000

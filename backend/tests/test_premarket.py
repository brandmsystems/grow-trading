"""Pre-market analysis: scoring rules, news filtering, storage and settling, the API, and the engine's stamp / block mode.
No network: every outside source is replaced by fixed data. Paper and replay only."""
import json
from datetime import date, datetime, time, timedelta

import psycopg2
import pytest
from sqlalchemy import text

import app.main as app_module
from app.config import settings as config
from app.database import db
from app.services.backtest import engine as backtest
from app.services.market_data.live import ReplayMarket
from app.services.premarket import scoring, service, sources
from app.services.trading import engine as le
from app.services.trading.brokers import PaperBroker

TEST_DB = "groww_trading_test_premarket"
START, END = date(2025, 6, 2), date(2025, 6, 27)
PARAMS = {"dataset": "synthetic", "start_date": START.isoformat(), "end_date": END.isoformat(),
          "timeframe": 15, "entry_start": "09:30", "cutoff": "14:30"}
DAYS = [d for d in (START + timedelta(days=i) for i in range(8, 13)) if d.weekday() < 5]
NOW = datetime(2026, 11, 19, 8, 40)


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
def no_news_leaks():
    sources.clear_cache()
    yield
    sources.clear_cache()


@pytest.fixture(autouse=True)
def clean():
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE premarket_reports, premarket_inputs, live_trades, live_events, live_sessions, candle_bias, paper_stop_changes RESTART IDENTITY CASCADE"))


def Q(key, name, change, price=100.0, series=None):
    return {"key": key, "name": name, "price": price, "prev_close": price / (1 + change / 100), "change_pct": change,
            "series": series or [price] * 8, "asof": "2026-11-19T08:30", "status": "last close", "source": "Yahoo Finance"}


def quotes(us=0.0, asia=0.0, brent=0.0, vix=0.0, vix_level=16.0, brent_series=None):
    return {"sp500": Q("sp500", "S&P 500", us), "nasdaq": Q("nasdaq", "Nasdaq", us), "dow": Q("dow", "Dow", us),
            "nikkei": Q("nikkei", "Nikkei", asia), "hangseng": Q("hangseng", "Hang Seng", asia),
            "brent": Q("brent", "Brent crude", brent, 80.0, brent_series), "wti": Q("wti", "WTI crude", brent, 76.0),
            "vix": Q("vix", "India VIX", vix, vix_level, [vix_level] * 8), "nifty": None}


# ------------------------------------------------------------------ scoring
def test_global_factor_scores_the_average_and_gives_no_point_for_missing_data():
    assert scoring.global_factor(quotes(us=0.8, asia=0.6))["score"] == 1
    assert scoring.global_factor(quotes(us=-0.9, asia=-0.2))["score"] == -1
    assert scoring.global_factor(quotes(us=0.2, asia=-0.1))["score"] == 0
    q = quotes(us=1.0, asia=1.0)
    q["sp500"] = q["nasdaq"] = q["dow"] = None                        # only 2 of 5 indices: below the minimum
    f = scoring.global_factor(q)
    assert f["score"] == 0 and f["status"] == "UNAVAILABLE" and not f["available"]
    assert any(r["label"] == "Gift Nifty" and r["value"] == "unavailable" for r in f["data"])


def test_crude_is_read_inversely_and_vix_by_its_move_and_level():
    assert scoring.crude_factor(quotes(brent=-2.0))["score"] == 1
    assert scoring.crude_factor(quotes(brent=2.0))["score"] == -1
    assert scoring.crude_factor(quotes(brent=0.1))["score"] == 0
    rising = [70, 71, 72, 74, 76, 78, 79, 80.0]
    assert scoring.crude_factor(quotes(brent=0.5, brent_series=rising))["score"] == -1    # soft rise confirmed by the 5-day trend
    assert scoring.vix_factor(quotes(vix=8.0))["score"] == -1
    assert scoring.vix_factor(quotes(vix=-7.0))["score"] == 1
    assert scoring.vix_factor(quotes(vix=-7.0, vix_level=25.0))["score"] == 0              # a fall from a high level is not bullish
    assert scoring.vix_factor(quotes(vix=1.0))["score"] == 0
    assert scoring.vix_factor({})["status"] == "UNAVAILABLE"


def test_fii_factor_needs_entered_figures():
    assert scoring.fii_factor(None, "2026-11-19")["status"] == "UNAVAILABLE"
    assert scoring.fii_factor({"fii_net_cash": 1800.0, "dii_net_cash": -200.0}, "2026-11-19")["score"] == 1
    assert scoring.fii_factor({"fii_net_cash": -2500.0}, "2026-11-19")["score"] == -1
    assert scoring.fii_factor({"fii_net_cash": 100.0}, "2026-11-19")["score"] == 0
    f = scoring.fii_factor({"fii_net_cash": 900.0, "fii_index_fut_long": 20000, "fii_index_fut_short": 60000}, "2026-11-19")
    assert f["score"] == 0                                           # buying cash but heavily short futures: they cancel


def test_structure_factor_weights_available_parts_only():
    base = {"day": "2026-11-18", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "rows": [], "asof": "x", "freshness": "x", "headline": "x"}
    assert scoring.structure_factor({**base, "daily_score": 0.6, "m15_score": 0.5, "swing": 1.0, "gap_vote": None})["score"] == 1
    assert scoring.structure_factor({**base, "daily_score": -0.6, "m15_score": -0.5, "swing": -1.0, "gap_vote": None})["score"] == -1
    assert scoring.structure_factor({**base, "daily_score": 0.3, "m15_score": -0.3, "swing": 0.0, "gap_vote": None})["score"] == 0
    assert scoring.structure_factor(None)["status"] == "UNAVAILABLE"


@pytest.mark.parametrize("total,label", [(5, "STRONG BULLISH"), (4, "STRONG BULLISH"), (3, "BULLISH"), (2, "BULLISH"), (1, "NEUTRAL / MIXED"),
                                         (0, "NEUTRAL / MIXED"), (-1, "NEUTRAL / MIXED"), (-2, "BEARISH"), (-3, "BEARISH"), (-4, "STRONG BEARISH"), (-5, "STRONG BEARISH")])
def test_total_maps_to_the_brief_bands(total, label):
    assert scoring.bias_label(total) == label


def test_total_counts_only_available_factors_and_the_conclusion_is_a_lean():
    fs = [scoring.global_factor(quotes(us=1, asia=1)), scoring.fii_factor(None, "d"), scoring.crude_factor(quotes(brent=-3)),
          scoring.vix_factor(quotes(vix=-8)), scoring.structure_factor(None)]
    t = scoring.total(fs)
    assert t["total"] == 3 and t["available_factors"] == 3 and t["bias"] == "BULLISH"
    c = scoring.conclusion(fs, {"breakout": 1}, t, [], expiry_today=True)
    assert c["preference"] == "BUY CE" and c["confidence"] == 60 and "not a probability" in c["confidence_note"]
    assert "not an order" in c["action"] and any("unavailable" in r for r in c["risks"]) and any("expiry" in r.lower() for r in c["risks"])
    flat = scoring.conclusion(fs[:1], {}, {"total": 1, "bias": "NEUTRAL / MIXED", "available_factors": 1}, [], False)
    assert flat["preference"] == "HOLD" and flat["confidence"] == 0


# ------------------------------------------------------------------ news
def test_news_is_deduplicated_classified_and_future_items_are_dropped(monkeypatch):
    t = NOW
    mk = lambda h, s, m: {"headline": h, "source": s, "published": t - timedelta(minutes=m), "link": ""}      # noqa: E731
    items = [mk("Wall Street rallies as Fed signals rate cut", "Reuters", 60), mk("Wall Street rallies as Fed signals a rate cut", "Mint", 90),
             mk("Crude oil slumps on demand fears", "Bloomberg", 30), mk("Nifty ends lower amid FII selling", "Moneycontrol", 200),
             mk("Random blog says markets will boom", "Some Blog", 20), mk("Cat video goes viral", "Reuters", 20), mk("Sensex jumps", "Reuters", -600)]
    monkeypatch.setattr(sources, "_rss", lambda q: items if q == sources.NEWS_QUERIES[0] else [])
    monkeypatch.setattr(sources, "_feed", lambda *a, **k: [])             # the publisher feeds are not read in tests
    kept, warn = sources.news(t)
    heads = {i["headline"] for i in kept}
    assert "Random blog says markets will boom" not in heads and "Cat video goes viral" not in heads and "Sensex jumps" not in heads
    shaped = scoring.shape_news(kept)
    assert len([s for s in shaped if s["headline"].startswith("Wall Street rallies")]) == 1      # near-duplicate removed
    by = {s["headline"]: s for s in shaped}
    assert by["Wall Street rallies as Fed signals rate cut"]["impact"] == "positive"
    assert by["Crude oil slumps on demand fears"]["impact"] == "negative" and by["Crude oil slumps on demand fears"]["topic"] == "Crude oil"
    assert by["Nifty ends lower amid FII selling"]["impact"] in ("negative", "neutral")
    assert all({"headline", "source", "published", "impact"} <= set(s) for s in shaped)


# ------------------------------------------------------------------ schedule and settling
def test_schedule_runs_before_the_open_and_only_on_trading_days():
    mon = datetime(2026, 11, 16)
    at = lambda h, m: mon.replace(hour=h, minute=m)                                                          # noqa: E731
    assert not service.due(at(8, 0), None, False)                           # too early
    assert service.due(at(8, 31), None, False)                              # no report yet: run at once
    assert not service.due(at(8, 40), at(8, 31), True)                      # already ran for the 08:30 mark
    assert service.due(at(8, 56), at(8, 31), True)                          # the 08:55 refresh
    assert service.due(at(9, 11), at(8, 56), True) and service.due(at(10, 1), at(9, 31), True)
    assert not service.due(at(15, 40), None, True)
    assert not service.due(datetime(2026, 11, 21, 9, 0), None, False)       # Saturday


@pytest.mark.parametrize("total,chg,out", [(3, 0.8, "CORRECT"), (3, -0.8, "INCORRECT"), (-3, -0.5, "CORRECT"), (-2, 0.4, "INCORRECT"),
                                           (1, 0.9, "NEUTRAL"), (3, 0.05, "NEUTRAL"), (0, -1.0, "NEUTRAL")])
def test_outcome_scoring(total, chg, out):
    assert service.outcome_for(total, chg) == out


def _report(total_quotes, day=NOW):
    return service.build(day, quotes=total_quotes, news_items=[], structure=None, fii=None)


def test_report_is_saved_once_per_day_and_snapshots_record_changes_only():
    r1 = _report(quotes(us=1, asia=1, brent=-2, vix=-8))
    assert service.save(r1)["changed"] is True
    assert service.save(r1)["changed"] is False                         # same result: no new snapshot
    r2 = _report(quotes(us=-1, asia=-1, brent=2, vix=8))
    out = service.save(r2)
    assert out["changed"] is True and len(out["snapshots"]) == 2
    got = service.get(NOW.date())
    assert got["total"]["total"] == -3 and got["conclusion"]["preference"] == "BUY PE"
    assert [s["total"] for s in got["snapshots"]] == [3, -3]
    with db.engine().connect() as c:
        assert c.execute(text("SELECT count(*) FROM premarket_reports")).scalar() == 1


def test_missing_data_scores_nothing_and_is_flagged():
    r = _report({k: None for k in quotes()})
    assert r["total"]["total"] == 0 and r["total"]["available_factors"] == 0
    assert all(f["status"] == "UNAVAILABLE" and f["score"] == 0 for f in r["factors"])
    assert r["warnings"] and r["conclusion"]["preference"] == "HOLD" and r["news"] == []


def test_fii_entry_validation_and_effect_on_the_report():
    yday = NOW.date() - timedelta(days=1)
    with pytest.raises(ValueError):
        service.add_input("fii_dii", NOW.date(), {"fii_net_cash": 100}, None, NOW)       # today/future is refused
    with pytest.raises(ValueError):
        service.add_input("fii_dii", yday, {"fii_net_cash": "abc"}, None, NOW)
    with pytest.raises(ValueError):
        service.add_input("fii_dii", yday, {}, None, NOW)
    service.add_input("fii_dii", yday, {"fii_net_cash": -3200, "dii_net_cash": 2500}, "NSE report", NOW)
    r = service.build(NOW, quotes=quotes(), news_items=[], structure=None)
    f = next(x for x in r["factors"] if x["key"] == "fii_dii")
    assert f["score"] == -1 and f["source"] == "NSE report" and "fii_dii" not in r["unavailable"]
    service.add_input("event", NOW.date(), {"title": "RBI policy decision"}, None, NOW)
    assert any("RBI" in e["title"] for e in service.build(NOW, quotes=quotes(), news_items=[], structure=None)["events"])
    with pytest.raises(ValueError):
        service.add_input("event", yday, {"title": "x"}, None, NOW)


def test_settle_uses_what_nifty_did_and_scores_the_report(monkeypatch):
    day = NOW.date()
    service.save(_report(quotes(us=1, asia=1, brent=-2, vix=-8)))
    monkeypatch.setattr(service, "actual_for", lambda d, eng=None: {"open": 100.0, "high": 103.0, "low": 99.0, "close": 102.0, "prev_close": 100.0, "source": "test"})
    assert service.settle(day) is True and service.settle(day) is False        # settled once
    got = service.get(day)
    assert got["outcome"] == "CORRECT" and got["actual"]["direction"] == "UP" and got["actual"]["gap_pct"] == 0.0
    h = service.history()
    assert h["accuracy"]["calls"] == 1 and h["accuracy"]["hit_pct"] == 100.0 and "Too few days" in h["accuracy"]["note"]
    assert h["days"][0]["total"] == 3


# ------------------------------------------------------------------ API
@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(sources, "quotes", lambda: quotes(us=1, asia=1, brent=-2, vix=-8))
    monkeypatch.setattr(sources, "news", lambda now, max_age_h=40: ([], ["News search failed"]))
    monkeypatch.setattr(service, "nifty_structure", lambda now, eng=None: None)
    return app_module.app.test_client()


def test_api_report_refresh_input_and_history(client):
    d = client.get("/api/premarket/report").get_json()["data"]
    assert d["report"] is None and "fii_dii" in d["unavailable"]
    r = client.post("/api/premarket/refresh").get_json()["data"]["report"]
    assert r["total"]["total"] == 3 and len(r["factors"]) == 5 and r["warnings"]
    assert client.get("/api/premarket/report").get_json()["data"]["report"]["conclusion"]["preference"] == "BUY CE"
    yday = (service._now().date() - timedelta(days=1)).isoformat()
    ok = client.post("/api/premarket/input", json={"kind": "fii_dii", "day": yday, "fii_net_cash": 2000, "source": "NSE"})
    assert ok.status_code == 200 and ok.get_json()["data"]["report"]["total"]["total"] == 4
    assert client.post("/api/premarket/input", json={"kind": "fii_dii", "day": "2999-01-01", "fii_net_cash": 5}).status_code == 400
    assert client.post("/api/premarket/input", json={"kind": "nope", "day": yday}).status_code == 400
    assert client.get("/api/premarket/report?day=bad").status_code == 400
    assert client.get("/api/premarket/history").get_json()["data"]["days"][0]["total"] == 4


# ------------------------------------------------------------------ the engine
LOOSE = {"signal_mode": "bias", "trade_mode": "replay", "timeframe": 5, "bias_min_confidence": 30, "bias_min_atr_pct": 0, "bias_trend_thr": 0.1,
         "bias_confirm_thr": 0.05, "min_premium": 0, "max_spread_pct": 0, "min_delta": 0, "max_daily_loss": 0, "lots": 1,
         "max_trades_per_day": 20, "entry_start": "09:30", "cutoff": "14:30", "bias_cooldown_bars": 2, "stop_mode": "pct", "stop_pct": 30}


def run_replay(over, days=DAYS):
    market = ReplayMarket("synthetic", START - timedelta(days=12), datetime.combine(days[0], time(9, 0)))
    eng = le.Engine(le.EngineConfig(**{**LOOSE, **over}), market, PaperBroker(market))
    eng.start(threaded=False)
    for d in days:
        market.clock = datetime.combine(d, time(9, 14))
        while market.clock <= datetime.combine(d, time(15, 31)):
            eng.tick()
            market.clock += timedelta(seconds=10)
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(text("SELECT direction, analysis FROM live_trades ORDER BY id")).mappings()]


def store_bias(total):
    for d in DAYS:
        rep = service.build(datetime.combine(d, time(8, 40)), quotes=quotes(), news_items=[], structure=None, fii=None)
        rep["total"].update(total=total, bias=scoring.bias_label(total))
        service.save(rep)
        with db.engine().begin() as c:                  # force the stored score regardless of the (neutral) test quotes
            c.execute(text("UPDATE premarket_reports SET total_score=:t, bias=:b WHERE day=:d"), {"t": total, "b": scoring.bias_label(total), "d": d})


def test_stamp_reads_the_stored_bias_and_is_silent_when_neutral_or_missing():
    assert service.stamp(NOW.date(), 1) is None                                     # no report: no view
    service.save(_report(quotes(us=1, asia=1, brent=-2, vix=-8)))
    assert service.stamp(NOW.date(), 1)["agrees"] is True and service.stamp(NOW.date(), -1)["agrees"] is False
    service.save(_report(quotes()))
    assert service.stamp(NOW.date(), 1)["agrees"] is None and service.stamp(NOW.date(), -1)["agrees"] is None


def test_trades_record_whether_the_premarket_bias_agreed_and_the_effect_is_measured():
    store_bias(3)                                                                    # a bullish day on every replay day
    trades = run_replay({"premarket_mode": "log"})
    assert trades, "the loosened thresholds must produce trades on these days"
    for t in trades:
        pm = t["analysis"]["premarket"]
        assert pm["bias"] == "BULLISH" and pm["total"] == 3
        assert pm["agrees"] is (t["direction"] == "Bullish")
    groups = {g["group"]: g for g in service.effectiveness()}
    assert sum(g["trades"] for g in groups.values()) == len(trades) and set(groups) <= {"agreed", "opposed"}


def test_block_opposed_skips_only_trades_against_the_bias_and_off_records_nothing():
    store_bias(3)
    blocked = run_replay({"premarket_mode": "block_opposed"})
    assert blocked and all(t["direction"] == "Bullish" for t in blocked)           # PE (bearish) entries were skipped
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, candle_bias, paper_stop_changes RESTART IDENTITY CASCADE"))
    off = run_replay({"premarket_mode": "off"})
    assert off and all("premarket" not in (t["analysis"] or {}) for t in off)
    with db.engine().begin() as c:
        c.execute(text("TRUNCATE live_trades, live_events, live_sessions, candle_bias, paper_stop_changes RESTART IDENTITY CASCADE"))
    store_bias(0)                                                                    # neutral: nothing is blocked
    neutral = run_replay({"premarket_mode": "block_opposed"})
    assert {t["direction"] for t in neutral} >= {"Bullish"} and all(t["analysis"]["premarket"]["agrees"] is None for t in neutral)


def test_premarket_mode_is_validated_and_live_mode_gets_no_stamp():
    with pytest.raises(ValueError):
        le.EngineConfig(premarket_mode="always").validate()
    assert le.EngineConfig(premarket_mode="block_opposed").validate().premarket_mode == "block_opposed"
    assert "premarket_mode" in le.Engine.LIVE_TUNABLE


# ------------------------------------------------------------------ live news feed (API) and factor evidence
def feed_items():
    mk = lambda h, src, m, **k: {"headline": h, "source": src, "published": service._now() - timedelta(minutes=m), "link": f"https://x.test/{abs(hash(h))}",   # noqa: E731
                                 "summary": k.get("summary"), "image": k.get("image"), "region": "in", "via": "publisher feed"}
    return [mk("Wall Street rallies as Fed signals rate cut", "CNBC", 600, summary="US stocks closed higher on easing hopes, helping risk appetite."),
            mk("Brent crude jumps 3% on supply fears", "Mint", 120), mk("FIIs sell Rs 2,000 crore of Indian shares", "Mint", 30, image="https://x.test/i.jpg")]


def fetched(items, stale=False, ok=True, at=None):
    feeds = [{"name": "Mint", "kind": "feed", "ok": ok, "count": len(items), "error": None if ok else "boom"},
             {"name": "Google News", "kind": "search", "ok": ok, "count": 0, "error": None if ok else "429"}]
    return {"items": items, "feeds": feeds, "warnings": [] if ok else ["Mint feed failed"], "fetched_at": at or service._now(), "stale": stale, "cached": False}


def test_api_news_returns_analysed_articles_categories_events_and_source_state(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(sources, "fetch_news", lambda now, max_age_h=96, force=False: seen.update(force=force) or fetched(feed_items()))
    d = client.get("/api/premarket/news").get_json()["data"]
    assert d["status"] == "live" and len(d["articles"]) == 3 and seen["force"] is False
    assert [c["key"] for c in d["categories"]] == ["all", "indian", "global", "us", "asia", "fii_dii", "central_banks", "crude", "economy", "nifty", "breaking"]
    by = {a["headline"]: a for a in d["articles"]}
    fii = by["FIIs sell Rs 2,000 crore of Indian shares"]
    assert fii["nifty_impact"] == "bearish" and fii["sentiment"] == "negative" and fii["factor"] == "fii_dii" and fii["image"] == "https://x.test/i.jpg"
    assert by["Brent crude jumps 3% on supply fears"]["nifty_impact"] == "bearish" and by["Brent crude jumps 3% on supply fears"]["summary"] is None
    assert by["Wall Street rallies as Fed signals rate cut"]["summary"].startswith("US stocks closed higher")
    assert d["sources"]["publishers"] == [{"name": "Mint", "feeds_ok": 1, "feeds": 1, "articles": 3}] and d["sources"]["searches_ok"] == 1
    assert d["fetched_at"] and d["now"] and "keyword rules" in d["method"] and d["previous_trading_day"] < d["now"][:10]
    client.get("/api/premarket/news?refresh=1")
    assert seen["force"] is True


def test_api_news_says_stale_when_a_refresh_failed_and_unavailable_when_nothing_answered(client, monkeypatch):
    old = service._now() - timedelta(minutes=30)
    monkeypatch.setattr(sources, "fetch_news", lambda now, max_age_h=96, force=False: fetched(feed_items(), stale=True, ok=False, at=old))
    d = client.get("/api/premarket/news").get_json()["data"]
    assert d["status"] == "stale" and d["fetched_at"] == old.isoformat(timespec="seconds") and d["articles"]
    monkeypatch.setattr(sources, "fetch_news", lambda now, max_age_h=96, force=False: fetched([], ok=False, at=None) | {"fetched_at": None})
    d = client.get("/api/premarket/news").get_json()["data"]
    assert d["status"] == "unavailable" and d["articles"] == [] and d["fetched_at"] is None and d["warnings"]


def test_api_news_failure_is_an_error_not_an_empty_feed(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("feed parser exploded")
    monkeypatch.setattr(sources, "fetch_news", boom)
    r = client.get("/api/premarket/news")
    assert r.status_code >= 500 and r.get_json()["ok"] is False


def test_report_attaches_news_evidence_to_each_factor_without_changing_any_score():
    now = service._now()
    items = feed_items()
    with_news = service.build(now, quotes=quotes(us=1, asia=1, brent=-2, vix=-8), news_items=items, structure=None, fii=None)
    without = service.build(now, quotes=quotes(us=1, asia=1, brent=-2, vix=-8), news_items=[], structure=None, fii=None)
    assert [f["score"] for f in with_news["factors"]] == [f["score"] for f in without["factors"]] and with_news["total"] == without["total"]
    ev = {f["key"]: f["news"] for f in with_news["factors"]}
    assert ev["crude"][0]["relation"] == "conflicts"           # crude up on the day's headline, but the factor read the market data (Brent -2%): bullish
    assert ev["global"][0]["relation"] == "supports" and ev["fii_dii"][0]["relation"] in ("context", "supports", "conflicts")
    seen = [n["id"] for v in ev.values() for n in v]
    assert len(seen) == len(set(seen))                          # no event counted for two factors
    assert without["news"] == [] and all(f["news"] == [] for f in without["factors"])
    assert len(with_news["news"]) == 3 and with_news["news_meta"]["total"] == 3 and {"headline", "source", "published", "impact", "link"} <= set(with_news["news"][0])


def test_stored_report_keeps_the_analysed_articles():
    now = service._now()
    rep = service.build(now, quotes=quotes(us=1, asia=1), news_items=feed_items(), structure=None, fii=None)
    service.save(rep)
    got = service.get(now.date())
    assert len(got["news"]) == 3 and got["factors"][0]["news"] is not None and got["news_meta"]["total"] == 3

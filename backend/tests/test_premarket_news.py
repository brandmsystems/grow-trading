"""Pre-market news: feed parsing, caching and failure handling, related-coverage grouping, categories, sentiment and NIFTY direction,
impact level, time periods, and the factor evidence. Pure functions and fixed data: no network, no database."""
from datetime import datetime, timedelta

import pytest
import requests

from app.services.premarket import news_analysis as na
from app.services.premarket import sources

NOW = datetime(2026, 11, 19, 8, 45)          # a Thursday before the open


def item(headline, source="Mint", minutes_ago=60, summary=None, region="in", via="publisher feed", link=None, image=None):
    return {"headline": headline, "source": source, "published": NOW - timedelta(minutes=minutes_ago), "link": link or f"https://x.test/{abs(hash(headline))}",
            "summary": summary, "image": image, "region": region, "via": via}


def one(headline, summary=None, **kw):
    return na.analyze([item(headline, summary=summary, **kw)], NOW)[0]


# ------------------------------------------------------------------ feed parsing
RSS = b"""<?xml version="1.0"?><rss xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title><![CDATA[Sensex surges 500 points as banks rally]]></title><link>https://pub.test/a</link>
<description><![CDATA[<img src="https://pub.test/thumb.jpg"/> Banking stocks led the rally on Thursday as foreign investors bought shares &amp; the rupee firmed.]]></description>
<pubDate>Thu, 19 Nov 2026 07:00:00 +0530</pubDate><media:content medium="image" url="https://pub.test/big.jpg"/></item>
<item><title>Only a headline repeated here</title><link>https://pub.test/b</link><description>Only a headline repeated here</description><pubDate>Wed, 18 Nov 2026 20:00:00 GMT</pubDate></item>
<item><title>No date so it is skipped</title><link>https://pub.test/c</link></item>
</channel></rss>"""


class Resp:
    def __init__(self, content=RSS, status=200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


def test_feed_items_carry_a_clean_summary_a_thumbnail_and_ist_times(monkeypatch):
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: Resp())
    got = sources._feed("Mint", "https://pub.test/rss", "in")
    assert [g["headline"] for g in got] == ["Sensex surges 500 points as banks rally", "Only a headline repeated here"]      # undated item skipped
    a, b = got
    assert a["summary"] == "Banking stocks led the rally on Thursday as foreign investors bought shares & the rupee firmed."      # tags and entities gone
    assert a["image"] == "https://pub.test/big.jpg" and a["published"] == datetime(2026, 11, 19, 7, 0)
    assert b["summary"] is None                                          # a description that only repeats the headline is not a summary
    assert b["published"] == datetime(2026, 11, 19, 1, 30)               # 20:00 GMT is 01:30 IST the next day
    assert b["published"] == datetime(2026, 11, 19, 1, 30) and a["via"] == "publisher feed"


def test_image_falls_back_to_the_picture_inside_the_description(monkeypatch):
    xml = b"""<rss><channel><item><title>Oil moves</title><link>https://pub.test/z</link><pubDate>Thu, 19 Nov 2026 07:00:00 +0530</pubDate>
    <description>&lt;img src="https://pub.test/inline.png" /&gt; Crude oil moved in early trade on supply worries today.</description></item></channel></rss>"""
    monkeypatch.setattr(sources.requests, "get", lambda *a, **k: Resp(xml))
    got = sources._feed("X", "u", "world")
    assert got[0]["image"] == "https://pub.test/inline.png" and got[0]["summary"].startswith("Crude oil moved")


# ------------------------------------------------------------------ fetching, caching, failure
@pytest.fixture()
def fresh_cache():
    sources.clear_cache()
    yield
    sources.clear_cache()


def _gather_returning(items, ok=True):
    feeds = [{"name": "Mint", "kind": "feed", "ok": ok, "count": len(items), "error": None if ok else "boom"}]
    return lambda: (list(items), feeds, [] if ok else ["Mint feed failed"])


def test_fetch_keeps_trusted_relevant_recent_items_and_drops_the_rest(monkeypatch, fresh_cache):
    items = [item("Nifty ends higher on bank buying"), item("Cat video goes viral", summary="A cat did something funny at home today."),
             item("Random blog says markets will boom", source="Some Blog", via="Google News search"),
             item("Sensex jumps", minutes_ago=-600), item("Markets slide on Fed worries", minutes_ago=60 * 24 * 6)]
    monkeypatch.setattr(sources, "_gather", _gather_returning(items))
    r = sources.fetch_news(NOW)
    assert [i["headline"] for i in r["items"]] == ["Nifty ends higher on bank buying"]            # irrelevant, untrusted, future and too-old gone
    assert r["stale"] is False and r["fetched_at"] == NOW


def test_fetch_is_cached_for_two_minutes_and_force_skips_the_cache(monkeypatch, fresh_cache):
    calls = []
    def gather():
        calls.append(1)
        return _gather_returning([item("Nifty ends higher")])()
    monkeypatch.setattr(sources, "_gather", gather)
    sources.fetch_news(NOW)
    r = sources.fetch_news(NOW + timedelta(seconds=60))
    assert len(calls) == 1 and r["cached"] is True
    sources.fetch_news(NOW + timedelta(seconds=60), force=True)
    sources.fetch_news(NOW + timedelta(seconds=200))
    assert len(calls) == 3


def test_when_every_source_fails_the_last_good_fetch_is_returned_as_stale_never_as_live(monkeypatch, fresh_cache):
    monkeypatch.setattr(sources, "_gather", _gather_returning([item("Nifty ends higher")]))
    sources.fetch_news(NOW)
    monkeypatch.setattr(sources, "_gather", _gather_returning([], ok=False))
    r = sources.fetch_news(NOW + timedelta(minutes=10))
    assert r["stale"] is True and r["fetched_at"] == NOW and [i["headline"] for i in r["items"]] == ["Nifty ends higher"]
    assert any("last successful fetch" in w for w in r["warnings"])


def test_when_nothing_was_ever_fetched_there_is_no_news_at_all(monkeypatch, fresh_cache):
    monkeypatch.setattr(sources, "_gather", _gather_returning([], ok=False))
    r = sources.fetch_news(NOW)
    assert r["items"] == [] and r["fetched_at"] is None and r["stale"] is False


# ------------------------------------------------------------------ related coverage
def test_related_coverage_is_combined_and_the_article_with_a_summary_leads():
    a = item("Wall Street rallies as Fed signals rate cut", source="Reuters", minutes_ago=90, via="Google News search")
    b = item("Wall Street rallies as Fed signals a rate cut", source="Mint", minutes_ago=60, summary="US stocks closed higher on Fed easing hopes today.")
    c = item("Crude oil slumps on demand fears", source="Bloomberg", minutes_ago=30, via="Google News search")
    out = na.analyze([a, b, c], NOW)
    assert len(out) == 2
    lead = next(x for x in out if x["headline"].startswith("Wall Street"))
    assert lead["source"] == "Mint" and lead["summary"] and lead["coverage"] == 2
    assert [r["source"] for r in lead["related"]] == ["Reuters"] and lead["related"][0]["link"]


def test_different_stories_are_not_merged_and_the_same_outlet_is_not_listed_twice():
    a = item("RBI holds repo rate steady", source="Mint", minutes_ago=30)
    b = item("RBI holds repo rate steady, says governor", source="Mint", minutes_ago=20, link="https://x.test/other")
    c = item("Sensex surges on bank buying", source="Mint", minutes_ago=10)
    out = na.analyze([a, b, c], NOW)
    assert len(out) == 2 and next(x for x in out if "RBI" in x["headline"])["coverage"] == 1


def test_future_dated_items_never_appear():
    assert na.analyze([item("Sensex jumps", minutes_ago=-30)], NOW) == []


# ------------------------------------------------------------------ categories, sentiment, direction
@pytest.mark.parametrize("headline,cat", [
    ("Wall Street rallies on tech earnings", "us"), ("Nikkei and Hang Seng slip as China data disappoints", "asia"),
    ("FIIs sell shares worth Rs 2,000 crore", "fii_dii"), ("RBI keeps repo rate unchanged", "central_banks"),
    ("Brent crude climbs on supply worries", "crude"), ("India CPI inflation cools in October", "economy"),
    ("Nifty ends at 25,200; Bank Nifty gains", "nifty")])
def test_categories(headline, cat):
    assert cat in one(headline)["categories"]


def test_global_markets_covers_us_and_asia_and_all_news_counts_everything():
    out = na.analyze([item("Wall Street rallies"), item("Nikkei falls"), item("Zomato results beat estimates, shares jump", minutes_ago=5)], NOW)
    cnt = na.counts(out)
    assert cnt["all"] == 3 and cnt["global"] == 2 and cnt["us"] == 1 and cnt["asia"] == 1


def test_crude_is_read_inversely_for_india_and_volume_stories_are_neutral():
    assert one("Brent crude jumps 3% on supply fears")["nifty_impact"] == "bearish"
    f = one("Crude oil slumps on demand fears")
    assert f["nifty_impact"] == "bullish" and f["sentiment"] == "positive"            # falling oil reads positive for India
    assert one("India's crude oil production to fall 20% over the next decade: IEA")["nifty_impact"] == "neutral"


def test_fii_buying_and_selling_follow_the_first_flow_word():
    assert one("FPIs buy Rs 45,960 crore in a week, surpassing October's total equity outflows")["nifty_impact"] == "bullish"
    assert one("FIIs sell Rs 2,000 crore of Indian shares")["nifty_impact"] == "bearish"
    assert one("Rupee gains on strong foreign inflows")["nifty_impact"] == "bullish"


def test_rate_and_inflation_signals():
    assert one("RBI signals rate cut as inflation cools")["nifty_impact"] == "bullish"
    assert one("Fed minutes point to a rate hike in December")["nifty_impact"] == "bearish"
    assert one("IMF calls for tighter monetary policy as global inflation rises to 4.7%")["nifty_impact"] == "bearish"


def test_a_company_only_story_is_neutral_for_the_index_but_keeps_its_own_tone():
    a = one("Tata Elxsi shares tumble after Q2 profit misses estimates")
    assert a["nifty_impact"] == "neutral" and a["sentiment"] == "negative" and a["impact_level"] == "Low"


def test_sentiment_is_neutral_when_the_words_do_not_decide():
    a = one("Markets await the Fed decision", summary="Investors are waiting for the central bank on Wednesday.")
    assert a["sentiment"] == "neutral"


def test_nothing_is_invented_when_the_publisher_gives_no_summary_or_picture():
    a = one("Sensex surges 500 points as banks rally")
    assert a["summary"] is None and a["image"] is None and a["link"].startswith("https://")
    assert a["verified"] == "publisher RSS feed"
    assert one("Sensex surges as banks rally", via="Google News search", source="Reuters")["verified"].startswith("trusted outlet list")


# ------------------------------------------------------------------ why, sectors, indices, impact level
def test_why_it_matters_and_the_sectors_and_indices_it_touches():
    a = one("RBI cuts repo rate; bank stocks and realty shares rally")
    assert "borrowing" in a["why"].lower() or "interest" in a["why"].lower()
    assert "Banking & financials" in a["sectors"] and "Realty" in a["sectors"] and "Bank NIFTY" in a["indices"]
    c = one("Brent crude rises as OPEC trims output")
    assert "import" in c["why"] and "Oil & gas" in c["sectors"] and "NIFTY 50" in c["indices"]
    assert "NIFTY IT" in one("Nasdaq rallies as Infosys and TCS ADRs gain, tech stocks lead Wall Street")["indices"]


def test_impact_level_rises_with_topic_breaking_words_and_how_many_outlets_cover_it():
    big = na.analyze([item("RBI shock rate hike as inflation surges", source=s, minutes_ago=m) for s, m in (("Mint", 30), ("The Hindu", 20), ("CNBC", 10))], NOW)[0]
    assert big["impact_level"] == "High" and big["coverage"] == 3 and big["is_breaking"] and "breaking" in big["categories"]
    mid = one("RBI governor to speak on monetary policy")
    assert mid["impact_level"] in ("Medium", "Low") and not mid["is_breaking"]
    assert one("Small company wins an order, shares rise")["impact_level"] == "Low"


def test_breaking_flag_needs_a_recent_article():
    old = na.analyze([item("Markets crash as war fears grow", source=s, minutes_ago=60 * 20) for s in ("Mint", "CNBC", "BBC News")], NOW)[0]
    assert not old["is_breaking"]


# ------------------------------------------------------------------ time periods
@pytest.mark.parametrize("now,pub,period", [
    (datetime(2026, 11, 19, 8, 45), datetime(2026, 11, 19, 7, 0), "today_pre_market"),
    (datetime(2026, 11, 19, 8, 45), datetime(2026, 11, 18, 20, 0), "overnight"),
    (datetime(2026, 11, 19, 8, 45), datetime(2026, 11, 18, 11, 0), "previous_day"),
    (datetime(2026, 11, 19, 8, 45), datetime(2026, 11, 17, 11, 0), "earlier"),
    (datetime(2026, 11, 19, 11, 0), datetime(2026, 11, 19, 10, 0), "today_session"),
    (datetime(2026, 11, 19, 11, 0), datetime(2026, 11, 19, 8, 0), "today_pre_market"),
    (datetime(2026, 11, 23, 8, 0), datetime(2026, 11, 20, 11, 0), "previous_day"),      # Monday: the previous trading day is Friday
    (datetime(2026, 11, 23, 8, 0), datetime(2026, 11, 21, 12, 0), "overnight")])         # weekend news is "since the last close"
def test_periods_separate_pre_market_overnight_previous_day_and_older_news(now, pub, period):
    assert na.period_of(pub, now) == period


def test_new_means_published_within_two_hours():
    out = na.analyze([item("Sensex surges", minutes_ago=30), item("Nifty slips", minutes_ago=300)], NOW)
    assert {a["headline"]: a["is_new"] for a in out} == {"Sensex surges": True, "Nifty slips": False}
    assert out[0]["published"] > out[1]["published"]                    # newest first


# ------------------------------------------------------------------ factor evidence
def factor(key, status):
    return {"key": key, "status": status}


def test_each_article_backs_one_factor_and_is_compared_with_that_factors_own_result():
    arts = na.analyze([item("FIIs buy Rs 3,000 crore of Indian shares"), item("Brent crude jumps on supply fears", minutes_ago=50),
                       item("Nifty ends higher on bank buying", minutes_ago=40), item("Wall Street rallies on tech earnings", minutes_ago=30)], NOW)
    fs = [factor("global", "BULLISH"), factor("fii_dii", "BEARISH"), factor("crude", "BULLISH"), factor("vix", "NEUTRAL"), factor("structure", "BULLISH")]
    ev = na.factor_evidence(arts, fs, now=NOW)
    flat = [e["id"] for v in ev.values() for e in v]
    assert len(flat) == len(set(flat))                                   # no article counted twice
    assert ev["fii_dii"][0]["relation"] == "conflicts"                   # buying vs a bearish FII result
    assert ev["crude"][0]["relation"] == "conflicts"                     # crude up is bearish for NIFTY vs a bullish crude result
    assert ev["structure"][0]["relation"] == "supports" and ev["global"][0]["relation"] == "supports"
    assert ev["vix"] == []


def test_unavailable_or_neutral_factors_only_get_context_and_old_news_is_left_out():
    arts = na.analyze([item("FIIs buy Rs 3,000 crore of Indian shares"), item("Brent crude jumps", minutes_ago=60 * 24 * 3)], NOW)
    ev = na.factor_evidence(arts, [factor("fii_dii", "UNAVAILABLE"), factor("crude", "BEARISH")], now=NOW)
    assert ev["fii_dii"][0]["relation"] == "context" and ev["crude"] == []


def test_evidence_never_changes_a_score():
    f = {"key": "global", "status": "BULLISH", "score": 1}
    na.factor_evidence(na.analyze([item("Wall Street slumps")], NOW), [f], now=NOW)
    assert f == {"key": "global", "status": "BULLISH", "score": 1}


def test_feed_summary_counts():
    s = na.feed_summary(na.analyze([item("Sensex surges", summary="Banks led the rally on Thursday morning in Mumbai.", image="https://x.test/i.jpg"), item("Nifty slips", minutes_ago=90)], NOW))
    assert s["total"] == 2 and s["with_summary"] == 1 and s["with_image"] == 1 and s["periods"]["today_pre_market"] == 2

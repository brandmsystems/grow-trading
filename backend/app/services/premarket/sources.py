"""Where the pre-market page gets its outside data (the only module that touches the network).

* Index, crude oil and India VIX quotes: Yahoo Finance's public chart endpoint (no key; can be delayed by up to
  15 minutes; unofficial, so it can fail or change).
* News: publisher RSS feeds (headline, summary, thumbnail, link, time) and Google News RSS searches (headline, outlet,
  time, link; no summary). Article text is never fetched or invented.
Not available from any free automated source that works from a script: Gift Nifty (not listed there) and the NSE
FII/DII figures (NSE blocks non-browser clients). Those two are reported as unavailable, or entered by hand on the page;
nothing is ever guessed. Every function returns None / [] on failure, so one dead source never stops the report.
"""
from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from app.utils.timeutil import IST

log = logging.getLogger("premarket.sources")
UA = {"User-Agent": "grow-trading-paper/1.0"}
TIMEOUT = 12

# key -> (Yahoo symbol, name, region)
QUOTES = {
    "sp500": ("^GSPC", "S&P 500", "us"), "nasdaq": ("^IXIC", "Nasdaq Composite", "us"), "dow": ("^DJI", "Dow Jones", "us"),
    "nikkei": ("^N225", "Nikkei 225", "asia"), "hangseng": ("^HSI", "Hang Seng", "asia"),
    "brent": ("BZ=F", "Brent crude", "oil"), "wti": ("CL=F", "WTI crude", "oil"),
    "vix": ("^INDIAVIX", "India VIX", "vol"), "nifty": ("^NSEI", "NIFTY 50", "india"),
}
UNAVAILABLE = {"gift_nifty": "Gift Nifty is not published by any free source this app can read.",
               "fii_dii": "NSE does not serve FII/DII figures to scripts. Enter them by hand below (NSE reports page)."}


def quote(key: str) -> dict | None:
    """Latest price, previous close, change % and the last ~month of daily closes. None if the source fails."""
    sym, name, region = QUOTES[key]
    try:
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "1mo", "interval": "1d"},
                         headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
        pts = [(t, c) for t, c in zip(ts, closes) if c is not None]
        meta = res["meta"]
        price, t_last = float(meta.get("regularMarketPrice") or pts[-1][1]), int(meta.get("regularMarketTime") or pts[-1][0])
        if len(pts) < 2:
            return None
        prev = float(pts[-2][1])            # the last daily bar is the current/latest session; the one before is the previous close
        age_min = (datetime.now(timezone.utc).timestamp() - t_last) / 60
        return {"key": key, "symbol": sym, "name": name, "region": region, "price": round(price, 2), "prev_close": round(prev, 2),
                "change_pct": round((price / prev - 1) * 100, 2),
                "series": [round(float(c), 2) for _, c in pts[-8:]],
                "asof": datetime.fromtimestamp(t_last, IST).replace(tzinfo=None).isoformat(timespec="minutes"),
                "status": "live (up to 15 min delayed)" if age_min < 20 else "last close",
                "source": "Yahoo Finance"}
    except Exception as exc:       # network, parsing, rate limit: the factor simply has no data
        log.warning("quote %s failed: %s", sym, exc)
        return None


def quotes() -> dict[str, dict | None]:
    return {k: quote(k) for k in QUOTES}


# ------------------------------------------------------------------ news
NEWS_QUERIES = [
    "Wall Street stocks Fed", "Asian markets Nikkei Hang Seng", "RBI monetary policy repo rate", "India inflation CPI WPI",
    "Federal Reserve interest rate inflation", "crude oil Brent OPEC", "Nifty Sensex FII", "geopolitical tensions markets",
    "India economy GDP rupee"]
TRUSTED = {"reuters", "bloomberg", "the economic times", "economic times", "mint", "livemint", "moneycontrol", "business standard",
           "cnbc", "cnbc tv18", "cnbctv18", "financial express", "the financial express", "the hindu businessline",
           "businessline", "the hindu", "hindustan times", "times of india", "the times of india", "associated press", "ap news",
           "bbc", "bbc news", "wsj", "the wall street journal", "financial times", "ndtv profit", "marketwatch", "yahoo finance",
           "investing.com", "zee business", "india today", "the indian express", "forbes", "barron's", "al jazeera", "cnn",
           "business today", "firstpost", "the print", "theprint", "ndtv", "pti", "press trust of india", "upstox", "groww"}
RELEVANT = re.compile(r"\b(nifty|sensex|stock|stocks|market|markets|equity|equities|fed|federal reserve|rbi|repo|rate|rates|inflation|cpi|"
                      r"gdp|crude|oil|brent|opec|fii|dii|rupee|bond|yield|nasdaq|dow|s&p|wall street|nikkei|hang seng|tariff|"
                      r"war|sanction|earnings|ipo|economy|budget|dollar)\b", re.I)
_TAIL = re.compile(r"\s+-\s+[^-]{2,60}$")


def _rss(query: str) -> list[dict]:
    r = requests.get("https://news.google.com/rss/search", params={"q": query + " when:2d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
                     headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for it in ElementTree.fromstring(r.content).iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        pub = it.findtext("pubDate")
        if not title or not pub:
            continue
        if src and title.endswith(" - " + src):
            title = title[:-(len(src) + 3)]
        else:
            title = _TAIL.sub("", title)
        try:
            at = parsedate_to_datetime(pub).astimezone(IST).replace(tzinfo=None)
        except Exception:
            continue
        out.append({"headline": title.strip(), "source": src, "published": at, "link": it.findtext("link") or "",
                    "summary": None, "image": None, "region": "", "via": "Google News search"})
    return out


# Publisher RSS feeds: (publisher, url, region). These carry a real summary and usually a thumbnail, which the Google News
# searches above do not. A feed that is dead or stale (nothing recent) is reported in `feeds`, never replaced by made-up items.
_ET = "https://economictimes.indiatimes.com"
FEEDS = [
    ("The Economic Times", _ET + "/markets/rssfeeds/1977021501.cms", "in"),
    ("The Economic Times", _ET + "/markets/stocks/rssfeeds/2146842.cms", "in"),
    ("The Economic Times", _ET + "/news/economy/rssfeeds/1373380680.cms", "in"),
    ("The Economic Times", _ET + "/markets/commodities/rssfeeds/1808152121.cms", "in"),
    ("Mint", "https://www.livemint.com/rss/markets", "in"),
    ("Mint", "https://www.livemint.com/rss/economy", "in"),
    ("Business Standard", "https://www.business-standard.com/rss/markets-106.rss", "in"),
    ("Business Standard", "https://www.business-standard.com/rss/economy-102.rss", "in"),
    ("The Hindu BusinessLine", "https://www.thehindubusinessline.com/markets/feeder/default.rss", "in"),
    ("The Hindu BusinessLine", "https://www.thehindubusinessline.com/economy/feeder/default.rss", "in"),
    ("BBC News", "https://feeds.bbci.co.uk/news/business/rss.xml", "world"),
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069", "world"),
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258", "world"),
    ("CNBC", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "world"),
]
_TAGS = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_IMG = re.compile(r"""<img[^>]+src=["']([^"']+)""")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clean(html: str | None, limit: int = 360) -> str | None:
    """Plain text of a feed description (tags, entities and a leading thumbnail removed); None when nothing useful is left."""
    if not html:
        return None
    t = _SPACE.sub(" ", unescape(_TAGS.sub(" ", unescape(html)))).strip()
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."
    return t if len(t) >= 25 else None


def _image(it) -> str | None:
    for e in it.iter():
        n, url = _local(e.tag), e.get("url")
        if url and url.startswith("http") and ((n in ("content", "thumbnail") and e.get("medium", "image") == "image")
                                               or (n == "enclosure" and (e.get("type") or "").startswith("image"))):
            return url
    m = _IMG.search(unescape(it.findtext("description") or ""))
    return m.group(1) if m and m.group(1).startswith("http") else None


def _feed(publisher: str, url: str, region: str) -> list[dict]:
    """Items of one publisher RSS feed: headline, plain-text summary (None when the feed gives none), thumbnail, link, time."""
    r = requests.get(url, headers=UA, timeout=TIMEOUT, allow_redirects=True)
    r.raise_for_status()
    out = []
    for it in ElementTree.fromstring(r.content).iter("item"):
        title = _SPACE.sub(" ", unescape((it.findtext("title") or "").strip()))
        pub, link = it.findtext("pubDate"), (it.findtext("link") or "").strip()
        if not title or not pub or not link:
            continue
        try:
            d = parsedate_to_datetime(pub.strip())
            at = d.astimezone(IST).replace(tzinfo=None) if d.tzinfo else d
        except Exception:
            continue
        summary = _clean(it.findtext("description"))
        if summary and summary.lower().rstrip(".") == title.lower().rstrip("."):
            summary = None                      # a description that only repeats the headline is not a summary
        out.append({"headline": title, "source": publisher, "published": at, "link": link, "summary": summary,
                    "image": _image(it), "region": region, "via": "publisher feed"})
    return out


_cache: dict = {"at": None, "items": [], "feeds": [], "warnings": []}
_cache_lock = threading.Lock()
CACHE_SECONDS = 120


def clear_cache() -> None:
    with _cache_lock:
        _cache.update(at=None, items=[], feeds=[], warnings=[])


def _gather() -> tuple[list[dict], list[dict], list[str]]:
    """Every feed and search once, in parallel. Returns (items, per-source status, warnings)."""
    jobs = [("feed", pub, url, reg) for pub, url, reg in FEEDS] + [("search", "Google News", q, "") for q in NEWS_QUERIES]

    def run(j):
        kind, name, arg, _reg = j
        try:
            return j, (_feed(name, arg, _reg) if kind == "feed" else _rss(arg)), None
        except Exception as exc:
            log.warning("news %s %r failed: %s", kind, arg, exc)
            return j, [], str(exc)[:120]

    items, status, warnings = [], [], []
    # Google News answers 429 when hit with many searches at once, so the searches run two at a time, the feeds eight.
    with ThreadPoolExecutor(max_workers=8) as pf, ThreadPoolExecutor(max_workers=2) as ps:
        results = list(pf.map(run, jobs[:len(FEEDS)])) + list(ps.map(run, jobs[len(FEEDS):]))
    for (kind, name, arg, _r), got, err in results:
        items += got
        status.append({"name": name, "kind": kind, "ok": err is None, "count": len(got), "error": err})
        if err:
            warnings.append(f"{name} feed failed" if kind == "feed" else f"News search '{arg}' failed")
    return items, status, warnings


def fetch_news(now: datetime, max_age_h: int = 96, force: bool = False) -> dict:
    """Articles from the feeds and searches, cached for two minutes. Nothing is invented: when every source fails the last
    successful fetch is returned with stale=True and its own fetch time, or nothing at all.
    Returns {items, feeds, warnings, fetched_at, stale, cached}."""
    with _cache_lock:
        fresh = _cache["at"] is not None and (now - _cache["at"]).total_seconds() < CACHE_SECONDS
        if fresh and not force:
            return {"items": list(_cache["items"]), "feeds": _cache["feeds"], "warnings": _cache["warnings"],
                    "fetched_at": _cache["at"], "stale": False, "cached": True}
    items, feeds, warnings = _gather()
    if not any(f["ok"] and f["count"] for f in feeds):          # nothing came back: never pass cached news off as live
        with _cache_lock:
            if _cache["at"] is not None:
                return {"items": list(_cache["items"]), "feeds": feeds, "warnings": warnings + ["Could not refresh: showing the last successful fetch"],
                        "fetched_at": _cache["at"], "stale": True, "cached": True}
        return {"items": [], "feeds": feeds, "warnings": warnings, "fetched_at": None, "stale": False, "cached": False}
    items = [i for i in items if i.get("via") == "publisher feed" or i["source"].lower() in TRUSTED]
    items = [i for i in items if RELEVANT.search(i["headline"] + " " + (i.get("summary") or ""))
             and now - timedelta(hours=max_age_h) <= i["published"] <= now + timedelta(minutes=5)]
    with _cache_lock:
        _cache.update(at=now, items=items, feeds=feeds, warnings=warnings)
    return {"items": list(items), "feeds": feeds, "warnings": warnings, "fetched_at": now, "stale": False, "cached": False}


def news(now: datetime, max_age_h: int = 40) -> tuple[list[dict], list[str]]:
    """Recent headlines from trusted outlets, newest first, with no future-dated items. Returns (items, warnings)."""
    r = fetch_news(now, max_age_h=max_age_h, force=True)
    cut = now - timedelta(hours=max_age_h)
    return [i for i in r["items"] if i["published"] >= cut], r["warnings"]


def nifty_daily(range_: str = "1mo") -> list[dict]:
    """NIFTY 50 daily open/high/low/close from Yahoo Finance (used to settle a day when no 1-minute candles are stored)."""
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI", params={"range": range_, "interval": "1d"},
                         headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        out = []
        for i, t in enumerate(res["timestamp"]):
            vals = [q[k][i] for k in ("open", "high", "low", "close")]
            if None not in vals:
                out.append({"day": datetime.fromtimestamp(t, IST).date(), "open": vals[0], "high": vals[1], "low": vals[2], "close": vals[3]})
        return out
    except Exception as exc:
        log.warning("nifty daily failed: %s", exc)
        return []

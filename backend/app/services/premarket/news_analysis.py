"""Reads the fetched articles: groups related coverage, sorts them into categories and time periods, and gives each one a
sentiment, an expected NIFTY direction, an impact level, the sectors and indices it touches, and a plain reason it matters.
Pure functions, no network and no database.

Everything here is a fixed keyword rule applied to the publisher's own headline and summary. It is a quick first read, not
an understanding of the article and not a forecast, and it has not been validated as a predictor. Nothing is invented: a
field with no basis is empty or "neutral", and the "why it matters" lines are general explanations of how that kind of
news usually reaches Indian markets, not claims about the article.

News is shown as *evidence* next to the five factors. It never changes a factor's score or the total.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, time, timedelta

from app.services.premarket import scoring

CATEGORIES = [("all", "All News"), ("indian", "Indian Stock Market"), ("global", "Global Markets"), ("us", "US Market"),
              ("asia", "Asian Markets"), ("fii_dii", "FII / DII"), ("central_banks", "RBI / Federal Reserve"), ("crude", "Crude Oil"),
              ("economy", "Economic News"), ("nifty", "NIFTY / Bank NIFTY"), ("breaking", "Important Breaking News")]
PERIODS = [("today_session", "Today, market hours"), ("today_pre_market", "Today, pre-market"), ("overnight", "Overnight (since the last close)"),
           ("previous_day", "Previous trading day"), ("earlier", "Earlier")]
MARKET_OPEN, MARKET_CLOSE = time(9, 15), time(15, 30)
NEW_HOURS = 2                    # published within this many hours = "new"
BREAKING_HOURS = 12

CAT_PATTERNS = {
    "us": r"wall street|wall st\b|s&p ?500|nasdaq|dow jones|\bdow\b|u\.?s\.? (stocks|markets?|equities)|treasury yields?|"
          r"u\.?s\.? (economy|jobs|inflation|consumer|retail)|\bnyse\b|us stocks|us markets?",
    "asia": r"nikkei|hang seng|kospi|shanghai|shenzhen|csi 300|topix|\basx\b|asian (markets?|stocks|shares|equities)|asia[- ]pacific|"
            r"asia markets|china stocks|taiwan|singapore",
    "europe": r"\bftse\b|\bdax\b|\bcac\b|stoxx|european (markets?|stocks|shares)|europe stocks",
    "fii_dii": r"\bfiis?\b|\bdiis?\b|\bfpis?\b|foreign (institutional|portfolio) investors?|foreign (inflows?|outflows?|investors)|"
               r"institutional (investors|flows)|net (buyers?|sellers?)",
    "central_banks": r"\brbi\b|reserve bank|repo rate|monetary policy|\bmpc\b|federal reserve|\bfed\b|fomc|powell|rate (cuts?|hikes?)|"
                     r"\becb\b|bank of (japan|england)|interest rates?",
    "crude": r"crude|brent|\bwti\b|opec|oil prices?|petroleum",
    "economy": r"inflation|\bcpi\b|\bwpi\b|\bgdp\b|\bpmi\b|\biip\b|fiscal|budget|jobs report|unemployment|trade deficit|\bgst\b|"
               r"\beconom(y|ic|ists?)\b|tariffs?|exports?|imports?|current account|industrial output|retail sales|recession",
    "nifty": r"\bnifty\b|bank ?nifty|\bsensex\b|finnifty|nifty (bank|it|50|midcap|smallcap)",
    "indian_words": r"\bindia\b|indian|\bbse\b|\bnse\b|dalal street|\brupee\b|\bsebi\b|mid-?cap|small-?cap|"
                    r"nifty|sensex|\bfiis?\b|\bdiis?\b|\bfpis?\b|\brbi\b",
    "market_words": r"stocks?|shares?|market|equit|\bipo\b|earnings|results|profit|index",
}
_RE = {k: re.compile(v, re.I) for k, v in CAT_PATTERNS.items()}

BREAKING = re.compile(r"\bbreaking\b|just in|\bcrash(es|ed)?\b|plunge[sd]?|surge[sd]?|soar(s|ed)?|tumble[sd]?|record (high|low)|emergency|"
                      r"\bhalt(s|ed)?\b|circuit breaker|\bdefault\b|\bwar\b|\battack|sanctions?|ceasefire|rate (cut|hike)|shock|collapse|"
                      r"panic|flash crash|black swan", re.I)
VOLATILITY = re.compile(r"\bvix\b|volatil|fear gauge|sell-?off|crash|panic|turmoil|circuit|whipsaw|jitters|\bwar\b|geopolit", re.I)
UP = r"(rise|rises|rose|rising|surge[sd]?|jump(s|ed)?|climb(s|ed)?|soar(s|ed)?|higher|spike[sd]?|gain(s|ed)?|up\b|rall(y|ies|ied)|hike[sd]?)"
DOWN = r"(fall(s|en)?|fell|drop(s|ped)?|slump(s|ed)?|slid(e|es)?|tumble[sd]?|lower|declin(e|es|ed)|plunge[sd]?|sink(s)?|dip(s|ped)?|cut(s)?|ease[sd]?|cool(s|ed)?)"
_CRUDE_UP = re.compile(rf"(crude|oil|brent|wti)[^.]{{0,50}}\b{UP}|\b{UP}[^.]{{0,30}}(crude|oil|brent|wti)", re.I)
_CRUDE_DOWN = re.compile(rf"(crude|oil|brent|wti)[^.]{{0,50}}\b{DOWN}|\b{DOWN}[^.]{{0,30}}(crude|oil|brent|wti)", re.I)
FLOW_OUT = re.compile(r"sell(s|ing)?\b|outflows?|offload|exit|withdr[ae]w|pull(s|ed)? out|net sellers?|dump", re.I)
FLOW_IN = re.compile(r"\bbuy(s|ing)?\b|inflows?|pour(s|ed)?|infus|net buyers?|invest(s|ed)?\b", re.I)
EASY = re.compile(r"rate cuts?|cuts? (key )?rates?|dovish|pause[sd]?|eases?|easing", re.I)
TIGHT = re.compile(r"rate hikes?|hikes? (key )?rates?|hawkish|tighten|tighter", re.I)
_INFL_UP = re.compile(rf"inflation[^.]{{0,40}}\b{UP}|\b{UP}[^.]{{0,15}}inflation", re.I)
_INFL_DOWN = re.compile(rf"inflation[^.]{{0,40}}\b{DOWN}|\b{DOWN}[^.]{{0,15}}inflation", re.I)
_NOT_PRICE = re.compile(r"\b(crude|oil|brent|petroleum)('s)?( oil)?\s+(production|demand|output|reserves|imports?|exports?|drilling|refining)\b|\b(production|output|imports?|exports?)\s+of\s+(crude|oil)\b|\bdrilling\b|\bwells?\b", re.I)

SECTORS = [
    ("Banking & financials", r"\bbank(s|ing)?\b|nbfc|lender|hdfc|icici|\bsbi\b|axis bank|kotak|credit growth|\bloans?\b|insurance"),
    ("IT & technology", r"\bit (stocks?|sector|services|firms?)\b|infosys|\btcs\b|wipro|hcl ?tech|tech mahindra|software|nasdaq|semiconductor|\bai\b"),
    ("Oil & gas", r"crude|\boil\b|brent|opec|\bongc\b|reliance|\bbpcl\b|\bioc\b|\bhpcl\b|petrol|diesel|\bgas\b|refin"),
    ("Auto", r"\bauto(mobile|s)?\b|maruti|tata motors|mahindra|bajaj auto|eicher|\bev\b|vehicles?"),
    ("Pharma & healthcare", r"pharma|\bdrugs?\b|sun pharma|cipla|dr reddy|usfda|healthcare|hospital"),
    ("Metals & mining", r"\bmetals?\b|\bsteel\b|tata steel|\bjsw\b|hindalco|vedanta|copper|aluminium|iron ore|\bgold\b|silver|mining"),
    ("FMCG", r"fmcg|hindustan unilever|\bhul\b|\bitc\b|nestle|consumer goods|packaged"),
    ("Realty", r"realty|real estate|\bdlf\b|housing|property"),
    ("Power & infrastructure", r"\bpower\b|\badani\b|\bntpc\b|infrastructure|capex|cement|larsen|\bl&t\b|railway|roads?"),
    ("Defence", r"defen[cs]e|\bhal\b|\bbel\b|bharat forge|shipbuild"),
    ("Telecom", r"telecom|airtel|\bjio\b|vodafone|spectrum"),
    ("Aviation & travel", r"airlines?|aviation|indigo|air india|\btravel\b"),
]
_SEC = [(n, re.compile(p, re.I)) for n, p in SECTORS]
INDEX_PATTERNS = [("Bank NIFTY", r"bank ?nifty|nifty bank"), ("NIFTY IT", r"nifty it\b"), ("NIFTY Midcap", r"nifty midcap|midcap 100"),
                  ("NIFTY Smallcap", r"nifty smallcap|smallcap 100"), ("Sensex", r"\bsensex\b"), ("NIFTY 50", r"\bnifty( 50)?\b")]
_IDX = [(n, re.compile(p, re.I)) for n, p in INDEX_PATTERNS]

WHY = {
    "central_banks": {"bullish": "Easier or steadier interest-rate signals lower borrowing costs and support valuations, which usually helps banks, realty, autos and NIFTY.",
                      "bearish": "Tighter or higher-for-longer interest-rate signals raise borrowing costs and pressure valuations, which usually weighs on banks, realty and NIFTY.",
                      "neutral": "RBI and Federal Reserve decisions set the cost of money and foreign flows, so they move banks, rate-sensitive sectors and the rupee."},
    "fii_dii": {"bullish": "Foreign buying adds demand for Indian shares and the rupee; foreign flows are one of the larger short-term drivers of NIFTY.",
                "bearish": "Foreign selling removes demand for Indian shares and weighs on the rupee; foreign flows are one of the larger short-term drivers of NIFTY.",
                "neutral": "Foreign and domestic institutional flows are one of the larger short-term drivers of NIFTY."},
    "crude": {"bullish": "India imports most of its oil, so lower crude eases the import bill, inflation and the rupee, which tends to help NIFTY, oil marketing companies and airlines.",
              "bearish": "India imports most of its oil, so higher crude raises the import bill, inflation and pressure on the rupee, which tends to weigh on NIFTY and margins.",
              "neutral": "India imports most of its oil, so oil prices feed into inflation, the rupee and company margins."},
    "us": {"bullish": "A firm Wall Street usually lifts global risk appetite and NIFTY's opening, and helps Indian IT firms in particular.",
           "bearish": "A weak Wall Street usually dampens global risk appetite and NIFTY's opening, and hits Indian IT firms in particular.",
           "neutral": "US markets close before India opens, and their move often carries into NIFTY's opening."},
    "asia": {"bullish": "Gains in Asian markets, which trade while India opens, tend to support regional sentiment and early NIFTY trade.",
             "bearish": "Losses in Asian markets, which trade while India opens, tend to weigh on regional sentiment and early NIFTY trade.",
             "neutral": "Asian markets trade alongside India's open and set the regional mood."},
    "global": {"bullish": "Firm global markets tend to support risk appetite and foreign buying of Indian shares.",
               "bearish": "Weak global markets tend to reduce risk appetite and foreign buying of Indian shares.",
               "neutral": "Global markets set the backdrop for foreign flows into India."},
    "economy": {"bullish": "Better growth or cooling inflation data supports earnings expectations and room for easier rates.",
                "bearish": "Weaker growth or hotter inflation data hurts earnings expectations and narrows room for easier rates.",
                "neutral": "Growth, inflation and trade data shape earnings expectations and interest-rate decisions."},
    "nifty": {"bullish": "This is about the index itself: its direction, levels or heavyweights directly affect NIFTY.",
              "bearish": "This is about the index itself: its direction, levels or heavyweights directly affect NIFTY.",
              "neutral": "This is about the index itself: its direction, levels or heavyweights directly affect NIFTY."},
    "indian": {"bullish": "Positive Indian market or company news can add to sentiment, mostly for the stocks and sectors named.",
               "bearish": "Negative Indian market or company news can weigh on sentiment, mostly for the stocks and sectors named.",
               "neutral": "Indian market and company news; the direct effect on NIFTY is limited unless the stocks named are heavyweights."},
}
FACTOR_ORDER = [("fii_dii", "fii_dii"), ("crude", "crude"), ("vix", None), ("structure", "nifty"), ("global", None)]
IMPACT_RANK = {"High": 0, "Medium": 1, "Low": 2}
_W = re.compile(r"[a-z0-9]+")
STOP = {"the", "and", "for", "with", "from", "that", "this", "has", "have", "are", "was", "were", "will", "its", "his", "her", "after",
        "amid", "over", "into", "than", "their", "about", "says", "said", "how", "why", "what", "who", "new", "may", "can", "could"}

_MORE_POS = {"bullish", "rebound", "rebounds", "advance", "advances", "soar", "soars", "climb", "climbs", "upbeat", "outperform", "overweight",
             "upgrades", "inflow", "inflows", "buying", "optimism", "hits record", "all-time high"}
_MORE_NEG = {"bearish", "sink", "sinks", "slide", "slides", "retreat", "retreats", "concern", "concerns", "worries", "turmoil", "exodus",
             "slashes", "dips", "dip", "declines", "decline", "pressure", "volatile", "jitters", "underweight", "downgrades"}


def _words(t: str) -> set[str]:
    return {w for w in _W.findall(t.lower()) if len(w) > 2 and w not in STOP}


def _hit(h: str, w: str) -> bool:
    return re.search(rf"\b{re.escape(w)}(s|es|ed|d|ing)?\b", h) is not None


def sentiment(headline: str, summary: str | None) -> str:
    """positive / negative / neutral from word lists, headline counted double. The article's own tone, not its effect on NIFTY."""
    h, s = headline.lower(), (summary or "").lower()
    pos, neg = scoring.POS | _MORE_POS, scoring.NEG | _MORE_NEG
    score = 2 * (sum(_hit(h, w) for w in pos) - sum(_hit(h, w) for w in neg)) + (sum(_hit(s, w) for w in pos) - sum(_hit(s, w) for w in neg))
    return "positive" if score > 0 else "negative" if score < 0 else "neutral"


def categories_of(headline: str, summary: str | None, region: str = "") -> list[str]:
    t = headline + " " + (summary or "")
    cats = [k for k in ("us", "asia", "fii_dii", "central_banks", "crude", "economy", "nifty") if _RE[k].search(t)]
    if _RE["asia"].search(t) or _RE["us"].search(t) or _RE["europe"].search(t) or re.search(r"global (markets?|stocks|equit)|world markets", t, re.I):
        cats.append("global")
    if _RE["indian_words"].search(t) or (region == "in" and _RE["market_words"].search(t)):
        cats.append("indian")
    return cats


def primary_topic(cats: list[str]) -> str | None:
    for k in ("central_banks", "fii_dii", "crude", "nifty", "us", "asia", "economy", "global", "indian"):
        if k in cats:
            return k
    return None


def nifty_direction(topic: str | None, tone: str, headline: str, summary: str | None, cats: list[str]) -> str:
    """Which way the news points for NIFTY (bullish / bearish / neutral). Crude is read inversely and rate news by its rate signal;
    a purely company-specific story is neutral for the index."""
    t = headline + " " + (summary or "")
    if topic == "crude":
        if _NOT_PRICE.search(headline):
            return "neutral"                                 # about volumes, not the price
        up, down = bool(_CRUDE_UP.search(headline)), bool(_CRUDE_DOWN.search(headline))
        return "bearish" if up and not down else "bullish" if down and not up else "neutral"
    if topic == "fii_dii":
        mo, mi = FLOW_OUT.search(headline), FLOW_IN.search(headline)
        if mo or mi:                                         # the flow word that comes first is the subject of the headline
            return "bearish" if mo and (not mi or mo.start() < mi.start()) else "bullish"
        return {"positive": "bullish", "negative": "bearish"}.get(tone, "neutral")
    if topic == "central_banks":
        easy, tight = bool(EASY.search(t)), bool(TIGHT.search(t))
        if easy != tight:
            return "bullish" if easy else "bearish"
    if _INFL_UP.search(headline) != _INFL_DOWN.search(headline) and topic in ("economy", "central_banks", "global", "us"):
        return "bearish" if _INFL_UP.search(headline) else "bullish"
    if topic == "indian" and not _RE["nifty"].search(t):
        return "neutral"                                     # company-specific: limited direct effect on the index
    return {"positive": "bullish", "negative": "bearish"}.get(tone, "neutral")


def sectors_of(text: str, topic: str | None) -> list[str]:
    out = [n for n, p in _SEC if p.search(text)]
    if topic == "central_banks" and "Banking & financials" not in out:
        out.insert(0, "Banking & financials")
    return out[:4]


def indices_of(text: str, topic: str | None, cats: list[str], sectors: list[str], headline: str = "") -> list[str]:
    out = [n for n, p in _IDX if p.search(text)]
    if topic == "central_banks" and "Bank NIFTY" not in out and re.search(r"\brbi\b|reserve bank|repo|\bbanks?\b|lender|rate (cut|hike)", headline, re.I):
        out.append("Bank NIFTY")
    if "IT & technology" in sectors and ("us" in cats) and "NIFTY IT" not in out:
        out.append("NIFTY IT")
    if not out and topic in ("central_banks", "fii_dii", "crude", "us", "asia", "global", "economy"):
        out.append("NIFTY 50")
    return out[:4]


def level_of(headline: str, topic: str | None, direction: str, coverage: int, breaking_word: bool, company_only: bool) -> str:
    pts = 2 if breaking_word else 0
    pts += 2 if topic in ("central_banks", "fii_dii", "nifty") else 1 if topic in ("crude", "us", "asia", "economy", "global") else 0
    pts += 2 if coverage >= 3 else 1 if coverage == 2 else 0
    pts += 1 if direction != "neutral" else 0
    pts -= 1 if company_only else 0
    return "High" if pts >= 5 else "Medium" if pts >= 3 else "Low"


def previous_trading_day(day):
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def period_of(published: datetime, now: datetime) -> str:
    today, prev = now.date(), previous_trading_day(now.date())
    if published.date() == today:
        return "today_session" if published.time() >= MARKET_OPEN and now.time() >= MARKET_OPEN else "today_pre_market"
    if published.date() == prev and published.time() < MARKET_CLOSE:
        return "previous_day"
    if published >= datetime.combine(prev, MARKET_CLOSE):
        return "overnight"
    return "earlier"


def _key(link: str, headline: str) -> str:
    return hashlib.sha1((link or headline).encode("utf-8")).hexdigest()[:12]


def cluster(items: list[dict], sim: float = 0.5) -> list[list[dict]]:
    """Related coverage grouped together: headlines sharing at least half their words (and every exact repeat)."""
    groups: list[tuple[set, list[dict]]] = []
    for it in sorted(items, key=lambda i: i["published"], reverse=True):
        w = _words(it["headline"])
        for gw, g in groups:
            if w and gw and len(w & gw) / len(w | gw) >= sim:
                g.append(it)
                gw |= w
                break
        else:
            groups.append((set(w), [it]))
    return [g for _, g in groups]


def _primary(group: list[dict]) -> dict:
    def rank(i):
        return (bool(i.get("summary")), bool(i.get("image")), i.get("via") == "publisher feed", i["published"])
    return max(group, key=rank)


def analyze(items: list[dict], now: datetime) -> list[dict]:
    """Articles (one per cluster of related coverage), newest first. No item is future-dated; none is invented."""
    items = [i for i in items if i["published"] <= now + timedelta(minutes=5) and i.get("headline")]
    out = []
    for g in cluster(items):
        p = _primary(g)
        summary = p.get("summary") or next((i["summary"] for i in g if i.get("summary")), None)
        image = p.get("image") or next((i["image"] for i in g if i.get("image")), None)
        text = p["headline"] + " " + (summary or "")
        cats = categories_of(p["headline"], summary, p.get("region", ""))
        topic = primary_topic(categories_of(p["headline"], None, p.get("region", ""))) or primary_topic(cats)
        tone = sentiment(p["headline"], summary)
        direction = nifty_direction(topic, tone, p["headline"], summary, cats)
        seen, related = {p["source"].lower()}, []
        for i in sorted(g, key=lambda x: x["published"], reverse=True):
            if i is p or i["source"].lower() in seen:
                continue
            seen.add(i["source"].lower())
            related.append({"source": i["source"], "headline": i["headline"], "link": i.get("link", ""),
                            "published": i["published"].isoformat(timespec="minutes")})
        coverage = 1 + len(related)
        age_h = (now - p["published"]).total_seconds() / 3600
        brk = bool(BREAKING.search(p["headline"]))
        company_only = topic == "indian" and "nifty" not in cats
        # shown sentiment: follows the NIFTY direction when there is one (crude falling reads positive for India); a company-only
        # story keeps its own word tone; anything else without a direction is neutral
        senti = {"bullish": "positive", "bearish": "negative"}.get(direction) or (tone if company_only else "neutral")
        level = level_of(p["headline"], topic, direction, coverage, brk, company_only)
        sec = sectors_of(text, topic)
        idx = indices_of(text, topic, cats, sec, p["headline"])
        factor = None
        for fk, ck in FACTOR_ORDER:
            if (ck and ck in cats) or (fk == "vix" and VOLATILITY.search(p["headline"])) or (fk == "global" and "global" in cats):
                factor = fk
                break
        if level == "High" and age_h <= BREAKING_HOURS and (brk or coverage >= 3):
            cats.append("breaking")
        out.append({
            "id": _key(p.get("link", ""), p["headline"]), "headline": p["headline"], "summary": summary, "image": image,
            "source": p["source"], "link": p.get("link", ""), "published": p["published"].isoformat(timespec="minutes"),
            "via": p.get("via", ""), "sentiment": senti, "impact": senti, "nifty_impact": direction, "impact_level": level,
            "why": WHY[topic][direction] if topic in WHY else "General market news; no specific route to NIFTY identified.",
            "sectors": sec, "indices": idx, "categories": cats, "topic": dict(CATEGORIES).get(topic, "Markets") if topic else "Markets",
            "period": period_of(p["published"], now), "is_new": age_h <= NEW_HOURS, "is_breaking": "breaking" in cats,
            "coverage": coverage, "related": related[:6], "factor": factor,
            "verified": "publisher RSS feed" if p.get("via") == "publisher feed" else "trusted outlet list (Google News)"})
    out.sort(key=lambda a: a["published"], reverse=True)
    return out


def counts(articles: list[dict]) -> dict:
    c = {k: 0 for k, _ in CATEGORIES}
    c["all"] = len(articles)
    for a in articles:
        for k in a["categories"]:
            if k in c and k != "all":
                c[k] += 1
    return c


def factor_evidence(articles: list[dict], factors: list[dict], per_factor: int = 5, max_age_h: int = 40, now: datetime | None = None) -> dict:
    """Which articles support each factor. One article backs ONE factor (its `factor`), so an event is never counted twice.
    relation: supports / conflicts / context, comparing the article's NIFTY direction with the factor's own result.
    This is evidence only: the factor's score comes from market data and is not changed by news."""
    status = {f["key"]: f["status"] for f in factors}
    out: dict = {f["key"]: [] for f in factors}
    for a in articles:
        k = a["factor"]
        if k not in out or a["period"] == "earlier":
            continue
        if now and (now - datetime.fromisoformat(a["published"])).total_seconds() > max_age_h * 3600:
            continue
        s, d = status.get(k), a["nifty_impact"]
        rel = "context" if s in (None, "UNAVAILABLE", "NEUTRAL") or d == "neutral" else \
            "supports" if (s == "BULLISH") == (d == "bullish") else "conflicts"
        out[k].append({"id": a["id"], "headline": a["headline"], "source": a["source"], "link": a["link"], "published": a["published"],
                       "nifty_impact": d, "impact_level": a["impact_level"], "relation": rel})
    for k in out:
        out[k] = sorted(out[k], key=lambda x: x["published"], reverse=True)
        out[k].sort(key=lambda x: IMPACT_RANK[x["impact_level"]])
        out[k] = out[k][:per_factor]
    return out


def feed_summary(articles: list[dict]) -> dict:
    by = {k: 0 for k, _ in PERIODS}
    for a in articles:
        by[a["period"]] += 1
    return {"periods": by, "total": len(articles), "with_summary": sum(1 for a in articles if a["summary"]),
            "with_image": sum(1 for a in articles if a["image"]), "breaking": sum(1 for a in articles if a["is_breaking"]),
            "sentiment": {s: sum(1 for a in articles if a["sentiment"] == s) for s in ("positive", "negative", "neutral")}}

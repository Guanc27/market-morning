"""Multi-source sector research from accredited financial press and niche newsletters."""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

import feedparser
import httpx

from app.config import settings
from app.mock_data import MOCK_NEWS

_USER_AGENT = "MarketMorning/1.0 (market research aggregator)"
_TODAY_HOURS = 36
_RECENT_DAYS = 14
_MAX_PER_SECTOR = 12
_FETCH_WORKERS = 10

# --- Google News RSS redirect resolution -------------------------------------
# Google News RSS article links are opaque `news.google.com/rss/articles/CBMi...`
# redirect blobs (200+ chars) that both blow the LLM token budget and leak into
# citations. We resolve them to the real publisher URL at ingestion (before they
# hit the prompt or the research cache) via Google's batchexecute endpoint, with
# a per-URL cache and a timeout+fallback to the original link.
_GNEWS_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_GNEWS_BATCH_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_GNEWS_RESOLVE_TIMEOUT = 8.0
_GNEWS_ID_RE = re.compile(r"/(?:rss/)?(?:articles|read)/([^/?#]+)")
_GNEWS_SIG_RE = re.compile(r'data-n-a-sg="([^"]+)"')
_GNEWS_TS_RE = re.compile(r'data-n-a-ts="([^"]+)"')
_GNEWS_URL_CACHE: dict[str, str] = {}
_GNEWS_CACHE_LOCK = threading.Lock()


def _extract_gnews_id(url: str) -> str | None:
    m = _GNEWS_ID_RE.search(url)
    return m.group(1) if m else None


def _parse_batchexecute_url(text: str) -> str | None:
    body = text
    if body.startswith(")]}'"):
        nl = body.find("\n")
        body = body[nl:] if nl != -1 else body
    try:
        data = json.loads(body)
        for row in data:
            if isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr" and isinstance(row[2], str):
                inner = json.loads(row[2])
                if isinstance(inner, list):
                    for v in inner:
                        if isinstance(v, str) and v.startswith("http") and "google.com" not in v:
                            return v
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    for cand in re.findall(r'https?://[^\s"\\]+', text):
        if "google.com" not in cand and "gstatic.com" not in cand:
            return cand
    return None


def _batchexecute_resolve(article_id: str, client: httpx.Client | None = None) -> str | None:
    own = client is None
    if own:
        client = httpx.Client(
            timeout=_GNEWS_RESOLVE_TIMEOUT,
            headers={"User-Agent": _GNEWS_BROWSER_UA},
            follow_redirects=True,
        )
    try:
        resp = client.get(f"https://news.google.com/rss/articles/{article_id}")
        if resp.status_code != 200:
            return None
        html = resp.text
        sig = _GNEWS_SIG_RE.search(html)
        ts = _GNEWS_TS_RE.search(html)
        if not (sig and ts):
            return None
        req = [
            "garturlreq",
            [
                ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                 None, None, None, None, None, 0, 1],
                "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
            ],
            article_id,
            int(ts.group(1)),
            sig.group(1),
        ]
        payload = [[["Fbv4je", json.dumps(req)]]]
        data = "f.req=" + quote(json.dumps(payload))
        resp2 = client.post(
            _GNEWS_BATCH_URL,
            data=data,
            headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        if resp2.status_code != 200:
            return None
        return _parse_batchexecute_url(resp2.text)
    except Exception:
        return None
    finally:
        if own:
            client.close()


def _resolve_google_news_url(url: str, client: httpx.Client | None = None) -> str:
    """Resolve a Google News RSS redirect URL to its canonical publisher URL.

    Cached per-URL; falls back to the original link if resolution fails.
    """
    if not url or "news.google.com" not in url:
        return url
    with _GNEWS_CACHE_LOCK:
        cached = _GNEWS_URL_CACHE.get(url)
    if cached is not None:
        return cached
    resolved = url
    try:
        article_id = _extract_gnews_id(url)
        if article_id:
            got = _batchexecute_resolve(article_id, client)
            if got:
                resolved = got
    except Exception:
        resolved = url
    with _GNEWS_CACHE_LOCK:
        _GNEWS_URL_CACHE[url] = resolved
    return resolved


def _resolve_selected_links(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve Google News redirect links for the final selected articles only.

    Mutates each article in place: canonical link + recomputed access tier.
    """
    targets = [
        a for a in articles
        if a.get("source_type") == "google_news" and "news.google.com" in (a.get("link") or "")
    ]
    if not targets:
        return articles
    with httpx.Client(
        timeout=_GNEWS_RESOLVE_TIMEOUT,
        headers={"User-Agent": _GNEWS_BROWSER_UA},
        follow_redirects=True,
    ) as client:
        def _resolve_one(article: dict[str, Any]) -> None:
            resolved = _resolve_google_news_url(article["link"], client)
            if resolved and resolved != article["link"]:
                article["link"] = resolved
                tier, access = _article_access_tier(article.get("publisher", ""), resolved)
                article["access_tier"] = access
                article["access_rank"] = tier

        with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
            list(pool.map(_resolve_one, targets))
    return articles


def _strip_publisher_suffix(title: str, publisher: str) -> str:
    """Drop the trailing ' - Publisher' that Google News appends to headlines."""
    title = (title or "").strip()
    pub = (publisher or "").strip()
    if pub and title.endswith(f" - {pub}"):
        return title[: -(len(pub) + 3)].strip()
    return title

_RESEARCH_PROGRESS: dict[str, Any] = {
    "running": False,
    "progress": 100,
    "message": "Ready",
    "done": True,
    "phase": "idle",
}
_RESEARCH_LOCK = threading.Lock()


def get_research_progress() -> dict[str, Any]:
    return dict(_RESEARCH_PROGRESS)


def start_research_background(force_refresh: bool = False) -> None:
    with _RESEARCH_LOCK:
        if _RESEARCH_PROGRESS["running"]:
            return
        _RESEARCH_PROGRESS.update(
            running=True,
            done=False,
            progress=0,
            message="Starting sector research…",
            phase="research",
        )

    def _run() -> None:
        try:
            get_market_research_bundle(force_refresh=force_refresh, _track_progress=True)
        finally:
            _RESEARCH_PROGRESS.update(
                running=False,
                done=True,
                progress=100,
                message="Research complete",
                phase="idle",
            )

    threading.Thread(target=_run, daemon=True).start()

# Source access tiers — prefer free/open RSS; keep MarketWatch; deprioritize hard paywalls
_FREE_PUBLISHERS = frozenset({
    "Reuters Technology", "Reuters Markets", "Reuters Business", "Reuters Energy", "Reuters World",
    "CNBC Technology", "CNBC Finance", "CNBC Retail", "CNBC Health", "CNBC Energy",
    "The Verge", "The Verge AI", "Ars Technica", "TechCrunch", "VentureBeat", "Crunchbase News",
    "Fierce Biotech", "Fierce Pharma", "OilPrice.com",
    "AP News", "AP Top News", "Yahoo Finance", "NPR Business", "Google News",
    "MarketWatch Top Stories", "MarketWatch", "MarketWatch Bulletins", "MarketWatch Investing",
})
_FREE_DOMAINS = (
    "reuters.com", "cnbc.com", "apnews.com", "finance.yahoo.com", "npr.org",
    "techcrunch.com", "venturebeat.com", "fiercebiotech.com", "fiercepharma.com",
    "theverge.com", "arstechnica.com", "oilprice.com", "crunchbase.com",
)
_MARKETWATCH_DOMAINS = ("marketwatch.com",)
_PAYWALLED_DOMAINS = (
    "barrons.com", "wsj.com", "ft.com", "bloomberg.com", "economist.com", "nytimes.com",
    "seekingalpha.com", "theinformation.com", "statnews.com",
)
_SECTOR_SOURCES: dict[str, dict[str, Any]] = {
    "information_technology": {
        "label": "Information Technology",
        "feeds": [
            ("Reuters Technology", "https://www.reuters.com/technology/rss"),
            ("CNBC Technology", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
            ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
            ("The Verge", "https://www.theverge.com/rss/index.xml"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
            ("MarketWatch Investing", "https://feeds.marketwatch.com/marketwatch/investing/"),
            ("Bloomberg Technology", "https://feeds.bloomberg.com/technology/news.rss"),
        ],
        "google_queries": [
            "technology stocks semiconductor cloud when:2d site:reuters.com OR site:cnbc.com OR site:marketwatch.com",
            "big tech earnings software platform when:2d site:apnews.com OR site:finance.yahoo.com",
        ],
    },
    "financials": {
        "label": "Financials",
        "feeds": [
            ("Reuters Markets", "https://www.reuters.com/markets/rss"),
            ("CNBC Finance", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
            ("MarketWatch Top Stories", "https://feeds.marketwatch.com/marketwatch/topstories/"),
            ("MarketWatch Bulletins", "https://feeds.marketwatch.com/marketwatch/bulletins/"),
            ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
            ("AP Top News", "https://feeds.apnews.com/apf-topnews"),
            ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
        ],
        "google_queries": [
            "banking net interest margin investment banking when:2d site:reuters.com OR site:cnbc.com OR site:marketwatch.com",
            "Federal Reserve consumer credit financial regulation when:2d site:apnews.com OR site:finance.yahoo.com",
        ],
    },
    "consumer_cyclicals": {
        "label": "Consumer Cyclicals",
        "feeds": [
            ("Reuters Business", "https://www.reuters.com/business/rss"),
            ("CNBC Retail", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000116"),
            ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
            ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
            ("AP Top News", "https://feeds.apnews.com/apf-topnews"),
        ],
        "google_queries": [
            "retail consumer spending autos hotels restaurants when:2d site:reuters.com OR site:cnbc.com OR site:marketwatch.com",
            "Amazon Walmart consumer discretionary when:2d site:apnews.com OR site:finance.yahoo.com",
        ],
    },
    "healthcare": {
        "label": "Healthcare",
        "feeds": [
            ("STAT News", "https://www.statnews.com/feed/"),
            ("Fierce Biotech", "https://www.fiercebiotech.com/rss/xml"),
            ("Fierce Pharma", "https://www.fiercepharma.com/rss/xml"),
            ("CNBC Health", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000108"),
            ("Reuters Business", "https://www.reuters.com/business/rss"),
            ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
        ],
        "google_queries": [
            "FDA drug approval biotech clinical trial when:3d site:statnews.com OR site:reuters.com OR site:marketwatch.com",
            "pharmaceutical medical device healthcare when:3d site:cnbc.com OR site:apnews.com",
        ],
    },
    "energy": {
        "label": "Energy",
        "feeds": [
            ("Reuters Energy", "https://www.reuters.com/business/energy/rss"),
            ("OilPrice.com", "https://oilprice.com/rss/main"),
            ("CNBC Energy", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000717"),
            ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
            ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
        ],
        "google_queries": [
            "oil gas OPEC energy prices when:2d site:reuters.com OR site:cnbc.com OR site:marketwatch.com",
            "renewable energy refining margins when:2d site:apnews.com OR site:finance.yahoo.com",
        ],
    },
    "inference_llm": {
        "label": "Inference & LLM",
        "feeds": [
            ("Reuters Technology", "https://www.reuters.com/technology/rss"),
            ("The Verge AI", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
            ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
            ("CNBC Technology", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
            ("MarketWatch Investing", "https://feeds.marketwatch.com/marketwatch/investing/"),
            ("TechCrunch", "https://techcrunch.com/feed/"),
        ],
        "google_queries": [
            "LLM inference AI model OpenAI Anthropic GPU datacenter when:2d site:reuters.com OR site:techcrunch.com OR site:marketwatch.com",
            "hyperscaler AI capex Nvidia AMD when:2d site:cnbc.com OR site:theverge.com",
        ],
    },
    "startup_venture": {
        "label": "Startup & Venture",
        "feeds": [
            ("TechCrunch", "https://techcrunch.com/feed/"),
            ("VentureBeat", "https://venturebeat.com/feed/"),
            ("Crunchbase News", "https://news.crunchbase.com/feed/"),
            ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
            ("CNBC Technology", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910"),
        ],
        "google_queries": [
            "startup funding venture capital Series when:3d site:techcrunch.com OR site:marketwatch.com",
            "IPO venture capital private market when:7d site:cnbc.com OR site:reuters.com",
        ],
    },
    "international_geopolitical": {
        "label": "Geopolitical Trades",
        "feeds": [
            ("Reuters World", "https://www.reuters.com/world/rss"),
            ("AP Top News", "https://feeds.apnews.com/apf-topnews"),
            ("CNBC Finance", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"),
            ("MarketWatch Top Stories", "https://feeds.marketwatch.com/marketwatch/topstories/"),
            ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
        ],
        "google_queries": [
            "geopolitical trade tariffs emerging markets when:2d site:reuters.com OR site:apnews.com OR site:marketwatch.com",
            "China Europe Middle East markets when:2d site:cnbc.com OR site:finance.yahoo.com",
        ],
    },
}


def _cache_path() -> Path:
    root = Path(__file__).resolve().parent.parent / "data" / "research_cache"
    root.mkdir(parents=True, exist_ok=True)
    # One file per UTC day — headlines are same-day content; refresh daily or via force_refresh.
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return root / f"{day}.json"


def _parse_entry_date(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _link_domain(link: str) -> str:
    try:
        from urllib.parse import urlparse
        host = urlparse(link).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


_GENERIC_FEED_TITLE_RE = re.compile(
    r"^(top (&|and) breaking|world news|marketwatch top stories|latest headlines?)\b",
    re.I,
)
_LIFESTYLE_HEADLINE_RE = re.compile(
    r"(reverse mortgage|inheritance|netflix, hulu|streaming in \w+ 20|aging parent|"
    r"trump account|home-equity|fourth of july|greedy|make it to 80|"
    r"new romance|personal finance|here'?s what'?s worth streaming|"
    r"protect your inheritance|opening a .trump account)",
    re.I,
)
_MARKET_HEADLINE_RE = re.compile(
    r"(stock|stocks|market|markets|fed\b|federal reserve|earnings|ipo|merger|acquisit|"
    r"nasdaq|s&p|dow\b|inflation|gdp|tariff|oil\b|crude|chip|semiconductor|"
    r"\bai\b|bitcoin|crypto|bank\b|etf|bond|yield|revenue|guidance|shares|"
    r"trading|investor|fund\b|opec|nvidia|apple|microsoft|rates?\b|interest rate|"
    r"\bsec\b|fda\b|biotech|pharma|defense|employment|jobs report|\bcpi\b|\bppi\b|"
    r"import|export|commodit|retail sales|consumer spending|housing starts|"
    r"treasury|geopolit|sanction|war\b|ceasefire|rate cut|rate hike)",
    re.I,
)


def is_market_relevant_headline(title: str) -> bool:
    title = (title or "").strip()
    if len(title) < 16:
        return False
    if _GENERIC_FEED_TITLE_RE.match(title):
        return False
    if _LIFESTYLE_HEADLINE_RE.search(title):
        return False
    return bool(_MARKET_HEADLINE_RE.search(title))


def headline_market_score(title: str, sector_key: str = "") -> int:
    if not is_market_relevant_headline(title):
        return -100
    score = 10 + min(5, len(_MARKET_HEADLINE_RE.findall(title or "")))
    if sector_key in {
        "financials",
        "information_technology",
        "energy",
        "healthcare",
        "inference_llm",
        "startup_venture",
        "consumer_cyclicals",
    }:
        score += 2
    return score


def _article_access_tier(publisher: str, link: str) -> tuple[int, str]:
    """Lower sort key = preferred. Returns (tier, label)."""
    domain = _link_domain(link)
    pub = (publisher or "").strip()

    if pub in _FREE_PUBLISHERS or any(d in domain for d in _FREE_DOMAINS):
        return 0, "free"
    if any(d in domain for d in _MARKETWATCH_DOMAINS) or "MarketWatch" in pub:
        return 1, "marketwatch"
    if any(d in domain for d in _PAYWALLED_DOMAINS):
        return 3, "premium"
    return 2, "standard"


def _normalize_article(
    *,
    title: str,
    link: str | None,
    publisher: str,
    published_at: datetime | None,
    sector: str,
    source_type: str,
) -> dict[str, Any] | None:
    title = re.sub(r"<[^>]+>", "", title or "")
    title = re.sub(r"\s+", " ", title).strip()
    link = (link or "").strip()
    if not title or not link or not link.startswith("http"):
        return None
    age_hours: float | None = None
    iso = None
    if published_at:
        iso = published_at.isoformat()
        age_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
    tier, access = _article_access_tier(publisher, link)
    return {
        "sector": sector,
        "title": title,
        "link": link,
        "publisher": publisher,
        "published_at": iso,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "source_type": source_type,
        "access_tier": access,
        "access_rank": tier,
    }


def _fetch_rss(publisher: str, url: str, sector: str) -> list[dict[str, Any]]:
    try:
        with httpx.Client(timeout=14.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT}) as client:
            resp = client.get(url)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for entry in parsed.entries[:20]:
        title = entry.get("title") or ""
        link = entry.get("link") or ""
        pub = _parse_entry_date(entry)
        item = _normalize_article(
            title=title,
            link=link,
            publisher=publisher,
            published_at=pub,
            sector=sector,
            source_type="rss",
        )
        if item:
            out.append(item)
    return out


def _google_news_rss(query: str, sector: str) -> list[dict[str, Any]]:
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        with httpx.Client(timeout=14.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT}) as client:
            resp = client.get(url)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for entry in parsed.entries[:15]:
        title = entry.get("title") or ""
        link = entry.get("link") or ""
        source = entry.get("source", {})
        publisher = source.get("title") if isinstance(source, dict) else "Google News"
        publisher = str(publisher or "Google News")
        title = _strip_publisher_suffix(title, publisher)
        pub = _parse_entry_date(entry)
        item = _normalize_article(
            title=title,
            link=link,
            publisher=publisher,
            published_at=pub,
            sector=sector,
            source_type="google_news",
        )
        if item:
            out.append(item)
    return out


def _dedupe_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in sorted(
        articles,
        key=lambda x: (
            x.get("access_rank", 2),
            x.get("age_hours") if x.get("age_hours") is not None else 9999,
        ),
    ):
        key = (a.get("link") or "") + "|" + (a.get("title") or "")[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _build_sector_bundle(sector_key: str, cfg: dict[str, Any]) -> dict[str, Any]:
    raw: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = []
        for publisher, url in cfg.get("feeds", []):
            futures.append(pool.submit(_fetch_rss, publisher, url, sector_key))
        for query in cfg.get("google_queries", []):
            futures.append(pool.submit(_google_news_rss, query, sector_key))
        for fut in as_completed(futures):
            try:
                raw.extend(fut.result())
            except Exception:
                pass

    articles = _dedupe_articles(raw)
    now = datetime.now(timezone.utc)
    today_cutoff = now - timedelta(hours=_TODAY_HOURS)
    recent_cutoff = now - timedelta(days=_RECENT_DAYS)

    today: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    for a in articles:
        iso = a.get("published_at")
        if not iso:
            recent.append({**a, "coverage": "undated"})
            continue
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            recent.append({**a, "coverage": "undated"})
            continue
        if dt >= today_cutoff:
            today.append({**a, "coverage": "today"})
        elif dt >= recent_cutoff:
            recent.append({**a, "coverage": "recent"})

    today = [a for a in today if is_market_relevant_headline(a.get("title", ""))]
    recent = [a for a in recent if is_market_relevant_headline(a.get("title", ""))]

    def _pick_ranked(pool: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
        return sorted(
            pool,
            key=lambda x: (
                x.get("access_rank", 2),
                x.get("age_hours") if x.get("age_hours") is not None else 9999,
            ),
        )[:n]

    using_fallback = len(today) < 2
    selected: list[dict[str, Any]] = []
    if today:
        selected.extend(_pick_ranked(today, 8))
    if using_fallback:
        need = _MAX_PER_SECTOR - len(selected)
        selected.extend(_pick_ranked(recent, max(need, 6)))

    selected = selected[:_MAX_PER_SECTOR]
    selected = _resolve_selected_links(selected)
    free_count = sum(1 for a in selected if a.get("access_tier") == "free")
    mw_count = sum(1 for a in selected if a.get("access_tier") == "marketwatch")
    return {
        "label": cfg["label"],
        "articles": selected,
        "today_count": len(today),
        "recent_count": len(recent),
        "using_recent_fallback": using_fallback,
        "free_source_count": free_count,
        "marketwatch_count": mw_count,
        "research_note": (
            "No major headlines in the last 36h — synthesize recent trends from dated articles below. "
            "Prefer citing free-access sources (Reuters, CNBC, AP, Yahoo Finance) and MarketWatch when available; "
            "avoid premium paywall links unless no free alternative exists."
            if using_fallback
            else "Today's headlines available — cite free-access and MarketWatch sources first; "
            "deprioritize Barron's, WSJ, FT, and Bloomberg paywall links when a free article covers the same story."
        ),
    }


def _mock_research() -> dict[str, Any]:
    flat = []
    for ticker, items in list(MOCK_NEWS.items())[:6]:
        if ticker == "_default":
            continue
        for n in items[:2]:
            flat.append({**n, "sector": "information_technology", "coverage": "today", "source_type": "mock"})
    return {
        "information_technology": {
            "label": "Information Technology",
            "articles": flat,
            "today_count": len(flat),
            "recent_count": 0,
            "using_recent_fallback": False,
            "research_note": "Mock research bundle.",
        }
    }


def _filter_bundle_headlines(bundle: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, block in bundle.items():
        if not isinstance(block, dict):
            continue
        articles = [
            a for a in (block.get("articles") or [])
            if is_market_relevant_headline(a.get("title", ""))
        ]
        out[key] = {**block, "articles": articles}
    return out


def get_market_research_bundle(force_refresh: bool = False, _track_progress: bool = False) -> dict[str, Any]:
    if settings.mock_mode:
        _RESEARCH_PROGRESS.update(progress=100, done=True, message="Mock research ready")
        return _mock_research()

    path = _cache_path()
    if not force_refresh and path.exists():
        try:
            data = json.loads(path.read_text())
            _RESEARCH_PROGRESS.update(progress=100, done=True, message="Using today's research cache")
            return _filter_bundle_headlines(data)
        except (json.JSONDecodeError, OSError):
            pass

    if _track_progress:
        _RESEARCH_PROGRESS.update(progress=5, message="Fetching accredited sources…")

    sector_keys = list(_SECTOR_SOURCES.keys())
    bundle: dict[str, Any] = {}
    completed = 0
    with ThreadPoolExecutor(max_workers=len(_SECTOR_SOURCES)) as pool:
        futs = {
            pool.submit(_build_sector_bundle, key, cfg): key
            for key, cfg in _SECTOR_SOURCES.items()
        }
        for fut in as_completed(futs):
            key = futs[fut]
            completed += 1
            label = _SECTOR_SOURCES[key]["label"]
            if _track_progress:
                _RESEARCH_PROGRESS.update(
                    progress=min(95, int(completed / len(sector_keys) * 95)),
                    message=f"Researching {label}…",
                )
            try:
                bundle[key] = fut.result()
            except Exception:
                bundle[key] = {
                    "label": label,
                    "articles": [],
                    "today_count": 0,
                    "recent_count": 0,
                    "using_recent_fallback": True,
                    "research_note": "Research fetch failed for this sector.",
                }

    if _track_progress:
        _RESEARCH_PROGRESS.update(progress=98, message="Saving research cache…")

    try:
        path.write_text(json.dumps(bundle, default=str))
    except OSError:
        pass
    return _filter_bundle_headlines(bundle)


def flatten_sector_research(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sector_key, block in bundle.items():
        if not isinstance(block, dict):
            continue
        for item in block.get("articles") or []:
            link = item.get("link") or item.get("title")
            if link in seen:
                continue
            seen.add(link)
            flat.append({**item, "sector_key": sector_key, "sector_label": block.get("label", sector_key)})
    return flat

"""Recent news for holdings, watchlist, and screening."""

from __future__ import annotations

import threading
import time
from typing import Any

import yfinance as yf

from app.config import settings
from app.mock_data import MOCK_NEWS

# yfinance headlines shift through the day — 4h in-memory TTL avoids duplicate fetches per session.
_NEWS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_NEWS_TTL_SECONDS = 4 * 3600
_NEWS_LOCK = threading.Lock()

# Sector proxy tickers for broad market news in morning brief
SECTOR_NEWS_TICKERS = [
    "SPY", "QQQ", "XLK", "XLF", "XLY", "XLV", "XLE",
    "JPM", "BAC", "GS", "AMZN", "WMT", "TSLA", "MCD",
    "LLY", "UNH", "XOM", "CVX", "NVDA", "MSFT", "GOOGL",
]


def _normalize_item(item: dict[str, Any], ticker: str) -> dict[str, Any] | None:
    title = item.get("title") or item.get("headline")
    link = item.get("link") or item.get("url")
    if not title:
        return None
    pub = item.get("providerPublishTime") or item.get("published_at")
    return {
        "ticker": ticker,
        "title": str(title).strip(),
        "link": str(link).strip() if link else None,
        "publisher": item.get("publisher") or item.get("source") or "Unknown",
        "published_at": pub,
    }


def get_ticker_news(ticker: str, limit: int = 5, *, force_refresh: bool = False) -> list[dict[str, Any]]:
    if settings.mock_mode:
        return [dict(n, ticker=ticker) for n in MOCK_NEWS.get(ticker, MOCK_NEWS.get("_default", []))[:limit]]
    key = ticker.upper()
    if not force_refresh:
        with _NEWS_LOCK:
            hit = _NEWS_CACHE.get(key)
            if hit and (time.time() - hit[0]) < _NEWS_TTL_SECONDS:
                return hit[1][:limit]
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        raw = []
    out: list[dict[str, Any]] = []
    for item in raw[:limit]:
        norm = _normalize_item(item, ticker)
        if norm and norm.get("link"):
            out.append(norm)
    with _NEWS_LOCK:
        _NEWS_CACHE[key] = (time.time(), out)
    return out


def get_news_bundle(
    tickers: list[str],
    per_ticker: int = 4,
    *,
    force_refresh: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    tickers = list(dict.fromkeys(t.upper() for t in tickers if t))
    return {t: get_ticker_news(t, per_ticker, force_refresh=force_refresh) for t in tickers}


def get_sector_news_bundle(per_ticker: int = 3) -> dict[str, list[dict[str, Any]]]:
    return get_news_bundle(SECTOR_NEWS_TICKERS, per_ticker=per_ticker)


def flatten_news(bundle: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    flat: list[dict[str, Any]] = []
    for items in bundle.values():
        for item in items:
            key = item.get("link") or item.get("title")
            if key in seen:
                continue
            seen.add(key)
            flat.append(item)
    return flat

"""Company logo resolution — Clearbit domain logos with Parqet/FMP fallbacks."""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import httpx
import yfinance as yf

from app.config import settings

_PARQET_ALIASES = {"BRK-B": "BRK.B", "BF-B": "BF.B"}


def _domain(website: str) -> str:
    raw = website.strip()
    if not raw.startswith("http"):
        raw = f"https://{raw}"
    return urlparse(raw).netloc or website.split("/")[0]


@lru_cache(maxsize=512)
def ticker_info(ticker: str) -> dict[str, Any]:
    """Static company website/name — safe to cache for process lifetime (logos rarely change)."""
    try:
        info = yf.Ticker(ticker).info or {}
        return {
            "website": info.get("website") or "",
            "shortName": info.get("shortName") or info.get("longName") or ticker,
        }
    except Exception:
        return {"website": "", "shortName": ticker}


def logo_api_path(ticker: str) -> str:
    return f"/logo/{ticker.upper().strip()}"


def logo_urls(tickers: list[str]) -> dict[str, str]:
    return {t.upper(): logo_api_path(t) for t in tickers if t}


def resolve_logo_fetch_urls(ticker: str) -> list[str]:
    sym = ticker.upper().strip()
    sym = _PARQET_ALIASES.get(sym, sym)
    urls: list[str] = []

    website = ticker_info(sym).get("website") or ""
    if website:
        urls.append(f"https://logo.clearbit.com/{_domain(website)}?size=128")

    urls.append(f"https://assets.parqet.com/logos/symbol/{sym}?format=png")

    if settings.fmp_api_key:
        urls.append(f"https://financialmodelingprep.com/image-stock/{sym}.png")

    # Google favicon fallback
    if website:
        urls.append(f"https://www.google.com/s2/favicons?domain={_domain(website)}&sz=128")

    return urls


def fetch_logo_bytes(ticker: str) -> tuple[bytes, str] | None:
    headers = {"User-Agent": "MarketMorning/1.0"}
    with httpx.Client(timeout=12.0, follow_redirects=True, headers=headers) as client:
        for url in resolve_logo_fetch_urls(ticker):
            try:
                resp = client.get(url)
                if resp.status_code != 200:
                    continue
                ctype = resp.headers.get("content-type", "")
                data = resp.content
                if len(data) < 80:
                    continue
                if "image" not in ctype and not data[:8].startswith(b"\x89PNG"):
                    continue
                media = ctype.split(";")[0] if "image" in ctype else "image/png"
                return data, media
            except Exception:
                continue
    return None

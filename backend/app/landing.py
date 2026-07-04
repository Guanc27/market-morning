"""Static landing content for Explore tab."""

from __future__ import annotations

from typing import Any

from app.research import (
    flatten_sector_research,
    get_market_research_bundle,
    headline_market_score,
    is_market_relevant_headline,
)

SUGGESTED_MARKETS = [
    "Semiconductors & AI chips",
    "Cloud & enterprise software",
    "Regional banks & NIM",
    "Biotech & GLP-1",
    "Energy & OPEC",
    "Consumer discretionary",
    "Defense & aerospace",
    "Crypto & fintech",
]

FREE_TIERS = frozenset({"free", "marketwatch"})


def get_explore_landing() -> dict[str, Any]:
    bundle = get_market_research_bundle()
    flat = flatten_sector_research(bundle)
    candidates: list[tuple[int, dict[str, Any]]] = []
    seen: set[str] = set()
    for item in flat:
        tier = item.get("access_tier", "standard")
        if tier not in FREE_TIERS:
            continue
        title = item.get("title") or ""
        if not is_market_relevant_headline(title):
            continue
        link = item.get("link") or ""
        if link in seen:
            continue
        seen.add(link)
        score = headline_market_score(title, item.get("sector_key", ""))
        candidates.append((score, item))

    candidates.sort(key=lambda x: (-x[0], x[1].get("age_hours") or 9999))
    headlines = []
    for _score, item in candidates[:8]:
        headlines.append({
            "title": item.get("title"),
            "link": item.get("link"),
            "publisher": item.get("publisher"),
            "sector_label": item.get("sector_label"),
            "access_tier": item.get("access_tier"),
        })
    return {
        "suggested_markets": SUGGESTED_MARKETS,
        "headlines": headlines,
    }

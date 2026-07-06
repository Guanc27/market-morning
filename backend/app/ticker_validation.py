"""Validate/repair emitted tickers against the real symbol universe.

The LLM occasionally hallucinates a ticker by appending a letter to a real one
(observed: CRWDS instead of CRWD). Before display we scan `$TICKER` and
`(TICKER)` mentions plus the mm-meta ticker arrays, and:
  - if the symbol is valid (in the NYSE universe, a known ETF/index, or a
    current holding/watchlist name) → keep it;
  - if it is invalid but trimming trailing letters yields a valid symbol
    (CRWDS → CRWD) → correct it;
  - otherwise leave prose untouched (never damage legitimate text) and drop the
    symbol from structured meta arrays.

Conservative by design: corrections only fire on symbols that are NOT valid, so
real tickers are never rewritten.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app.universe import get_all_us_tickers, get_nyse_tickers

# ETFs / indices / benchmarks that are valid but may not be in the NYSE list.
_EXTRA_VALID = {
    "SPY", "QQQ", "DIA", "IWM", "VOO", "VTI", "SMH", "SOXX", "XLK", "XLF", "XLE",
    "XLV", "XLY", "XLC", "XLI", "XLP", "XLU", "XLB", "XLRE", "IGV", "XBI", "ARKX",
    "ARKK", "ITA", "GLD", "SLV", "TLT", "HYG", "VIX", "GOOGL", "GOOG", "BRK-B",
    "BRK-A", "META", "TSM", "ASML", "NVO", "SAP",
}

_TICKER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])\$([A-Z]{1,6})\b|\(([A-Z]{2,6})\)")

# Common finance/English acronyms that appear in parentheses but are NOT tickers.
# Never rewrite these (prevents (CEO)->(CE), (GDP)->(GD) style corruption).
_ACRONYM_STOPWORDS = frozenset({
    "CEO", "CFO", "CTO", "COO", "CMO", "CIO", "GDP", "CPI", "PPI", "FDA", "SEC",
    "FED", "IPO", "EPS", "ETF", "ETFS", "AI", "ML", "LLM", "GPU", "CPU", "TPU",
    "API", "ROE", "ROI", "ROIC", "FCF", "OCF", "EBIT", "EBITDA", "NIM", "PE",
    "PS", "PEG", "EV", "USD", "EUR", "GBP", "JPY", "CNY", "YOY", "QOQ", "ATH",
    "RSI", "SMA", "EMA", "ATR", "IR", "HHI", "PMI", "ISM", "OPEC", "NATO", "UN",
    "EU", "US", "USA", "UK", "YTD", "MTD", "QTD", "TAM", "SAM", "SOM", "ARR",
    "MRR", "SaaS", "M&A", "IB", "AUM", "NAV", "MOIC", "TCO", "COGS", "CAGR",
    "DCF", "WACC", "BPS", "BP", "H1", "H2", "Q1", "Q2", "Q3", "Q4", "FY", "GAAP",
    "HBM", "DRAM", "NAND", "OEM", "ODM", "EPA", "DOJ", "FTC", "CBO", "GLP",
})


@lru_cache(maxsize=1)
def _universe() -> frozenset[str]:
    base: set[str] = set()
    try:
        base |= {t.upper() for t in get_all_us_tickers()}
    except Exception:
        pass
    if len(base) < 4000:  # incomplete (e.g. Nasdaq fetch failed) — add NYSE list
        try:
            base |= {t.upper() for t in get_nyse_tickers()}
        except Exception:
            pass
    return frozenset(base | _EXTRA_VALID)


def _valid(sym: str, extra: frozenset[str]) -> bool:
    s = sym.upper()
    return s in extra or s in _universe()


def _correct(sym: str, extra: frozenset[str]) -> str | None:
    """Return a corrected valid symbol by trimming trailing letters, else None."""
    s = sym.upper()
    if _valid(s, extra):
        return s
    for cut in (1, 2):
        cand = s[:-cut]
        if len(cand) >= 2 and _valid(cand, extra):
            return cand
    return None


def _extra_valid(holdings: list[str] | None, watchlist: list[str] | None) -> frozenset[str]:
    extra = set(_EXTRA_VALID)
    for t in (holdings or []) + (watchlist or []):
        if t:
            extra.add(t.upper())
    return frozenset(extra)


def validate_content_tickers(
    content: str,
    *,
    holdings: list[str] | None = None,
    watchlist: list[str] | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    """Repair hallucinated `$T`/`(T)` tickers in prose. Returns (content, corrections)."""
    if not content:
        return content, []
    extra = _extra_valid(holdings, watchlist)
    corrections: list[tuple[str, str]] = []

    def _sub(m: re.Match[str]) -> str:
        dollar_sym, paren_sym = m.group(1), m.group(2)
        sym = dollar_sym or paren_sym
        if not sym or sym.upper() in _ACRONYM_STOPWORDS or _valid(sym, extra):
            return m.group(0)
        # Parenthesized short tokens are almost always acronyms, not tickers —
        # only repair the unambiguous `$SYM` sigil or longer parenthesized symbols.
        if paren_sym and len(sym) <= 3:
            return m.group(0)
        fixed = _correct(sym, extra)
        if not fixed or fixed == sym:
            return m.group(0)
        corrections.append((sym, fixed))
        return m.group(0).replace(sym, fixed)

    return _TICKER_TOKEN_RE.sub(_sub, content), corrections


def validate_meta_tickers(
    meta: dict[str, Any],
    *,
    holdings: list[str] | None = None,
    watchlist: list[str] | None = None,
) -> dict[str, Any]:
    """Correct/drop invalid tickers in mm-meta actions & watchlist_adds arrays."""
    if not meta:
        return meta
    extra = _extra_valid(holdings, watchlist)

    def _fix_list(vals: list[str] | None) -> list[str]:
        out: list[str] = []
        for v in vals or []:
            fixed = _correct(str(v).upper(), extra)
            if fixed:
                out.append(fixed)
        return out

    for action in meta.get("actions") or []:
        if isinstance(action, dict) and "tickers" in action:
            action["tickers"] = _fix_list(action.get("tickers"))
    fixed_adds = []
    for add in meta.get("watchlist_adds") or []:
        if isinstance(add, dict) and add.get("ticker"):
            fixed = _correct(str(add["ticker"]).upper(), extra)
            if fixed:
                add["ticker"] = fixed
                fixed_adds.append(add)
        else:
            fixed_adds.append(add)
    if "watchlist_adds" in meta:
        meta["watchlist_adds"] = fixed_adds
    return meta

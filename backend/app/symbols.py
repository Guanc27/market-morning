"""Symbol search index — full NYSE universe with on-demand enrichment."""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yfinance as yf

from app.config import settings
from app.finance import get_technicals
from app.logos import logo_api_path
from app.universe import get_nyse_universe

_INDEX: dict[str, dict[str, Any]] = {}
_LIGHT_INDEX: dict[str, dict[str, Any]] = {}
_INDEX_LOCK = threading.Lock()
_WARM_STATE = {"running": False, "done": False, "progress": 0, "total": 0, "message": "Idle"}


def _cache_path() -> Path:
    # Enriched symbol metadata (name, sector, summary) persists until re-enriched for a ticker.
    p = Path(__file__).resolve().parent.parent / "data" / "symbol_index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_universe_tickers() -> list[str]:
    return [s["ticker"] for s in get_nyse_universe()]


def _ensure_light_index() -> None:
    global _LIGHT_INDEX
    with _INDEX_LOCK:
        if _LIGHT_INDEX:
            return
    for row in get_nyse_universe():
        ticker = row["ticker"]
        _LIGHT_INDEX[ticker] = {
            "ticker": ticker,
            "name": row.get("name") or ticker,
            "sector": "",
            "industry": "",
            "city": "",
            "state": "",
            "location": "",
            "country": "",
            "market_cap": 0,
            "price": None,
            "projection_pct": None,
            "buy_score": None,
            "summary": "",
            "logo_url": logo_api_path(ticker),
            "is_etf": row.get("is_etf", False),
            "exchange": "NYSE",
            "enriched": False,
        }


def _buy_score(info: dict[str, Any], tech: dict[str, Any]) -> int:
    score = 50.0
    rec = info.get("recommendationMean")
    if rec is not None:
        score += (2.5 - float(rec)) * 18
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    target = info.get("targetMeanPrice")
    if price and target:
        upside = (float(target) - float(price)) / float(price) * 100
        score += max(-25, min(25, upside * 0.8))
    rsi = tech.get("rsi14")
    if rsi is not None:
        if rsi < 35:
            score += 8
        elif rsi > 70:
            score -= 8
    return int(max(0, min(100, round(score))))


def _projection_pct(info: dict[str, Any]) -> float | None:
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    target = info.get("targetMeanPrice")
    if not price or not target:
        return None
    return round((float(target) - float(price)) / float(price) * 100, 1)


def _build_entry(ticker: str) -> dict[str, Any] | None:
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        if not info.get("shortName") and not info.get("longName"):
            light = _LIGHT_INDEX.get(ticker)
            if light:
                return {**light, "enriched": False}
            return None
        tech = get_technicals(ticker) if not settings.mock_mode else {}
        city = info.get("city") or ""
        state = info.get("state") or ""
        location = ", ".join(x for x in (city, state) if x)
        summary = (info.get("longBusinessSummary") or "")[:400]
        return {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName") or ticker,
            "sector": info.get("sector") or "",
            "industry": info.get("industry") or "",
            "city": city,
            "state": state,
            "location": location,
            "country": info.get("country") or "",
            "market_cap": info.get("marketCap") or 0,
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "projection_pct": _projection_pct(info),
            "buy_score": _buy_score(info, tech),
            "summary": summary,
            "logo_url": logo_api_path(ticker),
            "enriched": True,
        }
    except Exception:
        light = _LIGHT_INDEX.get(ticker)
        if light:
            return {**light, "enriched": False}
        return None


def _save_cache() -> None:
    try:
        enriched = {k: v for k, v in _INDEX.items() if v.get("enriched")}
        _cache_path().write_text(json.dumps(enriched, indent=0))
    except OSError:
        pass


def _load_cache() -> bool:
    path = _cache_path()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return False
        with _INDEX_LOCK:
            for k, v in data.items():
                if isinstance(v, dict):
                    _INDEX[k.upper()] = {**v, "enriched": True}
        if _INDEX:
            _WARM_STATE.update(done=True, progress=100, message="Enriched cache loaded")
        return bool(_INDEX)
    except (json.JSONDecodeError, OSError):
        return False


def warm_index(extra_tickers: list[str] | None = None, blocking: bool = False) -> None:
    """Enrich only explicit tickers (holdings, watchlist) — not the full NYSE."""
    tickers = list(dict.fromkeys(t.upper() for t in (extra_tickers or []) if t))
    if not tickers:
        return
    if _WARM_STATE["running"]:
        return

    def _run() -> None:
        _ensure_light_index()
        _WARM_STATE.update(running=True, done=False, progress=0, message="Enriching symbols…")
        total = len(tickers)
        _WARM_STATE["total"] = total
        done_count = 0

        def _index_one(ticker: str) -> tuple[str, dict[str, Any] | None]:
            return ticker, _build_entry(ticker)

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = {pool.submit(_index_one, t): t for t in tickers}
            for fut in as_completed(futures):
                ticker, entry = fut.result()
                done_count += 1
                if entry:
                    with _INDEX_LOCK:
                        _INDEX[ticker] = entry
                if done_count % 10 == 0:
                    _save_cache()
                _WARM_STATE.update(
                    progress=int(done_count / total * 100),
                    message=f"Enriched {done_count}/{total} symbols…",
                )

        _save_cache()
        _WARM_STATE.update(running=False, done=True, progress=100, message="Symbol enrichment ready")

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()


def ensure_index(extra: list[str] | None = None) -> None:
    _ensure_light_index()
    _load_cache()
    if extra:
        missing = [t.upper() for t in extra if t.upper() not in _INDEX]
        if missing:
            warm_index(missing, blocking=False)


def warm_status() -> dict[str, Any]:
    status = dict(_WARM_STATE)
    status["universe_size"] = len(_LIGHT_INDEX) or len(get_nyse_universe())
    status["enriched_count"] = len(_INDEX)
    return status


def _score_entry(entry: dict[str, Any], tokens: list[str], raw: str) -> float:
    score = 0.0
    ticker = entry["ticker"]
    name = entry.get("name", "").lower()
    sector = (entry.get("sector") or "").lower()
    industry = (entry.get("industry") or "").lower()
    location = (entry.get("location") or "").lower()
    summary = (entry.get("summary") or "").lower()
    blob = f"{ticker.lower()} {name} {sector} {industry} {location} {summary}"

    raw_u = raw.strip().upper()
    if raw_u == ticker:
        score += 200
    elif ticker.startswith(raw_u) and len(raw_u) >= 1:
        score += 120
    elif raw_u in ticker:
        score += 60

    for tok in tokens:
        if len(tok) < 2:
            continue
        if tok in name.split():
            score += 35
        if name.startswith(tok):
            score += 45
        if tok in sector or tok in industry:
            score += 28
        if tok in location or tok in blob:
            score += 18
        if tok in summary:
            score += 8

    if score > 0:
        score += min(20, (entry.get("market_cap") or 0) / 1e11)
        if entry.get("enriched"):
            score += 5
    return score


def _merge_enriched(entry: dict[str, Any]) -> dict[str, Any]:
    ticker = entry["ticker"]
    with _INDEX_LOCK:
        cached = _INDEX.get(ticker)
    if cached and cached.get("enriched"):
        return cached
    built = _build_entry(ticker)
    if built:
        with _INDEX_LOCK:
            _INDEX[ticker] = built
        return built
    return entry


def search_symbols(query: str, limit: int = 10, lite: bool = False) -> list[dict[str, Any]]:
    q = query.strip()
    if len(q) < 1:
        return []

    _ensure_light_index()
    _load_cache()

    tokens = [t.lower() for t in re.findall(r"[a-zA-Z0-9]+", q.lower()) if len(t) > 1]

    with _INDEX_LOCK:
        light_entries = list(_LIGHT_INDEX.values())
        enriched = dict(_INDEX)

    pool = light_entries
    if enriched:
        seen = {e["ticker"] for e in light_entries}
        for t, e in enriched.items():
            if t not in seen:
                pool.append(e)

    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in pool:
        s = _score_entry(entry, tokens, q)
        if s > 0:
            merged = enriched.get(entry["ticker"], entry)
            scored.append((s, merged))

    scored.sort(key=lambda x: (-x[0], -(x[1].get("market_cap") or 0), x[1]["ticker"]))
    top = [e for _, e in scored[:limit]]

    if not top and re.match(r"^[A-Za-z.\-]{1,8}$", q):
        t = q.upper().replace(".", "-")
        if t in _LIGHT_INDEX:
            top = [_merge_enriched(_LIGHT_INDEX[t])]
        else:
            entry = _build_entry(t)
            if entry:
                with _INDEX_LOCK:
                    _INDEX[t] = entry
                top = [entry]

    if not top:
        return []

    if lite:
        return top[:limit]

    with ThreadPoolExecutor(max_workers=min(5, len(top))) as pool_exec:
        futures = {pool_exec.submit(_merge_enriched, e): e["ticker"] for e in top}
        out = []
        for fut in as_completed(futures):
            try:
                out.append(fut.result())
            except Exception:
                pass
        order = {e["ticker"]: i for i, e in enumerate(top)}
        out.sort(key=lambda e: order.get(e["ticker"], 99))
        return out[:limit]


def get_cached_symbol(ticker: str) -> dict[str, Any] | None:
    ensure_index([ticker.upper()])
    with _INDEX_LOCK:
        hit = _INDEX.get(ticker.upper())
    if hit:
        return hit
    _ensure_light_index()
    light = _LIGHT_INDEX.get(ticker.upper())
    if light:
        return _merge_enriched(light)
    return None

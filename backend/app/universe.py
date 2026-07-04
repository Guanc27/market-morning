"""NYSE symbol universe from NASDAQ Trader symbol directory."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

_NYSE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "nyse_universe.json"
# Exchange listings change slowly (IPOs/delists) — weekly refresh is sufficient.
_MAX_AGE = timedelta(days=7)
_LOCK = threading.Lock()


def yfinance_ticker(symbol: str) -> str:
    """NASDAQ directory uses dots; yfinance expects hyphens (e.g. BRK.B → BRK-B)."""
    return symbol.strip().upper().replace(".", "-")


def _parse_nyse_lines(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if not line or line.startswith("File Creation") or line.startswith("ACT Symbol"):
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        raw_symbol, name, exchange, _cqs, etf, _lot, test_issue, _ = parts[:8]
        if exchange != "N" or test_issue == "Y":
            continue
        symbol = yfinance_ticker(raw_symbol)
        if not symbol or not re.match(r"^[A-Z][A-Z0-9\-]{0,7}$", symbol):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        rows.append(
            {
                "ticker": symbol,
                "name": name.strip(),
                "is_etf": etf == "Y",
                "exchange": "NYSE",
            }
        )
    rows.sort(key=lambda r: r["ticker"])
    return rows


def fetch_nyse_universe() -> list[dict[str, Any]]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        resp = client.get(_NYSE_URL, headers={"User-Agent": "MarketMorning/1.0"})
        resp.raise_for_status()
        return _parse_nyse_lines(resp.text)


def sync_nyse_universe(force: bool = False) -> list[dict[str, Any]]:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not force and _CACHE_PATH.exists():
        try:
            cached = json.loads(_CACHE_PATH.read_text())
            updated = cached.get("updated_at")
            symbols = cached.get("symbols") or []
            if symbols and updated:
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) - dt < _MAX_AGE:
                    return symbols
        except (json.JSONDecodeError, ValueError, OSError):
            pass

    with _LOCK:
        if not force and _CACHE_PATH.exists():
            try:
                cached = json.loads(_CACHE_PATH.read_text())
                if cached.get("symbols"):
                    updated = cached.get("updated_at")
                    if updated:
                        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                        if datetime.now(timezone.utc) - dt < _MAX_AGE:
                            return cached["symbols"]
            except (json.JSONDecodeError, ValueError, OSError):
                pass

        symbols = fetch_nyse_universe()
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(symbols),
            "symbols": symbols,
        }
        _CACHE_PATH.write_text(json.dumps(payload, indent=2))
        return symbols


def get_nyse_universe() -> list[dict[str, Any]]:
    return sync_nyse_universe(force=False)


def get_nyse_tickers(stocks_only: bool = False) -> list[str]:
    symbols = get_nyse_universe()
    if stocks_only:
        symbols = [s for s in symbols if not s.get("is_etf")]
    return [s["ticker"] for s in symbols]

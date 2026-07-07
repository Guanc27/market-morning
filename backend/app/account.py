"""Robinhood account snapshot (cash, buying power) from sync file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "robinhood_positions.json"


def load_account() -> dict[str, Any]:
    if not SNAPSHOT.exists():
        return {}
    try:
        data = json.loads(SNAPSHOT.read_text())
        return data.get("account") or {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_snapshot_positions() -> dict[str, dict[str, Any]]:
    """Per-ticker broker snapshot position data from the last sync.

    Each value may carry ``price`` / ``market_value`` / ``change_pct`` captured
    from the broker at sync time — the authoritative fallback used when a live
    quote is missing so a genuinely-held position never renders as "—".
    """
    if not SNAPSHOT.exists():
        return {}
    try:
        data = json.loads(SNAPSHOT.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in data.get("holdings") or []:
        ticker = row.get("ticker")
        if ticker:
            out[str(ticker).upper()] = row
    return out

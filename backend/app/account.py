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

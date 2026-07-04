"""Parse AI markdown + mm-meta JSON block."""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai_sanitize import sanitize_ai_output

META_PATTERN = re.compile(r"```mm-meta\s*([\s\S]*?)```", re.IGNORECASE)


def parse_ai_response(raw: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"actions": [], "watchlist_adds": [], "positions": []}
    content = raw.strip()
    match = META_PATTERN.search(raw)
    if match:
        content = META_PATTERN.sub("", raw).strip()
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict):
                meta["actions"] = parsed.get("actions") or []
                meta["watchlist_adds"] = parsed.get("watchlist_adds") or []
                meta["positions"] = parsed.get("positions") or []
        except json.JSONDecodeError:
            pass
    return {
        "content": sanitize_ai_output(content),
        "actions": meta["actions"],
        "watchlist_adds": meta["watchlist_adds"],
        "positions": meta["positions"],
    }

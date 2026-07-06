"""Additive per-analysis markdown persistence.

Every successful generation (morning brief, top picks, explore sector deep-dive,
portfolio analysis) is written to its own dated .md file under
``backend/data/analyses/<kind>/``. This is additive to the existing sqlite
storage and must never crash generation — all failures are logged and swallowed.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ANALYSES_ROOT = Path(__file__).resolve().parent.parent / "data" / "analyses"

# Map generation kind -> subdirectory. Kept explicit so paths stay predictable.
_KIND_DIRS = {
    "brief": "brief",
    "picks": "picks",
    "explore": "explore",
    "portfolio": "portfolio",
}


def _slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:max_len].strip("-")) or "market"


def _front_matter(kind: str, date: str, generated_at: str, model: str, extra: dict[str, Any] | None) -> str:
    lines = [
        "---",
        f"type: {kind}",
        f"date: {date}",
        f"generated_at: {generated_at}",
        f"model: {model or 'unknown'}",
    ]
    for key, value in (extra or {}).items():
        if value is None:
            continue
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def write_analysis_md(
    kind: str,
    content: str,
    *,
    model: str = "",
    slug: str | None = None,
    date: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path | None:
    """Write one generation's content to its own dated markdown file.

    Returns the written path, or ``None`` if the write failed (never raises).
    """
    try:
        if not content or not content.strip():
            return None
        subdir = _KIND_DIRS.get(kind)
        if not subdir:
            logger.warning("write_analysis_md: unknown kind %r", kind)
            return None

        now = datetime.now(timezone.utc)
        day = date or now.strftime("%Y-%m-%d")
        generated_at = now.isoformat()

        target_dir = _ANALYSES_ROOT / subdir
        target_dir.mkdir(parents=True, exist_ok=True)

        if kind == "explore":
            filename = f"{_slugify(slug or 'market')}-{day}.md"
        else:
            filename = f"{day}.md"
        path = target_dir / filename

        front_matter = _front_matter(kind, day, generated_at, model, extra)
        path.write_text(f"{front_matter}\n\n{content.strip()}\n", encoding="utf-8")
        return path
    except Exception as exc:  # never let persistence break generation
        logger.warning("write_analysis_md failed for kind=%s: %s", kind, exc)
        return None

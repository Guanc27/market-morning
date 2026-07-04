"""Strip model thinking artifacts from user-visible text."""

from __future__ import annotations

import re

# Anthropic thinking block repr leaked when only thinking block returned or cached badly
_THINKING_RE = re.compile(r"ThinkingBlock\([\s\S]*?\)\s*", re.MULTILINE)
_THINKING_TAIL_RE = re.compile(r"ThinkingBlock\([\s\S]*$", re.MULTILINE)
_META_FENCE_RE = re.compile(r"```mm-meta[\s\S]*?```", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_EMPH_RE = re.compile(r"\*+([^*]+)\*+")


def _normalize_emphasis_markers(text: str) -> str:
    if not text or "*" not in text:
        return text
    t = re.sub(r"\*\*\s+", "**", text)
    t = re.sub(r"\s+\*\*", "**", t)
    t = re.sub(r"\*\s+\*(?=\S)", "**", t)
    t = re.sub(r"(?<=\S)\*\s+\*", "**", t)
    return t


def sanitize_ai_output(text: str) -> str:
    if not text:
        return ""
    cleaned = _THINKING_RE.sub("", text)
    cleaned = _THINKING_TAIL_RE.sub("", cleaned)
    if "type='thinking'" in cleaned or 'type="thinking"' in cleaned:
        idx = cleaned.find("ThinkingBlock(")
        if idx >= 0:
            cleaned = cleaned[:idx]
    cleaned = _strip_production_meta(cleaned)
    cleaned = _strip_holdings_overview_table(cleaned)
    cleaned = _normalize_emphasis_markers(cleaned)
    return cleaned.strip()


_GENERIC_FEED_TITLE_RE = re.compile(
    r"^(top (&|and) breaking|world news today|marketwatch top stories|latest headlines?)\b",
    re.I,
)
_LIFESTYLE_HEADLINE_RE = re.compile(
    r"(reverse mortgage|inheritance|netflix, hulu|streaming in \w+ 20|aging parent|"
    r"trump account|home-equity|fourth of july|greedy|make it to 80|"
    r"new romance|personal finance|here'?s what'?s worth streaming|"
    r"protect your inheritance|opening a .trump account)",
    re.I,
)
_PRODUCTION_META_LINE_RE = re.compile(
    r"(?im)^(?:#+\s*)?(?:\*{0,2})?(?:Note:|FYI:)?.*"
    r"\b(small_cap_candidates|candidates array|exclusion list|screened against|"
    r"json context|provided context|data pipeline|array came back|sourced from the|"
    r"sector research and|empty so|was empty|context object)\b.*$"
)


def _strip_production_meta(text: str) -> str:
    if not text:
        return ""
    lines = []
    for line in text.split("\n"):
        if _PRODUCTION_META_LINE_RE.match(line.strip()):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


_HOLDINGS_OVERVIEW_SECTION_RE = re.compile(
    r"(?ms)^#{1,3}\s+Holdings overview\s*\n.*?(?=^#{1,4}\s|\Z)",
)
_PORTFOLIO_PULSE_TABLE_RE = re.compile(
    r"(?ms)(^#{1,2}\s+Portfolio Pulse\s*\n)\s*\|[^\n]+\|\s*\n\|[-:\s|]+\|\s*\n(?:\|[^\n]+\|\s*\n)*",
)
_HOLDINGS_SUMMARY_TABLE_RE = re.compile(
    r"(?ms)^\|[^\n]*Ticker[^\n]*\|[^\n]*Shares[^\n]*\|\s*\n\|[-:\s|]+\|\s*\n(?:\|[^\n]+\|\s*\n)*",
)


def _strip_holdings_overview_table(text: str) -> str:
    if not re.search(r"(?im)(portfolio pulse|holdings overview|\|[^\n]*ticker[^\n]*shares)", text):
        return text
    t = _HOLDINGS_OVERVIEW_SECTION_RE.sub("", text)
    t = _PORTFOLIO_PULSE_TABLE_RE.sub(r"\1", t)
    t = _HOLDINGS_SUMMARY_TABLE_RE.sub("", t)
    return re.sub(r"\n{3,}", "\n\n", t)


def markdown_plain_excerpt(text: str, max_chars: int = 520) -> str:
    """Readable plain-text blurb for recap cards — never raw markdown."""
    if not text:
        return ""
    t = sanitize_ai_output(text).replace("\r\n", "\n")
    t = _META_FENCE_RE.sub("", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.MULTILINE)
    t = _MD_LINK_RE.sub(r"\1", t)
    t = _MD_EMPH_RE.sub(r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()

    skip_prefixes = (
        "morning market brief",
        "overnight",
        "pre-market",
        "pre market",
    )
    parts: list[str] = []
    for raw_line in t.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("|") or line.startswith("---"):
            continue
        lower = line.lower()
        if any(lower.startswith(p) for p in skip_prefixes):
            continue
        parts.append(line)
        joined = " ".join(parts)
        if len(joined) >= max_chars:
            break

    out = " ".join(parts)
    if len(out) > max_chars:
        cut = out[: max_chars - 1]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        out = cut + "…"
    return out


def synopsis_looks_like_markdown(text: str) -> bool:
    if not text:
        return True
    head = text.lstrip()[:160]
    return head.startswith("#") or "\n## " in head or "\n# " in head

"""Strip model thinking artifacts from user-visible text."""

from __future__ import annotations

import re

from app.review_gate import (
    normalize_brief_title,
    normalize_source_spacing,
    scrub_generic_meta,
)

# Anthropic thinking block repr leaked when only thinking block returned or cached badly
_THINKING_RE = re.compile(r"ThinkingBlock\([\s\S]*?\)\s*", re.MULTILINE)
_THINKING_TAIL_RE = re.compile(r"ThinkingBlock\([\s\S]*$", re.MULTILINE)
_META_FENCE_RE = re.compile(r"```mm-meta[\s\S]*?```", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MD_EMPH_RE = re.compile(r"\*+([^*]+)\*+")


def _normalize_emphasis_markers(text: str) -> str:
    if not text or "*" not in text:
        return text
    # Only collapse HORIZONTAL whitespace around emphasis markers — never
    # newlines. Using \s+ here previously ate the blank line before a
    # line-leading "**Label**", gluing headings/paragraphs together
    # (e.g. "### Information Technology**News**").
    t = re.sub(r"\*\*[ \t]+", "**", text)
    t = re.sub(r"[ \t]+\*\*", "**", t)
    t = re.sub(r"\*[ \t]+\*(?=\S)", "**", t)
    t = re.sub(r"(?<=\S)\*[ \t]+\*", "**", t)
    return t


def _strip_raw_html(text: str) -> str:
    if not text or "<" not in text:
        return text
    protected: list[str] = []

    def _protect_term(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"@@TERMPROT{len(protected) - 1}@@"

    t = re.sub(
        r'<term\s+id="[^"]+"[^>]*>[\s\S]*?</term>',
        _protect_term,
        text,
        flags=re.I,
    )
    t = re.sub(
        r'<a\s+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
        lambda m: f"[{re.sub(r'<[^>]+>', '', m.group(2)).strip()}]({m.group(1)})",
        t,
        flags=re.I,
    )
    t = re.sub(r"<style[\s\S]*?</style>", "", t, flags=re.I)
    t = re.sub(r"<script[\s\S]*?</script>", "", t, flags=re.I)
    t = re.sub(r"<!--[\s\S]*?-->", "", t)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<a\s+href=[^>\n]*>?[^\n]*", "", t, flags=re.I)
    t = re.sub(r"</a>", "", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = re.sub(r"\{[^{}]*(?:color|font|margin|padding|display)\s*:[^{}]+\}", "", t, flags=re.I)

    def _restore_term(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return protected[idx] if 0 <= idx < len(protected) else ""

    t = re.sub(r"@@TERMPROT(\d+)@@", _restore_term, t)
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
    # Enforce PRODUCTION_RULE as an actual post-gen check for every generation:
    # drop pipeline/meta-commentary + self-correction narration. Fence-safe, so
    # the ``mm-meta`` JSON block is never touched (this runs inside _chat before
    # meta is parsed out).
    cleaned = scrub_generic_meta(cleaned)
    cleaned = _strip_holdings_overview_table(cleaned)
    cleaned = _strip_quant_actions_section(cleaned)
    cleaned = _strip_raw_html(cleaned)
    cleaned = _normalize_emphasis_markers(cleaned)
    # Re-space glued **bold**, a glued prose colon, and N. list markers as the
    # LAST step: _normalize_emphasis_markers collapses spaces adjacent to ``**``
    # (fixing spaces INSIDE emphasis) but that also re-glues legit OUTSIDE
    # boundaries, so the source-glue fixer must run after it. Fence-aware, so the
    # ``mm-meta`` JSON block is never touched.
    cleaned = normalize_source_spacing(cleaned)
    # Canonicalize the brief H1 on EVERY read path (today, recap, archive). Only
    # a brief-title-variant H1 is rewritten (picks/explore/portfolio H1s never
    # contain "brief"), and the date already in the title is preserved.
    cleaned = normalize_brief_title(cleaned)
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


_QUANT_ACTIONS_SECTION_RE = re.compile(
    r"(?ms)^## Quant Actions\s*\n.*?(?=^## |\Z)",
)


def _strip_quant_actions_section(text: str) -> str:
    if not text or "## Quant Actions" not in text:
        return text
    t = _QUANT_ACTIONS_SECTION_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", t)


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

"""Shared production-ready review/finalization gate for AI generations.

The picks path already enforces a deterministic review pass (`_scrub_picks_meta`
in `ai.py`) plus prompt rules so its FINAL output is clean and professional.
This module generalizes that idea into reusable, deterministic scrubbers +
lightweight detectors that every generation type (morning brief, explore
deep-dive, portfolio analysis, picks) runs before its output is stored/returned.

Design principles (mirrors the picks worker):
  - DETERMINISTIC FIRST: the mechanical failure classes (pipeline/meta-commentary
    leakage, self-correction narration, false data-integrity narration, stray or
    broken ``mm-meta`` fences, glued labels) are removed by regex here so the fix
    holds even when the LLM is unavailable / rate-limited.
  - FENCE-SAFE: scrubbing never touches text inside a fenced code block (so the
    ``mm-meta`` JSON is never corrupted) and never rewrites headings/tables.
  - CONSERVATIVE: patterns target phrasing that essentially never appears in
    legitimate finance prose, so real analysis is never damaged (same philosophy
    as ticker_validation: only fire on unambiguous cases).
  - DETECT-THEN-REPAIR: structural gaps that cannot be scrubbed in
    deterministically (a missing required section) are reported so the caller can
    run at most ONE lightweight LLM repair pass.
"""

from __future__ import annotations

import json
import re
from typing import Any

# --- Pipeline / meta-commentary leakage (ALL generation types) ---------------
# High-confidence "talking about the data pipeline / the prompt / being an AI"
# phrasing. Enforces PRODUCTION_RULE as an actual post-gen check. Any sentence
# containing one of these is dropped.
_PIPELINE_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.I) for p in [
    r"your provided research set",
    r"the news flow i have",
    r"\bcomparison set\b",
    r"this cycle'?s (?:data|dataset)",
    r"\bthis dataset\b",
    r"the provided (?:articles?|context|research|data|feed|news|headlines?)",
    r"\bprovided context\b",
    r"in the provided context",
    r"in the context provided",
    r"based on the (?:data|context|articles?|research|feed|information|news) (?:provided|i have|i was given|available)(?!\s+by\b)",
    r"\bmy research set\b",
    r"\bthe set i have\b",
    r"\bfrom the feed\b",
    r"\bdata pipeline\b",
    r"\bcontext (?:object|window)\b",
    r"\bexclusion list\b",
    r"\bscreening logic\b",
    r"\bcandidates? array\b",
    r"\bempty (?:array|dataset)\b",
    r"sourced from the (?:sector research|feed|context|provided)",
    r"the array (?:came back|was empty|is empty|returned)",
    r"no (?:direct )?source (?:in|from) (?:the )?(?:feed|context|research|data)",
    r"\bjson (?:context|field|block|object|array|payload)\b",
    r"\bin the json\b",
    r"the (?:data|information) (?:you |i was |i were |)(?:provided|gave me|fed me|supplied)(?!\s+by\b)",
    r"\b(?:was|were) (?:not )?(?:provided|fed|supplied) (?:in the (?:context|feed|data|json|dataset)|to me|to the model|by the (?:context|feed|pipeline|prompt))\b",
]]

# --- Self-correction / reasoning narration (ALL types) -----------------------
_SELF_CORRECTION_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.I) for p in [
    r"^\s*wait[,.\s]",
    r"\bwait[,—–-]\s*(?:this|that|i|let|no|actually|is)\b",
    r"\blet me (?:reconsider|rethink|revise|re-?examine|re-?work|re-?do|pivot|substitute|swap|replace|instead|correct|adjust|clarify|check|recalculate|reassess)\b",
    r"\bi'?ll (?:pivot|substitute|swap|replace)\b",
    r"\bactually,?\s*(?:let me|i should|scratch that|i need to|on second)\b",
    r"\bscratch that\b",
    r"\bon second thought\b",
    r"\bas an ai\b",
    r"\bas a language model\b",
    r"\bi (?:cannot|can'?t|can not|should not|shouldn'?t|won'?t|am unable to|do not have the ability to) (?:provide|access|generate|share|give|offer|fabricate)\b",
    r"\bi (?:apologize|apologise)\b",
    r"\bi (?:don'?t|do not) have (?:access to |)(?:real-?time|current|live|up-?to-?date)\b",
    r"\bmy (?:training data|knowledge cutoff|last update)\b",
    r"\b(?:substitut(?:e|ing)|replacing)\b[^.\n]*\balready (?:held|owned|in (?:the|your))\b",
    r"\balready (?:held|owned|a holding)\b[^.\n]*\b(?:skip|omit|substitut|replac|swap)\b",
]]

# --- False data-integrity narration (PORTFOLIO especially) -------------------
# A transient missing live quote must NEVER be narrated as a loss/wipeout. Any
# sentence with one of these is dropped (the QUOTE INTEGRITY rule's post-gen
# enforcement).
_DATA_INTEGRITY_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.I) for p in [
    r"\$0\.00\b",
    r"value (?:of )?\$0\b",
    r"priced? (?:at )?\$0\b",
    r"\$0(?!\.\d)(?!\d)",
    r"-\s?100\s?%",
    r"\b100\s?%\s*(?:loss|wipeout|wiped|decline|drop|down)\b",
    r"\bwiped out\b",
    r"\bwipeout\b",
    r"\breverse split\b",
    r"\bdelist(?:ed|ing)?\b",
    r"\bdata[- ]feed break\b",
    r"\btotal loss\b",
    r"\bwent to zero\b",
    r"\bzeroed out\b",
    r"\bworthless\b",
    r"\bcollapsed to (?:zero|\$0)\b",
]]

_LIST_PREFIX_RE = re.compile(r"^(\s*(?:[-*+]|\d+[.)])\s+)(.*)$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_HR_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")

META_FENCE_RE = re.compile(r"```mm-meta[\s\S]*?```", re.IGNORECASE)
_META_OPEN_RE = re.compile(r"```mm-meta", re.IGNORECASE)
_META_PARSE_RE = re.compile(r"```mm-meta\s*([\s\S]*?)```", re.IGNORECASE)


def _is_structural(line: str) -> bool:
    s = line.lstrip()
    if not s:
        return True
    if s.startswith("#") or s.startswith("|") or s.startswith(">"):
        return True
    if _HR_RE.match(line) or _TABLE_SEP_RE.match(line):
        return True
    return False


def _matches_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(text) for p in patterns)


def _scrub(content: str, patterns: list[re.Pattern[str]]) -> str:
    """Drop prose sentences matching any pattern; never touch fenced/structural text."""
    if not content:
        return content
    out: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or _is_structural(line):
            out.append(line)
            continue
        m = _LIST_PREFIX_RE.match(line)
        prefix, body = (m.group(1), m.group(2)) if m else ("", line)
        parts = [p for p in _SENTENCE_SPLIT_RE.split(body) if p]
        kept = [p for p in parts if not _matches_any(p, patterns)]
        new_body = " ".join(kept).strip()
        if not new_body:
            # Entire prose line was meta/false-data narration → drop the line.
            continue
        out.append(f"{prefix}{new_body}" if prefix else new_body)
    result = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def scrub_generic_meta(content: str) -> str:
    """Remove pipeline/meta-commentary + self-correction narration (all types)."""
    return _scrub(content, _PIPELINE_PATTERNS + _SELF_CORRECTION_PATTERNS)


def scrub_data_integrity(content: str) -> str:
    """Remove false $0 / -100% / wipeout / reverse-split / delisting narration."""
    return _scrub(content, _DATA_INTEGRITY_PATTERNS)


def count_meta_hits(content: str) -> int:
    """How many prose sentences would the generic-meta scrub drop (for evidence)."""
    return _count_hits(content, _PIPELINE_PATTERNS + _SELF_CORRECTION_PATTERNS)


def count_data_integrity_hits(content: str) -> int:
    return _count_hits(content, _DATA_INTEGRITY_PATTERNS)


def _count_hits(content: str, patterns: list[re.Pattern[str]]) -> int:
    if not content:
        return 0
    n = 0
    in_fence = False
    for line in content.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or _is_structural(line):
            continue
        _, _, body = ("", "", line)
        m = _LIST_PREFIX_RE.match(line)
        body = m.group(2) if m else line
        for p in [s for s in _SENTENCE_SPLIT_RE.split(body) if s]:
            if _matches_any(p, patterns):
                n += 1
    return n


def strip_stray_meta_fences(content: str) -> str:
    """Remove any ``mm-meta`` fence from DISPLAY content (meta lives in parsed meta).

    Handles the duplicated-fence and broken/unclosed-fence failure classes so a
    stray block never renders raw. MUST run only on the display body AFTER the
    real meta has been parsed out — never inside sanitize (which runs before the
    ideas sub-call's meta is parsed)."""
    if not content or "mm-meta" not in content.lower():
        return content
    cleaned = META_FENCE_RE.sub("", content)
    # A dangling, unclosed ```mm-meta … opener → strip from it to end of doc.
    opener = _META_OPEN_RE.search(cleaned)
    if opener:
        cleaned = cleaned[:opener.start()]
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


_GLUED_STOP_LIMIT_RE = re.compile(r"(?i)(stop\s*/\s*limit\s*:)(?=\S)")


def fix_glued_labels(content: str) -> str:
    """Ensure a space after the portfolio 'Stop / Limit:' label if glued to value."""
    if not content:
        return content
    return _GLUED_STOP_LIMIT_RE.sub(r"\1 ", content)


# --- Source-level glue normalization (defense-in-depth) ----------------------
# The frontend normalizes most glue at render, but a prose colon immediately
# before an OPENING bold ("clearly:**this") still leaks, and the stored .md /
# any non-frontend consumer sees the raw glue. These deterministic, fence-aware
# fixers space glued **bold**, add a space after a prose colon, and repair
# ``N.``-prefixed list items so the stored deliverables are clean too. They only
# fire on unambiguous glue (a missing space) so valid markdown is never damaged.
_LIST_NUM_GLUE_RE = re.compile(r"^(\s*\d+)\.(?=[^\s\d])")
# A prose colon glued to the next word/link/bold: char before is a letter/quote/
# asterisk (NOT a digit, so 10:30 / 3:1 are safe), char after starts a word / [ (
# / * — so "://" (slash) and shielded code/URLs are untouched.
_COLON_GLUE_RE = re.compile(r"(?<=[A-Za-z\"'\u2018\u2019*]):(?=[A-Za-z0-9\[(*])")
_LINK_RE = re.compile(r"\[[^\]]*\]\([^)]+\)")
_URL_RE = re.compile(r"https?://[^\s)]+")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_OPEN_BEFORE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,);%")
_CLOSE_AFTER = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789([")


def _space_bold_runs(text: str) -> str:
    """Insert a space at glued ``**bold**`` boundaries using an open/close state
    machine (so a missing space is added before an opening ``**`` and after a
    closing ``**``). Runs of ``*`` that are not exactly two are emitted verbatim
    (single-``*`` italics and ``***`` combos are left untouched)."""
    if "**" not in text:
        return text
    out: list[str] = []
    i = 0
    n = len(text)
    bold_open = False
    while i < n:
        if text[i] == "*":
            j = i
            while j < n and text[j] == "*":
                j += 1
            run = j - i
            if run == 2:
                after = text[j] if j < n else ""
                if not bold_open:
                    before = out[-1] if out else ""
                    if before in _OPEN_BEFORE:
                        out.append(" ")
                    out.append("**")
                    bold_open = True
                else:
                    out.append("**")
                    bold_open = False
                    if after in _CLOSE_AFTER:
                        out.append(" ")
                i = j
                continue
            out.append("*" * run)
            i = j
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _normalize_line_spacing(line: str) -> str:
    # Shield links, bare URLs, and inline code so their ":" / "*" are never touched.
    shielded: list[str] = []

    def _shield(m: re.Match[str]) -> str:
        shielded.append(m.group(0))
        return f"\x00{len(shielded) - 1}\x00"

    work = _LINK_RE.sub(_shield, line)
    work = _URL_RE.sub(_shield, work)
    work = _INLINE_CODE_RE.sub(_shield, work)

    work = _LIST_NUM_GLUE_RE.sub(r"\1. ", work)
    work = _COLON_GLUE_RE.sub(": ", work)
    work = _space_bold_runs(work)

    def _restore(m: re.Match[str]) -> str:
        idx = int(m.group(1))
        return shielded[idx] if 0 <= idx < len(shielded) else ""

    return re.sub(r"\x00(\d+)\x00", _restore, work)


def normalize_source_spacing(content: str) -> str:
    """Fence-aware source glue fixer for stored brief/explore/portfolio output.

    Adds missing spaces around glued ``**bold**``, after a glued prose colon, and
    after a ``N.`` list marker. Never touches text inside a fenced code block
    (so ``mm-meta`` JSON is safe) or a table-separator/horizontal-rule line."""
    if not content or ("*" not in content and ":" not in content):
        return content
    out: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or _HR_RE.match(line) or _TABLE_SEP_RE.match(line):
            out.append(line)
            continue
        out.append(_normalize_line_spacing(line))
    return "\n".join(out)


def meta_is_parseable(raw: str) -> bool:
    """True if there is at most one ``mm-meta`` fence and it parses as JSON."""
    fences = _META_PARSE_RE.findall(raw or "")
    if len(fences) > 1:
        return False
    if not fences:
        return True
    try:
        json.loads(fences[0].strip())
        return True
    except (json.JSONDecodeError, ValueError):
        return False


# --- Garbled-fragment repair (PICKS especially) ------------------------------
# A per-pick write-up can occasionally stitch/merge into a garbled fragment: a
# severed number glued to a word ("market cap.68, 5.5% of the book)"), an orphan
# "N," opening a clause, and/or a dangling close-paren with no opener. These
# signatures never occur in clean finance prose, so repair them deterministically.
# CONSERVATIVE by design (same philosophy as the meta scrubbers): the severed-
# number repair only fires when a letter-glued ".<digits>," is *also* followed by
# an unmatched close-paren, and the stray-close-paren drop only touches a line
# that has a ")" but no "(" at all — so legitimate decimals ("3.68"), matched
# parentheses, and normal prose are never mangled.

# "market cap.68, 5.5% of the book)": a letter glued to ``.<1-3 digits>,`` then
# non-paren text up to the first stray ``)``. The trailing unmatched close-paren
# is the tell that this is a severed fragment, not a valid abbreviation.
_SEVERED_NUM_FRAGMENT_RE = re.compile(r"(?<=[A-Za-z])\.\d{1,3},[^()]*?\)")
# A clause/line opening with an orphan numeric fragment: ".68, " or "68, ".
_ORPHAN_NUM_OPENER_RE = re.compile(r"^([ \t]*)\.?\d{1,3},[ \t]+")


def repair_garbled_fragments(content: str) -> str:
    """Deterministically repair obviously garbled prose fragments.

    Fence- and structure-aware. Repairs three signatures that do not occur in
    clean finance prose: (1) a severed number glued to a word followed by a
    dangling close-paren, (2) an orphan numeric clause opener, (3) a dangling
    close-paren on a line with no opener. Returns the content unchanged when no
    signature is present."""
    if not content or (")" not in content and "," not in content):
        return content
    out: list[str] = []
    in_fence = False
    for line in content.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or _is_structural(line):
            out.append(line)
            continue
        new = _SEVERED_NUM_FRAGMENT_RE.sub(".", line)
        new = _ORPHAN_NUM_OPENER_RE.sub(r"\1", new)
        # A close-paren with no opener anywhere on the line is a stray artifact.
        if ")" in new and "(" not in new:
            new = new.replace(")", "")
        if new != line:
            new = re.sub(r"[ \t]{2,}", " ", new).rstrip()
        out.append(new)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def strip_trailing_partial_heading(content: str) -> str:
    """Drop a trailing heading that has no body after it.

    A section body that truncated mid-generation can end on an empty or cut-off
    heading (e.g. ``### Cross-Compar`` with nothing under it). Such a heading
    renders as an empty/broken section, so remove any trailing run of
    heading-only lines (and their trailing blank lines) from the END of the
    content. Headings that DO have body text under them are untouched."""
    if not content or "#" not in content:
        return content
    lines = content.rstrip().split("\n")
    heading_re = re.compile(r"^\s*#{1,6}\s*\S.*$|^\s*#{1,6}\s*$")
    while lines:
        last = lines[-1]
        if not last.strip():
            lines.pop()
            continue
        if heading_re.match(last):
            lines.pop()
            continue
        break
    return "\n".join(lines).rstrip()


# A prose line that truncated mid-clause ends on a bare word character or a
# comma (e.g. "…with interest coverage" / "…their earnings power, with"). Any
# other ending — terminal punctuation, a colon lead-in, a closing quote/paren, a
# percent/number, or markdown emphasis (``*`` ``_`` `` ` ``) — is treated as a
# complete/intentional line and left untouched (conservative: never trim a line
# that merely lacks a period but is clearly finished).
_SENTENCE_END_RE = re.compile(r"^(.*[.!?…])(?=\s|$)", re.S)


def strip_trailing_partial_sentence(content: str) -> str:
    """Trim a dangling partial FINAL sentence left by a mid-generation cutoff.

    A section body whose model call hit its token cap can stop mid-clause,
    shipping a fragment like ``"…with interest coverage"`` with no terminal
    punctuation. This trims that trailing fragment: if the last prose line ends
    mid-clause it is cut back to its last complete sentence, or dropped whole
    (preserving the rest of a list) when it contains no complete sentence.

    Conservative by design — it only fires on an unambiguous mid-clause ending
    (last visible char is a letter or comma) and never touches headings, table
    rows, code fences, or lines that already end on terminal punctuation, a
    closing quote/paren, a percent/number, or markdown emphasis."""
    if not content or not content.strip():
        return content
    lines = content.rstrip().split("\n")
    while lines:
        last = lines[-1]
        stripped = last.strip()
        if not stripped:
            lines.pop()
            continue
        # Never touch structural lines (headings, tables, code fences, rules).
        if re.match(r"^\s*(?:#{1,6}\s|\||```|~~~|-{3,}\s*$|={3,}\s*$)", last):
            break
        last_char = stripped[-1]
        # Mid-clause ONLY when the raw line ends on a bare letter or a comma.
        if not (last_char.isalpha() or last_char == ","):
            break
        # Split off any leading list/quote marker so it survives a partial cut.
        m = re.match(r"^(\s*(?:[-*+]\s+|>\s+|\d+\.\s+)?)(.*)$", last, re.S)
        prefix, rest = (m.group(1), m.group(2)) if m else ("", last)
        sent = _SENTENCE_END_RE.match(rest.rstrip())
        if sent and sent.group(1).strip():
            lines[-1] = f"{prefix}{sent.group(1).rstrip()}"
        else:
            lines.pop()
        break
    return "\n".join(lines).rstrip()


# --- Canonical brief title (generation + on-read) ----------------------------
# Archived briefs drifted between "Market Morning Brief", "Market Brief",
# "Morning Brief", etc. The app is "Market Morning", so the ONE canonical H1 is
# "Morning Market Brief — <Month D, YYYY>". This normalizer rewrites any H1
# variant to that form. It only touches an H1 that is itself a brief-title
# variant (contains "brief"), so picks/explore/portfolio H1s — which never do —
# are never affected.
CANONICAL_BRIEF_TITLE = "Morning Market Brief"

_BRIEF_TITLE_H1_RE = re.compile(
    r"(?im)^[ \t]{0,3}#[ \t]+"
    r"(?:the[ \t]+)?"
    r"(?:morning[ \t]+market|market[ \t]+morning|market|morning)[ \t]+brief"
    r"[ \t]*(?:[—–\-:|][ \t]*(?P<date>.+?))?[ \t]*$"
)


def normalize_brief_title(content: str, date_display: str | None = None) -> str:
    """Rewrite the brief's H1 to `# Morning Market Brief — <date>`.

    When ``date_display`` is given (generation, or a known archive date) it is
    used verbatim; otherwise any date already present in the title is preserved
    (so on-read normalization keeps each archived brief's own date). Only the
    first brief-title H1 is rewritten."""
    if not content:
        return content

    def _repl(m: re.Match[str]) -> str:
        date = (date_display or "").strip() or (m.group("date") or "").strip()
        title = f"# {CANONICAL_BRIEF_TITLE}"
        return f"{title} — {date}" if date else title

    return _BRIEF_TITLE_H1_RE.sub(_repl, content, count=1)


def find_missing_sections(content: str, required: list[str]) -> list[str]:
    """Return required section headings that are absent from the markdown body."""
    if not content:
        return list(required)
    missing: list[str] = []
    for name in required:
        pat = re.compile(r"(?im)^#{1,4}\s+.*" + re.escape(name), re.I)
        if not pat.search(content):
            missing.append(name)
    return missing


# --- Equity reconciliation (PORTFOLIO) ---------------------------------------
_EQUITY_NEAR_RE = re.compile(
    r"(?i)(?P<label>total (?:portfolio |account )?(?:equity|value)|account equity|"
    r"portfolio (?:equity|value)|equity value|net liquidation(?:\s*value)?|"
    r"total account value|book (?:equity|value))"
    r"(?P<mid>[^$\n]{0,40}?)"
    r"(?P<dollar>\$\s?(?P<num>[\d,]+(?:\.\d+)?)(?:\s?(?P<suf>k|m|mm|bn|thousand|million|billion))?)\b"
)

_SUFFIX_MULT = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "million": 1e6,
    "bn": 1e9, "billion": 1e9,
}


def _num_to_float(num: str, suf: str | None) -> float | None:
    try:
        val = float(num.replace(",", ""))
    except ValueError:
        return None
    if suf:
        val *= _SUFFIX_MULT.get(suf.lower(), 1.0)
    return val


def _fmt_equity(value: float) -> str:
    if value >= 1000:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def reconcile_equity(content: str, expected_value: float | None) -> tuple[str, list[tuple[float, float]]]:
    """Replace a narrated portfolio total that is inconsistent with the computed
    aggregate. Returns (content, [(stated, corrected)]).

    Only fires on figures immediately tied to an unambiguous equity/total label,
    and only when the stated figure differs materially (> max(2%, $100)) from the
    authoritative aggregate — so a matching total is never rewritten."""
    if not content or not expected_value or expected_value <= 0:
        return content, []
    fixes: list[tuple[float, float]] = []

    def _repl(m: re.Match[str]) -> str:
        val = _num_to_float(m.group("num"), m.group("suf"))
        if val is None:
            return m.group(0)
        if abs(val - expected_value) <= max(expected_value * 0.02, 100.0):
            return m.group(0)
        fixes.append((val, expected_value))
        return m.group(0).replace(m.group("dollar"), _fmt_equity(expected_value))

    return _EQUITY_NEAR_RE.sub(_repl, content), fixes


# --- Top-level per-type finalization ------------------------------------------
def finalize(
    content: str,
    *,
    gen_type: str,
    required_sections: list[str] | None = None,
    expected_equity: float | None = None,
    brief_date_display: str | None = None,
) -> dict[str, Any]:
    """Run the deterministic review gate for a generation and report findings.

    Returns {content, issues, needs_repair, equity_fixes, meta_hits,
    data_integrity_hits, missing_sections}. `needs_repair` is True only for
    classes deterministic scrubbing cannot fix in place (a missing required
    section) — the caller may run at most ONE lightweight LLM repair pass."""
    original = content or ""
    meta_hits = count_meta_hits(original)
    di_hits = count_data_integrity_hits(original) if gen_type == "portfolio" else 0

    cleaned = scrub_generic_meta(original)
    if gen_type == "portfolio":
        cleaned = scrub_data_integrity(cleaned)
        cleaned = fix_glued_labels(cleaned)
    cleaned = strip_stray_meta_fences(cleaned)

    title_before = cleaned
    if gen_type == "brief":
        cleaned = normalize_brief_title(cleaned, brief_date_display)

    equity_fixes: list[tuple[float, float]] = []
    if gen_type == "portfolio" and expected_equity:
        cleaned, equity_fixes = reconcile_equity(cleaned, expected_equity)

    missing = find_missing_sections(cleaned, required_sections or [])

    issues: list[str] = []
    if gen_type == "brief" and cleaned != title_before:
        issues.append("normalized brief title")
    if meta_hits:
        issues.append(f"scrubbed {meta_hits} meta/pipeline sentence(s)")
    if di_hits:
        issues.append(f"scrubbed {di_hits} false data-integrity sentence(s)")
    if equity_fixes:
        issues.append(
            "reconciled narrated equity "
            + ", ".join(f"{_fmt_equity(a)}→{_fmt_equity(b)}" for a, b in equity_fixes)
        )
    if missing:
        issues.append("missing sections: " + ", ".join(missing))

    return {
        "content": cleaned,
        "issues": issues,
        "needs_repair": bool(missing),
        "missing_sections": missing,
        "equity_fixes": equity_fixes,
        "meta_hits": meta_hits,
        "data_integrity_hits": di_hits,
    }

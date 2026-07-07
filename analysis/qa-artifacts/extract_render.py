#!/usr/bin/env python3
"""Extract the real render-pipeline functions verbatim from extension/dist/app.js
into a standalone bundle runnable under jsc. QA only — does not modify source."""
import re, sys, pathlib

APP = pathlib.Path("/Users/guanchen/Projects/market-morning/extension/dist/app.js")
src = APP.read_text().split("\n")

# Names of top-level `function NAME(...) {` declarations we need (dependency closure).
NEEDED = [
    "mdBrief","mdExplore","mdPortfolio","md","mdInner","inlineMd","inlineMdInner",
    "escapeHtml","scrubRenderedHtml","spaceGluedBold","spaceGluedEmDash",
    "wrapMoneyAmounts","wrapBriefSections","wrapBriefSubsections","wrapExploreSections",
    "normalizeBriefTitles","normalizeMarkdownHeadings","parseHeadingLine",
    "isTableLine","isTableSep","renderTable","renderTableCards",
    "normalizeEmphasisMarkers","applyInlineEmphasis","cleanupStrayAsterisks",
    "cleanupStrayMarkdownHeaders","stripTradeSections","sanitizeContent",
    "sanitizeMarkdownSource","repairBrokenTermTokens","scrubTermArtifacts",
    "processTermTags","termToken","termHtml","renderWatchlistAdds",
]

def extract_function(name):
    start = None
    pat = re.compile(r"^function " + re.escape(name) + r"\b")
    for i, line in enumerate(src):
        if pat.match(line):
            start = i
            break
    if start is None:
        raise SystemExit(f"NOT FOUND: function {name}")
    # scan to first line that is exactly '}' (top-level close)
    for j in range(start + 1, len(src)):
        if src[j] == "}":
            return "\n".join(src[start:j+1])
    raise SystemExit(f"no close for {name}")

def extract_block(start_re, end_re):
    start = None
    sp = re.compile(start_re)
    for i, line in enumerate(src):
        if sp.match(line):
            start = i
            break
    if start is None:
        raise SystemExit(f"NOT FOUND block {start_re}")
    ep = re.compile(end_re)
    for j in range(start, len(src)):
        if ep.match(src[j]):
            return "\n".join(src[start:j+1])
    raise SystemExit(f"no end for {start_re}")

parts = []
parts.append("var _glossarySeen = null;")
parts.append(extract_block(r"^const GLOSSARY = \{", r"^\};"))
for n in NEEDED:
    parts.append(extract_function(n))

pathlib.Path("/Users/guanchen/Projects/market-morning/analysis/qa-artifacts/_render_bundle.js").write_text("\n\n".join(parts))
print("bundle written, functions:", len(NEEDED))

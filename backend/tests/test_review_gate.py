"""Tests for the deterministic review/finalization gate scrubbers."""

from app import review_gate


def test_scrub_generic_meta_drops_pipeline_sentence():
    text = "Nvidia looks strong. Based on the data provided I see momentum."
    out = review_gate.scrub_generic_meta(text)
    assert "Nvidia looks strong." in out
    assert "data provided" not in out.lower()


def test_scrub_generic_meta_drops_self_correction():
    text = "Buy XLF here. Wait, let me reconsider that call."
    out = review_gate.scrub_generic_meta(text)
    assert "Buy XLF here." in out
    assert "reconsider" not in out.lower()


def test_scrub_generic_meta_never_touches_fenced_block():
    text = "Prose line.\n```mm-meta\n{\"provided context\": 1}\n```\n"
    out = review_gate.scrub_generic_meta(text)
    assert "provided context" in out  # inside fence, untouched


def test_scrub_data_integrity_drops_false_wipeout():
    text = "NVDA is fine. This position is worthless, down -100% to $0.00."
    out = review_gate.scrub_data_integrity(text)
    assert "NVDA is fine." in out
    assert "-100" not in out
    assert "worthless" not in out.lower()


def test_normalize_brief_title_variants():
    assert review_gate.normalize_brief_title("# Market Brief — July 5, 2026").startswith(
        "# Morning Market Brief — July 5, 2026"
    )
    assert review_gate.normalize_brief_title("# Market Morning Brief").startswith(
        "# Morning Market Brief"
    )


def test_normalize_brief_title_uses_supplied_date():
    out = review_gate.normalize_brief_title("# Morning Brief — Old Date", "July 6, 2026")
    assert out.startswith("# Morning Market Brief — July 6, 2026")


def test_normalize_brief_title_preserves_existing_date_on_read():
    out = review_gate.normalize_brief_title("# Morning Brief — May 1, 2026")
    assert "May 1, 2026" in out


def test_normalize_brief_title_ignores_non_brief_h1():
    text = "# Top 5 Large-Cap Picks"
    assert review_gate.normalize_brief_title(text) == text


def test_find_missing_sections():
    content = "## Portfolio Pulse\n\nStuff.\n"
    assert review_gate.find_missing_sections(content, ["Portfolio Pulse"]) == []
    assert review_gate.find_missing_sections(content, ["Quant Actions"]) == ["Quant Actions"]


def test_strip_stray_meta_fences_removes_block():
    content = "Body text.\n\n```mm-meta\n{\"a\": 1}\n```\n"
    out = review_gate.strip_stray_meta_fences(content)
    assert "mm-meta" not in out
    assert "Body text." in out


def test_strip_unclosed_meta_fence():
    content = "Body.\n\n```mm-meta\n{\"a\": 1"
    out = review_gate.strip_stray_meta_fences(content)
    assert "mm-meta" not in out
    assert out.strip() == "Body."


def test_reconcile_equity_narration_fixes_wrong_total():
    content = "Total portfolio value is $9,000 as of today."
    out, fixes = review_gate.reconcile_equity(content, 11386.0)
    assert "$11,386" in out
    assert fixes and fixes[0][1] == 11386.0


def test_reconcile_equity_narration_leaves_matching_total():
    content = "Total portfolio value is $11,400 today."
    out, fixes = review_gate.reconcile_equity(content, 11386.0)
    assert out == content
    assert fixes == []


def test_repair_severed_number_and_dangling_paren():
    content = (
        "Up 5.06% to $8.92 on an $8.77B market cap.68, 5.5% of the book) — "
        "Joby leads the eVTOL race."
    )
    out = review_gate.repair_garbled_fragments(content)
    assert ".68," not in out
    assert "5.5% of the book" not in out
    assert out.count(")") == 0
    assert "$8.77B market cap." in out
    assert "Joby leads the eVTOL race." in out


def test_repair_drops_orphan_numeric_opener():
    content = "68, 5.5% of the book remains concentrated."
    out = review_gate.repair_garbled_fragments(content)
    assert out == "5.5% of the book remains concentrated."


def test_repair_drops_stray_close_paren_with_no_opener():
    content = "Margins expanded to 42% this quarter) which is notable."
    out = review_gate.repair_garbled_fragments(content)
    assert ")" not in out
    assert "Margins expanded to 42% this quarter which is notable." == out


def test_repair_keeps_valid_decimals_and_matched_parens():
    content = "Trades at 3.68x sales (a discount to peers at 5.2x)."
    out = review_gate.repair_garbled_fragments(content)
    assert out == content


def test_repair_never_touches_fenced_block():
    content = "Body.\n```mm-meta\n{\"a\": \"cap.68, x)\"}\n```"
    out = review_gate.repair_garbled_fragments(content)
    assert "cap.68, x)" in out  # inside fence, untouched


def test_finalize_brief_normalizes_title_and_scrubs():
    content = "# Market Brief\n\nBased on the data provided, buy XLF."
    result = review_gate.finalize(content, gen_type="brief", brief_date_display="July 6, 2026")
    assert result["content"].startswith("# Morning Market Brief — July 6, 2026")
    assert "data provided" not in result["content"].lower()

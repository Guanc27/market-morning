"""Tests for the deterministic picks review pass (_scrub_picks_meta)."""

from app import ai


def test_expand_held_includes_share_class_siblings():
    expanded = ai._expand_held({"GOOGL"})
    assert "GOOG" in expanded and "GOOGL" in expanded


def test_scrub_drops_held_pick_and_renumbers():
    content = (
        "# Top 5 Large-Cap Picks\n\n"
        "### 1. Apple Inc. (AAPL)\n\n"
        "Great fundamentals.\n\n"
        "### 2. Nvidia (NVDA)\n\n"
        "AI leader.\n"
    )
    held = ai._expand_held({"AAPL"})
    out = ai._scrub_picks_meta(content, held)
    assert "AAPL" not in out
    assert "Great fundamentals." not in out
    assert "### 1. Nvidia (NVDA)" in out


def test_scrub_strips_self_correction_narration():
    content = (
        "# Top 5 Small-Cap & Growth Picks\n\n"
        "### 1. Krystal (KRYS)\n\n"
        "Strong pipeline (already held, skip). Solid setup.\n"
    )
    out = ai._scrub_picks_meta(content, ai._expand_held(set()))
    assert "already held" not in out.lower()
    assert "Krystal" in out


def test_scrub_keeps_clean_content():
    content = (
        "# Top 5 Large-Cap Picks\n\n"
        "### 1. Nvidia (NVDA)\n\n"
        "AI leader.\n"
    )
    out = ai._scrub_picks_meta(content, ai._expand_held(set()))
    assert "### 1. Nvidia (NVDA)" in out
    assert "AI leader." in out

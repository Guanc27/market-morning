"""Subscription tier and usage enforcement tests."""

from __future__ import annotations

import pytest

from app.subscriptions import Feature, Tier, check_feature, quota_for_event, tier_spec


def test_free_tier_blocks_premium_features():
    ok, reason = check_feature(Tier.FREE, Feature.PICKS)
    assert not ok
    assert "Pro" in reason

    ok, reason = check_feature(Tier.FREE, Feature.PORTFOLIO_ANALYSIS)
    assert not ok
    assert "Pro" in reason

    ok, _ = check_feature(Tier.FREE, Feature.BRIEF_READ)
    assert ok

    ok, _ = check_feature(Tier.FREE, Feature.PORTFOLIO_VIEW)
    assert ok


def test_pro_tier_allows_picks_and_portfolio():
    ok, _ = check_feature(Tier.PRO, Feature.PICKS)
    assert ok
    ok, _ = check_feature(Tier.PRO, Feature.PORTFOLIO_ANALYSIS)
    assert ok
    ok, reason = check_feature(Tier.PRO, Feature.PICKS_REFRESH)
    assert not ok


def test_desk_tier_unlimited_explore():
    assert quota_for_event(Tier.DESK, "explore") is None
    assert tier_spec(Tier.DESK).portfolio_analysis_daily is True


def test_pricing_vs_claude_positioning():
    pro = tier_spec(Tier.PRO)
    desk = tier_spec(Tier.DESK)
    assert pro.price_monthly_usd > 0
    assert desk.price_monthly_usd > pro.price_monthly_usd
    assert pro.price_monthly_usd >= 19  # above Claude Pro anchor

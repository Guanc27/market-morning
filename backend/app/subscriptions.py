"""Subscription tiers, entitlements, and usage quotas."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Tier(str, Enum):
    FREE = "free"
    PRO = "pro"
    DESK = "desk"


@dataclass(frozen=True)
class TierSpec:
    id: Tier
    name: str
    tagline: str
    price_monthly_usd: int
    price_yearly_usd: int
    # Feature flags
    morning_brief_daily: bool
    morning_brief_regen_per_month: int
    late_day_daily: bool
    picks_daily: bool
    picks_force_refresh_per_month: int
    portfolio_analysis_per_month: int
    portfolio_analysis_daily: bool
    portfolio_force_refresh_per_month: int
    explore_per_month: int | None  # None = unlimited
    brief_archive_days: int | None  # None = unlimited
    robinhood_sync: bool
    watchlist_limit: int | None  # None = unlimited
    picks_preview_only: bool


TIERS: dict[Tier, TierSpec] = {
    Tier.FREE: TierSpec(
        id=Tier.FREE,
        name="Reader",
        tagline="Daily market brief and portfolio tracking",
        price_monthly_usd=0,
        price_yearly_usd=0,
        morning_brief_daily=True,
        morning_brief_regen_per_month=0,
        late_day_daily=False,
        picks_daily=False,
        picks_force_refresh_per_month=0,
        portfolio_analysis_per_month=0,
        portfolio_analysis_daily=False,
        portfolio_force_refresh_per_month=0,
        explore_per_month=1,
        brief_archive_days=7,
        robinhood_sync=False,
        watchlist_limit=15,
        picks_preview_only=True,
    ),
    Tier.PRO: TierSpec(
        id=Tier.PRO,
        name="Investor",
        tagline="AI picks and weekly portfolio analytics",
        price_monthly_usd=22,
        price_yearly_usd=211,
        morning_brief_daily=True,
        morning_brief_regen_per_month=2,
        late_day_daily=True,
        picks_daily=True,
        picks_force_refresh_per_month=0,
        portfolio_analysis_per_month=4,
        portfolio_analysis_daily=False,
        portfolio_force_refresh_per_month=0,
        explore_per_month=4,
        brief_archive_days=90,
        robinhood_sync=True,
        watchlist_limit=None,
        picks_preview_only=False,
    ),
    Tier.DESK: TierSpec(
        id=Tier.DESK,
        name="Active Trader",
        tagline="Daily quant portfolio and unlimited explore",
        price_monthly_usd=49,
        price_yearly_usd=470,
        morning_brief_daily=True,
        morning_brief_regen_per_month=5,
        late_day_daily=True,
        picks_daily=True,
        picks_force_refresh_per_month=5,
        portfolio_analysis_per_month=999,
        portfolio_analysis_daily=True,
        portfolio_force_refresh_per_month=5,
        explore_per_month=None,
        brief_archive_days=None,
        robinhood_sync=True,
        watchlist_limit=None,
        picks_preview_only=False,
    ),
}


class Feature(str, Enum):
    BRIEF_READ = "brief_read"
    BRIEF_REGEN = "brief_regen"
    LATE_DAY = "late_day"
    PICKS = "picks"
    PICKS_REFRESH = "picks_refresh"
    PORTFOLIO_VIEW = "portfolio_view"
    PORTFOLIO_ANALYSIS = "portfolio_analysis"
    PORTFOLIO_ANALYSIS_REFRESH = "portfolio_analysis_refresh"
    EXPLORE = "explore"
    ROBINHOOD_SYNC = "robinhood_sync"
    WATCHLIST_ADD = "watchlist_add"


# Maps usage ledger event types to monthly quota fields on TierSpec
USAGE_EVENT_QUOTA: dict[str, str] = {
    "brief_regen": "morning_brief_regen_per_month",
    "picks": "picks_daily",  # special: daily bucket
    "picks_refresh": "picks_force_refresh_per_month",
    "portfolio_analysis": "portfolio_analysis_per_month",
    "portfolio_analysis_refresh": "portfolio_force_refresh_per_month",
    "explore": "explore_per_month",
    "late_day": "late_day_daily",
}


def tier_spec(tier: Tier | str) -> TierSpec:
    if isinstance(tier, str):
        tier = Tier(tier)
    return TIERS[tier]


def tier_from_stripe_price(price_id: str, price_map: dict[str, Tier]) -> Tier | None:
    return price_map.get(price_id)


def check_feature(tier: Tier, feature: Feature) -> tuple[bool, str]:
    """Return (allowed, reason_if_denied)."""
    spec = tier_spec(tier)
    if feature == Feature.PORTFOLIO_VIEW:
        return True, ""
    if feature == Feature.BRIEF_READ:
        return spec.morning_brief_daily, "Morning brief requires an account"
    if feature == Feature.BRIEF_REGEN:
        if spec.morning_brief_regen_per_month <= 0:
            return False, "Brief regeneration is a Pro feature"
        return True, ""
    if feature == Feature.LATE_DAY:
        if not spec.late_day_daily:
            return False, "Late-day updates require Pro or Desk"
        return True, ""
    if feature == Feature.PICKS:
        if spec.picks_preview_only:
            return False, "Today's picks require Pro or Desk — preview yesterday's picks on Free"
        return spec.picks_daily, "Top picks require Pro or Desk"
    if feature == Feature.PICKS_REFRESH:
        if spec.picks_force_refresh_per_month <= 0:
            return False, "Pick refresh is a Desk feature"
        return True, ""
    if feature == Feature.PORTFOLIO_ANALYSIS:
        if spec.portfolio_analysis_per_month <= 0 and not spec.portfolio_analysis_daily:
            return False, "Portfolio AI analysis requires Pro or Desk"
        return True, ""
    if feature == Feature.PORTFOLIO_ANALYSIS_REFRESH:
        if spec.portfolio_force_refresh_per_month <= 0:
            return False, "Portfolio refresh is a Desk feature"
        return True, ""
    if feature == Feature.EXPLORE:
        if spec.explore_per_month is not None and spec.explore_per_month <= 0:
            return False, "Explore requires a paid plan"
        return True, ""
    if feature == Feature.ROBINHOOD_SYNC:
        if not spec.robinhood_sync:
            return False, "Robinhood sync requires Pro or Desk"
        return True, ""
    if feature == Feature.WATCHLIST_ADD:
        return True, ""
    return False, "Unknown feature"


def quota_for_event(tier: Tier, event_type: str) -> int | None:
    """Monthly quota for event_type; None = unlimited; 0 = not allowed."""
    spec = tier_spec(tier)
    if event_type == "brief_regen":
        return spec.morning_brief_regen_per_month
    if event_type == "picks":
        return 1 if spec.picks_daily else 0  # per day, checked separately
    if event_type == "picks_refresh":
        return spec.picks_force_refresh_per_month
    if event_type == "portfolio_analysis":
        if spec.portfolio_analysis_daily:
            return 1  # per day
        return spec.portfolio_analysis_per_month
    if event_type == "portfolio_analysis_refresh":
        return spec.portfolio_force_refresh_per_month
    if event_type == "explore":
        return spec.explore_per_month
    if event_type == "late_day":
        return 1 if spec.late_day_daily else 0
    return 0


def tiers_public_payload() -> list[dict[str, Any]]:
    out = []
    for t in TIERS.values():
        out.append({
            "id": t.id.value,
            "name": t.name,
            "tagline": t.tagline,
            "price_monthly_usd": t.price_monthly_usd,
            "price_yearly_usd": t.price_yearly_usd,
            "features": {
                "morning_brief_daily": t.morning_brief_daily,
                "morning_brief_regen_per_month": t.morning_brief_regen_per_month,
                "late_day_daily": t.late_day_daily,
                "picks_daily": t.picks_daily,
                "picks_preview_only": t.picks_preview_only,
                "portfolio_analysis_per_month": t.portfolio_analysis_per_month,
                "portfolio_analysis_daily": t.portfolio_analysis_daily,
                "explore_per_month": t.explore_per_month,
                "brief_archive_days": t.brief_archive_days,
                "robinhood_sync": t.robinhood_sync,
                "watchlist_limit": t.watchlist_limit,
            },
        })
    return out

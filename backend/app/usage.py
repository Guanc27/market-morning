"""Usage metering and quota enforcement."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.db import Database
from app.subscriptions import Feature, Tier, check_feature, quota_for_event, tier_spec


class UsageService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_user_tier(self, user_id: int) -> Tier:
        row = await self.db.get_user_subscription(user_id)
        if not row:
            return Tier.FREE
        status = row.get("status") or "active"
        if status not in ("active", "trialing"):
            return Tier.FREE
        tier_str = row.get("tier") or "free"
        try:
            return Tier(tier_str)
        except ValueError:
            return Tier.FREE

    async def usage_summary(self, user_id: int) -> dict:
        tier = await self.get_user_tier(user_id)
        spec = tier_spec(tier)
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        counts = await self.db.get_usage_counts(user_id, month)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = await self.db.get_usage_counts(user_id, today, period="day")
        return {
            "tier": tier.value,
            "tier_name": spec.name,
            "period_month": month,
            "usage_month": counts,
            "usage_today": daily,
            "limits": {
                "brief_regen_per_month": spec.morning_brief_regen_per_month,
                "picks_daily": spec.picks_daily,
                "picks_refresh_per_month": spec.picks_force_refresh_per_month,
                "portfolio_analysis_per_month": spec.portfolio_analysis_per_month,
                "portfolio_analysis_daily": spec.portfolio_analysis_daily,
                "portfolio_refresh_per_month": spec.portfolio_force_refresh_per_month,
                "explore_per_month": spec.explore_per_month,
                "late_day_daily": spec.late_day_daily,
                "watchlist_limit": spec.watchlist_limit,
            },
        }

    async def require_feature(self, user_id: int, feature: Feature) -> Tier:
        tier = await self.get_user_tier(user_id)
        ok, reason = check_feature(tier, feature)
        if not ok:
            raise HTTPException(status_code=403, detail=reason)
        return tier

    async def consume(
        self,
        user_id: int,
        event_type: str,
        *,
        force: bool = False,
        daily: bool = False,
    ) -> None:
        tier = await self.get_user_tier(user_id)
        feature_map = {
            "brief_regen": Feature.BRIEF_REGEN,
            "picks": Feature.PICKS,
            "picks_refresh": Feature.PICKS_REFRESH,
            "portfolio_analysis": Feature.PORTFOLIO_ANALYSIS,
            "portfolio_analysis_refresh": Feature.PORTFOLIO_ANALYSIS_REFRESH,
            "explore": Feature.EXPLORE,
            "late_day": Feature.LATE_DAY,
        }
        feat = feature_map.get(event_type)
        if feat:
            ok, reason = check_feature(tier, feat)
            if not ok:
                raise HTTPException(status_code=403, detail=reason)

        quota = quota_for_event(tier, event_type)
        if quota is None:
            await self.db.record_usage(user_id, event_type)
            return
        if quota <= 0:
            raise HTTPException(status_code=403, detail=f"{event_type} not included in your plan")

        spec = tier_spec(tier)
        if event_type == "picks" and not force:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            used = await self.db.get_usage_count(user_id, "picks", today, period="day")
            if used >= 1:
                raise HTTPException(status_code=429, detail="Today's picks already generated")
        elif event_type == "portfolio_analysis" and spec.portfolio_analysis_daily and not force:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            used = await self.db.get_usage_count(user_id, "portfolio_analysis", today, period="day")
            if used >= 1:
                # Allow read of cache without consuming again — caller should use cached path
                return
        elif event_type in ("picks_refresh", "portfolio_analysis_refresh"):
            if not force:
                return
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            used = await self.db.get_usage_count(user_id, event_type, month)
            if used >= quota:
                raise HTTPException(status_code=429, detail=f"Monthly {event_type} limit reached")
        elif event_type == "late_day":
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            used = await self.db.get_usage_count(user_id, "late_day", today, period="day")
            if used >= 1:
                raise HTTPException(status_code=429, detail="Late-day update already generated today")
        else:
            month = datetime.now(timezone.utc).strftime("%Y-%m")
            used = await self.db.get_usage_count(user_id, event_type, month)
            if used >= quota:
                raise HTTPException(status_code=429, detail=f"Monthly {event_type} limit reached")

        await self.db.record_usage(user_id, event_type)

    async def check_watchlist_limit(self, user_id: int, current_count: int) -> None:
        tier = await self.get_user_tier(user_id)
        spec = tier_spec(tier)
        if spec.watchlist_limit is not None and current_count >= spec.watchlist_limit:
            raise HTTPException(
                status_code=403,
                detail=f"Watchlist limit ({spec.watchlist_limit}) reached — upgrade to Pro",
            )

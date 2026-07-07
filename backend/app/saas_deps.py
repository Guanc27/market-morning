"""FastAPI dependencies for SaaS mode."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.auth import get_current_user_id
from app.config import settings
from app.db import Database
from app.subscriptions import Feature
from app.usage import UsageService


def get_usage_service(request: Request) -> UsageService:
    db: Database = request.app.state.db
    return UsageService(db)


async def require_saas_user(user_id: int = Depends(get_current_user_id)) -> int:
    if settings.saas_mode and user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def require_feature_dep(feature: Feature):
    async def _dep(
        user_id: int = Depends(require_saas_user),
        usage: UsageService = Depends(get_usage_service),
    ) -> int:
        if settings.saas_mode:
            await usage.require_feature(user_id, feature)
        return user_id

    return _dep

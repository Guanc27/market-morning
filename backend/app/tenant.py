"""Request-scoped tenant (user) context for multi-tenant SaaS."""

from __future__ import annotations

from contextvars import ContextVar

tenant_user_id: ContextVar[int] = ContextVar("tenant_user_id", default=1)


def get_tenant_user_id() -> int:
    return tenant_user_id.get()


def set_tenant_user_id(user_id: int) -> None:
    tenant_user_id.set(user_id)

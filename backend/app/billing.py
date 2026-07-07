"""Stripe billing integration (checkout + webhooks)."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.db import Database
from app.subscriptions import Tier

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None  # type: ignore


def _stripe_ready() -> bool:
    return bool(stripe and settings.stripe_secret_key)


def stripe_price_to_tier() -> dict[str, Tier]:
    mapping: dict[str, Tier] = {}
    pairs = [
        (settings.stripe_price_pro_monthly, Tier.PRO),
        (settings.stripe_price_pro_yearly, Tier.PRO),
        (settings.stripe_price_desk_monthly, Tier.DESK),
        (settings.stripe_price_desk_yearly, Tier.DESK),
    ]
    for price_id, tier in pairs:
        if price_id:
            mapping[price_id] = tier
    return mapping


class BillingService:
    def __init__(self, db: Database) -> None:
        self.db = db
        if stripe and settings.stripe_secret_key:
            stripe.api_key = settings.stripe_secret_key

    async def create_checkout_session(
        self,
        user_id: int,
        email: str,
        price_id: str,
        *,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        if not _stripe_ready():
            raise RuntimeError("Stripe is not configured")
        sub = await self.db.get_user_subscription(user_id)
        customer_id = (sub or {}).get("stripe_customer_id")
        if not customer_id:
            customer = stripe.Customer.create(email=email, metadata={"user_id": str(user_id)})
            customer_id = customer.id
            await self.db.upsert_subscription(
                user_id,
                tier=Tier.FREE.value,
                stripe_customer_id=customer_id,
            )
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"user_id": str(user_id)},
        )
        return {"checkout_url": session.url, "session_id": session.id}

    async def create_portal_session(self, user_id: int, return_url: str) -> dict[str, str]:
        if not _stripe_ready():
            raise RuntimeError("Stripe is not configured")
        sub = await self.db.get_user_subscription(user_id)
        customer_id = (sub or {}).get("stripe_customer_id")
        if not customer_id:
            raise RuntimeError("No billing account")
        portal = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
        return {"portal_url": portal.url}

    async def handle_webhook(self, payload: bytes, sig_header: str) -> dict[str, Any]:
        if not _stripe_ready():
            raise RuntimeError("Stripe is not configured")
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
        etype = event["type"]
        data = event["data"]["object"]

        if etype == "checkout.session.completed":
            user_id = int(data.get("metadata", {}).get("user_id", 0))
            customer_id = data.get("customer")
            subscription_id = data.get("subscription")
            if user_id and subscription_id:
                sub = stripe.Subscription.retrieve(subscription_id)
                price_id = sub["items"]["data"][0]["price"]["id"]
                tier = stripe_price_to_tier().get(price_id, Tier.PRO)
                await self.db.upsert_subscription(
                    user_id,
                    tier=tier.value,
                    status=sub.get("status", "active"),
                    stripe_customer_id=customer_id,
                    stripe_subscription_id=subscription_id,
                    stripe_price_id=price_id,
                    current_period_end=sub.get("current_period_end"),
                )
        elif etype in ("customer.subscription.updated", "customer.subscription.deleted"):
            subscription_id = data.get("id")
            row = await self.db.get_subscription_by_stripe_id(subscription_id)
            if row:
                user_id = row["user_id"]
                if etype == "customer.subscription.deleted":
                    await self.db.upsert_subscription(user_id, tier=Tier.FREE.value, status="canceled")
                else:
                    price_id = data["items"]["data"][0]["price"]["id"]
                    tier = stripe_price_to_tier().get(price_id, Tier(row.get("tier", "pro")))
                    await self.db.upsert_subscription(
                        user_id,
                        tier=tier.value,
                        status=data.get("status", "active"),
                        stripe_price_id=price_id,
                        current_period_end=data.get("current_period_end"),
                    )
        return {"received": True, "type": etype}

"""SaaS auth, billing, and subscription API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import create_access_token, get_current_user_id, hash_password, verify_password
from app.billing import BillingService
from app.config import settings
from app.db import Database
from app.subscriptions import tiers_public_payload
from app.usage import UsageService

router = APIRouter(prefix="/saas", tags=["saas"])


class SignupIn(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str = ""


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str


class CheckoutIn(BaseModel):
    price_id: str


def _db(request: Request) -> Database:
    return request.app.state.db


def _usage(request: Request) -> UsageService:
    return UsageService(request.app.state.db)


def _billing(request: Request) -> BillingService:
    return BillingService(request.app.state.db)


@router.get("/config")
async def saas_config() -> dict[str, Any]:
    return {
        "saas_mode": settings.saas_mode,
        "web_app_url": settings.web_app_url,
        "stripe_configured": bool(settings.stripe_secret_key),
        "prices": {
            "pro_monthly": settings.stripe_price_pro_monthly,
            "pro_yearly": settings.stripe_price_pro_yearly,
            "desk_monthly": settings.stripe_price_desk_monthly,
            "desk_yearly": settings.stripe_price_desk_yearly,
        },
    }


@router.get("/tiers")
async def list_tiers() -> dict[str, Any]:
    return {"tiers": tiers_public_payload()}


@router.post("/auth/signup")
async def signup(body: SignupIn, request: Request, response: Response) -> dict[str, Any]:
    if not settings.saas_mode:
        raise HTTPException(400, "SaaS mode is disabled")
    db = _db(request)
    existing = await db.get_user_by_email(body.email)
    if existing:
        raise HTTPException(409, "Email already registered")
    user = await db.create_user(body.email, hash_password(body.password), body.display_name)
    token = create_access_token(user["id"], user["email"])
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expire_days * 86400,
    )
    return {"token": token, "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]}}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    if not settings.saas_mode:
        raise HTTPException(400, "SaaS mode is disabled")
    db = _db(request)
    user = await db.get_user_by_email(body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")
    await db.touch_user_login(user["id"])
    token = create_access_token(user["id"], user["email"])
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expire_days * 86400,
    )
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"], "display_name": user["display_name"]},
    }


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(settings.session_cookie_name)
    return {"ok": True}


@router.get("/auth/me")
async def me(
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    db = _db(request)
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    usage = _usage(request)
    summary = await usage.usage_summary(user_id)
    return {"user": user, "subscription": summary}


@router.get("/usage")
async def usage(
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    return await _usage(request).usage_summary(user_id)


@router.post("/billing/checkout")
async def billing_checkout(
    body: CheckoutIn,
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    db = _db(request)
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    base = settings.web_app_url.rstrip("/")
    return await _billing(request).create_checkout_session(
        user_id,
        user["email"],
        body.price_id,
        success_url=f"{base}/?checkout=success",
        cancel_url=f"{base}/pricing?checkout=canceled",
    )


@router.post("/billing/portal")
async def billing_portal(
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, str]:
    base = settings.web_app_url.rstrip("/")
    return await _billing(request).create_portal_session(user_id, return_url=f"{base}/account")


@router.post("/billing/webhook")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    return await _billing(request).handle_webhook(payload, sig)

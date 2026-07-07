from __future__ import annotations

import asyncio
import subprocess
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.account import load_account, load_snapshot_positions
from app.ai import AIService
from app.auth import decode_access_token, get_current_user_id
from app.saas_routes import router as saas_router
from app.subscriptions import Feature, tier_spec
from app.tenant import set_tenant_user_id
from app.usage import UsageService
from app.ai_jobs import (
    BRIEF_AI_JOB,
    EXPLORE_JOB,
    PICKS_JOB,
    PORTFOLIO_JOB,
    clear_stale_job_if_needed,
    snapshot_job,
    start_async_job,
    update_job,
)
from app.ai_sanitize import sanitize_ai_output
from app.review_gate import normalize_brief_title
from app.config import settings
from app.db import Database
from app.finance import finance_warm_status, get_quotes, warm_finance_cache
from app.landing import get_explore_landing
from app.logos import fetch_logo_bytes, logo_urls
from app.mock_data import MOCK_HOLDINGS
from app.portfolio_quant import reconcile_equity, resolve_row_pricing
from app.research import get_research_progress, start_research_background
from app.robinhood_sync import sync_robinhood
from app.symbols import ensure_index, search_symbols, warm_index, warm_status
from app.universe import sync_nyse_universe

db = Database(settings.db_path)
ai = AIService(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    snapshot = Path(__file__).resolve().parent.parent / "data" / "robinhood_positions.json"
    if not settings.mock_mode and snapshot.exists():
        holdings = await db.get_holdings()
        if not holdings:
            import json
            data = json.loads(snapshot.read_text())
            for row in data.get("holdings", []):
                await db.upsert_holding(row["ticker"], row["shares"], row["avg_cost"], row.get("notes", "robinhood"))
            print(f"Loaded {len(data.get('holdings', []))} holdings from Robinhood snapshot")
    elif settings.mock_mode:
        holdings = await db.get_holdings()
        if not holdings:
            for row in MOCK_HOLDINGS:
                await db.upsert_holding(row["ticker"], row["shares"], row["avg_cost"], row.get("notes", ""))
            print("Mock mode: seeded demo portfolio")
    ensure_index()
    try:
        symbols = sync_nyse_universe(force=False)  # weekly disk cache — see universe.py
        print(f"NYSE universe: {len(symbols)} symbols loaded")
    except Exception as e:
        print(f"NYSE universe sync warning: {e}")
    # Daily research cache — headlines are same-day; skip fetch if today's file exists.
    start_research_background(force_refresh=False)
    try:
        holdings = await db.get_holdings()
        if holdings:
            tickers = [h["ticker"] for h in holdings]
            warm_index(tickers, blocking=False)
            warm_finance_cache(tickers, blocking=False)  # fundamentals persist; technicals 15m TTL
    except Exception:
        pass
    try:
        n = await db.backfill_portfolio_analysis_content(sanitize_ai_output)
        if n:
            print(f"Stripped holdings tables from {n} cached portfolio analysis row(s)")
    except Exception as e:
        print(f"Portfolio analysis backfill warning: {e}")
    yield


APP_VERSION = "0.2.0"
app = FastAPI(title="Market Morning API", version=APP_VERSION, lifespan=lifespan)
app.state.db = db
app.include_router(saas_router)


def _cors_origins() -> list[str]:
    if settings.saas_mode:
        return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    return _ALLOWED_ORIGINS


@app.middleware("http")
async def _tenant_context(request: Request, call_next):
    if settings.saas_mode:
        user_id = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                user_id = int(decode_access_token(auth[7:].strip())["sub"])
            except Exception:
                user_id = None
        if user_id is None:
            token = request.cookies.get(settings.session_cookie_name)
            if token:
                try:
                    user_id = int(decode_access_token(token)["sub"])
                except Exception:
                    user_id = None
        if user_id is not None:
            set_tenant_user_id(user_id)
    else:
        set_tenant_user_id(1)
    return await call_next(request)


# --- Local-only access hardening (CSRF / DNS-rebinding) ----------------------
# The backend binds to loopback and is consumed by the local file:// WebView.
# The WebView issues requests with an Origin of `null` (or none at all), while
# a browser page on a real site attacking localhost would carry its own site
# Origin. We therefore:
#   1. echo CORS headers ONLY for local/null origins (no wildcard, no creds), and
#   2. reject any request carrying a real cross-site Origin, plus any request
#      whose Host header is not loopback (closes the DNS-rebinding vector).
_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_ALLOWED_ORIGINS = ["null", "http://localhost", "http://127.0.0.1"]
_ALLOWED_ORIGIN_REGEX = r"^(null|https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?)$"


def _hostname_is_local(netloc: str) -> bool:
    """True when a Host/Origin authority points at loopback (port-agnostic)."""
    if not netloc:
        return False
    authority = netloc.rsplit("@", 1)[-1]
    if authority.startswith("["):  # bracketed IPv6, e.g. [::1]:8742
        host = authority[1: authority.find("]")] if "]" in authority else authority[1:]
    else:
        host = authority.rsplit(":", 1)[0] if ":" in authority else authority
    return host.lower() in _LOCAL_HOSTNAMES


def _origin_is_allowed(origin: str) -> bool:
    if origin.lower() == "null":
        return True
    parsed = urlparse(origin)
    return _hostname_is_local(parsed.netloc)


@app.middleware("http")
async def _local_only_guard(request: Request, call_next):
    if settings.saas_mode:
        return await call_next(request)
    origin = request.headers.get("origin")
    # A real cross-site Origin (a page on another host driving the browser) is
    # rejected outright — this is the localhost-CSRF / rebinding vector, esp. for
    # the destructive POST /portfolio/sync. Missing/null Origin = local WebView.
    if origin and not _origin_is_allowed(origin):
        return JSONResponse(status_code=403, content={"detail": "Cross-origin request rejected"})
    # DNS-rebinding: an attacker-controlled hostname resolving to 127.0.0.1 still
    # arrives with its own Host header — require loopback.
    host = request.headers.get("host")
    if host and not _hostname_is_local(host):
        return JSONResponse(status_code=403, content={"detail": "Non-local Host rejected"})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=None if settings.saas_mode else _ALLOWED_ORIGIN_REGEX,
    allow_credentials=settings.saas_mode,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


async def _usage_for(request: Request) -> UsageService:
    return UsageService(request.app.state.db)


async def _gate(request: Request, user_id: int, feature: Feature, event: str | None = None, *, force: bool = False) -> None:
    if not settings.saas_mode:
        return
    usage = await _usage_for(request)
    await usage.require_feature(user_id, feature)
    if event:
        await usage.consume(user_id, event, force=force)


async def _subscription_meta(request: Request, user_id: int) -> dict[str, Any]:
    if not settings.saas_mode:
        return {"tier": "desk", "saas_mode": False}
    usage = await _usage_for(request)
    summary = await usage.usage_summary(user_id)
    return {"tier": summary["tier"], "saas_mode": True, "usage": summary}


@lru_cache(maxsize=1)
def _build_stamp() -> dict[str, Any]:
    """Git SHA + build time so a stale launchd process is detectable at /health."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    sha = "unknown"
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(repo_root), stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip() or "unknown"
    except Exception:
        sha = "unknown"
    return {"git_sha": sha, "started_at": datetime.now(timezone.utc).isoformat()}


class HoldingIn(BaseModel):
    ticker: str
    shares: float
    avg_cost: float
    notes: str = ""


class ExploreIn(BaseModel):
    market: str = Field(..., min_length=1)


class ChooseActionIn(BaseModel):
    action_id: str
    label: str
    detail: str = ""
    tickers: list[str] = Field(default_factory=list)
    action_type: str = ""
    source: str = "brief"


class WatchlistIn(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=8)
    notes: str = ""
    source: str = "manual"


class SyncHoldingsIn(BaseModel):
    holdings: list[HoldingIn]


@app.get("/health")
async def health() -> dict[str, Any]:
    stamp = _build_stamp()
    return {
        "status": "ok",
        "version": APP_VERSION,
        "git_sha": stamp["git_sha"],
        "started_at": stamp["started_at"],
        "mock_mode": settings.mock_mode,
        "saas_mode": settings.saas_mode,
        "anthropic_configured": bool(settings.anthropic_api_key) or settings.mock_mode,
        "fmp_configured": bool(settings.fmp_api_key),
        "robinhood_configured": bool(
            settings.robinhood_mcp_access_token or settings.robinhood_sync_proxy_url
        ),
    }


async def _invalidate_portfolio_analysis() -> None:
    await db.clear_portfolio_analysis()


@app.get("/portfolio")
async def get_portfolio(user_id: int = Depends(get_current_user_id)) -> dict[str, Any]:
    holdings = await db.get_holdings()
    tickers = [h["ticker"] for h in holdings]
    quotes, logos, account, snapshot_positions = await asyncio.gather(
        asyncio.to_thread(get_quotes, tickers),
        asyncio.to_thread(logo_urls, tickers),
        asyncio.to_thread(load_account),
        asyncio.to_thread(load_snapshot_positions),
    )
    enriched = []
    total_cost = 0.0
    for h in holdings:
        q = quotes.get(h["ticker"], {})
        # Per-row display prefers live -> broker snapshot -> null. A missing live
        # quote must NEVER be coerced to $0/-100%; instead fall back to the real
        # as-of-last-sync broker value so a genuinely-held position shows real
        # numbers (source="snapshot", stale=True) rather than "—".
        priced = resolve_row_pricing(
            h["shares"],
            h["avg_cost"],
            q,
            snapshot_positions.get(str(h["ticker"]).upper()),
        )
        total_cost += h["avg_cost"] * h["shares"]
        enriched.append({
            **h,
            "name": q.get("name"),
            "logo_url": logos.get(h["ticker"]),
            "price": priced["price"],
            "change_pct": priced["change_pct"],
            "value": priced["value"],
            "return_pct": priced["return_pct"],
            "stale": priced["stale"],
            "source": priced["source"],
        })
    enriched.sort(key=lambda x: x.get("value") or 0, reverse=True)
    # Live quotes can be unavailable for illiquid or unrecognized tickers. Equity
    # reconciliation (snapshot fallback when any quote is stale) is centralized in
    # reconcile_equity() so the priced-value/stale/snapshot logic lives in one place.
    rec = reconcile_equity(enriched, account)
    snapshot_equity = account.get("equity_value")
    equity_value = rec["total_value"]
    return_pct = round((equity_value - total_cost) / total_cost * 100, 2) if total_cost else 0
    return {
        "holdings": enriched,
        "account": account,
        "totals": {
            "value": round(equity_value, 2),
            "cost": round(total_cost, 2),
            "return_pct": return_pct,
            "cash": account.get("cash"),
            "buying_power": account.get("buying_power"),
            "pending_deposits": account.get("pending_deposits"),
            "total_account_value": account.get("total_account_value"),
            "equity_value": snapshot_equity,
        },
    }


@app.post("/portfolio/sync-robinhood")
async def sync_robinhood_portfolio(
    request: Request,
    force: bool = False,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    await _gate(request, user_id, Feature.ROBINHOOD_SYNC)
    result = await sync_robinhood(db, force=force)
    result["portfolio"] = await get_portfolio()
    if result.get("synced"):
        await _invalidate_portfolio_analysis()
        holdings = result["portfolio"].get("holdings") or []
        if holdings:
            warm_finance_cache([h["ticker"] for h in holdings], blocking=False)
    return result


@app.post("/portfolio/sync")
async def sync_portfolio(body: SyncHoldingsIn) -> dict[str, Any]:
    if not body.holdings:
        raise HTTPException(
            status_code=400,
            detail="Refusing empty holdings sync — add at least one position or remove holdings individually.",
        )
    for h in await db.get_holdings():
        await db.remove_holding(h["ticker"])
    for h in body.holdings:
        await db.upsert_holding(h.ticker, h.shares, h.avg_cost, h.notes or "robinhood")
    await _invalidate_portfolio_analysis()
    return {"synced": len(body.holdings), "portfolio": await get_portfolio()}


@app.post("/portfolio/holding")
async def upsert_holding(body: HoldingIn) -> dict[str, Any]:
    result = await db.upsert_holding(body.ticker, body.shares, body.avg_cost, body.notes)
    await _invalidate_portfolio_analysis()
    return result


@app.delete("/portfolio/holding/{ticker}")
async def delete_holding(ticker: str) -> dict[str, bool]:
    removed = await db.remove_holding(ticker)
    if removed:
        await _invalidate_portfolio_analysis()
    return {"removed": removed}


@app.get("/portfolio/analysis")
async def portfolio_analysis(
    request: Request,
    force: bool = False,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    await _gate(request, user_id, Feature.PORTFOLIO_ANALYSIS)
    if force:
        await _gate(request, user_id, Feature.PORTFOLIO_ANALYSIS_REFRESH, "portfolio_analysis_refresh", force=True)
        await _gate(request, user_id, Feature.PORTFOLIO_ANALYSIS, "portfolio_analysis", force=True)
    result = await ai.portfolio_analysis(force=force)
    return {**result, **await _subscription_meta(request, user_id)}


@app.post("/portfolio/analysis/start")
async def portfolio_analysis_start(
    request: Request,
    force: bool = False,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    await _gate(request, user_id, Feature.PORTFOLIO_ANALYSIS)
    if force:
        await _gate(request, user_id, Feature.PORTFOLIO_ANALYSIS_REFRESH, "portfolio_analysis_refresh", force=True)
        await _gate(request, user_id, Feature.PORTFOLIO_ANALYSIS, "portfolio_analysis", force=True)
    else:
        await _gate(request, user_id, Feature.PORTFOLIO_ANALYSIS, "portfolio_analysis", force=False)
    if not force:
        cached = await ai.portfolio_analysis(force=False)
        content = (cached.get("content") or "").strip()
        if content and not content.startswith("**Setup required:**") and not content.startswith("**API key rejected:**"):
            update_job(
                PORTFOLIO_JOB,
                running=False,
                done=True,
                progress=100,
                message="Using cached analysis",
                error=None,
                result=cached,
            )
            return {"started": True, "cached": True}
    started, reason = start_async_job(
        PORTFOLIO_JOB,
        lambda: ai.portfolio_analysis_job(force=True),
    )
    return {"started": started, "cached": False, "reason": reason}


@app.get("/portfolio/analysis/progress")
async def portfolio_analysis_progress() -> dict[str, Any]:
    clear_stale_job_if_needed(PORTFOLIO_JOB)
    return snapshot_job(PORTFOLIO_JOB)


@app.get("/brief/recap")
async def brief_recap() -> dict[str, Any]:
    landing = await db.get_brief_landing()
    if landing.get("today"):
        # Stored content is already finalized/sanitized; only the date-dependent
        # canonical H1 is (re)applied on read.
        landing["today"]["content"] = normalize_brief_title(landing["today"]["content"])
    return landing


@app.get("/brief/landing")
async def brief_landing() -> dict[str, Any]:
    return await brief_recap()


@app.post("/brief/mini")
async def mini_brief(
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    await _gate(request, user_id, Feature.LATE_DAY, "late_day")
    return await ai.mini_brief()


@app.post("/brief/start")
async def brief_start(
    request: Request,
    force: bool = False,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    if force:
        await _gate(request, user_id, Feature.BRIEF_REGEN, "brief_regen", force=True)
    if not force:
        row = await db.get_brief_for_today_full()
        content = normalize_brief_title((row or {}).get("content") or "")
        if content.strip() and not content.startswith("**Setup required:**") and not content.startswith("**API key rejected:**"):
            update_job(
                BRIEF_AI_JOB,
                running=False,
                done=True,
                progress=100,
                message="Using today's cached brief",
                error=None,
                result={"content": content, "cached": True},
            )
            return {"started": True, "cached": True}
    started, reason = start_async_job(BRIEF_AI_JOB, lambda: ai.morning_brief_job(force=force))
    return {"started": started, "cached": False, "reason": reason}


@app.get("/picks/today")
async def picks_today(
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    usage = await _usage_for(request)
    tier = await usage.get_user_tier(user_id)
    spec = tier_spec(tier)
    if settings.saas_mode and spec.picks_preview_only:
        preview = await db.get_yesterday_picks_preview()
        return {
            "content": "",
            "cached": False,
            "premium_required": True,
            "preview": preview,
            "tier": tier.value,
        }
    today = datetime.now(timezone.utc).date().isoformat()
    row = await db.get_picks_by_date(today)
    if not row:
        return {"content": "", "cached": False, "tier": tier.value}
    content = row.get("content") or ""
    meta = row.get("meta") or {}
    return {"content": content, "cached": bool(content.strip()), "meta": meta, "tier": tier.value}


@app.post("/picks/start")
async def picks_start(
    request: Request,
    force: bool = False,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    await _gate(request, user_id, Feature.PICKS)
    if force:
        await _gate(request, user_id, Feature.PICKS_REFRESH, "picks_refresh", force=True)
    await _gate(request, user_id, Feature.PICKS, "picks", force=force)
    today = datetime.now(timezone.utc).date().isoformat()
    if not force:
        row = await db.get_picks_by_date(today)
        content = (row or {}).get("content") or ""
        if content.strip() and not content.startswith("**Setup required:**") and not content.startswith("**API key rejected:**"):
            result = {"content": content, "meta": (row or {}).get("meta") or {}}
            update_job(
                PICKS_JOB,
                running=False,
                done=True,
                progress=100,
                message="Using cached picks",
                error=None,
                result=result,
            )
            return {"started": True, "cached": True}
    started, reason = start_async_job(PICKS_JOB, lambda: ai.top_picks_job())
    return {"started": started, "cached": False, "reason": reason}


@app.get("/picks/progress")
async def picks_progress() -> dict[str, Any]:
    clear_stale_job_if_needed(PICKS_JOB)
    return snapshot_job(PICKS_JOB)


@app.get("/picks/landing")
async def picks_landing() -> dict[str, Any]:
    preview = await db.get_yesterday_picks_preview()
    return {"yesterday": preview}


@app.get("/explore/landing")
async def explore_landing() -> dict[str, Any]:
    return get_explore_landing()


@app.get("/brief/archive/dates")
async def brief_archive_dates() -> dict[str, Any]:
    return {"dates": await db.list_brief_archive_dates()}


@app.get("/brief/archive/{brief_date}")
async def brief_archive_day(brief_date: str) -> dict[str, Any]:
    row = await db.get_brief_by_date(brief_date)
    if not row:
        raise HTTPException(404, "Brief not found")
    # Canonicalize the archived H1 to "Morning Market Brief — <its own date>".
    try:
        date_display = datetime.strptime(brief_date, "%Y-%m-%d").strftime("%B %-d, %Y")
    except ValueError:
        date_display = None
    # Stored brief is already finalized/sanitized; only re-stamp the canonical H1
    # with this archived brief's own date (the genuinely date-dependent step).
    row["content"] = normalize_brief_title(row["content"], date_display)
    return row


@app.get("/logo/{ticker}")
async def get_logo(ticker: str) -> Response:
    result = await asyncio.to_thread(fetch_logo_bytes, ticker)
    if not result:
        raise HTTPException(404, "Logo not found")
    data, media = result
    return Response(content=data, media_type=media, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/research/progress")
async def research_progress() -> dict[str, Any]:
    return get_research_progress()


@app.get("/finance/warm-status")
async def finance_warm_status_route() -> dict[str, Any]:
    return finance_warm_status()


@app.post("/finance/warm")
async def finance_warm(force: bool = False) -> dict[str, Any]:
    holdings = await db.get_holdings()
    tickers = [h["ticker"] for h in holdings]
    if tickers:
        warm_finance_cache(tickers, blocking=False, force_refresh=force)
    return {"started": bool(tickers), "tickers": len(tickers), "force": force}


@app.post("/research/start")
async def research_start(force: bool = False) -> dict[str, Any]:
    start_research_background(force_refresh=force)
    return {"started": True}


@app.get("/symbols/search")
async def symbols_search(q: str = "", limit: int = 10, lite: bool = True) -> dict[str, Any]:
    results = await asyncio.to_thread(search_symbols, q, min(limit, 15), lite)
    return {"results": results}


@app.get("/symbols/warm-status")
async def symbols_warm_status() -> dict[str, Any]:
    return warm_status()


@app.get("/brief/compose-progress")
async def brief_compose_progress() -> dict[str, Any]:
    clear_stale_job_if_needed(BRIEF_AI_JOB)
    job = snapshot_job(BRIEF_AI_JOB)
    if job.get("result") and isinstance(job["result"], dict) and job["result"].get("content"):
        # Stored/generated brief is already clean; only re-apply the canonical H1.
        job["result"] = {
            **job["result"],
            "content": normalize_brief_title(job["result"]["content"]),
        }
    return job


@app.get("/brief/morning")
async def morning_brief(force: bool = False) -> dict[str, Any]:
    result = await ai.morning_brief(force=force)
    if isinstance(result, dict) and result.get("content"):
        result["content"] = normalize_brief_title(result["content"])
    return result


@app.get("/brief/top-picks")
async def top_picks() -> dict[str, Any]:
    return await ai.top_picks()


@app.post("/brief/explore")
async def explore_market(body: ExploreIn) -> dict[str, Any]:
    return await ai.explore_market(body.market)


@app.post("/explore/start")
async def explore_start(
    body: ExploreIn,
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    await _gate(request, user_id, Feature.EXPLORE, "explore")
    market = body.market.strip()
    if not market:
        raise HTTPException(status_code=400, detail="market is required")
    started, reason = start_async_job(EXPLORE_JOB, lambda: ai.explore_market_job(market))
    return {"started": started, "market": market, "reason": reason}


@app.get("/explore/progress")
async def explore_progress() -> dict[str, Any]:
    clear_stale_job_if_needed(EXPLORE_JOB)
    return snapshot_job(EXPLORE_JOB)


@app.get("/watchlist")
async def get_watchlist() -> dict[str, Any]:
    items = await db.get_watchlist()
    tickers = [w["ticker"] for w in items]
    quotes, logos = await asyncio.gather(
        asyncio.to_thread(get_quotes, tickers),
        asyncio.to_thread(logo_urls, tickers),
    )
    enriched = [{
        **w,
        "name": quotes.get(w["ticker"], {}).get("name"),
        "logo_url": logos.get(w["ticker"]),
        "price": quotes.get(w["ticker"], {}).get("price"),
    } for w in items]
    return {"items": enriched}


@app.post("/watchlist")
async def add_watchlist(
    body: WatchlistIn,
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    if settings.saas_mode:
        usage = await _usage_for(request)
        items = await db.get_watchlist()
        await usage.check_watchlist_limit(user_id, len(items))
    return await db.add_watchlist(body.ticker, body.notes, body.source)


@app.delete("/watchlist/{ticker}")
async def remove_watchlist(ticker: str) -> dict[str, bool]:
    return {"removed": await db.remove_watchlist(ticker)}


@app.get("/actions/chosen")
async def get_chosen_actions() -> dict[str, Any]:
    return {"items": await db.get_chosen_actions()}


@app.post("/actions/choose")
async def choose_action(body: ChooseActionIn) -> dict[str, Any]:
    item = await db.record_chosen_action(
        body.action_id, body.label, body.detail, body.tickers, body.action_type, body.source
    )
    return {"ok": True, "item": item}


@app.get("/memory")
async def get_memory() -> dict[str, Any]:
    return {"entries": await db.get_memory()}


# Standalone web app (SaaS) — static UI at /app
_web_root = Path(__file__).resolve().parent.parent.parent / "web"
_ext_root = Path(__file__).resolve().parent.parent.parent / "extension" / "dist"
if _ext_root.is_dir():
    app.mount("/extension/dist", StaticFiles(directory=str(_ext_root)), name="extension")
if _web_root.is_dir():
    app.mount("/app", StaticFiles(directory=str(_web_root), html=True), name="web")

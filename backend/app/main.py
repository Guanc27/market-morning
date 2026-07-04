from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.account import load_account
from app.ai import AIService
from app.ai_jobs import BRIEF_AI_JOB, EXPLORE_JOB, PICKS_JOB, PORTFOLIO_JOB, clear_stale_job_if_needed, start_async_job
from app.ai_sanitize import sanitize_ai_output
from app.config import settings
from app.db import Database
from app.finance import finance_warm_status, get_quotes, warm_finance_cache
from app.landing import get_explore_landing
from app.logos import fetch_logo_bytes, logo_urls
from app.mock_data import MOCK_HOLDINGS
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


app = FastAPI(title="Market Morning API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/portfolio")
async def get_portfolio() -> dict[str, Any]:
    holdings = await db.get_holdings()
    tickers = [h["ticker"] for h in holdings]
    quotes = get_quotes(tickers)
    logos = logo_urls(tickers)
    enriched = []
    total_value = 0.0
    total_cost = 0.0
    for h in holdings:
        q = quotes.get(h["ticker"], {})
        price = q.get("price") or 0
        value = price * h["shares"]
        cost = h["avg_cost"] * h["shares"]
        total_value += value
        total_cost += cost
        enriched.append({
            **h,
            "name": q.get("name"),
            "logo_url": logos.get(h["ticker"]),
            "price": price,
            "change_pct": q.get("change_pct"),
            "value": round(value, 2),
            "return_pct": round((price - h["avg_cost"]) / h["avg_cost"] * 100, 2) if h["avg_cost"] else 0,
        })
    enriched.sort(key=lambda x: x.get("value") or 0, reverse=True)
    account = load_account()
    return {
        "holdings": enriched,
        "account": account,
        "totals": {
            "value": round(total_value, 2),
            "cost": round(total_cost, 2),
            "return_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0,
            "cash": account.get("cash"),
            "buying_power": account.get("buying_power"),
            "pending_deposits": account.get("pending_deposits"),
            "total_account_value": account.get("total_account_value"),
        },
    }


@app.post("/portfolio/sync-robinhood")
async def sync_robinhood_portfolio(force: bool = False) -> dict[str, Any]:
    result = await sync_robinhood(db, force=force)
    if result.get("synced"):
        result["portfolio"] = await get_portfolio()
        holdings = await db.get_holdings()
        if holdings:
            warm_finance_cache([h["ticker"] for h in holdings], blocking=False)  # skip cached fundamentals
    return result


@app.post("/portfolio/sync")
async def sync_portfolio(body: SyncHoldingsIn) -> dict[str, Any]:
    for h in await db.get_holdings():
        await db.remove_holding(h["ticker"])
    for h in body.holdings:
        await db.upsert_holding(h.ticker, h.shares, h.avg_cost, h.notes or "robinhood")
    return {"synced": len(body.holdings), "portfolio": await get_portfolio()}


@app.post("/portfolio/holding")
async def upsert_holding(body: HoldingIn) -> dict[str, Any]:
    return await db.upsert_holding(body.ticker, body.shares, body.avg_cost, body.notes)


@app.delete("/portfolio/holding/{ticker}")
async def delete_holding(ticker: str) -> dict[str, bool]:
    removed = await db.remove_holding(ticker)
    return {"removed": removed}


@app.get("/portfolio/analysis")
async def portfolio_analysis(force: bool = False) -> dict[str, Any]:
    result = await ai.portfolio_analysis(force=force)
    if result.get("content"):
        result["content"] = sanitize_ai_output(result["content"])
    return result


@app.post("/portfolio/analysis/start")
async def portfolio_analysis_start(force: bool = False) -> dict[str, Any]:
    if not force:
        cached = await ai.portfolio_analysis(force=False)
        content = (cached.get("content") or "").strip()
        if content and not content.startswith("**Setup required:**"):
            cached["content"] = sanitize_ai_output(cached["content"])
            PORTFOLIO_JOB.update(
                running=False,
                done=True,
                progress=100,
                message="Using cached analysis",
                error=None,
                result=cached,
            )
            return {"started": True, "cached": True}
    started = start_async_job(
        PORTFOLIO_JOB,
        lambda: ai.portfolio_analysis_job(force=True),
    )
    return {"started": started, "cached": False}


@app.get("/portfolio/analysis/progress")
async def portfolio_analysis_progress() -> dict[str, Any]:
    clear_stale_job_if_needed(PORTFOLIO_JOB)
    job = dict(PORTFOLIO_JOB)
    if job.get("result") and isinstance(job["result"], dict) and job["result"].get("content"):
        job["result"] = {**job["result"], "content": sanitize_ai_output(job["result"]["content"])}
    return job


@app.get("/brief/recap")
async def brief_recap() -> dict[str, Any]:
    landing = await db.get_brief_landing()
    if landing.get("today"):
        landing["today"]["content"] = sanitize_ai_output(landing["today"]["content"])
        if landing["today"].get("mini_brief"):
            landing["today"]["mini_brief"] = sanitize_ai_output(landing["today"]["mini_brief"])
    return landing


@app.get("/brief/landing")
async def brief_landing() -> dict[str, Any]:
    return await brief_recap()


@app.post("/brief/mini")
async def mini_brief() -> dict[str, Any]:
    result = await ai.mini_brief()
    result["content"] = sanitize_ai_output(result.get("content", ""))
    return result


@app.post("/brief/start")
async def brief_start(force: bool = False) -> dict[str, Any]:
    if not force:
        row = await db.get_brief_for_today_full()
        content = sanitize_ai_output((row or {}).get("content") or "")
        if content.strip() and not content.startswith("**Setup required:**"):
            BRIEF_AI_JOB.update(
                running=False,
                done=True,
                progress=100,
                message="Using today's cached brief",
                error=None,
                result={"content": content, "cached": True},
            )
            return {"started": True, "cached": True}
    started = start_async_job(BRIEF_AI_JOB, lambda: ai.morning_brief_job(force=force))
    return {"started": started, "cached": False}


@app.get("/picks/today")
async def picks_today() -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    row = await db.get_picks_by_date(today)
    if not row:
        return {"content": "", "cached": False}
    content = sanitize_ai_output(row.get("content") or "")
    meta = row.get("meta") or {}
    return {"content": content, "cached": bool(content.strip()), "meta": meta}


@app.post("/picks/start")
async def picks_start(force: bool = False) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    if not force:
        row = await db.get_picks_by_date(today)
        content = sanitize_ai_output((row or {}).get("content") or "")
        if content.strip() and not content.startswith("**Setup required:**"):
            result = {"content": content, "meta": (row or {}).get("meta") or {}}
            PICKS_JOB.update(
                running=False,
                done=True,
                progress=100,
                message="Using cached picks",
                error=None,
                result=result,
            )
            return {"started": True, "cached": True}
    started = start_async_job(PICKS_JOB, lambda: ai.top_picks_job())
    return {"started": started, "cached": False}


@app.get("/picks/progress")
async def picks_progress() -> dict[str, Any]:
    clear_stale_job_if_needed(PICKS_JOB)
    job = dict(PICKS_JOB)
    if job.get("result") and isinstance(job["result"], dict) and job["result"].get("content"):
        job["result"] = {
            **job["result"],
            "content": sanitize_ai_output(job["result"]["content"]),
        }
    return job


@app.get("/picks/landing")
async def picks_landing() -> dict[str, Any]:
    preview = await db.get_yesterday_picks_preview()
    if preview:
        if preview.get("synopsis"):
            preview["synopsis"] = sanitize_ai_output(preview["synopsis"])
        if preview.get("preview"):
            preview["preview"] = sanitize_ai_output(preview["preview"])
        if preview.get("content"):
            preview["content"] = sanitize_ai_output(preview["content"])
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
    row["content"] = sanitize_ai_output(row["content"])
    return row


@app.get("/logo/{ticker}")
async def get_logo(ticker: str) -> Response:
    result = fetch_logo_bytes(ticker)
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
    results = search_symbols(q, limit=min(limit, 15), lite=lite)
    return {"results": results}


@app.get("/symbols/warm-status")
async def symbols_warm_status() -> dict[str, Any]:
    return warm_status()


@app.get("/brief/compose-progress")
async def brief_compose_progress() -> dict[str, Any]:
    clear_stale_job_if_needed(BRIEF_AI_JOB)
    job = dict(BRIEF_AI_JOB)
    if job.get("result") and isinstance(job["result"], dict) and job["result"].get("content"):
        job["result"] = {
            **job["result"],
            "content": sanitize_ai_output(job["result"]["content"]),
        }
    return job


@app.get("/brief/morning")
async def morning_brief(force: bool = False) -> dict[str, Any]:
    result = await ai.morning_brief(force=force)
    if isinstance(result, dict) and result.get("content"):
        result["content"] = sanitize_ai_output(result["content"])
    return result


@app.get("/brief/top-picks")
async def top_picks() -> dict[str, Any]:
    result = await ai.top_picks()
    if isinstance(result, dict) and result.get("content"):
        result["content"] = sanitize_ai_output(result["content"])
    return result


@app.post("/brief/explore")
async def explore_market(body: ExploreIn) -> dict[str, Any]:
    result = await ai.explore_market(body.market)
    if isinstance(result, dict) and result.get("content"):
        result["content"] = sanitize_ai_output(result["content"])
    return result


@app.post("/explore/start")
async def explore_start(body: ExploreIn) -> dict[str, Any]:
    market = body.market.strip()
    if not market:
        raise HTTPException(status_code=400, detail="market is required")
    started = start_async_job(EXPLORE_JOB, lambda: ai.explore_market_job(market))
    return {"started": started, "market": market}


@app.get("/explore/progress")
async def explore_progress() -> dict[str, Any]:
    clear_stale_job_if_needed(EXPLORE_JOB)
    job = dict(EXPLORE_JOB)
    if job.get("result") and isinstance(job["result"], dict) and job["result"].get("content"):
        job["result"] = {
            **job["result"],
            "content": sanitize_ai_output(job["result"]["content"]),
        }
    return job


@app.get("/watchlist")
async def get_watchlist() -> dict[str, Any]:
    items = await db.get_watchlist()
    tickers = [w["ticker"] for w in items]
    quotes = get_quotes(tickers)
    logos = logo_urls(tickers)
    enriched = [{
        **w,
        "name": quotes.get(w["ticker"], {}).get("name"),
        "logo_url": logos.get(w["ticker"]),
        "price": quotes.get(w["ticker"], {}).get("price"),
    } for w in items]
    return {"items": enriched}


@app.post("/watchlist")
async def add_watchlist(body: WatchlistIn) -> dict[str, Any]:
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

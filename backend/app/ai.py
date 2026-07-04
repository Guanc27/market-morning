from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from anthropic import Anthropic

from app.ai_jobs import set_brief_ai_progress, set_portfolio_progress
from app.ai_sanitize import markdown_plain_excerpt, sanitize_ai_output
from app.config import settings
from app.db import Database
from app.finance import get_market_snapshot, get_quotes, market_peers, portfolio_metrics, portfolio_technicals, screen_candidates
from app.account import load_account
from app.mock_data import (
    mock_explore_market,
    mock_morning_brief,
    mock_top_picks,
)
from app.news import flatten_news, get_news_bundle
from app.research import get_market_research_bundle
from app.prompts import brief_system, explore_system, picks_system, portfolio_system
from app.response_parser import parse_ai_response

DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "XOM", "LLY", "AVGO", "MA", "COST",
    "HD", "PG", "JNJ", "ABBV", "CRM", "AMD", "NFLX", "ORCL",
]

_PLACEHOLDER_MARKERS = ("**Setup required:**", "**API key rejected:**")


def _is_placeholder_content(text: str) -> bool:
    return any(text.strip().startswith(m) for m in _PLACEHOLDER_MARKERS)


def _slim_sector_research(bundle: dict[str, Any]) -> dict[str, Any]:
    """Trim sector research to fields the brief prompt needs — fewer input tokens."""
    slim: dict[str, Any] = {}
    for sector_key, block in bundle.items():
        if not isinstance(block, dict):
            continue
        articles = []
        for item in block.get("articles") or []:
            articles.append({
                "title": item.get("title"),
                "link": item.get("link"),
                "publisher": item.get("publisher"),
                "published_at": item.get("published_at"),
                "coverage": item.get("coverage"),
            })
        slim[sector_key] = {
            "label": block.get("label"),
            "articles": articles,
            "using_recent_fallback": block.get("using_recent_fallback"),
            "research_note": block.get("research_note"),
        }
    return slim


def _brief_model() -> str:
    return settings.anthropic_model_brief or settings.anthropic_model


class AIService:
    def __init__(self, db: Database) -> None:
        self.db = db
        placeholder_keys = {"", "your_anthropic_api_key_here"}
        self.client = (
            Anthropic(api_key=settings.anthropic_api_key)
            if settings.anthropic_api_key not in placeholder_keys
            else None
        )

    def _chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 4096,
        *,
        model: str | None = None,
    ) -> str:
        placeholder_keys = {"", "your_anthropic_api_key_here"}
        if not self.client or settings.anthropic_api_key in placeholder_keys:
            return (
                "**Setup required:** Add your `ANTHROPIC_API_KEY` to `backend/.env` and restart the backend "
                "(LaunchAgent: `launchctl kickstart -k gui/$(id -u)/com.market-morning.backend`).\n\n"
                "Portfolio and cash still load — only AI brief generation needs the key."
            )
        resolved_model = model or settings.anthropic_model
        try:
            msg = self.client.messages.create(
                model=resolved_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                extra_body={"thinking": {"type": "disabled"}},
            )
        except TypeError:
            msg = self.client.messages.create(
                model=resolved_model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            err = str(e).lower()
            if "authentication" in err or "401" in err or "api-key" in err:
                return (
                    "**API key rejected.** Your `ANTHROPIC_API_KEY` in `backend/.env` is invalid. "
                    "Update it and restart the backend."
                )
            if "not_found" in err or "404" in err or "model" in err:
                return (
                    f"**Model unavailable.** `{resolved_model}` is retired or invalid. "
                    "Set `ANTHROPIC_MODEL=claude-opus-4-8` and `ANTHROPIC_MODEL_FAST=claude-sonnet-5` in `backend/.env` and restart the backend."
                )
            raise
        return sanitize_ai_output(self._extract_message_text(msg))

    @staticmethod
    def _extract_message_text(msg: Any) -> str:
        parts: list[str] = []
        for block in msg.content:
            btype = getattr(block, "type", None)
            if btype == "text" and hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts).strip()

    async def _portfolio_context(self) -> dict[str, Any]:
        holdings = await self.db.get_holdings()
        tickers = [h["ticker"] for h in holdings]
        quotes = get_quotes(tickers) if tickers else {}
        portfolio_rows = []
        total_value = 0.0
        total_cost = 0.0
        for h in holdings:
            q = quotes.get(h["ticker"], {})
            price = q.get("price") or 0
            value = price * h["shares"]
            cost = h["avg_cost"] * h["shares"]
            total_value += value
            total_cost += cost
            ret = ((price - h["avg_cost"]) / h["avg_cost"] * 100) if h["avg_cost"] else 0
            portfolio_rows.append({
                **h,
                "price": price,
                "value": round(value, 2),
                "return_pct": round(ret, 2),
                "name": q.get("name"),
            })
        return {
            "portfolio": portfolio_rows,
            "totals": {
                "value": round(total_value, 2),
                "cost": round(total_cost, 2),
                "return_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0,
            },
            "holdings_tickers": tickers,
        }

    async def _brief_context(self, *, force_research: bool = False) -> dict[str, Any]:
        """Lean, parallel context for morning brief — no metrics or news_flat duplication."""
        holdings, watchlist, chosen_actions, portfolio_memory = await asyncio.gather(
            self.db.get_holdings(),
            self.db.get_watchlist(),
            self.db.get_chosen_actions(15),
            self.db.get_memory(15),
        )
        tickers = [h["ticker"] for h in holdings]
        watch_tickers = [w["ticker"] for w in watchlist]

        sector_research, quotes, news, market, account = await asyncio.gather(
            asyncio.to_thread(
                get_market_research_bundle,
                force_refresh=force_research,
                _track_progress=force_research,
            ),
            asyncio.to_thread(get_quotes, tickers),
            asyncio.to_thread(get_news_bundle, watch_tickers, 3),
            asyncio.to_thread(get_market_snapshot),
            asyncio.to_thread(load_account),
        )

        portfolio_rows = []
        total_value = 0.0
        total_cost = 0.0
        for h in holdings:
            q = quotes.get(h["ticker"], {})
            price = q.get("price") or 0
            value = price * h["shares"]
            cost = h["avg_cost"] * h["shares"]
            total_value += value
            total_cost += cost
            ret = ((price - h["avg_cost"]) / h["avg_cost"] * 100) if h["avg_cost"] else 0
            portfolio_rows.append({
                **h,
                "price": price,
                "value": round(value, 2),
                "return_pct": round(ret, 2),
                "name": q.get("name"),
            })

        return {
            "portfolio": portfolio_rows,
            "totals": {
                "value": round(total_value, 2),
                "cost": round(total_cost, 2),
                "return_pct": round((total_value - total_cost) / total_cost * 100, 2) if total_cost else 0,
            },
            "account": account,
            "market": market,
            "watchlist": watchlist,
            "chosen_actions": chosen_actions,
            "portfolio_memory": portfolio_memory,
            "sector_research": _slim_sector_research(sector_research),
            "news": news,
        }

    async def _full_context(
        self,
        extra_tickers: list[str] | None = None,
        *,
        metrics_tickers: list[str] | None = None,
        force_research: bool = False,
        force_news: bool = False,
    ) -> dict[str, Any]:
        base = await self._portfolio_context()
        watchlist = await self.db.get_watchlist()
        watch_tickers = [w["ticker"] for w in watchlist]
        sector_research = get_market_research_bundle(force_refresh=force_research)
        news = get_news_bundle(
            watch_tickers + (extra_tickers or []),
            per_ticker=3,
            force_refresh=force_news,
        )
        metric_list = metrics_tickers if metrics_tickers is not None else base["holdings_tickers"]
        return {
            **base,
            "account": load_account(),
            "market": get_market_snapshot(),
            "metrics": portfolio_metrics(metric_list) if metric_list else {},
            "watchlist": watchlist,
            "chosen_actions": await self.db.get_chosen_actions(15),
            "portfolio_memory": await self.db.get_memory(15),
            "sector_research": sector_research,
            "news": news,
            "news_flat": flatten_news(news),
        }

    async def morning_brief(self, force: bool = False) -> dict[str, Any]:
        return await self.morning_brief_job(force=force)

    async def morning_brief_job(self, force: bool = False) -> dict[str, Any]:
        if settings.mock_mode:
            result = mock_morning_brief()
            await self.db.save_brief(result["content"], {})
            return {"content": result["content"]}

        from app.ai_jobs import set_brief_ai_progress

        if not force:
            existing = await self.db.get_brief_for_today_full()
            if existing:
                content = sanitize_ai_output(existing.get("content") or "")
                if content.strip() and not _is_placeholder_content(content):
                    return {"content": content, "cached": True}
                await self.db.clear_brief_for_today()

        set_brief_ai_progress(8, "Gathering market data…")
        context = await self._brief_context(force_research=force)
        system = brief_system()
        user = f"Today's data:\n```json\n{json.dumps(context, default=str)}\n```"
        set_brief_ai_progress(22, "Composing market brief…")
        raw = self._chat(system, user, max_tokens=8192, model=_brief_model())
        set_brief_ai_progress(90, "Finalizing brief…")
        result = parse_ai_response(raw)
        content = sanitize_ai_output(result["content"])
        if _is_placeholder_content(content):
            await self.db.clear_brief_for_today()
            return {"content": "", "error": "Brief generation returned empty content"}
        await self.db.save_brief(
            content,
            {"synopsis": markdown_plain_excerpt(content)},
        )
        self._schedule_brief_synopsis(content)
        set_brief_ai_progress(100, "Brief ready")
        return {"content": content}

    async def mini_brief(self) -> dict[str, Any]:
        """Short late-day update paragraph — only fresh headlines since morning brief."""
        if settings.mock_mode:
            return {"content": "Markets steady into the close; no major late headlines in mock mode."}
        existing = await self.db.get_brief_for_today_full()
        prior = (existing or {}).get("content") or ""
        context = await self._full_context(force_research=True, force_news=True)
        headlines = (context.get("news_flat") or [])[:20]
        system = (
            "Write ONE dense paragraph (4–6 sentences) capturing late-breaking market news since the morning brief. "
            "Focus on new headlines only. Cite 1–2 markdown links [Headline](url) from the provided news context. "
            "Prefer free-access and MarketWatch sources. No headers, no bullets, no ThinkingBlock."
        )
        user = json.dumps(
            {"morning_brief_excerpt": prior[:2000], "latest_headlines": headlines},
            default=str,
        )
        raw = self._chat(system, user, max_tokens=512, model=settings.anthropic_model_fast)
        content = sanitize_ai_output(raw)
        await self.db.save_mini_brief(content)
        return {"content": content}

    def _schedule_brief_synopsis(self, content: str) -> None:
        """Generate recap synopsis in background so the brief returns without a second API wait."""
        if _is_placeholder_content(content) or len(content) < 100:
            return

        def _run() -> None:
            synopsis = self._generate_synopsis(content)
            if not synopsis:
                return
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._save_brief_synopsis(synopsis))
            finally:
                loop.close()

        threading.Thread(target=_run, daemon=True).start()

    async def _save_brief_synopsis(self, synopsis: str) -> None:
        row = await self.db.get_brief_for_today_full()
        if row and row.get("content"):
            await self.db.save_brief(row["content"], {"synopsis": synopsis})

    def _generate_synopsis(self, content: str) -> str:
        if _is_placeholder_content(content) or len(content) < 100:
            return ""
        system = (
            "Write a 2–3 paragraph plain-text recap of this market brief. "
            "Capture the day's dominant themes, sector moves, and key trade ideas. "
            "No markdown headers, no bullet lists, no hyperlinks, no URLs."
        )
        return sanitize_ai_output(
            self._chat(system, content[:12000], max_tokens=768, model=settings.anthropic_model_fast)
        )

    async def portfolio_analysis(self, force: bool = False) -> dict[str, Any]:
        if settings.mock_mode:
            holdings = await self.db.get_holdings()
            if not holdings:
                return {
                    "content": "**No holdings.** Sync Robinhood or add positions to generate analysis.",
                    "actions": [],
                    "positions": [],
                }
            return {
                "content": "## Portfolio Pulse\n\nMock mode — enable real API for quant analysis.",
                "actions": [],
                "positions": [],
            }
        if not force:
            existing = await self.db.get_portfolio_analysis()
            content = (existing or {}).get("content") or ""
            if existing and content.strip() and not _is_placeholder_content(content):
                cleaned = sanitize_ai_output(content)
                if cleaned != content:
                    meta = {
                        "actions": existing.get("actions") or [],
                        "positions": existing.get("positions") or [],
                    }
                    await self.db.save_portfolio_analysis(cleaned, meta)
                existing["content"] = cleaned
                return existing
            return {
                "content": "",
                "actions": [],
                "positions": [],
                "cached": False,
            }

        set_portfolio_progress(15, "Loading holdings…")
        context = await self._portfolio_context()
        tickers = context["holdings_tickers"]
        if not tickers:
            return {
                "content": "**No holdings.** Sync Robinhood to load positions, then refresh analysis.",
                "actions": [],
                "positions": [],
            }

        set_portfolio_progress(35, "Fetching market data…")
        context["account"] = load_account()
        context["market"] = get_market_snapshot()
        set_portfolio_progress(55, "Computing fundamentals & technicals…")
        context["metrics"] = portfolio_metrics(tickers, force_refresh=force)
        context["technicals"] = portfolio_technicals(tickers, force_refresh=force)

        set_portfolio_progress(70, "Running quant analysis…")
        system = portfolio_system()
        user = f"Today's portfolio data:\n```json\n{json.dumps(context, default=str)}\n```"
        raw = self._chat(system, user, max_tokens=8192, model=settings.anthropic_model_fast)
        set_portfolio_progress(92, "Parsing results…")
        result = parse_ai_response(raw)
        content = sanitize_ai_output(result["content"])
        meta = {
            "actions": result.get("actions", []),
            "positions": result.get("positions", []),
        }
        if _is_placeholder_content(content):
            return {"content": content, **meta}
        await self.db.save_portfolio_analysis(content, meta)
        set_portfolio_progress(100, "Analysis complete")
        return {"content": content, **meta}

    async def portfolio_analysis_job(self, force: bool = False) -> dict[str, Any]:
        return await self.portfolio_analysis(force=force)

    async def top_picks(self) -> dict[str, Any]:
        from app.ai_jobs import set_picks_progress

        set_picks_progress(8, "Screening candidates…")
        if settings.mock_mode:
            return mock_top_picks()
        holdings = await self.db.get_holdings()
        held = {h["ticker"] for h in holdings}
        set_picks_progress(18, "Ranking opportunities…")
        candidates = [c for c in screen_candidates(DEFAULT_UNIVERSE)[:20] if c["ticker"] not in held][:12]
        small_cap = [c for c in screen_candidates(DEFAULT_UNIVERSE, max_market_cap=15e9)[:20] if c["ticker"] not in held][:8]
        pick_tickers = [c["ticker"] for c in candidates] + [c["ticker"] for c in small_cap]
        set_picks_progress(32, "Gathering market context…")
        held_tickers = [h["ticker"] for h in holdings]
        metrics_tickers = list(dict.fromkeys(held_tickers + pick_tickers[:8]))
        context = await self._full_context(extra_tickers=pick_tickers, metrics_tickers=metrics_tickers)
        context["candidates"] = candidates
        if small_cap:
            context["small_cap_candidates"] = small_cap
        all_m = context.get("metrics") or {}
        held_set = set(held_tickers)
        pick_set = set(pick_tickers[:8])

        def _slice(full: dict[str, Any], tickers: set[str]) -> dict[str, Any]:
            if not tickers:
                return {"ratios": {}, "performance": {}, "risk": {}}
            return {
                "ratios": {
                    "profitability": {t: v for t, v in (full.get("ratios") or {}).get("profitability", {}).items() if t in tickers},
                    "valuation": {t: v for t, v in (full.get("ratios") or {}).get("valuation", {}).items() if t in tickers},
                },
                "performance": {
                    "cumulative_returns": {t: v for t, v in (full.get("performance") or {}).get("cumulative_returns", {}).items() if t in tickers},
                },
                "risk": {
                    "volatility": {t: v for t, v in (full.get("risk") or {}).get("volatility", {}).items() if t in tickers},
                },
            }

        context["metrics"] = _slice(all_m, held_set)
        context["metrics_picks"] = _slice(all_m, pick_set)
        set_picks_progress(55, "Running CIO analysis…")
        system = picks_system()
        user = json.dumps(context, default=str)
        raw = self._chat(system, user, max_tokens=4096, model=settings.anthropic_model_fast)
        set_picks_progress(88, "Parsing picks…")
        result = parse_ai_response(raw)
        content = sanitize_ai_output(result.get("content") or "")
        synopsis = self._generate_synopsis(content) if content else ""
        if content and not _is_placeholder_content(content):
            await self.db.save_picks(content, synopsis, {"watchlist_adds": result.get("watchlist_adds", [])})
        set_picks_progress(100, "Picks ready")
        return result

    async def top_picks_job(self) -> dict[str, Any]:
        return await self.top_picks()

    async def explore_market(self, query: str) -> dict[str, Any]:
        return await self.explore_market_job(query)

    async def explore_market_job(self, query: str) -> dict[str, Any]:
        from app.ai_jobs import set_explore_progress

        if settings.mock_mode:
            return mock_explore_market(query)
        set_explore_progress(12, f"Mapping {query} peers…")
        peers = market_peers(query)
        set_explore_progress(38, "Gathering market context…")
        context = await self._full_context(extra_tickers=peers.get("tickers", [])[:8])
        context["explore"] = peers
        context["query"] = query
        set_explore_progress(58, f"Analyzing {query}…")
        system = explore_system(query)
        user = json.dumps(context, default=str)
        raw = self._chat(system, user, max_tokens=4096, model=settings.anthropic_model_fast)
        set_explore_progress(90, "Formatting results…")
        return parse_ai_response(raw)


from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from anthropic import Anthropic

logger = logging.getLogger("market_morning.ai")

# Bounded exponential backoff + jitter for transient LLM failures (429 rate
# limits, 529 overloaded, 5xx). Anthropic can transiently 429/overload; without
# this a whole section silently dropped to out="".
_RETRYABLE_MARKERS = (
    "429", "529", "overloaded", "rate_limit", "rate limit",
    "500", "502", "503", "504", "internal server error",
    "service unavailable", "timeout", "timed out", "connection",
)
_MAX_CHAT_RETRIES = 4
_BACKOFF_BASE_SECONDS = 1.5
_BACKOFF_MAX_SECONDS = 20.0
# Cap on concurrent LLM sub-calls in a fan-out so a burst can't trip rate limits.
_FANOUT_MAX_WORKERS = 6


def _is_retryable_llm_error(err_lower: str) -> bool:
    return any(marker in err_lower for marker in _RETRYABLE_MARKERS)

from app.ai_jobs import (
    set_brief_ai_progress,
    set_explore_progress,
    set_picks_progress,
    set_portfolio_progress,
)
from app.ai_sanitize import markdown_plain_excerpt, sanitize_ai_output
from app.analysis_export import write_analysis_md
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
from app.portfolio_quant import compute_portfolio_quant, portfolio_concentration, reconcile_equity
from app.research import get_market_research_bundle
from app.prompts import (
    BRIEF_SECTION_SPECS,
    EXPLORE_SECTION_SPECS,
    brief_fanout_system,
    brief_ideas_task,
    brief_overview_task,
    brief_sector_task,
    brief_system,
    explore_body_task,
    explore_ideas_system,
    explore_overview_task,
    explore_section_system,
    explore_system,
    late_day_update_system,
    picks_detail_system,
    picks_rank_system,
    picks_system,
    portfolio_system,
    review_repair_system,
)
from app.response_parser import parse_ai_response
from app import review_gate
from app.ticker_validation import validate_content_tickers, validate_meta_tickers

DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "BRK-B",
    "JPM", "V", "UNH", "XOM", "LLY", "AVGO", "MA", "COST",
    "HD", "PG", "JNJ", "ABBV", "CRM", "AMD", "NFLX", "ORCL",
]

# Genuine small/mid-cap universe for the small-cap picks screen. DEFAULT_UNIVERSE
# is all mega-caps, so screening it with max_market_cap=15e9 returned an empty
# pool and the model invented small-caps. These are real, liquid small/mid names
# across sectors; the market-cap filter in screen_candidates still drops any that
# have grown past the cap, so the pool stays a true small/mid set.
SMALL_MID_CAP_UNIVERSE = [
    # Software / internet
    "PATH", "GTLB", "DOCN", "BOX", "ASAN", "APPN", "BRZE", "AI", "FROG", "PD",
    "BILL", "FSLY", "YEXT", "DV", "SEMR",
    # Semiconductors / hardware
    "LSCC", "POWI", "SITM", "AMBA", "NVTS", "ALGM", "INDI", "CRUS", "RMBS", "FORM",
    # Biotech / medtech
    "KRYS", "CRNX", "ARWR", "RARE", "INSM", "ACLX", "IONS", "RXRX", "TGTX", "AXSM",
    # Energy / clean energy
    "AMPY", "CRGY", "VTLE", "GPOR", "TALO", "SHLS", "ARRY", "FLNC", "RUN", "STEM",
    # Consumer / retail
    "CROX", "WING", "CAVA", "SG", "YETI", "PLNT", "FIGS", "OLPX",
    # Fintech
    "UPST", "LMND", "MQ", "DAVE", "PSFE",
    # Space / thematic / industrials
    "RKLB", "ASTS", "LUNR", "RDW", "ACHR", "JOBY",
]

# --- Output token caps per generation type -----------------------------------
# Raised from the prior 8192/4096 values which truncated briefs/picks/explore
# mid-sentence: the requested length plus ~30 verbose Google-News redirect URLs
# blew the budget, dropped the "Watchlist Mentions" section, and left a broken
# ```mm-meta``` fence that zeroed out all actionable ideas. Verified 2026-07 that
# both configured models (opus-4-8, sonnet-5) accept these non-streaming; the
# Anthropic SDK forces streaming above ~24k tokens, so these stay well under the
# models' true API max (>=64k with streaming).
MAX_TOKENS_BRIEF = 16000
MAX_TOKENS_PICKS = 16000
MAX_TOKENS_EXPLORE = 8000
MAX_TOKENS_PORTFOLIO = 8192
# Per-call cap for the fan-out brief: each of the ~10 concurrent sub-calls emits
# one section (~350-550 words) well under this, so no single call truncates.
MAX_TOKENS_BRIEF_SECTION = 2000
# Explore fan-out: one section per concurrent sub-call. Kept comfortably above
# the ~350-550 word section length so a body never truncates mid-heading.
MAX_TOKENS_EXPLORE_SECTION = 2400
# The ideas sub-call emits the Actionable Ideas markdown AND the mm-meta JSON, so
# it needs extra headroom — a too-tight cap truncated the JSON mid-string and
# left an unclosed ```mm-meta fence in stored output.
MAX_TOKENS_EXPLORE_IDEAS = 3200
MAX_TOKENS_EXPLORE_OVERVIEW = 2000
# Picks fan-out: a single ranking call (JSON) then one concurrent call per pick.
MAX_TOKENS_PICKS_RANK = 1600
MAX_TOKENS_PICKS_DETAIL = 1400

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


_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort parse of a single JSON object from an LLM response."""
    if not text:
        return None
    candidate = text.strip()
    fence = _CODE_FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()
    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = _JSON_OBJ_RE.search(candidate)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


# --- Held-ticker exclusion for picks ----------------------------------------
# Dual-class / multi-listing families that must be treated as one holding so a
# pick can't slip through as a share-class variant of a name already owned.
_SHARE_CLASS_GROUPS: list[frozenset[str]] = [
    frozenset({"GOOG", "GOOGL"}),
    frozenset({"BRK-A", "BRK-B"}),
    frozenset({"FOX", "FOXA"}),
    frozenset({"NWS", "NWSA"}),
    frozenset({"UA", "UAA"}),
    frozenset({"LEN", "LEN-B"}),
    frozenset({"HEI", "HEI-A"}),
    frozenset({"PARA", "PARAA"}),
]


def _norm_ticker(ticker: Any) -> str:
    """Canonical form for comparison: upper-case, trimmed, dots -> dashes."""
    return str(ticker or "").strip().upper().replace(".", "-")


def _expand_held(held: set[str] | list[str] | None) -> set[str]:
    """Normalized held set expanded with known share-class siblings."""
    norm = {_norm_ticker(t) for t in (held or []) if t}
    expanded = set(norm)
    for t in norm:
        for group in _SHARE_CLASS_GROUPS:
            if t in group:
                expanded |= set(group)
    return expanded


def _is_held(ticker: Any, held_expanded: set[str]) -> bool:
    return _norm_ticker(ticker) in held_expanded


# A pick heading in either the fan-out format (`### 2. Name (TKR)`) or the
# single-call fallback format (`**2. Name (TKR)**— body...`). Numbered marker at
# the start of a line is the reliable signal; the ticker (if any) is a
# parenthesized upper-case token.
_PICK_START_RE = re.compile(r"^\s*(?:#{2,4}\s*)?(?:\*\*)?\s*(\d+)\.\s+\S")
_SECTION_HEADER_RE = re.compile(r"^\s*(?:#{1,3}\s+\S|-{3,}\s*$)")
_PAREN_TICKER_RE = re.compile(r"\(([A-Z][A-Z.\-]{0,5})\)")
# A leading symbol form: "**1. AAPL — Apple Inc.**" / "1. AAPL: ..." / "### 1. AAPL - ...".
_LEAD_TICKER_RE = re.compile(r"^\s*(?:#{2,4}\s*)?(?:\*\*)?\s*\d+\.\s*([A-Z][A-Z.\-]{0,5})\b(?=\s*[—–:\-])")
_RANK_PREFIX_RE = re.compile(r"^(\s*(?:#{2,4}\s*)?(?:\*\*)?\s*)(\d+)(\.)")

# Self-correction / "we-already-own-this" narration that must never reach the
# user. Broad on purpose: covers the single-call fallback's freeform variants.
_PICKS_META_PATTERNS = [
    re.compile(r"\s*\*?\(\s*already (?:held|owned|a holding|in (?:the|your) (?:book|portfolio))[^)]*\)\*?", re.I),
    re.compile(r"\s*[—–-]?\s*wait,?\s*(?:this is\s*)?already (?:held|owned|in (?:the|your) (?:book|portfolio))[^.\n]*\.?", re.I),
    re.compile(r"\s*[—–-]?\s*already (?:held|owned|a holding|in (?:the|your) (?:book|portfolio))(?:,)?\s*(?:skip|omit)?[^.\n]*\.?", re.I),
    re.compile(r"\s*[—–-]?\s*(?:which |that )?you already (?:hold|own)[^.\n]*\.?", re.I),
    re.compile(r"\s*Substitut(?:e|ing):?[^.\n]*\.?", re.I),
    re.compile(r"\s*Replacing[^.\n]*\.?", re.I),
    re.compile(r"\s*(?:so I(?:'ll)?|let me|I'?ll)\s+(?:pivot|substitute|swap|replace)[^.\n]*\.?", re.I),
]


def _heading_held_ticker(line: str, held_expanded: set[str]) -> bool:
    candidates = list(_PAREN_TICKER_RE.findall(line))
    lead = _LEAD_TICKER_RE.match(line)
    if lead:
        candidates.append(lead.group(1))
    return any(_is_held(t, held_expanded) for t in candidates)


def _scrub_picks_meta(content: str, held_expanded: set[str]) -> str:
    """Deterministic review pass over picks output.

    1) Drop any pick block whose heading names an already-held ticker (works for
       both the fan-out `###` format and the single-call `**N. …**` fallback).
    2) Strip residual self-correction / "already held / Substitute:" narration.
    3) Renumber the surviving picks per section so ranks stay contiguous.

    Runs deterministically so it holds even when the LLM is unavailable.
    """
    if not content:
        return content

    # 1) Drop held-headed pick blocks. A block runs from its numbered heading
    #    line until the next pick heading or section header.
    lines = content.split("\n")
    kept: list[str] = []
    dropping = False
    for line in lines:
        is_pick_start = bool(_PICK_START_RE.match(line))
        is_section = bool(_SECTION_HEADER_RE.match(line))
        if is_pick_start:
            dropping = _heading_held_ticker(line, held_expanded)
            if dropping:
                continue
        elif is_section:
            dropping = False
        if dropping:
            continue
        kept.append(line)

    cleaned = "\n".join(kept)

    # 2) Strip residual meta-commentary clauses on surviving lines.
    for pat in _PICKS_META_PATTERNS:
        cleaned = pat.sub("", cleaned)

    # 3) Renumber surviving picks within each section.
    out: list[str] = []
    rank = 0
    for line in cleaned.split("\n"):
        if _SECTION_HEADER_RE.match(line) and not _PICK_START_RE.match(line):
            rank = 0
            out.append(line)
            continue
        if _PICK_START_RE.match(line):
            rank += 1
            line = _RANK_PREFIX_RE.sub(lambda m, r=rank: f"{m.group(1)}{r}{m.group(3)}", line, count=1)
        out.append(line)

    result = "\n".join(out)
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _metric_for(sources: list[dict[str, Any]], ticker: str) -> dict[str, Any]:
    """Pull a single ticker's fundamentals slice from one or more metrics dicts."""
    for src in sources:
        if not isinstance(src, dict):
            continue
        ratios = src.get("ratios") or {}
        prof = (ratios.get("profitability") or {}).get(ticker)
        val = (ratios.get("valuation") or {}).get(ticker)
        cum = ((src.get("performance") or {}).get("cumulative_returns") or {}).get(ticker)
        vol = ((src.get("risk") or {}).get("volatility") or {}).get(ticker)
        if prof or val or cum is not None or vol is not None:
            return {"profitability": prof or {}, "valuation": val or {},
                    "cumulative_return": cum, "volatility": vol}
    return {}


def _research_headlines(research: dict[str, Any] | None, per_sector: int = 3, limit: int = 30) -> list[dict[str, Any]]:
    """Flatten top linked headlines from a research bundle for section sub-calls."""
    flat: list[dict[str, Any]] = []
    for block in (research or {}).values():
        if isinstance(block, dict):
            for a in (block.get("articles") or [])[:per_sector]:
                flat.append({
                    "title": a.get("title"),
                    "link": a.get("link"),
                    "publisher": a.get("publisher"),
                    "sector": block.get("label"),
                })
    return flat[:limit]


class AIService:
    def __init__(self, db: Database) -> None:
        self.db = db
        placeholder_keys = {"", "your_anthropic_api_key_here"}
        self.client = (
            Anthropic(api_key=settings.anthropic_api_key)
            if settings.anthropic_api_key not in placeholder_keys
            else None
        )

    @staticmethod
    def _system_blocks(system: str) -> list[dict[str, Any]]:
        """Send the static system prefix as a cacheable block.

        Anthropic prompt caching gives ~90% input-token savings on the large,
        identical persona/instruction prefix that is re-sent on every call
        (and re-used across the ~10 concurrent fan-out sub-calls)."""
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]

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
        system_arg: Any = self._system_blocks(system)
        for attempt in range(_MAX_CHAT_RETRIES + 1):
            try:
                msg = self._create_message(resolved_model, max_tokens, system_arg, user)
                break
            except Exception as e:
                err = str(e).lower()
                if "authentication" in err or "401" in err or "api-key" in err:
                    return (
                        "**API key rejected.** Your `ANTHROPIC_API_KEY` in `backend/.env` is invalid. "
                        "Update it and restart the backend."
                    )
                # Retry transient rate-limit/overload/5xx with exponential backoff
                # + jitter before falling back to the friendly-error / raise paths.
                if _is_retryable_llm_error(err) and attempt < _MAX_CHAT_RETRIES:
                    delay = min(_BACKOFF_BASE_SECONDS * (2 ** attempt), _BACKOFF_MAX_SECONDS)
                    delay += random.uniform(0, delay * 0.25)
                    logger.warning(
                        "LLM transient error (attempt %d/%d, model=%s): %s — retrying in %.1fs",
                        attempt + 1, _MAX_CHAT_RETRIES, resolved_model, e, delay,
                    )
                    time.sleep(delay)
                    continue
                if "not_found" in err or "404" in err or "model" in err:
                    return (
                        f"**Model unavailable.** `{resolved_model}` is retired or invalid. "
                        "Set `ANTHROPIC_MODEL=claude-opus-4-8` and `ANTHROPIC_MODEL_FAST=claude-sonnet-5` in `backend/.env` and restart the backend."
                    )
                logger.error("LLM call failed (model=%s): %s", resolved_model, e)
                raise
        return sanitize_ai_output(self._extract_message_text(msg))

    def _create_message(self, resolved_model: str, max_tokens: int, system_arg: Any, user: str) -> Any:
        try:
            return self.client.messages.create(
                model=resolved_model,
                max_tokens=max_tokens,
                system=system_arg,
                messages=[{"role": "user", "content": user}],
                extra_body={"thinking": {"type": "disabled"}},
            )
        except TypeError:
            return self.client.messages.create(
                model=resolved_model,
                max_tokens=max_tokens,
                system=system_arg,
                messages=[{"role": "user", "content": user}],
            )

    @staticmethod
    def _extract_message_text(msg: Any) -> str:
        parts: list[str] = []
        for block in msg.content:
            btype = getattr(block, "type", None)
            if btype == "text" and hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts).strip()

    def _repair_missing_sections(
        self,
        content: str,
        missing: list[str],
        *,
        gen_type: str,
    ) -> str:
        """One cheap fast-model pass that writes ONLY the missing section(s).

        Deterministic scrubbing handles every mechanical failure class; this is
        the single, gated LLM repair used only when a required section is absent
        (which the fan-out normally prevents). Appends the generated section(s)
        to the existing body. Best-effort — a failed/empty repair leaves the
        original content untouched."""
        if not missing or not self.client:
            return content
        try:
            out = self._chat(
                review_repair_system(gen_type, missing),
                json.dumps({"missing_sections": missing, "existing_markdown": content[:12000]}, default=str),
                max_tokens=1800,
                model=settings.anthropic_model_fast,
            )
        except Exception:
            return content
        addition = sanitize_ai_output(out or "")
        if not addition or _is_placeholder_content(addition):
            return content
        return f"{content.rstrip()}\n\n{addition.strip()}".strip()

    async def _portfolio_context(self) -> dict[str, Any]:
        holdings = await self.db.get_holdings()
        tickers = [h["ticker"] for h in holdings]
        quotes = get_quotes(tickers) if tickers else {}
        account = load_account()
        portfolio_rows = []
        total_cost = 0.0
        for h in holdings:
            q = quotes.get(h["ticker"], {})
            raw_price = q.get("price")
            # A missing/zero/unavailable live quote must NEVER be coerced to 0 —
            # that fabricates value=0 and a bogus -100% per-name loss, which then
            # understates equity and makes the analysis narrate a false wipeout.
            # Leave price/value/return null (stale) so the model treats it as a
            # quote-unavailable name rather than a total loss.
            price_known = isinstance(raw_price, (int, float)) and raw_price > 0
            cost = h["avg_cost"] * h["shares"]
            total_cost += cost
            if price_known:
                price = float(raw_price)
                value = price * h["shares"]
                value_out = round(value, 2)
                ret = round((price - h["avg_cost"]) / h["avg_cost"] * 100, 2) if h["avg_cost"] else None
            else:
                price = None
                value_out = None
                ret = None
            portfolio_rows.append({
                **h,
                "price": price,
                "value": value_out,
                "return_pct": ret,
                "name": q.get("name"),
                "sector": q.get("sector"),
                "industry": q.get("industry"),
                "quote_unavailable": not price_known,
            })
        # Equity reconciliation (snapshot fallback when any quote is stale) is
        # centralized in reconcile_equity() — one implementation for every path.
        rec = reconcile_equity(portfolio_rows, account)
        equity_value = rec["total_value"]
        reconciled = rec["source"] == "broker_snapshot"
        return {
            "portfolio": portfolio_rows,
            "totals": {
                "value": round(equity_value, 2),
                "cost": round(total_cost, 2),
                "return_pct": round((equity_value - total_cost) / total_cost * 100, 2) if total_cost else 0,
                "priced_value": rec["priced_value"],
                "equity_source": rec["source"],
                "quotes_complete": not rec["stale_tickers"],
            },
            "holdings_tickers": tickers,
            "account": account,
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

    @staticmethod
    def _generation_date_display() -> str:
        # Use the UTC date so the H1 matches the brief_date key used for storage
        # (fixes "July 6 stored under 07-05" style mismatches).
        return datetime.now(timezone.utc).strftime("%B %-d, %Y")

    async def _prior_brief_context(self) -> dict[str, Any] | None:
        """Compact prior-day framing + themes so today's brief avoids repetition."""
        today = datetime.now(timezone.utc).date().isoformat()
        try:
            dates = await self.db.list_brief_archive_dates()
        except Exception:
            return None
        prior_date = next((d for d in dates if d < today), None)
        if not prior_date:
            return None
        row = await self.db.get_brief_by_date(prior_date)
        if not row or not row.get("content"):
            return None
        content = sanitize_ai_output(row.get("content") or "")
        meta = row.get("meta") or {}
        return {
            "date": prior_date,
            "opening_excerpt": markdown_plain_excerpt(content, 700),
            "themes": (meta.get("synopsis") or "")[:900],
            "instruction": "Surface net-new angles vs this prior brief; do not reuse identical framing, lead story, or index numbers.",
        }

    def _fanout_brief(self, context: dict[str, Any], prior: dict[str, Any] | None) -> str | None:
        """Generate the brief as concurrent per-section Sonnet calls, then stitch.

        Returns assembled markdown, or None if too few sections came back (caller
        falls back to the single-call path).
        """
        date_display = self._generation_date_display()
        market = context.get("market")
        watch = context.get("watchlist")
        research = context.get("sector_research") or {}
        news = context.get("news")

        def _top_headlines(limit: int = 24) -> list[dict[str, Any]]:
            flat: list[dict[str, Any]] = []
            for block in research.values():
                if isinstance(block, dict):
                    for a in (block.get("articles") or [])[:3]:
                        flat.append({"title": a.get("title"), "link": a.get("link"),
                                     "publisher": a.get("publisher"), "sector": block.get("label")})
            return flat[:limit]

        overview_payload = {"market": market, "top_headlines": _top_headlines(),
                            "prior_brief": prior}
        ideas_payload = {"top_headlines": _top_headlines(30), "watchlist": watch,
                         "chosen_actions": context.get("chosen_actions"), "prior_brief": prior}

        # Build the concurrent task list: overview, 8 sectors, closing ideas.
        # (order, system, user, max_tokens)
        tasks: list[tuple[int, str, str, int]] = []
        tasks.append((0, brief_fanout_system(brief_overview_task(date_display)),
                      json.dumps(overview_payload, default=str), 2200))
        section_headings: dict[int, str] = {}
        for i, (heading, key, guidance) in enumerate(BRIEF_SECTION_SPECS, start=1):
            section_headings[i] = heading
            sector_block = research.get(key) or {}
            payload = {"sector_research": {key: sector_block}, "market": market,
                       "watchlist": watch, "news": news}
            tasks.append((i, brief_fanout_system(brief_sector_task(heading, guidance, key)),
                          json.dumps(payload, default=str), MAX_TOKENS_BRIEF_SECTION))
        # The closing block carries 3-5 trade ideas + watchlist — give it headroom.
        tasks.append((len(BRIEF_SECTION_SPECS) + 1,
                      brief_fanout_system(brief_ideas_task()),
                      json.dumps(ideas_payload, default=str), 3600))

        results: dict[int, str] = {}

        def _run_one(order: int, system: str, user: str, max_tokens: int) -> tuple[int, str]:
            try:
                out = self._chat(system, user, max_tokens=max_tokens,
                                 model=settings.anthropic_model_fast)
            except Exception:
                out = ""
            return order, sanitize_ai_output(out or "")

        from concurrent.futures import ThreadPoolExecutor, as_completed
        completed = 0
        total = len(tasks)
        with ThreadPoolExecutor(max_workers=min(_FANOUT_MAX_WORKERS, total)) as pool:
            futs = [pool.submit(_run_one, o, s, u, mt) for o, s, u, mt in tasks]
            for fut in as_completed(futs):
                order, text = fut.result()
                if text and not _is_placeholder_content(text):
                    results[order] = text
                completed += 1
                set_brief_ai_progress(min(88, 25 + int(completed / total * 60)),
                                      "Composing sections…")

        dropped = [o for o, *_ in tasks if o not in results]
        if dropped:
            def _brief_label(o: int) -> str:
                if o == 0:
                    return "Overview"
                if o == len(BRIEF_SECTION_SPECS) + 1:
                    return "Closing Ideas"
                return section_headings.get(o, f"section {o}")
            logger.warning(
                "brief fan-out dropped %d/%d section(s): %s",
                len(dropped), total, ", ".join(_brief_label(o) for o in sorted(dropped)),
            )

        # Require the overview + a majority of sectors to consider the fan-out good.
        sector_orders = [o for o in results if 1 <= o <= len(BRIEF_SECTION_SPECS)]
        if 0 not in results or len(sector_orders) < max(4, len(BRIEF_SECTION_SPECS) // 2):
            return None

        parts: list[str] = []
        for o in sorted(results):
            text = results[o]
            heading = section_headings.get(o)
            if heading:
                # Prepend the canonical heading and strip any the model emitted
                # anyway (prevents "### Heading**News**" glued output).
                text = re.sub(r"^\s*#{1,4}\s*.*\n?", "", text, count=1) if text.lstrip().startswith("#") else text
                text = f"### {heading}\n\n{text.strip()}"
            parts.append(text.strip())
        return "\n\n".join(parts).strip()

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
        prior = await self._prior_brief_context()
        set_brief_ai_progress(22, "Composing market brief…")

        # Fan-out into concurrent per-section calls (fast + truncation-proof).
        assembled = await asyncio.to_thread(self._fanout_brief, context, prior)
        if assembled:
            content = sanitize_ai_output(assembled)
        else:
            # Fallback: single large call if the fan-out failed / returned too little.
            system = brief_system(self._generation_date_display())
            user = f"Today's data:\n```json\n{json.dumps(context, default=str)}\n```"
            raw = self._chat(system, user, max_tokens=MAX_TOKENS_BRIEF, model=_brief_model())
            content = sanitize_ai_output(parse_ai_response(raw)["content"])
        set_brief_ai_progress(90, "Finalizing brief…")
        if _is_placeholder_content(content):
            await self.db.clear_brief_for_today()
            return {"content": "", "error": "Brief generation returned empty content"}
        holdings_t = [h["ticker"] for h in (context.get("portfolio") or [])]
        watch_t = [w["ticker"] for w in (context.get("watchlist") or [])]
        content, _corr = validate_content_tickers(content, holdings=holdings_t, watchlist=watch_t)
        # Production-ready finalization gate: scrub pipeline/meta leakage + stray
        # meta fences, then repair (once) if a required section is missing.
        date_display = self._generation_date_display()
        gate = review_gate.finalize(
            content, gen_type="brief",
            required_sections=["Market Trade Ideas", "Watchlist Mentions"],
            brief_date_display=date_display,
        )
        content = gate["content"]
        if gate["needs_repair"]:
            content = self._repair_missing_sections(content, gate["missing_sections"], gen_type="brief")
            content = review_gate.finalize(content, gen_type="brief", brief_date_display=date_display)["content"]
        content = sanitize_ai_output(content)
        await self.db.save_brief(
            content,
            {"synopsis": markdown_plain_excerpt(content)},
        )
        write_analysis_md("brief", content, model=_brief_model())
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
        system = late_day_update_system()
        user = json.dumps(
            {"morning_brief_excerpt": prior[:2000], "latest_headlines": headlines},
            default=str,
        )
        raw = self._chat(system, user, max_tokens=512, model=settings.anthropic_model_fast)
        content = sanitize_ai_output(raw)
        await self.db.save_mini_brief(content)
        return {"content": content}

    @staticmethod
    def _run_async_background(coro_factory: Callable[[], Any]) -> None:
        """Run an async coroutine to completion on a throwaway loop in a daemon
        thread. One place for the off-response-path background pattern (synopsis
        generation + persistence) instead of repeating new-event-loop plumbing."""
        def _run() -> None:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(coro_factory())
            finally:
                loop.close()

        threading.Thread(target=_run, daemon=True).start()

    def _schedule_brief_synopsis(self, content: str) -> None:
        """Generate recap synopsis in background so the brief returns without a second API wait."""
        if _is_placeholder_content(content) or len(content) < 100:
            return

        async def _job() -> None:
            synopsis = await asyncio.to_thread(self._generate_synopsis, content)
            if synopsis:
                await self._save_brief_synopsis(synopsis)

        self._run_async_background(_job)

    def _schedule_picks_synopsis(self, content: str, watchlist_adds: list[Any]) -> None:
        if _is_placeholder_content(content) or len(content) < 100:
            return

        async def _job() -> None:
            synopsis = await asyncio.to_thread(self._generate_synopsis, content)
            if synopsis:
                await self.db.save_picks(content, synopsis, {"watchlist_adds": watchlist_adds})

        self._run_async_background(_job)

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
        # Fundamentals are quarterly — never force-refetch them (serial FMP round-trips
        # dominate latency). Scope force_refresh to technicals (15m TTL) only.
        context["metrics"] = portfolio_metrics(tickers, force_refresh=False)
        context["technicals"] = portfolio_technicals(tickers, force_refresh=force)

        set_portfolio_progress(65, "Decomposing factors & correlations…")
        # Code-computed quant analytics (aggregates that reconcile, beta/residual/IR
        # vs sector ETF, correlation + effective bets, ATR stops, sector templates).
        context["quant"] = compute_portfolio_quant(
            context["portfolio"], context.get("technicals"), context.get("market"),
            account=context.get("account"),
        )

        set_portfolio_progress(70, "Running quant analysis…")
        system = portfolio_system()
        user = f"Today's portfolio data:\n```json\n{json.dumps(context, default=str)}\n```"
        raw = self._chat(system, user, max_tokens=MAX_TOKENS_PORTFOLIO, model=settings.anthropic_model_fast)
        set_portfolio_progress(92, "Parsing results…")
        result = parse_ai_response(raw)
        content = sanitize_ai_output(result["content"])
        held_t = list(tickers)
        content, _c = validate_content_tickers(content, holdings=held_t)
        # Production-ready finalization gate: scrub pipeline/meta leakage, drop
        # false $0/-100%/wipeout/delisting narration, and reconcile any narrated
        # portfolio total to the computed aggregate (never a false wipeout).
        expected_equity = (context.get("quant", {}).get("aggregates", {}) or {}).get("total_value")
        gate = review_gate.finalize(
            content, gen_type="portfolio",
            required_sections=["Portfolio Pulse"],
            expected_equity=expected_equity,
        )
        content = gate["content"]
        content = sanitize_ai_output(content)
        result = validate_meta_tickers(result, holdings=held_t)
        meta = {
            "actions": result.get("actions", []),
            "positions": result.get("positions", []),
        }
        if _is_placeholder_content(content):
            return {"content": content, **meta}
        await self.db.save_portfolio_analysis(content, meta)
        write_analysis_md("portfolio", content, model=settings.anthropic_model_fast)
        set_portfolio_progress(100, "Analysis complete")
        return {"content": content, **meta}

    async def portfolio_analysis_job(self, force: bool = False) -> dict[str, Any]:
        return await self.portfolio_analysis(force=force)

    def _fanout_picks(self, context: dict[str, Any], held_expanded: set[str]) -> dict[str, Any] | None:
        """Rank once (single call), then write each pick concurrently, then stitch.

        The ranking call fixes the global head-to-head ordering and emits
        watchlist_adds; per-pick detail write-ups fan out under those fixed
        ranks. Returns a parsed result dict or None (caller falls back).
        """
        # Held names are excluded from the candidate universe BEFORE ranking so
        # the model can never rank a name the user already owns (case- and
        # share-class-insensitive).
        candidates = [c for c in (context.get("candidates") or [])
                      if not _is_held(c.get("ticker"), held_expanded)]
        small_cap = [c for c in (context.get("small_cap_candidates") or [])
                     if not _is_held(c.get("ticker"), held_expanded)]
        news_flat = context.get("news_flat")
        research = context.get("sector_research") or {}
        metrics_picks = context.get("metrics_picks") or {}
        metrics_held = context.get("metrics") or {}
        watch = context.get("watchlist")
        headlines = _research_headlines(research, limit=30)

        rank_payload = {
            "candidates": candidates,
            "small_cap_candidates": small_cap,
            "headlines": headlines,
            "news": (news_flat or [])[:40],
            "metrics_picks": metrics_picks,
            "held_tickers": sorted(held_expanded),
            "watchlist": watch,
        }
        try:
            rank_raw = self._chat(picks_rank_system(), json.dumps(rank_payload, default=str),
                                  max_tokens=MAX_TOKENS_PICKS_RANK, model=settings.anthropic_model_fast)
        except Exception:
            return None
        ranking = _extract_json_object(rank_raw)
        if not ranking:
            return None

        def _clean_picks(items: Any) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for p in items or []:
                if isinstance(p, dict) and p.get("ticker"):
                    t = _norm_ticker(p["ticker"])
                    if not t or t in seen or _is_held(t, held_expanded):
                        continue
                    seen.add(t)
                    out.append({"ticker": t, "name": p.get("name") or t,
                                "angle": p.get("angle") or "", "evidence": p.get("evidence") or ""})
            return out

        def _refill(picks: list[dict[str, Any]], pool: list[dict[str, Any]],
                    taken: set[str], want: int = 5) -> None:
            """Top up a section from non-held screened candidates so a section
            short on ranked names never forces the meta-commentary-prone
            single-call fallback."""
            for c in pool:
                if len(picks) >= want:
                    break
                t = _norm_ticker(c.get("ticker"))
                if not t or t in taken or _is_held(t, held_expanded):
                    continue
                taken.add(t)
                picks.append({"ticker": t, "name": c.get("name") or t,
                              "angle": "", "evidence": ""})

        large = _clean_picks(ranking.get("large_cap"))[:5]
        small = _clean_picks(ranking.get("small_cap"))[:5]
        # Re-fill any slots vacated by dropped held names with fresh non-held
        # screened candidates so the FINAL list is complete and held-free.
        taken = {p["ticker"] for p in large} | {p["ticker"] for p in small}
        _refill(large, candidates, taken)
        _refill(small, small_cap, taken)
        if len(large) + len(small) < 6:
            return None

        # (section, index-in-section, pick)
        detail_specs: list[tuple[str, int, dict[str, Any]]] = []
        for idx, p in enumerate(large):
            detail_specs.append(("large", idx, p))
        for idx, p in enumerate(small):
            detail_specs.append(("small", idx, p))

        def _run_detail(section: str, idx: int, pick: dict[str, Any]) -> tuple[str, int, str]:
            ticker = pick["ticker"]
            payload = {
                "pick": pick,
                "ticker": ticker,
                "metrics": _metric_for([metrics_picks, metrics_held], ticker),
                "headlines": headlines,
                "news": (news_flat or [])[:25],
                # Authoritative holdings membership so the persona never asserts
                # from memory that a name is / isn't in the user's book.
                "held_tickers": sorted(held_expanded),
            }
            try:
                out = self._chat(picks_detail_system(), json.dumps(payload, default=str),
                                 max_tokens=MAX_TOKENS_PICKS_DETAIL, model=settings.anthropic_model_fast)
            except Exception:
                return section, idx, ""
            return section, idx, sanitize_ai_output(out or "")

        details: dict[tuple[str, int], str] = {}
        from concurrent.futures import ThreadPoolExecutor, as_completed
        completed = 0
        total = len(detail_specs)
        with ThreadPoolExecutor(max_workers=min(_FANOUT_MAX_WORKERS, total)) as pool:
            futs = [pool.submit(_run_detail, s, i, p) for s, i, p in detail_specs]
            for fut in as_completed(futs):
                section, idx, text = fut.result()
                if text and not _is_placeholder_content(text):
                    details[(section, idx)] = text
                completed += 1
                set_picks_progress(min(90, 55 + int(completed / total * 33)), "Writing picks…")

        dropped_picks = [(s, i, p) for s, i, p in detail_specs if (s, i) not in details]
        if dropped_picks:
            logger.warning(
                "picks fan-out dropped %d/%d pick detail(s): %s",
                len(dropped_picks), total,
                ", ".join(f"{s}:{p['ticker']}" for s, _i, p in dropped_picks),
            )

        def _assemble(section: str, picks: list[dict[str, Any]]) -> list[str]:
            lines: list[str] = []
            rank = 0
            for idx, p in enumerate(picks):
                body = details.get((section, idx))
                if not body:
                    continue
                rank += 1
                body = re.sub(r"^\s*#{1,4}\s*.*\n?", "", body, count=1) if body.lstrip().startswith("#") else body
                lines.append(f"### {rank}. {p['name']} ({p['ticker']})\n\n{body.strip()}")
            return lines

        large_parts = _assemble("large", large)
        small_parts = _assemble("small", small)
        # Require enough coherent picks in each section, else fall back.
        if len(large_parts) < 3 or len(small_parts) < 3:
            return None

        sections_md: list[str] = ["# Top 5 Large-Cap Picks", *large_parts,
                                  "# Top 5 Small-Cap & Growth Picks", *small_parts]
        content = "\n\n".join(sections_md).strip()
        return {"content": content, "actions": [],
                "watchlist_adds": ranking.get("watchlist_adds") or [], "positions": []}

    async def top_picks(self) -> dict[str, Any]:
        from app.ai_jobs import set_picks_progress

        set_picks_progress(8, "Screening candidates…")
        if settings.mock_mode:
            return mock_top_picks()
        holdings = await self.db.get_holdings()
        held = {h["ticker"] for h in holdings}
        held_expanded = _expand_held(held)
        set_picks_progress(18, "Ranking opportunities…")
        candidates = [c for c in screen_candidates(DEFAULT_UNIVERSE)[:20] if not _is_held(c["ticker"], held_expanded)][:12]
        # Screen the genuine small/mid-cap universe (not the mega-cap DEFAULT set)
        # so small-cap picks are really screened rather than fabricated.
        small_cap = [c for c in screen_candidates(SMALL_MID_CAP_UNIVERSE, max_market_cap=15e9)[:20] if not _is_held(c["ticker"], held_expanded)][:8]
        pick_tickers = [c["ticker"] for c in candidates] + [c["ticker"] for c in small_cap]
        set_picks_progress(32, "Gathering market context…")
        held_tickers = [h["ticker"] for h in holdings]
        metrics_tickers = list(dict.fromkeys(held_tickers + pick_tickers[:8]))
        context = await self._full_context(extra_tickers=pick_tickers, metrics_tickers=metrics_tickers)
        context["candidates"] = candidates
        if small_cap:
            context["small_cap_candidates"] = small_cap
        # Single source of truth for any portfolio-concentration figure picks
        # narrates (so it never free-forms a wrong "$8,151 / 65%" number).
        context["portfolio_concentration"] = portfolio_concentration(
            context.get("portfolio") or [], context.get("account"),
        )
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
        set_picks_progress(55, "Ranking picks…")
        # Rank once (single call, head-to-head), then fan out per-pick detail.
        assembled = await asyncio.to_thread(self._fanout_picks, context, held_expanded)
        if assembled and assembled.get("content"):
            result = assembled
        else:
            system = picks_system()
            user = json.dumps(context, default=str)
            raw = self._chat(system, user, max_tokens=MAX_TOKENS_PICKS, model=settings.anthropic_model_fast)
            result = parse_ai_response(raw)
        set_picks_progress(88, "Parsing picks…")
        content = sanitize_ai_output(result.get("content") or "")
        held_t = [h["ticker"] for h in holdings]
        watch_t = [w["ticker"] for w in (context.get("watchlist") or [])]
        content, _c = validate_content_tickers(content, holdings=held_t, watchlist=watch_t)
        # Review pass: strip any self-correction / "already held / Substitute:"
        # narration and drop any block that still heads a held ticker so the
        # final output is clean, professional, and held-free.
        content = _scrub_picks_meta(content, held_expanded)
        # Repair any garbled/severed-number/unmatched-paren fragment that slipped
        # through the fan-out stitch so this class can never reach the user.
        content = review_gate.repair_garbled_fragments(content)
        result["content"] = content
        result = validate_meta_tickers(result, holdings=held_t, watchlist=watch_t)
        if content and not _is_placeholder_content(content):
            # Save immediately; generate the recap synopsis off the response path
            # (a second blocking Sonnet call added ~10s to every picks run).
            await self.db.save_picks(content, "", {"watchlist_adds": result.get("watchlist_adds", [])})
            write_analysis_md("picks", content, model=settings.anthropic_model_fast)
            self._schedule_picks_synopsis(content, result.get("watchlist_adds", []))
        set_picks_progress(100, "Picks ready")
        return result

    async def top_picks_job(self) -> dict[str, Any]:
        return await self.top_picks()

    def _fanout_explore(self, context: dict[str, Any], query: str) -> dict[str, Any] | None:
        """Generate the deep-dive as concurrent per-section Sonnet calls, then stitch.

        Sections (overview, biggest players, key metrics, trends, portfolio
        adjacency) run in parallel; a single dedicated call produces the
        actionable-ideas markdown AND the mm-meta block so meta can never be
        duplicated or split. Returns a parsed result dict, or None if too few
        sections came back (caller falls back to the single-call path).
        """
        research = context.get("sector_research") or {}
        news = context.get("news")
        news_flat = context.get("news_flat")
        explore = context.get("explore") or {}
        market = context.get("market")
        watch = context.get("watchlist")
        portfolio = context.get("portfolio")
        headlines = _research_headlines(research, limit=30)

        section_payloads: dict[str, dict[str, Any]] = {
            "players": {"query": query, "explore": explore, "headlines": headlines},
            "metrics": {"query": query, "explore": explore},
            "trends": {"query": query, "headlines": headlines, "news": news_flat},
            "portfolio": {"query": query, "portfolio": portfolio, "watchlist": watch,
                          "explore_tickers": explore.get("tickers")},
        }
        overview_payload = {"query": query, "market": market, "headlines": headlines,
                            "explore": explore}
        ideas_payload = {"query": query, "headlines": headlines, "news": news_flat,
                         "explore": explore, "watchlist": watch}

        IDEAS_ORDER = len(EXPLORE_SECTION_SPECS) + 1
        # (order, heading|None, system, user, max_tokens, is_ideas)
        tasks: list[tuple[int, str | None, str, str, int, bool]] = []
        tasks.append((0, None, explore_section_system(query, explore_overview_task(query)),
                      json.dumps(overview_payload, default=str), MAX_TOKENS_EXPLORE_OVERVIEW, False))
        section_headings: dict[int, str] = {}
        for i, (heading, key, guidance) in enumerate(EXPLORE_SECTION_SPECS, start=1):
            section_headings[i] = heading
            tasks.append((i, heading,
                          explore_section_system(query, explore_body_task(heading, guidance)),
                          json.dumps(section_payloads[key], default=str),
                          MAX_TOKENS_EXPLORE_SECTION, False))
        tasks.append((IDEAS_ORDER, None, explore_ideas_system(query),
                      json.dumps(ideas_payload, default=str), MAX_TOKENS_EXPLORE_IDEAS, True))

        results: dict[int, str] = {}
        meta: dict[str, Any] = {"actions": [], "watchlist_adds": [], "positions": []}

        def _run_one(order: int, system: str, user: str, max_tokens: int,
                     is_ideas: bool) -> tuple[int, str, dict[str, Any] | None]:
            try:
                out = self._chat(system, user, max_tokens=max_tokens,
                                 model=settings.anthropic_model_fast)
            except Exception:
                return order, "", None
            if is_ideas:
                # parse_ai_response only strips a CLOSED mm-meta fence; a
                # truncated (unclosed / unparseable) fence would otherwise land
                # raw in stored output, so scrub any stray/broken fence from the
                # display body here (the parsed meta is returned separately).
                parsed = parse_ai_response(out or "")
                ideas_content = review_gate.strip_stray_meta_fences(parsed.get("content") or "")
                return order, ideas_content, parsed
            body = sanitize_ai_output(out or "")
            # A section body that truncated mid-generation can end on an empty or
            # cut-off heading (e.g. "### Cross-Compar"); drop it so no broken or
            # empty heading is stitched into the deep-dive.
            body = review_gate.strip_trailing_partial_heading(body)
            return order, body, None

        from concurrent.futures import ThreadPoolExecutor, as_completed
        completed = 0
        total = len(tasks)
        with ThreadPoolExecutor(max_workers=min(_FANOUT_MAX_WORKERS, total)) as pool:
            futs = [pool.submit(_run_one, o, s, u, mt, ideas) for o, _, s, u, mt, ideas in tasks]
            for fut in as_completed(futs):
                order, text, parsed = fut.result()
                if text and not _is_placeholder_content(text):
                    results[order] = text
                    if parsed is not None:
                        meta["actions"] = parsed.get("actions") or []
                        meta["watchlist_adds"] = parsed.get("watchlist_adds") or []
                completed += 1
                set_explore_progress(min(88, 58 + int(completed / total * 28)),
                                     f"Analyzing {query}…")

        dropped = [o for o, *_ in tasks if o not in results]
        if dropped:
            def _explore_label(o: int) -> str:
                if o == 0:
                    return "Overview"
                if o == IDEAS_ORDER:
                    return "Actionable Ideas"
                return section_headings.get(o, f"section {o}")
            logger.warning(
                "explore fan-out (%s) dropped %d/%d section(s): %s",
                query, len(dropped), total, ", ".join(_explore_label(o) for o in sorted(dropped)),
            )

        # Require overview, the ideas/meta block, and a majority of body sections.
        body_orders = [o for o in results if 1 <= o <= len(EXPLORE_SECTION_SPECS)]
        if 0 not in results or IDEAS_ORDER not in results or len(body_orders) < 3:
            return None

        parts: list[str] = []
        for o in sorted(results):
            text = results[o].strip()
            heading = section_headings.get(o)
            if heading:
                # Only strip a duplicated SECTION-level heading (# or ##) the
                # model may have echoed — never a `### Name (TICKER)` sub-header,
                # which previously dropped the FIRST player/metric entry's header
                # and left its bullets orphaned under the ## section heading.
                text = re.sub(r"^\s*#{1,2}\s+.*\n?", "", text, count=1) if text.lstrip().startswith("#") else text
                text = review_gate.strip_trailing_partial_heading(text)
                if not text.strip():
                    continue
                text = f"## {heading}\n\n{text.strip()}"
            parts.append(text.strip())
        content = "\n\n".join(parts).strip()
        return {"content": content, "actions": meta["actions"],
                "watchlist_adds": meta["watchlist_adds"], "positions": []}

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
        # Fan-out into concurrent per-section calls (fast + truncation-proof).
        assembled = await asyncio.to_thread(self._fanout_explore, context, query)
        if assembled and assembled.get("content"):
            result = assembled
        else:
            system = explore_system(query)
            user = json.dumps(context, default=str)
            raw = self._chat(system, user, max_tokens=MAX_TOKENS_EXPLORE, model=settings.anthropic_model_fast)
            result = parse_ai_response(raw)
        set_explore_progress(90, "Formatting results…")
        content = result.get("content") or ""
        held_t = context.get("holdings_tickers") or []
        watch_t = [w["ticker"] for w in (context.get("watchlist") or [])]
        content, _c = validate_content_tickers(content, holdings=held_t, watchlist=watch_t)
        # Production-ready finalization gate: scrub pipeline/meta leakage + stray
        # meta fences, then repair (once) if the required ideas section is missing.
        gate = review_gate.finalize(
            content, gen_type="explore",
            required_sections=["Actionable Ideas"],
        )
        content = gate["content"]
        if gate["needs_repair"]:
            content = self._repair_missing_sections(content, gate["missing_sections"], gen_type="explore")
            content = review_gate.finalize(content, gen_type="explore")["content"]
        content = sanitize_ai_output(content)
        result["content"] = content
        result = validate_meta_tickers(result, holdings=held_t, watchlist=watch_t)
        if content and not _is_placeholder_content(content):
            write_analysis_md(
                "explore",
                content,
                model=settings.anthropic_model_fast,
                slug=query,
                extra={"market": query},
            )
        return result


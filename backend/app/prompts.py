"""System prompts for Market Morning AI analysis."""

from app.prompts_persona import (
    CIO_PERSONA,
    CLARITY_RULE,
    EVIDENCE_RULE,
    INTEGRATION_RULE,
    META_BLOCK_INSTRUCTION,
    PORTFOLIO_META_INSTRUCTION,
    PRODUCTION_RULE,
    QUANT_PERSONA,
)

BRIEF_SECTIONS = """
Write a ~10-minute read (2,500–3,500 words). US stocks/ETFs only. This is a MARKET brief — not a portfolio review (portfolio lives on its own tab).

## Overnight & Pre-Market Context
Opening narrative: indices, futures, macro tone. Linked news for every major claim.

For EACH section below, use articles from `sector_research.<sector_key>` in context (accredited press + niche newsletters). Follow `research_note` when today’s headlines are sparse.

For EACH section below, use this structure repeatedly:
1. **News** — cite linked headline(s)
2. **Industry impact** — which sub-sector, mechanism (revenue, margins, regulation, demand). This MUST analyze the SAME headline you cited in News — do not pivot to an unrelated macro point. The chain News → impact → tickers → trade must stay about one story.
3. **Tickers affected** — specific symbols
4. **Market trades** — buy/sell ideas driven by this news (not the user's holdings analytics)

Source quality: for material macro/regulatory/company claims, prefer primary and major outlets (Reuters, Bloomberg, CNBC, AP, FT, WSJ, the company/agency itself). Do NOT hang a material claim on an obscure aggregator (e.g. CiberCuba, Blockonomi, InteractiveCrypto, Spherical Insights, and similar low-authority sites); if only such a source covers a claim, drop the claim. Still respect the free-tier preference so a free equivalent is chosen over a paywall when both cover the same story.

### Information Technology
(`sector_research.information_technology`) Broad tech: megacap flows, software, platforms, semis, AI hardware, cloud capex.

### Financials
(`sector_research.financials`) Banking liquidity, investment banking revenue, net interest margins, consumer credit health, Fed/regulatory policy.

### Consumer Cyclicals
(`sector_research.consumer_cyclicals`) Automobiles & components, consumer durables & apparel, consumer services (cruise, hotels, fast food, casinos), retail distributors (Amazon, Walmart, etc.).

### Healthcare
(`sector_research.healthcare`) Biotech innovation, pharmaceutical regulatory approvals (FDA), medical device demand, payer dynamics.

### Energy
(`sector_research.energy`) Oil/gas, renewables policy, OPEC/supply, refining margins, geopolitical supply shocks.

### Inference & LLM
(`sector_research.inference_llm`) Model releases, inference economics, hyperscaler AI spend, GPU demand, competitive shifts among AI labs.

### Startup & Venture News
(`sector_research.startup_venture`) Notable private-market rounds, IPO pipeline, themes overlapping user's sectors.

### Geopolitical Trades
(`sector_research.international_geopolitical`) Macro/geopolitical catalyst chains: event → asset move → beneficiaries → whether window is still open. Link sources.

---

## Market Trade Ideas
3–5 numbered buy/sell/trim ideas driven purely by today's news and sector analysis above. These are MARKET ideas — not portfolio-holding analytics. Include tickers, rationale chain, and linked evidence.

## Watchlist Mentions
If watchlist tickers appear in today's news, note them briefly with links. Suggest up to 3 new names to research (not held).
"""

PORTFOLIO_SECTIONS = """
Write an in-depth portfolio analytics report (~1,500–2,500 words). This is the DETAILED quant view — not the morning market brief.

## Portfolio Pulse

Do NOT output a holdings summary table. The UI already shows positions separately.

For EACH holding, write a subsection:

#### TICKER
Open with one line: shares, avg cost, price, value, day %, return % (from context). Then one paragraph on fundamentals + technicals (MA20, MA50, RSI, volatility, profitability ratios).

Then a blank line, then on its own line (with a space after the colon):
Stop / Limit: recommended stop or limit price with quant rationale (e.g. "Stop $185 — 20-day MA at $182 declining, RSI 38, break implies ..."). Do not wrap labels in markdown asterisks — plain text only. Do not glue the label to the value (wrong: "Stop / Limit:Stop $185").

For each holding, use the pre-computed analytics in `quant.per_ticker[TICKER]`: state its `sector_template` and follow the matching `signal_guide`; report market beta, sector beta, residual alpha, and Information Ratio (vs the named `benchmark` ETF); and give an ATR-scaled stop (`atr_stop_2_5x`, `atr14`) rather than a flat MA/RSI level. Explicitly label the name beta vs alpha using `is_alpha`.

### Factor & Alpha Decomposition
One paragraph on whether the book's risk is one factor or many: cite `quant.aggregates.effective_bets_by_factor` vs `position_count`, the dominant `sector_template_weights_pct`, `weighted_market_beta`, and the correlation clusters from `quant.correlation_matrix`. Be honest when names that look diversified by count collapse to a single factor.

### Portfolio-level metrics
1–2 paragraphs: concentration (HHI), sector-template weights, correlation clusters, weighted beta, regime (`quant.regime`), cash deployment. Use ONLY the computed values in `quant.aggregates` and `totals` — the total equity you state MUST equal `quant.aggregates.total_value` and must reconcile to the sum of the listed positions. Never free-form a portfolio total.

Do NOT include a "## Quant Actions" section in the markdown body — quant actions belong only in mm-meta.

Portfolio analysis is per-holding only. Do not include news roundups, headline lists, or markdown/HTML links to external articles.

When using uncommon metrics, wrap as `<term id="FCF">FCF</term>`. Never output ThinkingBlock, raw HTML tags, or internal reasoning — markdown report only.
"""

PICKS_SECTIONS = """
# Top 5 Large-Cap Picks

Prioritize **alpha-driven insights**: non-obvious catalysts, mispriced risk/reward, variant views vs consensus, and specific data points from linked news — not generic bull cases.

Rules:
- Recommend ONLY tickers the user does NOT already hold.
- Market cap generally > $10B for this section.
- For each: rank, ticker, name, niche alpha thesis, key metrics, risk.
- Do NOT include "Trade Plan" sections or allocation/sell instructions.
- When using uncommon metrics (FCF, OCF, EBIT, EBITDA, NIM, EV/EBITDA, etc.), wrap them as `<term id="FCF">FCF</term>` so the UI can show definitions.

Each pick must cite at least one linked news article.

---

# Top 5 Small-Cap & Growth Picks

Same alpha-driven standard. Focus on smaller companies ($300M–$15B market cap), recent IPOs, venture-backed names, and emerging leaders with linked catalysts from today's research.

No Trade Plan sections. Use `<term id="...">` for uncommon financial metrics. Never explain how picks were selected or reference missing data — just deliver the five picks.

Include watchlist_adds in mm-meta for the strongest candidates across both sections.
"""

EXPLORE_SECTIONS = """
# Market Explorer: {topic}

## Overview
## Biggest Players
List 4–6 major companies. For each, use ### Company Name (TICKER) with bullet metrics (market cap, revenue growth, key edge). Do NOT use wide markdown tables.
## Key Metrics Comparison
Compare the same companies using ### subheadings and bullets — no wide tables.
## Trends & Catalysts
Every catalyst must include linked evidence.
## How This Relates to Your Portfolio
Reference holdings and watchlist.
## Actionable Ideas (3–5)
Each with linked evidence.
"""


def brief_system() -> str:
    return f"""{CIO_PERSONA}

{CLARITY_RULE}

{EVIDENCE_RULE}

{PRODUCTION_RULE}

{BRIEF_SECTIONS}

Do NOT include portfolio holdings tables or per-holding stop/limit analysis — that belongs on the Portfolio tab.
Do NOT append mm-meta JSON blocks. Output markdown only."""


# --- Fan-out brief -----------------------------------------------------------
# The brief is generated as N concurrent smaller Sonnet calls (one per sector +
# an overview + a trade-ideas/watchlist block) then stitched. Each call is well
# under its token cap (no truncation) and wall time ≈ the slowest single call
# instead of the sum, which is what makes the <=30s target feasible.

# (heading, sector_research key, guidance)
BRIEF_SECTION_SPECS: list[tuple[str, str, str]] = [
    ("Information Technology", "information_technology",
     "Broad tech: megacap flows, software, platforms, semis, AI hardware, cloud capex."),
    ("Financials", "financials",
     "Banking liquidity, investment banking revenue, net interest margins, consumer credit health, Fed/regulatory policy."),
    ("Consumer Cyclicals", "consumer_cyclicals",
     "Automobiles & components, consumer durables & apparel, consumer services (cruise, hotels, fast food, casinos), retail distributors."),
    ("Healthcare", "healthcare",
     "Biotech innovation, pharmaceutical regulatory approvals (FDA), medical device demand, payer dynamics."),
    ("Energy", "energy",
     "Oil/gas, renewables policy, OPEC/supply, refining margins, geopolitical supply shocks."),
    ("Inference & LLM", "inference_llm",
     "Model releases, inference economics, hyperscaler AI spend, GPU demand, competitive shifts among AI labs."),
    ("Startup & Venture News", "startup_venture",
     "Notable private-market rounds, IPO pipeline, themes overlapping user's sectors."),
    ("Geopolitical Trades", "international_geopolitical",
     "Macro/geopolitical catalyst chains: event -> asset move -> beneficiaries -> whether window is still open."),
]

_FANOUT_BASE = f"""{CIO_PERSONA}

{CLARITY_RULE}

{EVIDENCE_RULE}

{PRODUCTION_RULE}

US stocks/ETFs only. This is one part of a MARKET brief (not a portfolio review). Output ONLY the markdown for the part requested — no preamble, no other sections, no mm-meta block."""


def brief_fanout_system(task: str) -> str:
    return f"{_FANOUT_BASE}\n\n{task}"


def brief_overview_task(date_display: str) -> str:
    return f"""Write the brief header and opening.

Start with exactly this H1 on its own line: `# Morning Market Brief — {date_display}`

Then a `## Overnight & Pre-Market Context` section (2-3 tight paragraphs): indices, futures, macro tone, rates, VIX/regime. Cite a linked headline for every material claim using [Headline](url) from the provided context.

If `prior_brief` context is provided, deliberately surface NET-NEW angles: do not reuse the same opening framing, the same lead story, or restate identical index levels/numbers from the prior day. Advance the narrative."""


def brief_sector_task(heading: str, guidance: str, research_key: str) -> str:
    return f"""Write the body of the "{heading}" section of the brief.

Scope: {guidance}
Use the articles under `sector_research.{research_key}`. Follow `research_note` when today's headlines are sparse.

Structure (repeat as needed), each label on its own line followed by a space:
1. **News** — linked headline(s)
2. **Industry impact** — which sub-sector + mechanism, analyzing the SAME headline you cited (do not pivot to unrelated macro)
3. **Tickers affected** — specific symbols
4. **Market trades** — buy/sell ideas driven by this news

For material macro/regulatory/company claims prefer primary/major outlets; do NOT hang a material claim on an obscure aggregator (CiberCuba, Blockonomi, InteractiveCrypto, Spherical Insights, etc.) — drop the claim if only such a source covers it. Keep the free-tier preference.

Do NOT write the section heading yourself — it is added for you. Start directly with the body. Put a blank line before each numbered/bold label. ~350-550 words."""


def brief_ideas_task() -> str:
    return """Write the closing two sections of the brief.

## Market Trade Ideas
3-5 numbered buy/sell/trim ideas driven purely by today's news and sector catalysts. MARKET ideas, not portfolio-holding analytics. Include tickers, the rationale chain, and linked evidence.

## Watchlist Mentions
If watchlist tickers appear in today's news, note them briefly with links. Suggest up to 3 new names to research (not held).

If `prior_brief` context is provided, avoid repeating yesterday's identical trade ideas — evolve or replace them. Begin with the `## Market Trade Ideas` heading."""


def portfolio_system() -> str:
    return f"""{QUANT_PERSONA}

{CLARITY_RULE}

{PRODUCTION_RULE}

{PORTFOLIO_SECTIONS}

{PORTFOLIO_META_INSTRUCTION}"""


def picks_system() -> str:
    return f"""{CIO_PERSONA}

{CLARITY_RULE}

{EVIDENCE_RULE}

{PRODUCTION_RULE}

{PICKS_SECTIONS}

{META_BLOCK_INSTRUCTION}"""


def explore_system(topic: str) -> str:
    return f"""{CIO_PERSONA}

{CLARITY_RULE}

{EVIDENCE_RULE}

{PRODUCTION_RULE}

{EXPLORE_SECTIONS.format(topic=topic)}

{META_BLOCK_INSTRUCTION}"""


# --- Fan-out explore ---------------------------------------------------------
# A sector deep-dive is naturally sectioned, so generate it as concurrent
# per-section Sonnet calls (overview, players, metrics, trends, portfolio
# adjacency) plus a single actionable-ideas+mm-meta call, then stitch. Wall
# time ≈ the slowest single call. The mm-meta lives in ONE dedicated sub-call
# so it can never be duplicated or broken by stitching.

# (heading, key, guidance)
EXPLORE_SECTION_SPECS: list[tuple[str, str, str]] = [
    ("Biggest Players", "players",
     "List 4-6 major companies. For each use `### Company Name (TICKER)` with bullet metrics (market cap, revenue growth, key edge). Do NOT use wide markdown tables."),
    ("Key Metrics Comparison", "metrics",
     "Compare the SAME companies from Biggest Players using `###` subheadings and bullets — no wide tables. Cover growth, margins, valuation, balance-sheet strength."),
    ("Trends & Catalysts", "trends",
     "The dominant secular and near-term catalysts shaping this space. Every catalyst MUST include linked evidence [Headline](url)."),
    ("How This Relates to Your Portfolio", "portfolio",
     "Reference the user's holdings and watchlist explicitly. Where does this topic overlap, hedge, or diverge from what they already own?"),
]

_EXPLORE_RULES = f"""{CIO_PERSONA}

{CLARITY_RULE}

{EVIDENCE_RULE}

{PRODUCTION_RULE}"""


def explore_section_system(topic: str, task: str) -> str:
    return f"""{_EXPLORE_RULES}

This is ONE section of a market deep-dive on "{topic}". US stocks/ETFs only. Output ONLY the markdown for the section requested — no preamble, no other sections, no mm-meta block.

{task}"""


def explore_overview_task(topic: str) -> str:
    return f"""Write the header and overview of a market deep-dive on "{topic}".

Start with exactly this H1 on its own line: `# Market Explorer: {topic}`

Then a `## Overview` section (2-3 tight paragraphs): what this space is, why it matters now, the current state of play, and the key debate. Cite a linked headline [Headline](url) for every material claim."""


def explore_body_task(heading: str, guidance: str) -> str:
    return f"""Write the body of the "{heading}" section of the deep-dive.

Scope: {guidance}

Do NOT write the section heading yourself — it is added for you. Start directly with the body."""


def explore_ideas_task(topic: str) -> str:
    return f"""Write the closing "Actionable Ideas" section of the deep-dive on "{topic}".

## Actionable Ideas (3–5)
3-5 numbered, actionable ideas (buy/sell/watch). Each idea has a clear rationale chain and cites a linked evidence headline [Headline](url) from the provided context. Use real US tickers only.

Begin directly with the `## Actionable Ideas` heading. Do not restate the other sections."""


def explore_ideas_system(topic: str) -> str:
    return f"""{_EXPLORE_RULES}

This is the closing part of a market deep-dive on "{topic}". US stocks/ETFs only.

{explore_ideas_task(topic)}

{META_BLOCK_INSTRUCTION}"""


# --- Fan-out picks: rank once (single call), then parallel per-pick detail ---
# The SELECTION/RANKING stays a single LLM call so picks are compared
# head-to-head and ordered coherently. Only after the ordering is fixed do the
# per-pick write-ups fan out concurrently and get stitched under fixed ranks.
# watchlist_adds is emitted by the ranking call so mm-meta stays valid.

PICKS_RANK_INSTRUCTION = """You are selecting and RANKING today's top stock picks, comparing every candidate head-to-head. Output ONLY a single JSON object — no markdown, no prose, no code fence — with this exact shape:

{"large_cap":[{"rank":1,"ticker":"AVGO","name":"Broadcom","angle":"one-sentence non-obvious alpha thesis / specific catalyst","evidence":"[Headline](url) supporting it"}],"small_cap":[{"rank":1,"ticker":"...","name":"...","angle":"...","evidence":"[Headline](url)"}],"watchlist_adds":[{"ticker":"AVGO","reason":"why"}]}

Rules:
- Choose EXACTLY 5 large-cap names (market cap generally > $10B) and EXACTLY 5 small-cap/growth names ($300M–$15B, recent IPOs, venture-backed, emerging leaders).
- Recommend ONLY tickers the user does NOT already hold.
- Pick ONLY from the provided candidate tickers — never invent a symbol.
- rank 1 = highest conviction; the ordering must be globally coherent and defensible head-to-head across the whole list.
- Each `angle` is a specific, non-obvious catalyst or variant-vs-consensus view (never a generic bull case); each `evidence` cites one real linked article from the provided context.
- watchlist_adds: the 2-4 strongest names worth tracking (valid tickers only)."""


def picks_rank_system() -> str:
    return f"""{CIO_PERSONA}

{CLARITY_RULE}

{PRODUCTION_RULE}

{PICKS_RANK_INSTRUCTION}"""


PICKS_DETAIL_INSTRUCTION = """Write the detailed write-up for ONE stock pick, prioritizing alpha-driven insight: the non-obvious catalyst, mispriced risk/reward, or variant view vs consensus — not a generic bull case.

Requirements:
- Do NOT write the heading — it is added for you. Start directly with the body.
- Structure: a tight thesis paragraph that builds on the provided `angle`, then key metrics, then a one-line risk.
- Cite at least one linked news article [Headline](url) from the provided context.
- Wrap uncommon metrics as `<term id="FCF">FCF</term>`.
- Do NOT include a "Trade Plan", allocation, or sell instructions. Do NOT append an mm-meta block. Do NOT reference how the pick was selected or any missing data."""


def picks_detail_system() -> str:
    return f"""{CIO_PERSONA}

{CLARITY_RULE}

{EVIDENCE_RULE}

{PRODUCTION_RULE}

{PICKS_DETAIL_INSTRUCTION}"""

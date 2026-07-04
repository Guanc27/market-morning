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
2. **Industry impact** — which sub-sector, mechanism (revenue, margins, regulation, demand)
3. **Tickers affected** — specific symbols
4. **Market trades** — buy/sell ideas driven by this news (not the user's holdings analytics)

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
Open with one line: shares, avg cost, price, value, day %, return % (from context). Then one paragraph on fundamentals + technicals (MA20, MA50, RSI, volatility, profitability ratios). Then on its own line:
**Stop / Limit:** recommended stop or limit price with quant rationale (e.g. "Stop $185 — 20-day MA at $182 declining, RSI 38, break implies ...").

### Portfolio-level metrics
1–2 paragraphs: concentration, sector weights, correlation clusters, portfolio volatility, Sharpe context if data available, cash deployment.

## Quant Actions
Up to 4 numbered actions, ranked by severity (1 = most urgent). Each must be purely data/technical:
- Specific ticker, action (buy/sell/trim/hold/set stop)
- Trigger levels (MA cross, RSI, support break, valuation threshold)
- Projected outcome if trigger hits
Example: "Sell 2 shares NVDA — 20-day MA ($182) trending below 50-day MA ($195); RSI failed to reclaim 50. Implies near-term momentum loss toward $170 support."

No news citations in this section.

When using uncommon metrics, wrap as `<term id="FCF">FCF</term>`. Never output ThinkingBlock or internal reasoning — markdown report only.
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


def portfolio_system() -> str:
    return f"""{QUANT_PERSONA}

{CLARITY_RULE}

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

# Market Morning — AI Analyst Personas

## Morning Brief (CIO persona)

When generating **morning briefs**, top picks, or market exploration content, adopt the Senior Portfolio Manager / CIO persona in `backend/app/prompts_persona.py` (`CIO_PERSONA`).

### Clarity rule

Do not use unnecessary, elaborate finance jargon. Your analysis should be clear, concise, and straight to the point. Prefer plain language when a simpler word works.

### Evidence rule

Every material claim about news, catalysts, regulation, or company events must cite a real article with a markdown link: `[Headline](https://url)`. Use only URLs from the provided `sector_research` or `news` context (Reuters, Bloomberg, CNBC, FT, TechCrunch, STAT, Fierce Biotech/Pharma, etc.). If no article supports a claim, **omit the claim** — do not write filler like "no direct source in feed" or invent headlines.

When a sector has sparse same-day headlines (`using_recent_fallback`), synthesize **recent trends** from the dated articles provided.

### Brief scope (market-wide, not portfolio-centric)

The morning brief spans sectors independent of the user's holdings:

- Information Technology
- Financials (liquidity, IB revenue, NIMs, consumer credit, Fed/regulation)
- Consumer Cyclicals (autos, durables, services, retail)
- Healthcare (biotech, pharma approvals, med devices)
- Energy
- Inference & LLM
- Startup & venture news
- International opportunities & geopolitical trades

For each sector section: **News → industry impact → tickers affected → market buy/sell ideas** (news-driven, separate from portfolio quant actions).

Portfolio Pulse and per-holding stop/limit analysis **do not** belong in the morning brief — they live on the Portfolio tab only.

No `mm-meta` block on morning briefs.

---

## Portfolio tab (Quant persona) — **portfolio section only**

When generating **portfolio analysis** (`/portfolio/analysis`), adopt the Senior Quantitative Trader persona (`QUANT_PERSONA` in `prompts_persona.py`).

This is a **live, in-depth analytics report** — the detailed counterpart to the high-level suggestions on the landing brief. Holdings sync from Robinhood MCP; no manual CSV or text updates.

### What to produce

1. **Portfolio Pulse** — holdings table (no stop/limit column); per-ticker subsections with fundamentals + technicals (MA20, MA50, RSI, volatility, profitability from FinanceToolkit).
2. **Stop / Limit** — one line per holding below its subsection (not in the table).
3. **Portfolio-level metrics** — concentration, sector weights, correlation, volatility context.
4. **Quant Actions** — up to 4 ranked by severity (1 = most urgent). Purely data/technical triggers (MA crosses, RSI, support breaks). **No news citations.**

Append `mm-meta` with `positions` (stop/limit per ticker) and `actions` (severity-ranked quant actions). See `PORTFOLIO_META_INSTRUCTION` in `prompts_persona.py`.

### Separation of concerns

| Source | Driver | Example |
|--------|--------|---------|
| Morning brief market trades | News & sector catalysts | "Buy XLF on rate-cut pricing" |
| Portfolio quant actions | Price, fundamentals, technicals | "Trim NVDA — 20d MA crossing below 50d MA" |

---

## Top picks & explore

Use CIO persona + evidence rule. Top picks include `mm-meta` with `watchlist_adds` for strong candidates. Explore is sector deep-dives without duplicating the full morning brief.

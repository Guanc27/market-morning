"""Demo portfolio, market data, and AI brief fixtures for MOCK_MODE."""

from __future__ import annotations

from typing import Any

from app.response_parser import parse_ai_response

MOCK_HOLDINGS = [
    {"ticker": "NVDA", "shares": 15.0, "avg_cost": 118.50, "notes": "core AI position"},
    {"ticker": "AAPL", "shares": 25.0, "avg_cost": 178.20, "notes": ""},
    {"ticker": "MSFT", "shares": 12.0, "avg_cost": 405.00, "notes": ""},
    {"ticker": "AMD", "shares": 20.0, "avg_cost": 142.80, "notes": "semiconductor tilt"},
    {"ticker": "VOO", "shares": 8.0, "avg_cost": 485.00, "notes": "index anchor"},
]

MOCK_QUOTES: dict[str, dict[str, float | str | None]] = {
    "NVDA": {"name": "NVIDIA Corporation", "price": 132.45, "prev_close": 130.10, "change_pct": 1.81, "sector": "Technology", "industry": "Semiconductors"},
    "AAPL": {"name": "Apple Inc.", "price": 211.30, "prev_close": 210.05, "change_pct": 0.60, "sector": "Technology", "industry": "Consumer Electronics"},
    "MSFT": {"name": "Microsoft Corporation", "price": 428.75, "prev_close": 424.90, "change_pct": 0.91, "sector": "Technology", "industry": "Software"},
    "AMD": {"name": "Advanced Micro Devices", "price": 156.20, "prev_close": 152.98, "change_pct": 2.10, "sector": "Technology", "industry": "Semiconductors"},
    "VOO": {"name": "Vanguard S&P 500 ETF", "price": 512.40, "prev_close": 510.35, "change_pct": 0.40, "sector": "ETF", "industry": "Large Blend"},
    "^GSPC": {"name": "S&P 500", "price": 5487.20, "prev_close": 5468.10, "change_pct": 0.35, "sector": None, "industry": None},
    "^IXIC": {"name": "Nasdaq Composite", "price": 17842.50, "prev_close": 17750.30, "change_pct": 0.52, "sector": None, "industry": None},
    "^DJI": {"name": "Dow Jones Industrial Average", "price": 39420.80, "prev_close": 39350.10, "change_pct": 0.18, "sector": None, "industry": None},
    "^VIX": {"name": "CBOE Volatility Index", "price": 14.22, "prev_close": 14.68, "change_pct": -3.13, "sector": None, "industry": None},
    "GOOGL": {"name": "Alphabet Inc.", "price": 178.90, "prev_close": 176.40, "change_pct": 1.42, "sector": "Technology", "industry": "Internet Content"},
    "META": {"name": "Meta Platforms", "price": 542.10, "prev_close": 538.20, "change_pct": 0.72, "sector": "Technology", "industry": "Internet Content"},
    "AVGO": {"name": "Broadcom Inc.", "price": 168.40, "prev_close": 165.80, "change_pct": 1.57, "sector": "Technology", "industry": "Semiconductors"},
    "CRM": {"name": "Salesforce", "price": 298.50, "prev_close": 294.10, "change_pct": 1.50, "sector": "Technology", "industry": "Software"},
    "ORCL": {"name": "Oracle Corporation", "price": 142.30, "prev_close": 140.80, "change_pct": 1.07, "sector": "Technology", "industry": "Software"},
}

MOCK_NEWS: dict[str, list[dict[str, Any]]] = {
    "NVDA": [
        {"title": "Nvidia data-center revenue beats as hyperscalers expand AI clusters", "link": "https://www.reuters.com/technology/nvidia/", "publisher": "Reuters"},
        {"title": "Blackwell chip ramp on track for Q3 shipments", "link": "https://www.bloomberg.com/news/nvidia-blackwell", "publisher": "Bloomberg"},
    ],
    "AMD": [
        {"title": "AMD MI350 series targets inference workloads vs Nvidia H200", "link": "https://www.reuters.com/technology/amd-mi350", "publisher": "Reuters"},
    ],
    "AAPL": [
        {"title": "Apple Services revenue hits record on App Store growth", "link": "https://www.reuters.com/technology/apple-services", "publisher": "Reuters"},
    ],
    "MSFT": [
        {"title": "Microsoft Azure AI revenue grows 60% YoY in latest quarter", "link": "https://www.reuters.com/technology/microsoft-azure", "publisher": "Reuters"},
    ],
    "AVGO": [
        {"title": "Broadcom custom AI chip orders surge from Google, Meta", "link": "https://www.reuters.com/technology/broadcom-custom-ai", "publisher": "Reuters"},
    ],
    "GOOGL": [
        {"title": "Google unveils Trillium TPU to rival Nvidia inference chips", "link": "https://www.reuters.com/technology/google-tpu-trillium", "publisher": "Reuters"},
    ],
    "CRM": [
        {"title": "Salesforce Agentforce adoption beats internal targets", "link": "https://www.reuters.com/technology/salesforce-agentforce", "publisher": "Reuters"},
    ],
    "_default": [
        {"title": "S&P 500 futures rise as tech leads pre-market", "link": "https://www.reuters.com/markets/us/futures", "publisher": "Reuters"},
    ],
}

MOCK_METRICS: dict[str, Any] = {
    "ratios": {
        "profitability": {"NVDA": {"Gross Margin": 0.75, "Net Margin": 0.55}, "AAPL": {"Gross Margin": 0.46, "Net Margin": 0.24}},
        "valuation": {"NVDA": {"P/E": 68.2, "P/S": 28.4}, "AAPL": {"P/E": 33.1, "P/S": 8.9}},
    },
    "performance": {"cumulative_returns": {"NVDA": 0.42, "AAPL": 0.18, "MSFT": 0.22, "AMD": 0.31, "VOO": 0.12}},
    "risk": {"volatility": {"NVDA": 0.38, "AAPL": 0.22, "MSFT": 0.20, "AMD": 0.35, "VOO": 0.14}},
}


def mock_quotes(tickers: list[str]) -> dict[str, dict[str, float | str | None]]:
    out: dict[str, dict[str, float | str | None]] = {}
    for ticker in tickers:
        if ticker in MOCK_QUOTES:
            out[ticker] = MOCK_QUOTES[ticker]
        else:
            out[ticker] = {"name": ticker, "price": 100.0, "prev_close": 99.0, "change_pct": 1.0, "sector": "Unknown", "industry": None}
    return out


def mock_market_snapshot() -> dict[str, Any]:
    labels = {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones", "^VIX": "VIX"}
    return {labels[k]: MOCK_QUOTES[k] for k in labels}


def mock_portfolio_metrics(tickers: list[str]) -> dict[str, Any]:
    return MOCK_METRICS


def mock_screen_candidates(tickers: list[str]) -> list[dict[str, Any]]:
    quotes = mock_quotes(tickers)
    scored = []
    for ticker in tickers:
        q = quotes.get(ticker, {})
        change = q.get("change_pct") or 0
        scored.append({
            "ticker": ticker,
            "name": q.get("name", ticker),
            "price": q.get("price"),
            "change_pct": change,
            "sector": q.get("sector"),
            "score": round(float(change), 2),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def mock_morning_brief() -> dict[str, Any]:
    rows = []
    total_value = 0.0
    total_cost = 0.0
    for h in MOCK_HOLDINGS:
        q = MOCK_QUOTES[h["ticker"]]
        price = float(q["price"] or 0)
        value = price * h["shares"]
        cost = h["avg_cost"] * h["shares"]
        ret = ((price - h["avg_cost"]) / h["avg_cost"] * 100) if h["avg_cost"] else 0
        total_value += value
        total_cost += cost
        rows.append((h["ticker"], value, q.get("change_pct") or 0, ret))

    total_ret = ((total_value - total_cost) / total_cost * 100) if total_cost else 0
    table = "\n".join(
        f"| {t} | ${v:,.0f} | {d:+.1f}% | {r:+.1f}% |" for t, v, d, r in rows
    )
    mkt = mock_market_snapshot()
    nvda_news = MOCK_NEWS["NVDA"][0]
    amd_news = MOCK_NEWS["AMD"][0]

    raw = f"""## Overnight & Pre-Market Context

Indices: S&P {mkt["S&P 500"]["change_pct"]:+.2f}%, Nasdaq {mkt["Nasdaq"]["change_pct"]:+.2f}%, VIX {mkt["VIX"]["price"]:.1f}. Tech breadth improved overnight.

### Information Technology
**NVDA (+{rows[0][2]:+.1f}%)** — [{nvda_news["title"]}]({nvda_news["link"]}) explains hyperscaler capex still flowing into GPU clusters.

**AMD (+{rows[3][2]:+.1f}%)** — [{amd_news["title"]}]({amd_news["link"]}) positions MI350 against Nvidia H200 in inference.

### Inference & LLM
**AAPL (+{rows[1][2]:+.1f}%)** — [{MOCK_NEWS["AAPL"][0]["title"]}]({MOCK_NEWS["AAPL"][0]["link"]}). Services mix supports margin stability.

## Market Trade Ideas
1. **Buy GOOGL** — TPU inference diversification ([Google chip story](https://www.reuters.com/technology/google-tpu-trillium))
2. **Watch AVGO** — [{MOCK_NEWS["AVGO"][0]["title"]}]({MOCK_NEWS["AVGO"][0]["link"]})

*Demo brief — mock data.*"""
    return {"content": raw}


def mock_top_picks() -> dict[str, Any]:
    raw = """# Top 5 Stocks Today

*Excludes names you already hold (NVDA, AAPL, MSFT, AMD, VOO). Demo data.*

### 1. GOOGL — Alphabet Inc.
**Niche thesis:** [Google unveils Trillium TPU to rival Nvidia inference chips](https://www.reuters.com/technology/google-tpu-trillium) — not generic "AI train"; specific silicon competing with your NVDA inference exposure.
**Trade Plan:** Allocate **4%** of portfolio (~$785). Fund by trimming **2 AMD shares** — [MI350 vs H200 story](https://www.reuters.com/technology/amd-mi350) is crowded; Google vertical integration is under-owned in your book.

### 2. AVGO — Broadcom Inc.
**Niche thesis:** [Custom AI chip orders surge from Google, Meta](https://www.reuters.com/technology/broadcom-custom-ai) — ASIC + networking, not GPU duplicate.
**Trade Plan:** **3%** allocation. No sell required if you execute GOOGL trim first.

### 3. CRM — Salesforce
**Niche thesis:** [Agentforce adoption beats targets](https://www.reuters.com/technology/salesforce-agentforce) — enterprise AI monetization distinct from MSFT Dynamics overlap.
**Trade Plan:** **2%** — small starter; complements MSFT without doubling cloud capex risk.

### 4. ORCL — Oracle Corporation
**Niche thesis:** OCI GPU cloud contracts gaining share from legacy enterprise DB installed base (mock metric +1.07% day).
**Trade Plan:** **2%** — diversify cloud AI away from Azure-only MSFT exposure.

### 5. META — Meta Platforms
**Niche thesis:** Ad rebound + Llama inference at scale; not held in portfolio.
**Trade Plan:** **3%** — sell signal: none today; buy on next cash inflow after GOOGL/AVGO.

```mm-meta
{"actions":[
  {"id":"p1","label":"Buy GOOGL 4% — trim 2 AMD","detail":"Fund GOOGL TPU thesis by reducing redundant semi beta","tickers":["GOOGL","AMD"],"type":"buy"},
  {"id":"p2","label":"Add AVGO 3%","detail":"Custom silicon diversification","tickers":["AVGO"],"type":"buy"}
],"watchlist_adds":[{"ticker":"ORCL","reason":"OCI GPU enterprise wedge"}]}
```"""
    return parse_ai_response(raw)


def mock_explore_market(query: str) -> dict[str, Any]:
    topic = query.strip() or "semiconductors"
    raw = f"""# Market Explorer: {topic}

## Overview
Your book is **26% NVDA + 16% AMD** in mock data — direct {topic} exposure without equipment or networking names.

## Biggest Players

| Rank | Ticker | Price | Day | Role |
|-----:|--------|------:|----:|------|
| 1 | NVDA | $132.45 | +1.8% | GPU training leader |
| 2 | AMD | $156.20 | +2.1% | MI300/MI350 accelerators |
| 3 | AVGO | $168.40 | +1.6% | Custom ASIC + networking |

## Trends & Catalysts

**Export controls / China supply chain** — This matters because advanced GPU exports to China remain restricted, forcing supply chain rerouting and benefiting domestic Chinese alternatives while tightening accessible TAM for US semi vendors. Read: [US tightens AI chip export rules](https://www.reuters.com/technology/us-chip-export-rules) (mock link for demo). **NVDA/AMD** revenue mix with China exposure is the transmission channel to your holdings.

**Custom silicon shift** — [{MOCK_NEWS["AVGO"][0]["title"]}]({MOCK_NEWS["AVGO"][0]["link"]}) — hyperscalers designing own chips reduces long-term GPU share; relevant to sizing NVDA.

## How This Relates to Your Portfolio
You are long the two most volatile {topic} names. Missing AVGO left networking/custom ASIC upside on the table today.

## Actionable Ideas
1. Hold NVDA — capex story intact ([NVDA news]({MOCK_NEWS["NVDA"][0]["link"]}))
2. Trim AMD if combined semi >25%
3. Add AVGO to watchlist — linked evidence above

```mm-meta
{{"actions":[{{"id":"e1","label":"Add AVGO to watchlist","detail":"Custom silicon catalyst with linked Broadcom article","tickers":["AVGO"],"type":"watch"}}],"watchlist_adds":[{{"ticker":"AVGO","reason":"{topic} diversification away from GPU-only"}}]}}
```"""
    return parse_ai_response(raw)


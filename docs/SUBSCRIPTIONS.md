# Market Morning — Subscription Tiers

Pricing is anchored to **what it would cost to replicate this product in raw Claude API usage**, plus the value of market-data integration, Robinhood sync, structured personas, and caching.

## Estimated API cost per generation (hosted)

Assumptions: prompt caching on static system prefixes (~90% input savings on repeat calls), typical fan-out patterns in `ai.py`.

| Feature | Model | Approx. API cost | Notes |
|---------|-------|------------------|-------|
| Morning brief | Opus 4.8 | **$0.45–0.85** | ~10 fan-out sub-calls + assembly |
| Late-day update | Sonnet 5 | **$0.04–0.08** | Single short call |
| Top 5 picks | Sonnet 5 | **$0.25–0.45** | Rank + 10 detail calls |
| Portfolio analysis | Sonnet 5 | **$0.18–0.35** | Large quant context |
| Explore deep-dive | Sonnet 5 | **$0.12–0.28** | Section fan-out |

**Power-user DIY (Claude API, daily everything):** ~$25–45/mo in inference alone, before market data, Robinhood, or your time writing prompts.

**Claude Pro ($20/mo):** Chat-only, message caps, no structured pipeline, no live quotes, no held-exclusion picks, no quant portfolio factor decomposition.

**Market Morning value:** One subscription replaces a stack of manual Opus/Sonnet sessions *and* yfinance/FinanceToolkit ingestion *and* Robinhood sync.

---

## Tiers

### Free — **Reader** ($0)

Hook tier. Enough to build a daily habit; premium analytics gated.

| Feature | Access |
|---------|--------|
| Morning brief | Daily (**shared platform cache** — one generation serves all free users) |
| Late-day update | ❌ |
| Top 5 picks | Yesterday's preview only (read-only teaser) |
| Portfolio holdings + quotes | ✅ Manual entry, live prices |
| Portfolio AI analysis | ❌ |
| Explore | 1 / month |
| Brief archive | Last 7 days |
| Robinhood sync | ❌ |
| Watchlist | Up to 15 tickers |

**Why free works economically:** Brief is amortized across all free users (~$0.50/day total, not per user).

---

### Pro — **Investor** ($22/mo · $211/yr)

Primary paid tier. Priced **above Claude Pro ($20)** because picks + portfolio AI exceed chat limits, but **below DIY API** for the same workflow.

| Feature | Access |
|---------|--------|
| Morning brief | Daily (shared cache + on-demand regen **2×/month**) |
| Late-day update | Daily |
| Top 5 picks | **Daily generation** (held-excluded) |
| Portfolio AI analysis | **4 / month** (~weekly) |
| Explore | 4 / month |
| Brief archive | 90 days |
| Robinhood sync | ✅ |
| Watchlist | Unlimited |

**Unit economics (steady Pro user):** ~$8–14/mo marginal inference → **~35–55% gross margin** at $22 before infra.

---

### Desk — **Active Trader** ($49/mo · $470/yr)

For users who would otherwise burn **$40–90+/mo** on Claude API replicating this stack daily.

| Feature | Access |
|---------|--------|
| Morning brief | Daily + **5 force regens / month** |
| Late-day update | Daily |
| Top 5 picks | Daily + **5 force refresh / month** |
| Portfolio AI analysis | **Daily auto + 5 force refresh / month** |
| Explore | **Unlimited** |
| Brief archive | Full history |
| Robinhood sync | ✅ Priority queue |
| Watchlist | Unlimited |

**Unit economics (heavy Desk user):** ~$18–28/mo marginal inference → **~45–65% gross margin** at $49.

---

## Premium gates (enforced server-side)

| Endpoint / action | Free | Pro | Desk |
|-------------------|------|-----|------|
| `POST /brief/start` (regen) | ❌ (read cache only) | 2/mo | 5/mo |
| `POST /brief/mini` | ❌ | ✅ | ✅ |
| `POST /picks/start` | ❌ | ✅ daily | ✅ + refresh |
| `GET/POST /portfolio/analysis*` | ❌ | 4/mo | daily + refresh |
| `POST /explore/start` | 1/mo | 4/mo | unlimited |
| `POST /portfolio/sync-robinhood` | ❌ | ✅ | ✅ |

Portfolio **holdings view** (`GET /portfolio`) stays free so users can track positions without paying.

---

## Stripe price IDs

Set in `.env` (see `backend/.env.example`):

- `STRIPE_PRICE_PRO_MONTHLY` / `STRIPE_PRICE_PRO_YEARLY`
- `STRIPE_PRICE_DESK_MONTHLY` / `STRIPE_PRICE_DESK_YEARLY`

Use Stripe Dashboard test mode for development. Webhook: `POST /billing/webhook`.

---

## Local vs SaaS mode

| Mode | `SAAS_MODE` | Auth | Billing |
|------|-------------|------|---------|
| Mac app (default) | `false` | None | N/A — user’s own `ANTHROPIC_API_KEY` |
| Hosted standalone | `true` | JWT / magic link | Stripe subscriptions |

Mac app behavior is unchanged when `SAAS_MODE=false`.

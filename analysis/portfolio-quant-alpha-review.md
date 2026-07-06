# Portfolio Quant Actions — Alpha Review

**Reviewer stance:** Senior quantitative trader evaluating the app's portfolio "Quant Actions" as if they were signals proposed for a real book.
**Date of review:** 2026-07-05 (analysis run stamped `2026-07-06T01:27:50Z`).
**Repo:** `/Users/guanchen/Projects/market-morning` · **Backend:** FastAPI `http://127.0.0.1:8742` (confirmed **non-mock**).
**Scope note:** This is a research critique of the *signal quality* of the app's output. No application source was modified.

---

## 1. Executive verdict

**There is no independent alpha in the current Quant Actions. What the app produces is a competent, well-written risk-management overlay on a single high-beta factor bet (semiconductors / AI-compute), dressed in per-name narrative.** Three of the four actions are stop/trim rules and the fourth is a buy-the-dip add — all on semis. The four actions collectively touch **56.5% of equity and are ~100% the same trade**: long-vol, high-beta semis momentum. Sized and traded literally, they would not "drive revenue"; they would mostly re-time exposure to one factor, and on a fractional-share ~$11.4k book the implied edge is smaller than the round-trip friction.

Verdict by dimension:

| Dimension | Assessment |
|---|---|
| Is it alpha or beta? | **Beta/factor tilt repackaged as per-name calls.** Weighted β ≈ **1.50**. "Alpha" language is hindsight-consistent narrative. |
| Signal independence | **Fails.** All 4 actions are semis; effective bet count ≈ 1, not 4. |
| Edge vs cost | **Marginal-to-negative** at this account size for the discretionary trims; the *risk-reduction* value (tail-avoidance on NVTS/MU concentration) is the only defensible economic benefit. |
| Signal construction | **Lagging, univariate, thresholded** (MA20/MA50/RSI14 only). No cross-sectional ranking, no vol scaling, no expected-return/cost model, no backtest. |
| False-positive control | **None.** MA-cross / RSI triggers have low base-rate precision in choppy tapes; no confirmation filter or hit-rate tracking. |
| Risk-management value | **Genuinely useful.** Concentration flag on MU (19.4%) and the busted micro-cap NVTS (2.5%, −255% net margin) are correct and actionable. |

**One-line take:** *Keep the actions as a risk overlay, stop calling them alpha, and either (a) neutralize the sector factor before ranking names, or (b) reframe the product honestly as position risk management. Right now the "quant edge" is levered exposure to one theme.*

---

## 2. Live-vs-stored data provenance

I ran the pipeline live and documented exactly what was fresh vs. stored.

| Component | Status | Evidence |
|---|---|---|
| Backend mode | **LIVE, non-mock** | `sync_robinhood` returned `synced:true` (mock mode returns `{"skipped":true,"reason":"mock_mode"}`); config `MOCK_MODE=0` in `backend/.env`. |
| Anthropic / FMP keys | **Present & working** | `.env` has both; live analysis job completed via Anthropic (`claude-*`) with real FMP quotes. |
| Portfolio quotes | **LIVE** | `/portfolio` returned real-time FMP prices (e.g., MU $975.56, NVDA $194.83) timestamped `2026-07-06T00:56Z`. |
| Portfolio analysis + Quant Actions | **LIVE, generated this session** | `POST /portfolio/analysis/start?force=true` → progressed 55→70→100 → new row `analysis_date=2026-07-06`, `created_at=2026-07-06T01:27:50Z`, 4 actions. Not cached. |
| Robinhood **live re-sync (MCP)** | **BLOCKED → fell back to snapshot** | `POST /portfolio/sync-robinhood?force=true` returned `source:"snapshot"` with error `503 Service Unavailable` from the MCP proxy at `127.0.0.1:8743`. Proxy `/health` reports `"authenticated": false`. |
| Holdings themselves | **REAL** (originally MCP-synced) | 12 positions tagged `notes:"robinhood"` with fractional shares; snapshot `robinhood_positions.json` dated Jul 2. |

**What was live:** the analysis engine, the LLM call, the quotes, and the resulting Quant Actions — all generated fresh on the user's real holdings this session.
**What was stored/stale:** the *holdings list* came from the Jul 2 Robinhood snapshot because the live MCP re-pull failed. So positions may not reflect trades since Jul 2, but they are genuine Robinhood positions (not mock fixtures).

### The one blocker + exact fix
The Robinhood MCP OAuth session has expired. The local MCP proxy (`:8743`) is running but reports `authenticated:false`, so `get_accounts`/`get_equity_positions` return 503.

**User action required to get a fully-live holdings pull:** re-authenticate the Robinhood MCP proxy — trigger its OAuth login flow (redirect URI `http://127.0.0.1:8787/callback`, client name "Robinhood Trading"). Once the proxy `/health` shows `"authenticated": true`, re-run `POST /portfolio/sync-robinhood?force=true` (it will report `source:"mcp"`), then `POST /portfolio/analysis/start?force=true`. No code change needed; keys are all present.

### The book under review (live values)

| Ticker | Shares | Px | Value | Weight | Trend (vs MA20/MA50) | RSI14 | Theme |
|---|---:|---:|---:|---:|---|---:|---|
| MU | 2.263 | 975.56 | $2,207 | **19.4%** | mixed (< MA20, > MA50) | 49.0 | semis |
| AMD | 3.136 | 517.82 | $1,624 | 14.3% | ↑ above both | 54.6 | semis |
| TSM | 2.875 | 434.16 | $1,248 | 11.0% | mixed | 53.1 | semis |
| GOOG | 3.006 | 356.18 | $1,071 | 9.4% | ↓ below both | 49.8 | mega-tech |
| NVDA | 5.446 | 194.83 | $1,061 | 9.3% | ↓ below both | 40.4 | semis |
| VRT | 2.487 | 300.53 | $747 | 6.6% | ↓ below both | 50.6 | AI-infra |
| UBER | 10.0 | 74.43 | $744 | 6.5% | ↑ above both | 59.3 | mobility |
| AIP | 18.883 | 35.06 | $662 | 5.8% | ↓ below both | 46.9 | semi-IP |
| SPCX | 4.0 | 162.00 | $648 | 5.7% | no data | — | space |
| MRVL | 2.244 | 245.29 | $550 | 4.8% | mixed | 42.3 | semis |
| SOFI | 29.274 | 18.24 | $534 | 4.7% | ↑ above both | 66.1 | fintech |
| NVTS | 20.0 | 14.46 | $289 | 2.5% | ↓ below both | 25.6 | semis |

Equity ≈ **$11,386**; cash ≈ **$1,278** (+$2,000 pending) → ~11–28% dry powder.
**HHI = 0.108 → effective N ≈ 9.3 by name**, but by *factor* the book is close to a single position. **Semis = 67.1% of equity; broad AI-theme = 83.1%. Weighted β ≈ 1.50** (≈1.35 including cash drag). **8 of 11** names with data are below their 20-day MA.

---

## 3. Per-action alpha teardown

For each action I state the implied trade, horizon, the metric that fires it, the estimated edge, the cost hurdle, and the honest verdict. Friction assumptions for a retail Robinhood fractional-share account: commission $0, but effective **spread + slippage ≈ 3–8 bps** on these large-cap names (worse for NVTS/AIP/SPCX micro/low-liquidity), plus **short-term tax drag** — this is the dominant cost, since trims of >300% winners in a taxable account realize gains taxed up to ~40% federal+state. Tax is the real "transaction cost" here.

### Action 1 — **Trim MU** (severity 1)
- **Implied trade:** sell part of a +320%, 19.4%-weight position on a confirmed break below MA50 ($852). Horizon: open-ended risk reduction.
- **Signal firing it:** concentration (weight) + `price < MA20` + conditional `MA50 break`. RSI 49 neutral.
- **Edge:** This is **not an alpha signal, it's a risk-budget signal** — and a correct one. A single name at 19.4% with 4x embedded gain is a variance and gap-risk problem. Expected *return* edge from timing the trim is ~0; expected *risk-adjusted* benefit is real (cuts idiosyncratic + sector variance).
- **Cost hurdle:** Highest of the four. Trimming a +320% position in a taxable account realizes a large short/long-term gain — the tax drag likely exceeds any drawdown you'd avoid unless MU truly rolls over. The action does not weigh this.
- **Verdict:** **Right risk call, incomplete economics.** Correct to flag; the "trim on MA50 break" trigger is a reasonable disaster-avoidance rule but says nothing about alpha. Missing: tax-aware sizing and whether to hedge (buy puts / collar) instead of realizing gains.

### Action 2 — **Set stop NVDA $185** (severity 2)
- **Implied trade:** stop-loss exit if NVDA breaks $185 (below MA20 $203 / MA50 $210, RSI 40.4). Horizon: days–weeks.
- **Signal:** dual MA breakdown + RSI < 50 (trend-following exit).
- **Edge:** Momentum-exit signals have **weak, regime-dependent precision.** In a trending bear leg, a stop below support avoids the left tail — positive expectancy. In a choppy/mean-reverting tape (VIX 16, "calm" per the brief), sub-support stops are **whipsaw generators**: you sell the low and the name reclaims. NVDA is the book's highest-beta mega-name (β≈1.9); its "momentum loss" is ~90% market/semis beta, not NVDA-specific alpha.
- **Cost hurdle:** Low direct cost, but **high opportunity cost / false-positive risk**: base rate of a clean $185 break *continuing* to $170 (vs. bouncing) in a low-VIX regime is roughly coin-flip. No confirmation filter (e.g., close-below + volume, or 2-day hold) is applied.
- **Verdict:** **Reasonable protective stop, zero alpha, meaningful whipsaw risk.** It's a beta-timing rule on the most beta name.

### Action 3 — **Exit / hard-stop NVTS $12.50** (severity 3)
- **Implied trade:** exit the busted 2.5% micro-cap (RSI 25.6, price 32% below both MAs, operating margin −195%, negative ROE).
- **Signal:** full technical breakdown + no fundamental floor.
- **Edge:** **The most defensible action in the set.** This is not alpha either — it's **cutting a value-trap / quality-short candidate** you happen to be long. Negative-margin micro-caps in downtrends have fat left tails; removing it improves the book's quality factor and truncates a −40% air-pocket. Small dollar amount ($289), so the *portfolio* impact is minor, but the decision is correct.
- **Cost hurdle:** NVTS spread/slippage is the worst in the book (low-price micro-cap), but on $289 the friction is trivial vs. the tail avoided.
- **Verdict:** **Correct and cheap. Keep.** Caveat: RSI 25.6 "oversold" is *also* the classic dead-cat-bounce zone — the action correctly resists bottom-fishing, but a systematic version should short/avoid, not wait to be stopped at $12.50 after already being 32% below the MAs (the signal is late).

### Action 4 — **Add AMD/TSM on pullback to MA50** (severity 4)
- **Implied trade:** deploy the $1,278 cash into AMD (MA50 $460) or TSM (MA50 $419) on a dip. Horizon: swing (weeks).
- **Signal:** `price > MA20 and > MA50` (uptrend) + healthy RSI → buy-the-dip within trend.
- **Edge:** This is a **momentum + buy-the-dip factor tilt** — a real, documented risk premium, but **not proprietary alpha**, and it **adds to the exact factor the book is already 67% exposed to.** From a portfolio construction view this is the *worst* of the four: it increases concentration and beta rather than diversifying. Expected edge = the semis-momentum premium minus the extra tail you're taking by doubling down.
- **Cost hurdle:** Low friction, but high *marginal risk* cost — you're spending diversification, not just cash.
- **Verdict:** **Directionally fine as a trade, poor as portfolio advice.** Adding semis to an 83%-AI-theme book is concentration-accretive. A quant desk would size this to *sector-neutralize*, not amplify.

### Aggregate teardown

| # | Action | Type | Names | β of target | Alpha? | Keep? |
|---|---|---|---|---:|---|---|
| 1 | Trim MU | risk/concentration | MU (19.4%) | 1.35 | No (risk mgmt) | Yes, tax-aware |
| 2 | Stop NVDA $185 | momentum exit | NVDA (9.3%) | 1.90 | No (beta timing) | Conditionally |
| 3 | Exit NVTS $12.50 | quality/tail cut | NVTS (2.5%) | 2.00 | No (tail cut) | **Yes** |
| 4 | Add AMD/TSM dip | momentum add | AMD+TSM (25.3%) | 1.2–1.75 | No (factor tilt) | **No / resize** |

---

## 4. Cross-action correlation & factor analysis

This is where the "4 independent quant ideas" framing breaks down.

- **All four actions are semiconductor names.** MU, NVDA, NVTS, AMD, TSM are the underlyings. They touch **56.5% of equity** and share the dominant risk factors: AI-capex sentiment, memory/logic pricing cycle, rate-driven multiple compression, and Taiwan/geopolitics for the fabs.
- **Pairwise realized correlation among these is high** (typically 0.6–0.85 for large-cap semis in the same cycle). So "Trim MU," "Stop NVDA," "Exit NVTS," and "Add AMD/TSM" are **not four bets — they are one bet (semis beta) sliced by name.** Two of the actions (trim/stop) *reduce* semis exposure and one (add) *increases* it, so the net factor tilt is partially self-cancelling — the actions are internally arguing with each other about the same factor.
- **Effective independent bets ≈ 1.** With HHI 0.108 the by-name diversification looks like ~9 names, but on a factor basis the book collapses toward a single semis position. A drawdown in AI-capex sentiment hits MU + NVDA + AMD + MRVL + TSM + NVTS + AIP + VRT simultaneously.
- **The one genuinely orthogonal action would be about the non-semis sleeve** (SOFI = rate/credit factor, UBER = consumer/mobility, GOOG = mega-cap quality, SPCX = idiosyncratic space). The engine surfaced **zero** actions there, even though SOFI at RSI 66 (near-overbought, rate-sensitive) and the SPCX no-data position are the most *information-additive* places to have an opinion.

**Factor decomposition (estimated):** of the book's variance, roughly **75–85% is explained by a single "AI/semis-beta" factor**; residual idiosyncratic variance is small. The actions operate almost entirely inside that factor. **Conclusion: the app is measuring and acting on beta while labeling it alpha.**

---

## 5. Metric methodology — what a quant desk actually looks at (with formulas)

The app currently uses **only** these inputs (verified in `finance.py`): `MA20`, `MA50`, `RSI14`, 52-week high/low, `above_ma20/50` flags (from yfinance 1y), plus latest-row profitability/valuation ratios and a single weekly volatility scalar (FinanceToolkit). There is **no** correlation matrix, beta, Sharpe/Sortino, factor model, expected-return model, or transaction-cost model anywhere in the pipeline — the "correlation/diversification" language in the output is LLM prose, not computed.

Here is the metric set a desk would require before treating any action as a signal, and *why*:

**1. Expected net edge per trade (the gate every signal must pass)**
\[
E[\text{net}] = p\cdot W - (1-p)\cdot L - (\text{spread} + \text{slippage} + \text{fees} + \text{tax})
\]
Why: a signal with positive raw hit rate can still lose money after friction. On a $11k taxable book, the tax term dominates trims of large winners. **The app never estimates this.**

**2. Hit rate & payoff asymmetry (win/loss geometry)**
\[
\text{Expectancy} = p\cdot \text{avg win} - (1-p)\cdot \text{avg loss}, \qquad \text{Payoff ratio} = \frac{\text{avg win}}{\text{avg loss}}
\]
Why: trend-following stops (Actions 2–3) are *low-p, high-payoff* (many small whipsaws, rare big saves); trims (Action 1) are the opposite. You must know the geometry to size. **Not tracked.**

**3. Risk-adjusted return of the *signal*, not the stock**
\[
\text{Sharpe}=\frac{E[r]-r_f}{\sigma},\quad
\text{Sortino}=\frac{E[r]-r_f}{\sigma_{\text{down}}},\quad
\text{IR}=\frac{\alpha}{\text{tracking error}}=\frac{E[r-r_b]}{\sigma(r-r_b)}
\]
Why: **Information Ratio is the acid test for alpha** — return *in excess of the benchmark* (here SOXX/SMH for semis) per unit of active risk. A semis-momentum rule can have a great Sharpe purely from being long a bull market (beta), yet an IR near 0 vs. SOXX. **This is the single most important missing metric.** Compute every action's return net of its sector ETF.

**4. Factor exposures (is the alpha just beta?)**
\[
r_i - r_f = \alpha_i + \beta_{\text{mkt}}\text{MKT} + \beta_{\text{mom}}\text{MOM} + \beta_{\text{val}}\text{HML} + \beta_{\text{size}}\text{SMB} + \beta_{\text{qual}}\text{QMJ} + \beta_{\text{lowvol}}\text{BAB} + \epsilon
\]
Why: regress the action's PnL on factor returns. If \( \alpha \approx 0 \) and \( \beta_{\text{mom}}, \beta_{\text{mkt}} \) are large-and-significant, the "signal" is repackaged momentum/beta. This book's actions would load heavily on MKT + MOM + (negative) BAB (high-beta). **Not computed.**

**5. Correlation / redundancy across signals**
\[
\text{Effective bets} = \frac{1}{\sum_i w_i^2}\ \text{(names)} \quad\text{vs.}\quad \text{PCA on return covariance (factors)}
\]
Why: to know whether 4 actions are 4 bets or 1. Here PCA would show one dominant eigenvector (semis). **Not computed** (HHI I computed manually = 0.108; factor-effective ≈ 1).

**6. Signal decay / holding-period sensitivity**
\[
\text{IC}(h) = \text{corr}(\text{signal}_t,\ r_{t\rightarrow t+h})
\]
Why: MA-cross signals decay fast and are horizon-sensitive; you must know the half-life to set exits. **Not modeled** — stops are static price levels with no time stop.

**7. False-positive / base-rate control on the triggers**
\[
\text{Precision} = \frac{\text{true breakdowns}}{\text{true} + \text{false breakdowns}}
\]
Why: "close below MA50" and "RSI<30" have modest precision in range-bound tapes. A desk adds confirmation (volume, multi-day close, ATR-scaled buffer) and tracks realized precision. **None present** — a single-print break fires the action.

**8. Volatility scaling / position sizing**
\[
w_i \propto \frac{1}{\sigma_i}\ \ (\text{risk parity}), \qquad \text{stop distance} = k\cdot \text{ATR}_i
\]
Why: NVTS (β≈2) and MU (β≈1.35) should not carry the same stop logic or the same dollar risk. The app sets stops at ad-hoc price levels, not ATR-scaled, so risk-per-trade is inconsistent. **Not scaled.**

**9. Capacity & liquidity** — irrelevant at $11k, but the framework should flag that NVTS/AIP/SPCX stops can gap through the level (low liquidity), making the "stop at $X" unreliable. **Not flagged.**

**10. PnL attribution (timing vs. drift)** — decompose realized PnL into market drift, sector, factor, and residual timing to see if the *actions* added anything beyond holding. **Not done.**

**Summary:** the app has steps 0 of these 10. It computes lagging trend descriptors and lets the LLM narrate. That's a *screening/monitoring* layer, not a *signal* layer.

---

## 6. Industry-by-industry: how the signal set and risk model must change

A senior quant does **not** apply the same MA/RSI template across sectors — the information content of a technical signal, and the dominant risk factor, differ sharply by industry. The app applies one identical template to all 12 names, which is its second-biggest flaw after the beta/alpha confusion.

| Sector (holdings) | Dominant risk factor | Do technicals work? | Signals a quant would actually use | Risk model change |
|---|---|---|---|---|
| **Semis — cyclical/logic/memory** (NVDA, AMD, MRVL, MU, TSM, NVTS, AIP) | AI-capex cycle, memory/logic pricing, hyperscaler capex, HBM supply, Taiwan geopolitics; **high beta (1.2–2.0)** | **Yes, but momentum-heavy & regime-dependent** — semis trend hard then crash; MA/RSI have signal *in trends*, whipsaw in ranges | Momentum + earnings-revision breadth, capex/HBM order signals, book-to-bill, days-of-inventory, hyperscaler capex guides; cross-name **relative strength vs. SOXX** (not absolute) | Sector-neutralize; vol-scale (β up to 2); model the *cycle* regime; treat as ONE factor for sizing |
| **Memory specifically** (MU) | Commodity DRAM/NAND price cycle — **deeply cyclical, mean-reverting on multiples** | Partial — price momentum works late-cycle, but valuation (P/FCF 192x flagged) matters more at turns | Contract price trends, inventory, capex/FCF conversion (app *did* catch thin FCF), cycle position | Expect mean-reversion; trims into strength are structurally right for memory |
| **Mega-cap quality** (GOOG) | Earnings durability, ad cycle, AI-capex-as-cost, rate-driven duration | Weak — quality names grind; MA crosses are noise | Quality (ROE 35%, margin), FCF, estimate revisions, reasonable multiple; low technical weight | Low vol, low active risk; buyable on weakness — the app's own text says this but still had no action |
| **AI-infra / data-center power** (VRT) | Derivative of the *same* AI-capex factor as semis — **not a diversifier** | Momentum works but correlated to semis | Order backlog, data-center capex, book-to-bill | Bucket WITH semis for factor exposure, not as "non-semi offset" |
| **Fintech** (SOFI) | **Rate sensitivity / yield curve, credit spreads, loan growth, deposit beta** | Momentum works but is driven by *rate* news, not chart | NIM, charge-offs, credit spreads, curve steepness, deposit growth, book value; **rate beta** | Different factor model entirely (rates/credit, not AI-capex); RSI 66 overbought is a *rate-trade* readout |
| **Mobility / consumer platform** (UBER) | Consumer demand, take-rate, gig regulation, fuel; moderate beta | Moderate — trend signals OK, event risk from regulation | Bookings growth, take-rate, FCF inflection, reg headlines | Consumer-cyclical factor; idiosyncratic reg risk needs event overlay |
| **Space / long-duration thematic** (SPCX) | Idiosyncratic program/contract risk, cash burn, financing risk | **Low** — "no MA/RSI data," thin history; technicals near-useless | Contract wins, cash runway, dilution risk, program milestones | Treat as venture-like; size tiny; ignore chart, watch financing |
| **Biotech/pharma** (none held, but the methodology asks) | **Binary catalyst/event risk** (trial readouts, FDA/PDUFA dates) | **Technicals are actively misleading** — price gaps 40–80% on binary events; MA/RSI meaningless pre-catalyst | Catalyst calendar, probability-of-success, cash runway, event-vol (implied move) | Event-driven risk model; position for the *distribution* (options), never chart-based stops |
| **Energy** (none held) | **Commodity beta (oil/gas), mean-reverting** | Mean-reversion > momentum; different sign than semis | Crude curve, inventories, breakevens, backwardation | Mean-reversion model, commodity factor, not trend-following |

**The core methodological point:** the *same* RSI-30/MA-cross rule means different things in different sectors. RSI 25 on a memory name (MU) = potential cycle bounce; RSI 25 on a negative-margin micro-cap (NVTS) = broken and stay-broken; RSI 25 on a biotech = irrelevant vs. a pending trial. A quant swaps the **signal set** (add rate/credit factors for financials, catalyst calendars for biotech, commodity curves for energy) and swaps the **risk model** (vol-scaling, event-vol, mean-reversion vs. momentum) per sector. The app does none of this — one template, twelve names.

---

## 7. Recommendations to make the actions actually alpha-generative

Two layers: prompt-level (cheap, immediate) and data-level (the real fix). Ordered by impact.

### Data-level (this is where the alpha would come from)
1. **Compute a factor/beta decomposition and report Information Ratio vs. the sector ETF.** Regress each action's implied PnL on SMH/SOXX (and MKT/MOM). Only surface an action as "alpha" if residual α is positive after removing sector beta. This single change would correctly reclassify today's 4 actions as "risk management," not alpha.
2. **Add a real correlation/covariance matrix and PCA "effective bets" metric.** Feed the LLM the actual pairwise correlations so it can't call four semis trades "four independent ideas." Enforce that surfaced actions span *distinct* factors.
3. **Build a transaction-cost + tax model.** Net every proposed trade by spread/slippage (scaled by name liquidity) and realized-gain tax. Trims of large winners must show after-tax expected benefit or be replaced by a hedge (collar/put) recommendation.
4. **Vol-scale everything (ATR-based stops, risk-parity sizing).** Replace ad-hoc price stops with `k·ATR` distances so NVTS (β≈2) and GOOG (β≈1.05) carry consistent *risk*, not consistent *price* buffers. Add a **time stop** (signal decay), not just a price stop.
5. **Add confirmation filters to reduce false positives.** Require multi-day close-through + volume (or an ATR buffer) before a MA-break action fires; track realized precision/hit-rate over time and display it (a self-calibrating base rate).
6. **Sector-aware signal sets.** Route each holding to a sector template: momentum+capex for semis, rate/credit factors for financials (SOFI), catalyst-calendar/event-vol for biotech, commodity curve/mean-reversion for energy, financing-runway for pre-profit thematics (SPCX). Stop applying MA/RSI to names where it's misleading (SPCX, any future biotech).
7. **Cross-sectional ranking, not absolute thresholds.** Rank the book by relative strength / expected residual return and act on the *spread* (trim weakest-vs-sector, add strongest-vs-sector) so the net trade is sector-neutral and captures dispersion — that dispersion is the only place real alpha lives here.

### Prompt-level (immediate, in `prompts_persona.py` / `PORTFOLIO_META_INSTRUCTION`)
8. **Force factor honesty in the prompt.** Instruct the QUANT persona to explicitly label each action `beta/factor` vs. `idiosyncratic/alpha`, and to state the sector-neutral version. Ban the words "diversified/independent" unless a correlation input supports it.
9. **Require action independence.** Add a rule: "the 4 actions must span at least 3 distinct risk factors; do not surface multiple same-sector momentum calls." This alone would push the engine to finally have an opinion on SOFI/UBER/GOOG.
10. **Demand the cost/edge line per action.** Require each action to include an estimated net edge (bps) after friction and, for trims, an after-tax note or hedge alternative. If edge < cost, the persona must say "monitor, don't trade."
11. **Regime tag.** Have the persona read VIX/market context (already in `context["market"]`) and down-weight momentum-breakdown stops in low-VIX/range regimes (whipsaw risk) — which is exactly today's tape (VIX 16).

**Expected effect:** implementing 1–3 and 8–10 would transform the output from "well-written momentum narrative on a semis book" into a defensible signal that either (a) demonstrates residual alpha after beta, or (b) honestly presents itself as risk management — either of which is more valuable and more trustworthy than the current framing.

---

## 8. Appendix — verification trail

- Non-mock confirmed: `sync-robinhood` returned `synced:true` + `.env MOCK_MODE=0`.
- Live analysis: `portfolio_analyses` row `analysis_date=2026-07-06`, `created_at=2026-07-06T01:27:50Z`, 4 actions, 12,531-char content — generated this session via `POST /portfolio/analysis/start?force=true`.
- Live-blocker: MCP proxy `:8743` `/health` → `{"authenticated": false}`; `get_accounts` → HTTP 503; sync fell back to `source:"snapshot"` (real holdings, Jul 2).
- Signal set verified in source: `backend/app/finance.py::get_technicals` (MA20/MA50/RSI14/52w only) and `_fetch_ticker_fundamentals` (profitability/valuation/vol scalar). No beta/correlation/Sharpe/factor code exists.
- Quant backbone computed from live values: HHI 0.108, effective N≈9.3 (by name), semis 67.1%, AI-theme 83.1%, weighted β≈1.50, 8/11 below MA20, 4 actions touch 56.5% of equity (all semis).
- **Data-integrity catch:** the analysis headline states "Total equity value $11,711.11," but the sum of the 12 per-name values it lists is **$11,386.30** — a **$325 (2.8%) discrepancy**. The engine narrates a portfolio total that doesn't reconcile to its own position values, confirming that totals/concentration are LLM-generated prose rather than computed aggregates. A quant tool must compute these server-side and pass them in, not let the model do arithmetic.

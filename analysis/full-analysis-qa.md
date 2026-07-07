# Market Morning — Full Live Analysis QA

**Run:** Mon Jul 6 2026, ~23:00 ET (UTC-4) · backend `:8742` non-mock, `git_sha=865a8d9` · all five analyses generated **sequentially** (no parallel LLM bursts; **rate limit never tripped**).
**Method:** live generation via the real endpoints (force where supported), polled to completion; **frontend render verified by extracting the actual `app.js` pipeline** (`mdBrief/mdExplore/mdPortfolio/md/inlineMd/scrubRenderedHtml/escapeHtml/renderWatchlistAdds` + full dependency closure) into a jsc bundle and rendering the freshly-generated content — the checks below quote the *resulting HTML*, not source.
**Constraint honored:** no app source edited, no git commit. QA artifacts in `analysis/qa-artifacts/`.

> **Live-vs-static caveat:** Generation ran off-hours, so only **2 of 12** portfolio names (NVTS, SPCX) resolved a live equity quote this cycle; the rest fell back to broker-snapshot pricing. This degraded the *code-computed* portfolio quant aggregates (HHI / effective-bets / weighted-beta / sector weights) and means Explore/Portfolio use slightly different equity bases. During market hours these would resolve; I could not verify the market-hours numbers.

---

## STEP 1 — Generation results

| Type | Endpoint | Time | Size | Result |
|---|---|---|---|---|
| Brief | `POST /brief/start?force=true` → `/brief/compose-progress` | ~180s | 40,170 ch | ✅ complete |
| Picks | `POST /picks/start?force=true` → `/picks/progress` | ~240s | 9,256 ch | ✅ complete — **fell back to single-call path** (fan-out dropped) |
| Explore | `POST /explore/start {"market":"semiconductors"}` | ~200s | 27,186 ch | ✅ complete — **Key-Metrics section truncated mid-sentence** |
| Portfolio | `POST /portfolio/analysis/start?force=true` | ~240s | 12,585 ch | ✅ complete — quant aggregates degraded (2/12 live quotes) |
| Late-day | `POST /brief/mini` | ~14s | 1,181 ch | ✅ complete — clean |

Notes: No endpoint errored. Each heavy generation takes ~3–4 min (internal Sonnet fan-out, capped at 6 workers). The progress-snapshot payloads grow large once `result` is populated; that is expected. No `429`/overload observed anywhere.

---

## STEP 2 — Content: Quality / Cohesiveness / Accuracy

### 1. Morning Brief — *Morning Market Strategist*  → **QUALITY PASS · COHESIVENESS PASS · ACCURACY PASS**

- **Quality (PASS):** Number-anchored, non-boilerplate, correct persona. e.g. *"The VIX has slipped a further 3.59% to 15.57 … options desks are pricing this advance as low-drama grind rather than a squeeze that needs hedging."* Each industry runs the mandated chain, e.g. IT: *"NVDA is the direct read-through on the Kyber delay; AMD, AVGO, and MRVL trade on the 'revenge trade' … TSMC (TSM) sits at the center of the manufacturing snag"* → **Market trades:** *"argues against chasing NVDA at current levels … TSM remains the highest-conviction name if the delay is fab-capacity-driven."*
- **Cohesiveness (PASS):** All **8 industries present** (Information Technology, Financials, Consumer Cyclicals, Healthcare, Energy, Inference & LLM, Startup & Venture News, Geopolitical Trades) + Overnight context + **Market Trade Ideas** (5, numbered) + **Watchlist Mentions**. VIX 15.57 / S&P 7,537.43 stay consistent across sections. News→impact→tickers→trades chain followed in every section.
- **Accuracy (PASS):** Canonical H1 `# Morning Market Brief — July 7, 2026`. No portfolio/holdings content, no `mm-meta`. Every claim carries a real cited link. No invalid tickers.
- **Minor (P3):** Inconsistent label formatting *between* sections — IT/Healthcare use a block `**News**` on its own line; Financials/Energy/Inference/Startup/Geopolitical use inline `**News**— …`; and a few `**Tickers affected**` run straight into text with no separator (*"**Tickers affected** Computational drug-discovery names…"*). Cosmetic only.

### 2. Top Picks — *Buy-Side Ideas Analyst*  → **QUALITY PASS · COHESIVENESS PASS · ACCURACY PASS**

- **Quality (PASS):** High-conviction, variant-view framing with metrics + risk per name. e.g. AVGO: *"the mispricing is that it's really a hyperscaler-capex derivative … Operating margin of 40.8% and EV/EBITDA of 49.4x … Risk: EV-to-sales of 27x leaves zero room for a slowdown."*
- **Cohesiveness (PASS):** Head-to-head ranking established up front (*"Morgan Stanley is flagging a rotation away from chipmakers into hyperscalers … that's the tension I'm underwriting across this list"*), then **Top 5 Large-Cap** (AVGO, META, TSLA, ORCL, JPM) ranked 1–5 and **Top 5 Small-Cap** (LMND, ACHR, INDI, SHLS, FLNC) ranked 1–5.
- **Accuracy (PASS):** **Zero overlap with held names** (held = MU/AMD/TSM/GOOG/NVDA/VRT/UBER/AIP/SPCX/MRVL/SOFI/NVTS). References to held names are correctly framed as *portfolio context* ("the mega-cap semi names in the portfolio"), never as picks. No false "already held/substitute" narration. `mm-meta.watchlist_adds` populated (5) and consistent (AVGO/META/LMND/ACHR/FLNC). Real cited links throughout.
- **Defect (P2 — format):** Fan-out dropped → **single-call fallback**, so picks render as **bold-lead paragraphs** (`<p><strong>1. AVGO — Broadcom Inc.</strong> …`) instead of the designed `### N. Name (TICKER)` cards. 10× `<p><strong>N.` and **0** `<h3>`. Functional but loses per-pick headings/anchors/scannability.

### 3. Explore (semiconductors) — *Sector Specialist*  → **QUALITY PASS · COHESIVENESS PASS · ACCURACY PARTIAL**

- **Quality (PASS):** Deep, metric-dense per-player breakdown (NVDA/AMD/AVGO/TSM/ASML/MU) + profitability/growth/valuation/balance-sheet comparisons + portfolio-adjacency + 5 actionable ideas with triggers/invalidations. Correctly notes data anomalies (*"TSMC's headline P/E of 0.92x … distorted by ADR share-count … shouldn't be read at face value"*).
- **Cohesiveness (PASS):** Overview → Biggest Players → Key Metrics → Trends & Catalysts → How This Relates to Your Portfolio → Actionable Ideas. Ties directly to the book (*"Seven of twelve positions sit directly in the space: AIP, AMD, MRVL, MU, NVDA, NVTS, and TSM"*). `mm-meta`: 5 actions + 2 watchlist_adds (ASML, INTC), consistent with the ideas.
- **Accuracy (PARTIAL):**
  - **P1 defect — mid-sentence truncation.** The *Balance sheet strength* subsection ends: *"Qualcomm and AMD both carry modest leverage relative to their earnings power, with interest coverage"* — **sentence cut off, nothing after.** Rendered HTML: `…with interest coverage</li></ul>\n<h2>Trends &amp; Catalysts</h2>`. `strip_trailing_partial_heading` does not catch a truncated *sentence*.
  - Equity basis differs from Portfolio: Explore cites *"$11,144 tracked here"* (live-priced subset) vs Portfolio's $11,460.84 (snapshot) — internally consistent (76% = $8,436/$11,144); cross-type mismatch is a live-vs-snapshot artifact (note only).

### 4. Portfolio Analysis — *Senior Quantitative Trader*  → **QUALITY PASS · COHESIVENESS PASS · ACCURACY PARTIAL**

- **Quality (PASS):** Per-ticker Pulse with fundamentals+technicals, ATR/MA-scaled Stop/Limit per name, Factor & Alpha Decomposition, portfolio-level metrics, honest alpha discipline (*"beta and IR did not resolve this cycle … any hold decision here is a beta call, not alpha"*).
- **Cohesiveness (PASS):** Pulse → 12 per-ticker `#### TKR` subsections → Factor decomposition → Portfolio metrics; `mm-meta` Quant Actions (4, severity 1/1/2/3) span ≥3 factors (semis, memory/commodity, ai_infra, financials), all `alpha:false`, **no news citations**. 12 `positions` each with `stop_limit`. Actions cohere with prose (NVTS breakdown, MU trim, VRT re-bucket, SOFI redeploy).
- **Accuracy (PARTIAL):**
  - **Reconciles ✅** — narrated *"$11,460.84 in equity, up 36.68% on cost of $8,385.37"* == `/portfolio` totals exactly. Cash $1,277.70 + $2,000 pending == account.
  - **QUOTE INTEGRITY ✅** — *"Ten of twelve names are showing a transient quote gap this sync — snapshot values are intact and used for equity, so nothing below should be read as impaired."* No $0/-100%/wipeout/delisting anywhere.
  - **No news links ✅** (grep: zero URLs in portfolio body).
  - **P2 defect — factual mischaracterization of AIP.** Portfolio: *"#### AIP … a small **aerospace-adjacent** name mapped here under the semis template."* But **AIP is Arteris (on-chip interconnect/NoC IP)** — and Explore gets it right: *"AIP … Arteris licenses the on-chip fabric IP that underpins custom ASIC design."* **Two generation types contradict each other about a real holding**, and the Portfolio version is the wrong one.
  - **P3 defect — degraded quant aggregates.** With only 2/12 live quotes, the code-computed figures are unreliable: *"HHI reads a very low 0.0038 and effective-bets-by-name is 263.2 … distorted by the ten quote-unavailable snapshot positions"* and *"Weighted market beta shows as 0.0 in the aggregate feed … reflects the missing per-ticker beta data."* The persona **flags them as distorted** rather than asserting them, so user-facing risk is low, but the underlying `compute_portfolio_quant` numbers are garbage when live quotes are missing.

### 5. Late-Day Update — *Closing-Bell Desk*  → **QUALITY PASS · COHESIVENESS PASS · ACCURACY PASS**

- **Quality (PASS):** Short (2 tight paragraphs), quant-flavored, no boilerplate. *"the S&P 500's 0.72% push to 7,537.43 and the Nasdaq's 1.12% run to 26,121.16 are holding into the close … The VIX's slide to 15.57 hasn't reversed."*
- **Cohesiveness (PASS):** Explicitly builds on the morning read (*"keeps the 'grind, not squeeze' read intact from this morning"*).
- **Accuracy / defining requirement (PASS):** Headlines are **embedded as fluent in-sentence links**, not raw URLs / not verbatim headlines: *"…with [SpaceX-linked exposure steepening the index's beta relative to the S&P 500](…) … Layer on the seasonal tailwind from [the low-conviction rally pattern tied to Congress's summer recess](…)."* Real provided articles.

---

## STEP 3 — Frontend render correctness (quoted rendered HTML)

All checks run through the **real** extracted pipeline via `jsc`. Full renders: `analysis/qa-artifacts/{brief,picks,explore,portfolio,lateday}.html`.

### ✅ Space after EVERY colon — including colon immediately before an article `[link]` (the explicit case)
Directly tested `inlineMd` on the colon-glued-to-link form; a visible space precedes the anchor in every variant:

| Source | Rendered HTML |
|---|---|
| `News:[Chip rally](https://ex.com/a)` | `News: <a href="https://ex.com/a" …>Chip rally</a>` |
| `News: [Chip rally](https://ex.com/a)` | `News: <a href="https://ex.com/a" …>Chip rally</a>` |
| `**News:**[Chip rally](https://ex.com/a)` | `<strong>News:</strong> <a href="https://ex.com/a" …>Chip rally</a>` |
| `Impact:tickers move` | `Impact: tickers move` |
| `**Thesis:**You buy` | `<strong>Thesis:</strong> You buy` |

Negative controls preserved: `at 10:30 a 3:1 ratio` → unchanged; `https://ex.com:8080/x` → unchanged. Real-content scan: **0** occurrences of `:`-immediately-before-`<a>` in any rendered file. **PASS.**

### ✅ Spaces around bold; no glued `word**bold**`
- `positioning.**Buy** now` → `positioning. <strong>Buy</strong> now`
- `the **catalyst**drives it` → `the <strong>…catalyst…</strong> drives it`
- Real files: **0** stray literal `**` across brief/picks/explore/portfolio/lateday. **PASS.**
- Edge **FAIL (P3):** a *lone unmatched* `**` right before a link leaks: `gain**[link](…)` → `gain**<a …>link</a>`. Rare malformed input only.

### ✅ No placeholder / artifact leakage
Scanned all five rendered files for `@@TERMSLOT`, `@@TERM`, `@END@`, `@@FENCE`, `@@H4`, `@@TERMPROT`, `<term>`, `ThinkingBlock`, `mm-meta` → **all zero**. **PASS.**

### ✅ Ordered lists render as real bold-numbered `<ol>`; em-dash labels spaced
- `1.**Trim NVDA** …\n2.**Add TSM** …` → `<ol><li><strong>Trim NVDA</strong> …</li><li><strong>Add TSM</strong> …</li></ol>`
- Real: Brief *Market Trade Ideas* → `<ol><li><strong>Trim/Avoid Solstice…</strong>…`; Explore *Actionable Ideas* → `<ol><li><strong>Trim/Take profits on AMD…</strong>…`.
- Em-dash: `chips affected—tickers move` → `chips affected — tickers move`; `**Tickers affected**—NVDA` → `<strong>Tickers affected</strong> — NVDA`; numeric range kept: `2024—2025` → `2024—2025`. **PASS.**

### ✅ Links: single `&amp;`, well-formed anchors; late-day fluent
- `[go](https://ex.com/x?g=1&mod=rss&z=2)` → `href="https://ex.com/x?g=1&amp;mod=rss&amp;z=2"` (single `&amp;`, no `&amp;amp;`).
- Real files: **0** `&amp;amp;`, **0** non-https hrefs, all anchors `target="_blank" rel="noopener noreferrer"`.
- Late-day: two fluent embedded anchors (SpaceX-vol, Congress-recess). **PASS.**
- Note (P3, informational): scheme gate is `^https?://` so a plain `http://` link *would* be allowed (none appear in content); `javascript:` is neutralized but leaves a stray `)` (`[x](javascript:alert(1))` → `x)`). No XSS.

### ✅ No mm-meta fence / truncation in rendered body; canonical H1; glossary first-occurrence; clean tickers
- Brief H1: `<h1>Morning Market Brief — July 7, 2026</h1>`. **PASS.**
- No unclosed/duplicated ```` ```mm-meta ```` fence in any body. **PASS.**
- Glossary dedup (document-scoped): `RSI is high. Later RSI again and RSI more.` → only the **first** RSI is a `<span class="glossary-term">`; repeats plain. **PASS.**
- Worth-watching tickers clean: `renderWatchlistAdds` for LMND/ACHR → `<div class="watch-add-ticker">LMND</div>` (no `LM LMND` splitting). **PASS.**

### ❌ FAIL (P2, systemic) — `-**bold**` unordered bullets collapse into one run-on paragraph with literal dashes
Model emits list items as `-**Label**—…` (dash glued to `**`, **no space**). `mdInner`'s list test requires `- ` (a space), so these are **not** treated as list items; consecutive items merge into one `<p>` and the literal `-` renders glued to the bold.

**Brief → Watchlist Mentions (rendered):**
```
<p>-<strong>Element Solutions (ESI)</strong> — the counterparty … post-separation <a …>…</a>. -<strong>Netflix (NFLX)</strong> — sliding … <a …>…</a>, <a …>…</a>. -<strong>Merck (MRK)</strong> — flagged …</p>
```
**Explore → How This Relates to Your Portfolio (rendered):**
```
<p>-<strong>Compute/GPU:</strong> NVDA ($1,065, +7.2%) and AMD ($1,731, +39.6%) … not offsetting. -<strong>Memory:</strong> MU ($2,228, +324%) is th…
```
Three brief watchlist names and five explore layer-bullets each collapse into a single wall-of-text paragraph with leading `-` glued to the ticker. (Contrast: the renderer *does* fix the ordered-list analog `1.**` → `1. `, but has no equivalent for `-**` / `*` unordered markers.)

---

## Prioritized defect list (P0→P3) with source

**P0 (blocker):** none. No crash, no data corruption, no XSS, no false-holdings, no $0/-100% wipeout, no placeholder leakage.

**P1 — content integrity**
1. **Explore Key-Metrics section truncates mid-sentence** ("…with interest coverage" → nothing) and ships to the user.
   - Source: `backend/app/ai.py` — explore fan-out `metrics` section (`MAX_TOKENS_EXPLORE_SECTION = 2400`) and/or model early-stop; `review_gate.strip_trailing_partial_heading` only removes partial *headings*, not partial *sentences*. Consider a trailing partial-sentence trim and/or higher token cap for the metrics section.

**P2 — visible quality/consistency**
2. **`-**bold**` unordered bullets collapse into a run-on paragraph with literal dashes** (Brief *Watchlist Mentions*; Explore *How This Relates to Your Portfolio*).
   - Render source: `extension/dist/app.js` `mdInner()` (~L1260 list detection). It already normalizes `^(\s*\d+)\.(?=[^\s\d]) → "$1. "` (L1219); add the unordered analog, e.g. normalize `^(\s*[-*])(?=\*\*|\[|\w) → "$1 "` before block parsing.
   - Generation source: `backend/app/prompts.py` `brief_ideas_task()` / explore section prompts emit `-**` without the required space.
3. **Portfolio mislabels AIP as "aerospace-adjacent"** — AIP is Arteris (chip-IP); contradicts Explore.
   - Source: `backend/app/prompts.py` `portfolio_system()` + the sector-template bucket mapping (AIP "mapped here under the semis template for lack of a cleaner bucket"). Consider passing the resolved company name/sector into the portfolio context so the persona doesn't guess.
4. **Picks fell back to single-call path** → bold-lead paragraphs instead of `### N. Name (TICKER)` cards (no per-pick headings/anchors).
   - Source: `backend/app/ai.py` `_fanout_picks()` returned `None` (ranking JSON absent or <3 detail write-ups per section). Intermittent; worth logging which sub-step dropped and/or loosening the fallback threshold.

**P3 — minor / cosmetic / environmental**
5. **Portfolio quant aggregates unreliable when live quotes are missing** (HHI 0.0038, effective-bets 263.2, weighted-beta 0.0, sector weights). Persona flags them, so low user impact. Source: `backend/app/portfolio_quant.py` `compute_portfolio_quant` weighting when rows are snapshot-only. (Environmental: off-hours.)
6. **Inconsistent brief label formatting** across industries (block `**News**` vs inline `**News**—` vs `**Tickers affected** text` with no separator). Source: `backend/app/prompts.py` `brief_sector_task()`.
7. **Lone unmatched `**` before a link leaks literal `**`** (`gain**[link]`). Source: `extension/dist/app.js` `cleanupStrayAsterisks` / `spaceGluedBold`.
8. **`javascript:`/non-`https` link handling** leaves a stray `)` and permits plain `http://`. Safe (no XSS) but cosmetic/policy. Source: `extension/dist/app.js` `inlineMd` link replacer (~L1120, `^https?://` gate).
9. **Explore vs Portfolio equity basis differs** ($11,144 live vs $11,460.84 snapshot) — expected live-vs-snapshot; note only.

---

### Verdict summary

| Type | Quality | Cohesiveness | Accuracy | Render |
|---|---|---|---|---|
| Brief | PASS | PASS | PASS | PASS (P3 label cosmetics) |
| Picks | PASS | PASS | PASS | PASS body; P2 fallback format |
| Explore | PASS | PASS | PARTIAL (P1 truncation) | P2 `-**` bullets |
| Portfolio | PASS | PASS | PARTIAL (P2 AIP, P3 aggregates) | PASS |
| Late-day | PASS | PASS | PASS | PASS |

**Bottom line:** Content quality, persona fit, evidence discipline, held-exclusion, quote-integrity, equity reconciliation, and the entire colon/bold/em-dash/link/glossary/`mm-meta`/H1 render surface are all solid. The **highest-value fixes** are: **P1** the explore mid-sentence truncation, and **P2** the systemic `-**` unordered-bullet collapse (two generation types), the AIP mislabel, and the picks fan-out fallback.

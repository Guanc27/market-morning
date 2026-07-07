# Market Morning — Final QA Round (Content-Grammar + Functional + Regression)

**Date:** 2026-07-06 21:xx ET · **Backend:** live on `:8742` (rate limit clear) · **Mode:** read-only critique, no code edits, no commits.
**Fresh content under test:** `market_morning.db` (`backend/data/market_morning.db`) rows for `2026-07-07` (brief/picks/portfolio) + latest explore (`cybersecurity-software-2026-07-07`) + most-recent late-day (`daily_briefs.meta_json.mini_brief` for `2026-07-06`).

## Method — verified LIVE vs STATICALLY

- **LIVE (real render pipeline):** Extracted the actual frontend functions (`md`, `inlineMd`/`inlineMdInner`, `mdBrief`, `mdExplore`, `mdPortfolio`, `scrubRenderedHtml`, `spaceGluedBold`, `escapeHtml`, glossary/term machinery) verbatim from `extension/dist/app.js` (lines 1–1350) and ran them under `jsc` (`/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc`) against the fresh DB content. So all HTML defects below are from the **rendered** output, not the raw markdown.
- **LIVE (HTTP):** `GET /portfolio`, `/portfolio/analysis`, `/picks/today`, `/brief/landing`, `/explore/landing`, and the Origin/Host guard (curl with spoofed `Origin`).
- **STATIC:** `main.py` Origin guard code, `keychain.py` / `robinhood_mcp_oauth.py`, `ai.py` review_gate wiring, `sidepanel.html` / `styles.css` for icons/44px/reduced-motion, DB `meta_json` for portfolio mm-meta (07-07 analysis row was mid-regeneration during the run — see D4 — so the 07-06 structured meta was validated as the last complete one).
- **NOT run:** backend `pytest` suite — neither system Python nor `backend/.venv` has `pytest` installed, and installing deps is out of scope for a read-only pass. The tests exist (`test_review_gate.py`, `test_picks_scrub.py`, `test_reconcile_equity.py`, `test_ticker_validation.py`, `test_keychain_storage.py`, `test_portfolio_quant.py`) but were not executed.

---

## PASS / FAIL per area

| Area | Verdict | Notes |
|---|---|---|
| 1. Rendered grammar/formatting | **PASS w/ nits** | No `@@TERMSLOT@@`/placeholder leak, no literal `**`, no `word<strong>`/`</strong>word` glue, colons all spaced, glossary tags dedup to first occurrence, brief title canonical, no truncation, no unclosed fence. Two real defects: double-escaped `&` in hrefs (D3) + cosmetic bold-label→em-dash spacing (D5). |
| 2a. Portfolio equity reconcile | **PASS** | Live `/portfolio`: `equity_value=$11,524.46`, `return_pct=+37.44%`, snapshot fallback (all 12 holdings stale this sync → sum-of-MV=0 → falls back to broker equity). Positive, no `$0`/`-100%`. |
| 2b. Holdings ordering (return% desc, stale→null) | **PASS** | Sort at `app.js:507-515` orders by return desc, `null` (stale "—") to bottom, stable. All 12 stale this sync → all render "—". |
| 2c. Picks exclude held + real small-caps | **PASS** | Picks tickers `AVGO META ORCL JPM AMZN / LMND JOBY INDI SHLS FLNC`; ∩ held = ∅. Small-caps all real. |
| 2d. Portfolio mm-meta (4 actions, 12 positions, no news) | **PASS** | `meta_json`: 4 actions severities `[1,2,2,3]`, 12 positions (all held tickers) each with `stop_limit`, **zero** `http` links in actions/positions. |
| 2e. explore/brief mm-meta parses | **PASS** | `mm-meta` is extracted server-side into `meta_json` (stripped from served content); picks `watchlist_adds`, brief `synopsis`, portfolio actions/positions all parse as valid JSON. |
| 2f. Origin/CSRF guard | **PASS** | `Origin: https://evil.example.com` → **403** (`{"detail":"Cross-origin request rejected"}`); no-Origin/loopback/`null` → **200**; destructive `POST /portfolio/sync` w/ evil Origin → **403**. |
| 3. Regression sweep | **PASS w/ 1 data error** | All session fixes hold (see table). One picks factual error (D1) + one garble (D2) are content-generation defects, not regressions of a prior fix. |
| Late-day rendering | **PASS** | 07-06 mini renders with 2 grammatical in-sentence links, 0 raw URLs, 0 asterisks/placeholders. |
| Late-day presence (fresh set) | **FAIL/timing** | `mini_brief` is **empty** for `2026-07-07` (D4). |

---

## Prioritized defect list

### P0 — none
### P1 — none

### P2 — Correctness (should fix)

**D1. Picks falsely claims AAPL is a holding** — *source: `daily_picks` 07-07 content → served by `GET /picks/today`; render `md()`*
The ORCL write-up states AAPL is in the user's book, but current holdings are exactly `AIP AMD GOOG MRVL MU NVDA NVTS SOFI SPCX TSM UBER VRT` (12, no AAPL).
> "Return on Equity of 53.4% dwarfs every name in **your book except AAPL**."
This is a hallucinated portfolio-composition claim. Picks correctly excludes held names as *picks*, but the prose asserts a false holding. (`_scrub_picks_meta` does not catch factual claims about the book.)

**D2. Garbled sentence in Joby (JOBY) pick** — *source: `daily_picks` 07-07 content, line 28; render `md()`*
> "Up 5.06% to $8.92 on an **$8.77B market cap.68, 5.5% of the book)** — JOBY gives you adjacent aerospace-innovation torque…"
Orphan `.68,` + dangling close-paren `)` with no opening `(`. Reads like a parenthetical about SPCX's book weight whose opening got chewed off. User-visible garble; renders verbatim.

**D3. Double-escaped `&` in every href containing a query separator** — *source: render pipeline `inlineMdInner` in `app.js` (escapeHtml applied to the whole prepared string, then again inside `safeExternalHref`)*
MarketWatch bulletin URLs with `&mod=` render as `&amp;amp;`:
> `href="https://www.marketwatch.com/bulletins/redirect/go?g=1e7d756e-…&amp;amp;mod=mw_rss_bulletins"`
Counts on fresh content: **brief 2, explore 3, late-day 1** (all hrefs with a literal `&`; URLs with only `?param` are unaffected). On attribute decode the browser navigates to `…&amp;mod=…`, so the query param becomes `amp;mod`. In practice these redirect URLs still resolve (the `g=` UUID is intact and the mangled `mod` tracking param is ignored), so user impact is low — but the emitted HTML is objectively wrong and will break any link whose `&`-delimited param is load-bearing. Root cause is double HTML-escaping of the URL.

**D4. Late-day (`mini_brief`) empty for the fresh 07-07 set** — *source: `daily_briefs.meta_json` 07-07 / `GET /brief/landing`*
`GET /brief/landing` → `today.mini_brief == ""` and the 07-07 `meta_json` has only a `synopsis` key (no `mini_brief`). The most recent actual late-day is 07-06. So the late-day panel would render **empty** for the current day. If the worker was expected to regenerate late-day for the fresh set, it did not persist. (May be timing — late-day runs later in the session — but flagged because the brief regen for 07-07 did complete without a paired late-day.)
> Also observed live during the run: the `2026-07-07` **portfolio_analyses** row was deleted and not yet re-inserted (DELETE-then-INSERT regen pattern), so `GET /portfolio/analysis` returned empty (`content:"",actions:[],positions:[]`) at snapshot time. Transient regeneration artifact — the 07-06 analysis validated clean.

### P3 — Cosmetic / by-design nuance

**D5. Brief section labels render glued to the em-dash (67×)** — *source: brief content structure; render `mdBrief` → `spaceGluedBold` intentionally skips dashes*
Rendered text:
> "**Tickers affected—** Money-center and trading-heavy banks…", "**Industry impact—** A falling VIX…", "**News—** The Dow closed…", "**Market trades—** The setup favors…"
`<strong>…</strong>` is immediately followed by `—` with no separating space (67 occurrences across the brief), while a handful of other labels use a plain space (`<strong>News</strong> Tec…`). Asymmetric em-dash (space after, none before) reads slightly off and is inconsistent. Cosmetic; against a strict "spaces around every bold" reading. Not the `word**bold**word` class (that is fully clean — 0 found).

**D6. Portfolio em-dash spacing nits** — *source: portfolio 07-07 content; render `mdPortfolio`*
> "…but ATR14 did compute at **$106.03— a** very wide absolute range…" (no space before em-dash)
> "No IR/alpha computed **—beta**", "No alpha computed **—beta/venture-risk**" (~6×, no space after em-dash)
Minor typography; content-generation origin, render pipeline does not normalize dash spacing.

**D7. `review_gate.finalize` is not the path for picks or late-day** — *source: `ai.py`*
`finalize(gen_type=…)` is wired for **brief** (`ai.py:788,796`), **portfolio** (`:954`), **explore** (`:1357,1363`). **Picks** uses the deterministic `_scrub_picks_meta` (`:1187`) instead (documented in CLAUDE.md, so by-design). **Late-day** (`mini_brief`, `:822`) uses only `sanitize_ai_output(raw)` — no `review_gate.finalize`. So the literal claim "review_gate wired into all types" is 3/5 direct; picks + late-day use separate mechanisms. No leakage observed in output, but the coverage is not uniform.

---

## Session-fix regression confirmation

| Session fix | Status | Evidence |
|---|---|---|
| Scroll-redirect guards | **HOLDS** | `cancelScrollRestore()` / `safeScrollIntoView()` / `attachBriefToggleGuards` present; brief-nav jump and details-toggle both cancel in-flight restore (`app.js` ~18-28, 1352-1367). |
| No `$0`/-100% wipeout narrative | **HOLDS** | Portfolio prose: "eleven of twelve holdings did not return a live quote… a transient feed gap, **not a loss**". No `$0.00`/`-100%`/"wiped out"/"delisted" in any content (only false positives: "60-100%" takeout premium). Live `/portfolio` return `+37.44%`. |
| No "already held / Substitute" picks commentary | **HOLDS** | Grep of picks content for `already held|substitut|non-held|we (chose\|picked\|selected)` → none. |
| No pipeline/meta leakage | **HOLDS** | No `pipeline`(meta)/`JSON`/`system prompt`/`persona`/`mm-meta` leakage. Only false positives = biotech "pipeline gaps"/"late-stage pipelines". |
| Ticker validity (no `CRWDS`) | **HOLDS** | No `CRWDS`. All picks + holdings tickers are real/valid. |
| Tab-bar SVG icons | **HOLDS** | 4 main tabs each carry inline `<svg class within .tab-icon>` (`sidepanel.html:230-242`). |
| 44px touch targets | **HOLDS** | `.tab { min-width:44px; min-height:44px }` (`styles.css:562-563`) + many `min-height:44px` controls. |
| Reduced-motion | **HOLDS** | `@media (prefers-reduced-motion: reduce)` (`styles.css:2490`); `safeScrollIntoView` uses `behavior:"auto"` when reduced. |
| review_gate wired into all types | **PARTIAL** | See D7 — brief/portfolio/explore via `finalize`; picks via `_scrub_picks_meta`; late-day via `sanitize_ai_output` only. |
| Tokens in Keychain (not plaintext) | **HOLDS** | `keychain.py` uses `security` CLI `add/find/delete-generic-password`; `robinhood_mcp_oauth.py` migrates any legacy plaintext into Keychain then deletes it (write verified before delete). No `backend/data/robinhood_mcp_oauth.json` on disk. |
| Canonical brief title | **HOLDS** | Rendered `<h1>` = "Morning Market Brief — July 7, 2026". |
| Glossary tag first-occurrence only | **HOLDS** | Rendered: every `data-term` value appears exactly once per document (brief 13, picks 18, portfolio 30, explore 15 unique terms, 0 duplicates). |

---

## Bottom line

- **No P0/P1.** The pipeline hardening from this session holds across the board.
- **3 content-correctness issues worth fixing:** D1 (false AAPL holding claim in picks), D2 (garbled JOBY sentence), D3 (double-escaped `&` in hrefs — a real render-pipeline bug, low live impact).
- **1 gap:** D4 — no late-day for the fresh 07-07 set (and the 07-07 portfolio-analysis row was mid-regen at snapshot time).
- **Cosmetic:** D5/D6 dash spacing; D7 review_gate coverage nuance.

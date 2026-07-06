# Market Morning — Backend Generation Latency Analysis & ≤30s Plan

**Scope:** End-to-end wall-clock latency of the four AI generation types (morning brief, top picks, explore deep-dive, portfolio analysis) in NON-mock mode (real Anthropic + FMP/yfinance + FinanceToolkit + Robinhood MCP bridge). Read-only analysis; no source edits.

**Evidence discipline:** Every number is tagged **[MEASURED]** (with source) or **[ESTIMATED]** (with reasoning). Timing was derived from source-code pipeline analysis, backend terminal logs, DB `created_at` + `content` sizes, on-disk caches, and light read-only network probes — no heavy end-to-end LLM generations were fired (a separate worker is live on `:8742`).

---

## 0. Key evidence collected

| Signal | Value | Source |
|---|---|---|
| Brief content size | 23,064 chars (07-06), 19,250 (07-05), 31,651 (07-03) | **[MEASURED]** `daily_briefs.content` length |
| Picks content size | 10,366 chars (07-05), 10,076 (07-04) | **[MEASURED]** `daily_picks.content` length |
| Portfolio content size | 12,531 chars (07-06), 11,958 (07-05), 13,024 (07-04) | **[MEASURED]** `portfolio_analyses.content` length |
| Holdings count | 12 tickers (AIP, AMD, GOOG, MRVL, MU, NVDA, NVTS, SOFI, SPCX, TSM, UBER, VRT) | **[MEASURED]** `holdings` table |
| Research cache (today) | 8 sectors, 65 articles, 30 KB, **0** google-redirect links remaining | **[MEASURED]** `data/research_cache/2026-07-06.json` |
| Fundamentals cache | 26 tickers pre-computed | **[MEASURED]** `data/finance_cache/metrics.json` |
| FinanceToolkit fundamentals (10 tickers) | **~62 s per statement-type batch**; total elapsed 229,796 ms and **still incomplete**; Yahoo rate-limit + proxy 403 | **[MEASURED]** terminal `336792.txt` |
| Google-News RSS query fetch | 0.60 s / 145 KB per query | **[MEASURED]** probe |
| Reuters RSS feed | HTTP 401 (blocks non-browser UA) | **[MEASURED]** probe |
| Robinhood bridge `:8743` | `{"status":"ok","authenticated":false}` | **[MEASURED]** probe |
| Backend `:8742` | `{"status":"ok"}` | **[MEASURED]** probe |
| Output caps | brief 16k, picks 16k, explore 8k, portfolio 8,192 | **[MEASURED]** `ai.py:41-44` |
| Models | brief → `claude-opus-4-8`; picks/portfolio/explore/synopsis → `claude-sonnet-5` | **[MEASURED]** `config.py:14-18`, `ai.py` |
| Streaming | **None** — `messages.create` non-streaming (`ai.py:108`) | **[MEASURED]** |
| Prompt caching | **None** — no `cache_control` anywhere | **[MEASURED]** |

**Token conversion used throughout:** output content is markdown with many verbose URLs, so ~4 chars/token. Content sizes → output tokens: brief ≈ 5,800–7,900; picks ≈ 2,600; portfolio ≈ 3,100; explore ≈ 2,000–3,000.

**Assumed model throughput [ESTIMATED, industry-observed non-streaming]:** Opus-4-class ≈ **40–55 output tok/s**; Sonnet-5-class ≈ **65–90 output tok/s**; time-to-first-token (TTFT) at 8–20k input tokens ≈ 1.5–3.5 s.

---

## 1. Pipeline map + per-stage latency breakdown

Each generation runs as a background thread job (`start_async_job` → new event loop). The synchronous Anthropic call (`_chat`) blocks that worker thread for the full generation. **Note:** the direct GET endpoints `/brief/morning`, `/brief/top-picks`, `/portfolio/analysis` call the service inline and therefore **block the FastAPI event loop** for the entire LLM duration — only the `/start` + `/progress` polling endpoints are safe.

### 1A. Morning brief — `ai.morning_brief_job` → `_brief_context` (`ai.py:270-305`, `178-234`)

| Stage | Sequential/Parallel | Latency | Tag |
|---|---|---|---|
| DB gather (holdings, watchlist, chosen_actions, memory) | parallel `asyncio.gather` | 10–50 ms | **[MEASURED]** local sqlite WAL |
| **Research bundle** `force_research=force` | in `asyncio.gather` (thread) | **cached: ~5–30 ms**; **force rebuild: 10–30 s** | **[MEASURED]** cache read; **[ESTIMATED]** rebuild (8 sectors ×~9 fetches @0.6 s + redirect resolution, concurrent) |
| **Quotes for 12 holdings** `get_quotes` | in gather, but **serial per-ticker inside** | **12–36 s** | **[ESTIMATED]** `finance.py:106-138` loops `yf.Ticker().info` + `.history()` per ticker, **uncached**, Yahoo rate-limited (see log) |
| News bundle (watchlist yfinance `.news`) | in gather, serial per-ticker | 1–8 s (4 h TTL cache) | **[ESTIMATED]** `news.py:42-72` |
| Market snapshot = `get_quotes(4 indices)` | in gather, serial | 4–12 s | **[ESTIMATED]** |
| Account load | in gather | <5 ms | **[MEASURED]** file read |
| Prompt assembly (`json.dumps`) | sequential | 5–30 ms | **[ESTIMATED]** ~20–35 KB JSON |
| **LLM call (Opus, ~5,800–7,900 out tok)** | sequential | **110–180 s** | **[ESTIMATED]** 5,800–7,900 tok @ 40–55 tok/s + TTFT |
| Parse mm-meta / sanitize | sequential | <20 ms | code fact |
| Persist (sqlite + `.md`) + async synopsis (background) | sequential (synopsis off-thread) | <30 ms | `analysis_export.py`, `ai.py:329` |

Because the data fetches run concurrently, brief data-fetch wall time ≈ **max(research, quotes+snapshot)**. With warm daily research cache (the normal case, background-warmed at startup) it is bounded by the **serial yfinance quote path ≈ 15–40 s**. On `force=True` it also rebuilds research (~10–30 s, overlapped).

- **Warm-cache brief total [ESTIMATED]:** ~15–40 s data + ~110–180 s LLM ≈ **≈ 2–3.5 min**.
- Dominant term: **LLM output generation on Opus (~110–180 s).**

### 1B. Top picks — `ai.top_picks` (`ai.py:435-488`) → `_full_context`

| Stage | Seq/Par | Latency | Tag |
|---|---|---|---|
| `screen_candidates(DEFAULT_UNIVERSE=24)` | **serial** `get_quotes(24)` | 24–72 s | **[ESTIMATED]** `finance.py:310-342` |
| `screen_candidates(24, max_market_cap)` | **serial** `get_quotes(24)` **+ `yf.Ticker().info` per ticker** | +30–90 s | **[ESTIMATED]** double yfinance pass |
| `_full_context`: quotes(12) + news + research(cached) + metrics(cached) | mostly serial | 15–40 s | **[ESTIMATED]** |
| **LLM (Sonnet, ~2,600 out tok)** | sequential | **35–47 s** | **[ESTIMATED]** |
| Synopsis (`_generate_synopsis`, Sonnet 768 tok) | **sequential, inline** | +8–12 s | **[MEASURED]** `ai.py:483` blocks before return |
| Persist | sequential | <30 ms | |

- **Picks total [ESTIMATED]:** ~60–150 s data (double 24-ticker yfinance screen is the killer) + ~40 s LLM + ~10 s synopsis ≈ **≈ 2–3+ min**. This is the **slowest data-fetch path**.

### 1C. Explore deep-dive — `ai.explore_market_job` (`ai.py:496-522`)

| Stage | Seq/Par | Latency | Tag |
|---|---|---|---|
| `market_peers(query)` = `get_quotes(8)` + `portfolio_metrics(8)` | serial | 8–24 s (metrics cached → less) | **[ESTIMATED]** `finance.py:345-354` |
| `_full_context(extra_tickers=peers[:8])` | serial | 15–40 s | **[ESTIMATED]** |
| **LLM (Sonnet, cap 8k, ~2,000–3,000 out tok)** | sequential | **27–40 s** | **[ESTIMATED]** |
| Persist `.md` | sequential | <20 ms | |

- **Explore total [ESTIMATED]:** ~25–60 s data + ~30–40 s LLM ≈ **≈ 1–1.7 min**.

### 1D. Portfolio analysis — `ai.portfolio_analysis` (`ai.py:363-430`)

| Stage | Seq/Par | Latency | Tag |
|---|---|---|---|
| `_portfolio_context` quotes(12) | serial yfinance | 12–36 s | **[ESTIMATED]** |
| account + market snapshot | serial | 4–12 s | **[ESTIMATED]** |
| **`portfolio_metrics(tickers, force_refresh=force)`** | **serial per-ticker** `_fetch_ticker_fundamentals` | **cached: <1 s**; **force: 60–200 s** | **[MEASURED]** terminal 336792 (~62 s/batch, 229 s incomplete) |
| `portfolio_technicals(tickers, force)` | **parallel** ThreadPool(8) yfinance `.history(1y)` | 2–5 s | **[MEASURED]** `finance.py:412-425` (already concurrent) |
| **LLM (Sonnet, ~3,100 out tok)** | sequential | **41–51 s** | **[ESTIMATED]** |
| Persist | sequential | <30 ms | |

- **Portfolio total, cached fundamentals [ESTIMATED]:** ~20–50 s data + ~45 s LLM ≈ **≈ 1–1.5 min**.
- **Portfolio total, `force=True` (Refresh button) [ESTIMATED/MEASURED]:** fundamentals re-fetch dominates → **≈ 2–4 min** (or worse under Yahoo throttling).

---

## 2. Dominant costs & biggest wins

Ranked by leverage:

1. **LLM output-token time is the #1 cost for the brief (110–180 s) and material for the others (~35–50 s).** It scales linearly with requested words and gets *worse* as the in-flight worker raises caps to stop truncation. Opus on the brief is ~1.6× slower per token than Sonnet.
2. **Serial `get_quotes` via yfinance `.info`+`.history` (uncached).** Called for holdings, indices, and — worst — the **two 24-ticker screens in picks**. This adds 15–90 s across generations and is the biggest *data* cost. Yahoo rate-limiting (observed in logs) makes it spiky.
3. **`force=True` fundamentals refetch in portfolio.** `_fetch_ticker_fundamentals` runs **serially per ticker**, each building its own `Toolkit([ticker])` (multiple FMP/Yahoo round-trips). Measured ~62 s per statement batch, minutes total when throttled. Cache (`metrics.json`, 26 tickers) saves this on non-force runs.
4. **Inline synopsis call in picks** adds a *second* blocking Sonnet call (~10 s) before returning.
5. **No prompt caching** on the ~2,500-token static persona/instructions (re-billed and re-processed every call). Small latency effect, easy win.
6. **No streaming** → zero perceived progress; users wait the full 2–3 min with only a coarse progress bar.
7. **Research rebuild on `force`** (RSS 401/403 from Reuters etc. + Google-News redirect resolution) adds 10–30 s — but it is already daily-cached, background-warmed, and per-URL memoized, so it only bites on forced refresh.

---

## 3. The ≤30 s plan (prioritized, with expected savings & tradeoffs)

### P0 — Batch/parallelize all quote fetches (data layer)
- Replace the per-ticker `get_quotes` loop with a **single batched FMP quote call** (`/quote/AAPL,MSFT,...` accepts comma-joined symbols) or, if staying on yfinance, wrap the loop in a `ThreadPoolExecutor` (like `portfolio_technicals` already does) + add a **60 s TTL quote cache**.
- Fix `screen_candidates` to batch-quote the 24-ticker universe once and cache market caps (drop the per-ticker `yf.Ticker().info`).
- **Expected saving:** picks −60 to −120 s; brief/portfolio/explore −10 to −35 s each.
- **Tradeoff:** FMP quote quota usage; batch quote gives slightly less field coverage than `.info` (sector/industry) — fetch those from the already-cached fundamentals instead.

### P0 — Parallelize fundamentals; never serial-refetch on force
- Replace the serial `for ticker in missing: _fetch_ticker_fundamentals` loop with a `ThreadPoolExecutor`, or build **one `Toolkit(all_tickers)`** instead of N single-ticker toolkits.
- Keep `force=True` scoped to *technicals only* (15 min TTL) and let fundamentals stay on the persistent cache unless truly stale.
- **Expected saving:** portfolio `force` path −60 to −180 s.
- **Tradeoff:** slightly staler fundamentals (acceptable — they are quarterly).

### P0 — Use the warm research cache; stop forcing research per brief
- The morning brief passes `force_research=force`; on user "refresh" this rebuilds all 8 sectors. Prefer the background-warmed daily cache and refresh research on a schedule, not on the user's click.
- **Expected saving:** −10 to −30 s on forced briefs. **Tradeoff:** headlines up to ~1 day old on manual refresh (mitigated by the startup/background warm).

### P1 — Fan-out the LLM generation (the decisive win)
This is what actually gets each generation under 30 s **without truncation**:

- **Brief:** issue the 8 sector sections + the overview/trade-ideas block as **~9 concurrent Sonnet calls** (`asyncio.gather` over `to_thread`), each capped ~1,000–1,400 out tok (~500–700 words), then stitch the markdown. Wall time ≈ the single slowest call (~12–18 s) instead of 110–180 s.
- **Picks:** 2 concurrent Sonnet calls (large-cap 5, small-cap 5), ~1,300 tok each → ~18–22 s. Move synopsis generation **off the response path** (background thread, like the brief already does).
- **Portfolio:** split holdings into 2 concurrent batches (~1,500 tok each) or trim to ~2,300 tok → ~22–25 s.
- **Explore:** 2 concurrent calls (players+metrics / trends+ideas) → ~18–22 s, or trim to ~2,000 tok.
- **Expected saving:** brief −90 to −160 s; picks/portfolio/explore −15 to −25 s.
- **Tradeoff:** more concurrent API calls (watch rate limits / concurrency caps), plus stitching logic and slight cross-section redundancy risk. This also **resolves the truncation tension** (see §4).

### P1 — Switch the brief off Opus
- Set `ANTHROPIC_MODEL_BRIEF=claude-sonnet-5`. Sonnet is ~1.6× faster per token and already used for the other three types.
- **Expected saving:** brief LLM −35 to −60 s (single-call) or compounds with fan-out. **Tradeoff:** marginally less "CIO-grade" prose depth.

### P2 — Anthropic prompt caching on the static persona/instructions
- Add `cache_control: {"type":"ephemeral"}` to the ~2,500-token system block (persona + rules + section templates are identical across calls).
- **Expected saving:** ~0.5–1.5 s TTFT/call + ~90% input-token cost on the cached prefix (big cost win, modest latency win; compounds under fan-out where the same system is reused N times).

### P2 — Stream responses
- Switch to `messages.stream`; push tokens to the UI. **Cuts perceived latency to ~2 s TTFT.** Does **not** reduce total completion time (see §4).

### Concrete target config to guarantee ≤30 s

| Generation | Model | Structure | Out tok/call | Concurrency | Projected wall time |
|---|---|---|---|---|---|
| Brief | sonnet-5 | 8 sector calls + 1 overview | ~1,200 | 9 parallel | data ≤3 s + LLM ~15 s = **~18–22 s** |
| Picks | sonnet-5 | 2 section calls, synopsis async | ~1,300 | 2 parallel | data ≤3 s + LLM ~20 s = **~22–25 s** |
| Portfolio | sonnet-5 | 2 holding batches | ~1,500 | 2 parallel | data ≤3 s (cached) + LLM ~22 s = **~25 s** |
| Explore | sonnet-5 | 2 calls or 1 trimmed to ~2,000 tok | ~1,300 | 2 parallel | data ≤3 s + LLM ~18 s = **~20 s** |

Prereqs for the ≤3 s data budget: batched/cached quotes (P0), cached/parallel fundamentals (P0), warm research cache (P0).

---

## 4. What cannot hit 30 s without a product tradeoff

**A single non-streaming LLM call cannot produce a 2,500–3,500-word brief in 30 s. This is physics, not tuning.**

- 3,500 words ≈ 5,800–7,900 output tokens (**[MEASURED]** current briefs are 23k–31k chars).
- Max tokens deliverable in 30 s: Sonnet @ 80 tok/s → **2,400 tok ≈ ~1,500 words**; Opus @ 55 tok/s → **1,650 tok ≈ ~1,000 words**.
- Therefore a single-call brief in 30 s must be **≤ ~1,500 words (Sonnet)** — roughly **half** the current spec.

**Raising `max_tokens` (what the other worker is doing) does not slow generation by itself** — it is only a ceiling. The slowness *and* the earlier truncation share one root cause: **the prompt requests 2,500–3,500 words**, which is both slow to emit and prone to overrunning the old 8k cap. Maxing the cap fixes truncation but *locks in* the 110–180 s brief.

**The synthesis that satisfies both ≤30 s and no-truncation:** keep the full 2,500–3,500-word product, but produce it as **N smaller parallel calls** (§3 P1). Each call is well under its cap (no truncation) and they run concurrently (wall time = one small section, not the sum). If fan-out is not adopted, the only single-call options are: (a) **reduce the brief to ~1,500 words** (product tradeoff), or (b) **stream** and accept that full completion still takes ~90 s while the user reads from the top (perceived-latency tradeoff, not a true ≤30 s completion).

- Picks/portfolio/explore (~2,600–3,200 out tok) are **borderline** as single Sonnet calls (~35–50 s) and *do* fit ≤30 s once trimmed to ~2,300 tok or split in two.

---

## 5. Summary

- **Current per-generation latency [MEASURED sizes + ESTIMATED throughput]:** brief **≈ 2–3.5 min** (LLM-dominated, Opus 110–180 s); picks **≈ 2–3+ min** (double 24-ticker yfinance screen + 40 s LLM + 10 s inline synopsis); explore **≈ 1–1.7 min**; portfolio **≈ 1–1.5 min** cached / **2–4 min** on `force` (serial fundamentals refetch).
- **Top 5 highest-leverage optimizations:** (1) fan-out the brief into ~9 parallel Sonnet sub-calls (−90 to −160 s); (2) batch + TTL-cache quotes and kill the double 24-ticker `.info` screen in picks (−60 to −120 s); (3) parallelize/cache fundamentals, keep force scoped to technicals (−60 to −180 s on portfolio force); (4) move brief off Opus to Sonnet (−35 to −60 s); (5) move the picks synopsis off the response path + add prompt caching + streaming for perceived latency.
- **Config to guarantee ≤30 s:** all generations on `claude-sonnet-5`, fan-out to 2–9 concurrent calls of ~1,200–1,500 output tokens each, data budget ≤3 s via batched/cached quotes + cached/parallel fundamentals + warm research cache, prompt-cache the static system prefix, stream to the client.
- **Hard limit:** a single-call 2,500–3,500-word brief physically cannot complete in 30 s (needs ~90 s streaming even on Sonnet). Either fan-out (recommended) or cut the brief to ~1,500 words.

---

# Cost — LLM/API cost of ONE full run (brief + picks + explore + portfolio)

**READ-ONLY guesstimate.** A "full run" = one morning brief + one top-picks + one explore deep-dive + one portfolio analysis, plus the two secondary synopsis calls that fire automatically (brief synopsis is backgrounded; picks synopsis is inline).

## Pricing assumptions (no pricing is configured in the repo/env — grep found none)

The configured model ids are `claude-opus-4-8` (brief) and `claude-sonnet-5` (others) — confirmed `config.py:14-16`, `ai.py:77-78,417,479,510`. I don't have authoritative public prices for those exact ids, so I use **representative tier rates** (long-standing Anthropic Opus/Sonnet list prices). Recompute with the formula if your contract differs.

| Tier | Model id | Input $/Mtok | Output $/Mtok | (cache write / read) |
|---|---|---|---|---|
| Opus-tier | `claude-opus-4-8` | **$15** *(assumed)* | **$75** *(assumed)* | 18.75 / 1.50 |
| Sonnet-tier | `claude-sonnet-5` | **$3** *(assumed)* | **$15** *(assumed)* | 3.75 / 0.30 |

**Formula:** `cost = input_tok/1e6 × in_rate + output_tok/1e6 × out_rate`. Prompt caching: cached-prefix writes bill at 1.25× input, cached reads at 0.10× input. `thinking` is **disabled** (`ai.py:113`), so no reasoning tokens are billed — output = visible content only.

## Token assumptions (all **[MEASURED]** unless noted; ~4 chars/token)

- **System prompts [MEASURED via import]:** brief 1,442 tok · picks 1,160 · portfolio 1,067 · explore 1,006.
- **Slimmed research context (brief) [MEASURED]:** 22,346 bytes ≈ **5,586 tok**. Full (unslimmed) research used by picks/explore [MEASURED]: 30,325 bytes ≈ **7,581 tok**.
- **Fundamentals cache [MEASURED]:** ~1,320 bytes/ticker ≈ **~330 tok/ticker** injected.
- **Output tokens [MEASURED content sizes /4]:** brief 5,800–7,900 (expected ~6,500) · picks ~2,700 · portfolio ~3,200 · explore ~2,500 [ESTIMATED, no DB row]. Synopsis calls output ≤768 tok (`ai.py:324,360`).

| Generation | Input build | Est. input tok | Est. output tok |
|---|---|---|---|
| Brief | sys 1,442 + slim research 5,586 + portfolio/market/acct ~600 + watchlist/actions/memory ~1,000 + news ~500 + JSON ~400 | **~9,500** (8k–12k) | **~6,500** (5,800–7,900) |
| Picks | sys 1,160 + **full** research 7,581 + news+news_flat ~2,500 + metrics(held+picks ~20t) ~2,500 + candidates ~500 | **~15,000** (13k–17k) | **~2,700** |
| Explore | sys 1,006 + full research 7,581 + news+news_flat ~2,000 + peers/quotes/metrics(8) ~2,000 | **~13,000** | **~2,500** |
| Portfolio | sys 1,067 + portfolio/market ~600 + metrics(12×330) ~4,000 + technicals ~1,200 | **~7,000** | **~3,200** |
| Brief synopsis | content[:12000] ~3,000 | ~3,000 (Sonnet) | ~600 |
| Picks synopsis | content ~2,600 | ~2,600 (Sonnet) | ~600 |

Picks/explore carry the **largest input** because `_full_context` injects the *unslimmed* research bundle **plus** a flattened `news_flat` duplicate (`ai.py:262-264`).

## CURRENT cost breakdown (brief on Opus, others Sonnet, no caching)

| Generation | Model | Input tok | Output tok | Input $ | Output $ | **$ / run** |
|---|---|---|---|---|---|---|
| Brief | Opus | 9,500 | 6,500 | 0.143 | 0.488 | **0.630** |
| ↳ brief synopsis | Sonnet | 3,000 | 600 | 0.009 | 0.009 | 0.018 |
| Picks | Sonnet | 15,000 | 2,700 | 0.045 | 0.041 | **0.085** |
| ↳ picks synopsis | Sonnet | 2,600 | 600 | 0.008 | 0.009 | 0.017 |
| Explore | Sonnet | 13,000 | 2,500 | 0.039 | 0.038 | **0.077** |
| Portfolio | Sonnet | 7,000 | 3,200 | 0.021 | 0.048 | **0.069** |
| **TOTAL (expected)** | | ~52k | ~16k | | | **≈ $0.90** |

**Per-run range:** low **≈ $0.76** · expected **≈ $0.90** · high **≈ $1.15**.
**Per 1,000 runs:** **≈ $760 – $1,150** (expected ~$900).

**Biggest cost driver:** the **brief's Opus output tokens** — $0.49 of the ~$0.90 run (**~54%**). Opus output at $75/Mtok is 5× Sonnet's $15/Mtok, and the brief emits the most tokens of any generation.

## POST-OPTIMIZATION cost (brief → Sonnet + ~9-way fan-out + prompt-cached persona)

The in-flight worker's changes reshape the brief cost:
- **Model swap Opus→Sonnet:** output $75→$15/Mtok on the biggest generation — the dominant saving.
- **Fan-out (~9 concurrent sub-calls):** total *output* stays ~6,500 tok (same content, split), but *input can duplicate* if every sub-call re-sends the shared research/system. Sensible impl sends each sector only its slice (~700 tok) + a cached shared prefix.
- **Prompt caching** of the static persona/rules (~1,442 tok, identical every call): billed ~once at 1.25× write, then read at 0.10× — neutralizes most of the fan-out input duplication.

| Generation | Model | Input $ | Output $ | **$ / run** | Note |
|---|---|---|---|---|---|
| Brief (fan-out + cache) | Sonnet | ~0.034 | ~0.098 | **~0.13** | per-sector context + cached prefix |
| ↳ brief synopsis | Sonnet | | | 0.018 | unchanged |
| Picks (+cache) | Sonnet | ~0.043 | ~0.041 | **~0.085** | caching trims system re-send |
| ↳ picks synopsis | Sonnet | | | 0.017 | (move off response path recommended) |
| Explore (+cache) | Sonnet | ~0.037 | ~0.038 | **~0.075** | |
| Portfolio (+cache) | Sonnet | ~0.020 | ~0.048 | **~0.068** | |
| **TOTAL (expected)** | | | | **≈ $0.37** | |

**Post-opt per-run range:** ~$0.30 – $0.50 (expected **≈ $0.37**). **Per 1,000 runs ≈ $370.**

**Delta vs current: ≈ −$0.53/run (~−59%, 2.4× cheaper)** — almost entirely from moving the brief off Opus. Prompt caching's role is defensive: it stops the ~9-way fan-out from clawing the input cost back up. *Naive* fan-out (full research+system re-sent in all 9 calls, no caching) would push the brief input to ~63k tok (~$0.19) → brief ~$0.29 and run ~$0.55; still cheaper than today because Sonnet output is 5× cheaper, but caching + per-sector slicing is what lands it at ~$0.13.

## Secondary API costs (per run)

| Source | Basis | Marginal $/run |
|---|---|---|
| FMP (quotes/ratios) | flat subscription/quota, not per-token | **~$0 (negligible)** |
| yfinance / Yahoo | free unofficial endpoints | **$0** (cost is latency/rate-limits, not $) |
| FinanceToolkit | library over FMP/Yahoo | **$0** |
| Google News / RSS | free | **$0** |
| Robinhood MCP bridge | no per-call fee | **$0** |
| Embeddings / vector search | **none present** (grep: no `embedding`/`voyage`/vector calls; symbol search is a local index) | **$0** |

Secondary APIs are effectively free at the margin — the run cost is **~100% Anthropic tokens**.

## Key caveats

1. **Prices are representative assumptions**, not from the repo (none configured) and not verified against the exact `opus-4-8` / `sonnet-5` ids — re-derive with the formula if your rates differ.
2. Token counts are `chars/4` approximations; the real tokenizer can differ ±~15%.
3. Input scales with **watchlist size and holdings count** (12 holdings measured; watchlist assumed small). More holdings → more fundamentals/technicals tokens (portfolio input especially).
4. If the worker injects `portfolio_quant.py` factor/correlation output into the portfolio prompt, portfolio input tokens rise (correlation matrix + factor decomposition) — not in the path measured here.
5. Post-opt brief figure assumes a *sensible* fan-out (per-sector context + cached prefix). A naive fan-out without caching roughly doubles the brief cost (shown above).

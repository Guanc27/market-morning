const API = "http://127.0.0.1:8742";
const PORTFOLIO_CACHE_KEY = "mm_portfolio_cache";
const BRIEF_CACHE_KEY = "mm_brief_cache";
const PICKS_CACHE_KEY = "mm_picks_cache";
const EXPLORE_STORE_KEY = "mm_explore_store";
const EXPLORE_LANDING_KEY = "mm_explore_landing_v2";
const NETWORK_RETRY_DELAYS_MS = [400, 800, 1500, 2500, 4000];
const OFFLINE_MSG = "Can't reach Market Morning right now";
const OFFLINE_HINT = "The app may still be starting — give it a moment and try again.";
const RECONNECT_MSG = "Reconnecting…";
const RETRY_BUSY_MSG = "Still waking up — trying again…";
const APP_VERSION = "0.1.50";

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function safeScrollIntoView(el, opts = {}) {
  if (!el) return;
  // Kill any in-flight tab/subtab restore or animate loop first so it can't
  // re-assert a stale position a frame after this intentional scroll (error
  // banner reveal, brief nav jump).
  cancelScrollRestore();
  el.scrollIntoView({
    block: opts.block || "nearest",
    behavior: prefersReducedMotion() ? "auto" : opts.behavior || "smooth",
  });
}

function safeExternalHref(raw) {
  const href = String(raw || "").trim();
  if (!/^https?:\/\//i.test(href)) return null;
  return escapeHtml(href);
}

// Ping the native macOS shell so it can bounce the Dock icon when a background
// generation finishes while the app isn't focused. No-ops in a plain browser.
function pingGenerationDone(kind) {
  try {
    window.webkit?.messageHandlers?.ping?.postMessage({ type: "generation-done", kind });
  } catch {
    /* not running inside the native WKWebView — ignore */
  }
}

let tab = "brief";
let picksSubTab = "today";
let exploreSubTab = "explore";
let briefSubTab = "today";
let portfolioSubTab = "analysis";
let portfolio = null;
let portfolioAnalysis = null;
let portfolioTickerSections = {};
let activeHoldingModalTicker = null;
let holdingModalPrevFocus = null;
let picksCache = null;
let picksMeta = null;
let exploreCache = {};
let yesterdayPicksData = null;
let yesterdayPicksExpanded = false;
const _logoReady = new Set();
const watchlistTickers = new Set();
const watchlistPending = new Set();
let archiveSelectedDate = null;
let portfolioAnalysisRunning = false;
let briefGenerating = false;
let picksLoading = false;
let exploreRunning = false;
let miniBriefLoading = false;
let backendOnline = false;
let healthInfo = null;
let briefLandingMeta = null;
const tabErrors = { brief: "", picks: "", explore: "", portfolio: "" };
const tabRetryFns = { brief: null, picks: null, explore: null, portfolio: null };
let errorRetryFn = null;
let exploreCacheLabel = null;
// Per-rendered-document set of glossary terms already tagged (lower-cased
// canonical id). Only the FIRST occurrence of each term in a document gets the
// dotted underline — kills the "measles" effect in dense prose. md() opens a
// fresh scope for a whole document; a standalone inlineMd() call opens its own.
let _glossarySeen = null;

const GLOSSARY = {
  FCF: "Free Cash Flow — cash generated after capital expenditures. Higher FCF signals stronger cash generation and flexibility for buybacks, dividends, or reinvestment.",
  OCF: "Operating Cash Flow — cash from core business operations. Higher OCF means the business converts earnings into cash reliably.",
  EBIT: "Earnings Before Interest and Taxes — operating profit before financing and tax effects. Higher EBIT margin often indicates stronger operating efficiency.",
  EBITDA: "Earnings Before Interest, Taxes, Depreciation & Amortization — proxy for operating cash earnings. Useful for comparing capital-light vs capital-heavy businesses.",
  NIM: "Net Interest Margin — spread banks earn on loans vs deposits. Higher NIM generally improves bank profitability.",
  "EV/EBITDA": "Enterprise Value to EBITDA — valuation multiple. Lower vs peers can suggest relative cheapness; context matters by sector.",
  ROE: "Return on Equity — net income divided by shareholder equity. Higher ROE can indicate efficient use of equity capital.",
  ROIC: "Return on Invested Capital — profit relative to total capital deployed. Higher ROIC suggests durable competitive advantage.",
  PEG: "Price/Earnings to Growth — P/E adjusted for expected growth. Below 1.0 is often viewed as growth at a reasonable price.",
  EPS: "Earnings Per Share — profit allocated to each share. Rising EPS supports bullish narratives when quality of earnings is solid.",
  YoY: "Year over Year — comparison to the same period last year. Positive YoY growth indicates expansion vs prior year.",
  QoQ: "Quarter over Quarter — sequential comparison. Helps spot inflections between annual periods.",
  CAGR: "Compound Annual Growth Rate — smoothed growth rate over multiple years.",
  WACC: "Weighted Average Cost of Capital — hurdle rate for investments. Projects should earn above WACC to create value.",
  DCF: "Discounted Cash Flow — valuation method based on projected future cash flows.",
  "P/E": "Price-to-Earnings — share price divided by earnings per share. Lower P/E can mean cheaper earnings, or lower growth expectations.",
  "P/S": "Price-to-Sales — market cap divided by revenue. Common for early-stage or low-margin companies.",
  "P/B": "Price-to-Book — market value vs accounting book value. Often used for banks and asset-heavy firms.",
  RSI: "Relative Strength Index — momentum oscillator (0–100). Above 70 overbought, below 30 oversold (rule of thumb).",
  MACD: "Moving Average Convergence Divergence — trend/momentum indicator from moving averages.",
  ATR: "Average True Range — volatility measure used for stop placement and position sizing.",
  IV: "Implied Volatility — market's expectation of future price swings embedded in options prices.",
  NAV: "Net Asset Value — per-share value of fund/assets. Common in REITs and closed-end funds.",
  TAM: "Total Addressable Market — revenue opportunity ceiling for a product or sector.",
  ARR: "Annual Recurring Revenue — subscription revenue run-rate; key for SaaS quality.",
  NRR: "Net Revenue Retention — expansion minus churn from existing customers. Above 100% is strong for SaaS.",
  GMV: "Gross Merchandise Value — total transaction volume on a marketplace before fees.",
  Capex: "Capital Expenditures — investment in long-lived assets. High capex can depress near-term FCF.",
  OpEx: "Operating Expenses — day-to-day costs to run the business.",

  // --- Valuation multiples ---
  "P/FCF": "Price-to-Free-Cash-Flow — market cap divided by free cash flow. Lower can signal cheaper cash generation; very high suggests rich expectations.",
  "free cash flow": "Free Cash Flow — cash left after capital spending. Higher means more room for buybacks, dividends, or paying down debt.",
  "operating cash flow": "Operating Cash Flow — cash produced by the core business. Higher, steadier OCF signals healthier earnings quality.",
  "FCF-to-OCF": "Free-Cash-Flow to Operating-Cash-Flow — how much operating cash survives capital spending. Higher (closer to 1) means capital-light, more cash actually kept.",
  "Income Quality Ratio": "Income Quality Ratio — operating cash flow divided by net income. Above 1 means profits are backed by real cash; well below 1 hints at low-quality, accrual-heavy earnings.",
  "gross margin": "Gross Margin — revenue minus cost of goods sold, as a percent of revenue. Higher margins usually mean stronger pricing power.",
  "operating margin": "Operating Margin — operating profit as a percent of revenue. Higher means more of each sales dollar survives operating costs.",
  "net margin": "Net Margin — bottom-line profit as a percent of revenue. Higher means more of each sales dollar becomes profit.",
  "market cap": "Market Capitalization — share price times shares outstanding, i.e. the equity value of the company. Larger caps are generally more liquid and less volatile.",
  valuation: "Valuation — what the market pays for a company's earnings, cash flow, or assets. Higher valuation prices in more optimism and leaves less margin for error.",

  // --- Technicals & price levels ---
  "moving average": "Moving Average — the average price over a trailing window, used to read trend. Price above a rising average is a bullish tilt; below a falling one is bearish.",
  MA20: "20-Day Moving Average — average closing price over the last 20 sessions (short-term trend). Price above MA20 is near-term bullish; below is a short-term warning.",
  MA50: "50-Day Moving Average — average closing price over the last 50 sessions (intermediate trend). Price crossing below MA50 often flags weakening momentum.",
  "support level": "Support — a price zone where buyers have repeatedly stepped in. Holding above support is constructive; a decisive break below often opens more downside.",
  "resistance level": "Resistance — a price zone where selling has repeatedly capped rallies. Breaking above it can unlock further upside.",
  resistance: "Resistance — a price zone where selling has repeatedly capped rallies. A clean break above often signals more upside.",
  drawdown: "Drawdown — the drop from a peak to a trough. Larger drawdowns mean deeper losses and a bigger climb needed to recover.",

  // --- Risk & factor analytics ---
  beta: "Beta — how much a stock moves versus the market. Above 1 means it swings more than the market (higher risk); below 1 means it's steadier.",
  alpha: "Alpha — return beyond what market and sector exposure explain. Positive alpha is genuine skill/edge; negative means you're paying for risk without extra reward.",
  "residual alpha": "Residual Alpha — return left after stripping out sector beta, so it isn't just riding the sector. Positive is a real idiosyncratic edge; negative means it's underperforming its own sector.",
  "Information Ratio": "Information Ratio — active return divided by how consistently it's earned. Higher means more reliable skill; near zero or negative means the excess return isn't dependable.",
  IR: "Information Ratio — active return divided by tracking error (how reliably it's earned). Above ~0.5 is solid; negative means it's lagging its benchmark.",
  "Sharpe ratio": "Sharpe Ratio — return earned per unit of total risk. Higher is better risk-adjusted return; below 1 is generally considered weak.",
  Sharpe: "Sharpe Ratio — return earned per unit of total volatility. Higher means you're paid more for the risk taken.",
  "Sortino ratio": "Sortino Ratio — like Sharpe but only penalizes downside volatility. Higher means better return per unit of harmful risk.",
  Sortino: "Sortino Ratio — return per unit of downside risk only. Higher is better; it ignores 'good' upside swings.",
  volatility: "Volatility — how sharply a price swings around its average. Higher volatility means bigger, less predictable moves and larger position risk.",
  "standard deviation": "Standard Deviation — a measure of how widely returns spread around the average. Higher means more dispersion and, usually, more risk.",
  correlation: "Correlation — how closely two assets move together, from -1 to +1. Near +1 means they rise and fall together (little diversification); near 0 or negative adds diversification.",
  concentration: "Concentration — how much of a portfolio sits in a few positions. Higher concentration raises single-name and single-factor risk.",
  HHI: "Herfindahl-Hirschman Index — sum of squared position weights, a concentration score. Higher means more concentrated (less diversified).",
  Herfindahl: "Herfindahl Index — sum of squared weights measuring concentration. Higher means fewer names carry more of the risk.",
  "effective bets": "Effective Number of Bets — how many truly independent positions you really have after correlations. Far below your position count means the book is one bet sliced many ways.",

  // --- Stops, limits, hedges ---
  "stop-loss": "Stop-Loss — a preset exit level to cap a loss. A tighter (higher) stop limits losses but risks being shaken out by normal noise.",
  "trailing stop": "Trailing Stop — a stop that ratchets up as price rises to lock in gains, but never moves down. It protects profit while letting winners run.",
  "time stop": "Time Stop — exit if the trade hasn't worked within a set number of sessions. It frees capital from ideas that stall regardless of price.",
  collar: "Collar — owning the stock while buying a protective put and selling a call to fund it. It caps downside (and upside) — a low-cost hedge instead of an outright taxable sale.",

  // --- Rates & financials ---
  "yield curve": "Yield Curve — interest rates plotted across maturities. A steeper curve tends to help bank margins; an inverted curve (short rates above long) often warns of slowdown.",
  duration: "Duration — sensitivity to interest-rate changes. Higher duration (long bonds, high-growth 'long-duration' stocks) falls more when rates rise.",
  "net interest margin": "Net Interest Margin — the spread banks earn between loan yields and deposit costs. Higher NIM generally lifts bank profitability.",
  "basis points": "Basis Points — hundredths of a percent (100 bps = 1%). Used for precise moves in rates, yields, and fees.",
  bps: "Basis Points — hundredths of a percent (100 bps = 1%). A 25 bps rate cut equals 0.25%.",
  catalyst: "Catalyst — a specific event (earnings, approval, ruling, product) expected to move a stock. Bigger, nearer catalysts widen the range of outcomes.",
};

const $ = (id) => document.getElementById(id);

const CONTENT_IDS = {
  brief: "content-brief",
  picks: "content-picks",
  explore: "content-explore",
  portfolio: "content-portfolio",
};

const tabScrollState = {
  brief: { firstVisit: true, scrollTop: 0 },
  picks: { firstVisit: true, scrollTop: 0 },
  explore: { firstVisit: true, scrollTop: 0 },
  portfolio: { firstVisit: true, scrollTop: 0 },
};

const portfolioScrollState = {
  analysis: { firstVisit: true, scrollTop: 0 },
  actions: { firstVisit: true, scrollTop: 0 },
};

function getMainScroller() {
  return document.querySelector(".main");
}

function saveTabScroll(tabName) {
  const main = getMainScroller();
  if (!main || !tabScrollState[tabName]) return;
  tabScrollState[tabName].scrollTop = main.scrollTop;
}

let _scrollRestoreRaf = null;
// Bumped on every new restore and on any user scroll intent. In-flight retry
// frames capture the token they started with and bail out the instant it
// changes, so a superseded (rapid tab switch) or user-interrupted loop can
// never re-assert scrollTop and fight the user or a newer tab.
let _scrollRestoreToken = 0;

function cancelScrollRestore() {
  if (_scrollRestoreRaf) {
    cancelAnimationFrame(_scrollRestoreRaf);
    _scrollRestoreRaf = null;
  }
  _scrollRestoreToken += 1;
}

// If the user scrolls/keys while a restore loop is still catching up, stop
// fighting them — abandon the pending restore and leave them where they are.
function handleUserScrollIntent(e) {
  if (!_scrollRestoreRaf) return;
  if (e && e.type === "keydown") {
    const scrollKeys = [
      "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", " ", "Spacebar",
    ];
    if (!scrollKeys.includes(e.key)) return;
  }
  cancelScrollRestore();
}

window.addEventListener("wheel", handleUserScrollIntent, { passive: true });
window.addEventListener("touchstart", handleUserScrollIntent, { passive: true });
window.addEventListener("keydown", handleUserScrollIntent);

// Restore a saved scroll offset robustly. Content for a tab often loads
// asynchronously (fetch → innerHTML) AFTER we try to restore, so a single
// synchronous assignment gets clamped to ~0 while the panel is still short,
// leaving the user stuck at the top once the taller content arrives. We retry
// across a handful of frames until the scroller is tall enough to honor the
// target, then apply it exactly once more and stop.
function applyScrollWithRetry(target) {
  const main = getMainScroller();
  if (!main) return;
  cancelScrollRestore();
  const token = _scrollRestoreToken;
  if (!target || target <= 0) {
    main.scrollTop = 0;
    return;
  }
  let attempts = 0;
  const apply = () => {
    if (token !== _scrollRestoreToken) return;
    const maxScroll = Math.max(0, main.scrollHeight - main.clientHeight);
    main.scrollTop = Math.min(target, maxScroll);
    attempts += 1;
    if (maxScroll < target - 1 && attempts < 30) {
      _scrollRestoreRaf = requestAnimationFrame(apply);
    } else {
      _scrollRestoreRaf = null;
    }
  };
  apply();
}

function restoreTabScroll(tabName) {
  const main = getMainScroller();
  const state = tabScrollState[tabName];
  if (!main || !state) return;
  if (state.firstVisit) {
    state.firstVisit = false;
    main.scrollTop = 0;
    return;
  }
  applyScrollWithRetry(state.scrollTop);
}

function repairBrokenTermTokens(text) {
  if (!text || !text.includes("@END@")) return text;
  return text
    .replace(/([A-Z0-9./]{2,20})\]([A-Za-z0-9./]+)@END@/g, "$2")
    .replace(/([A-Z]{2,12})\]\1@END@/g, "$1")
    .replace(/\]([A-Z0-9./]{2,20})@END@/g, "$1")
    .replace(/@+TERM\[[^\]]*\]?/g, "")
    .replace(/@END@/g, "");
}

function scrubTermArtifacts(html) {
  if (!html || !html.includes("@END")) return html;
  let out = html;
  for (let pass = 0; pass < 4; pass++) {
    out = out.replace(/@+TERM\[([^\]]+)\]([^@]+)@END@/g, (_, id, label) => termHtml(id, label));
  }
  return out
    .replace(/([A-Z0-9./]{2,20})\]([A-Za-z0-9./]+)@END@/g, "$2")
    .replace(/\]([A-Za-z0-9./]{2,20})@END@/g, "$1")
    .replace(/@+TERM\[[^\]]*\]?/g, "")
    .replace(/@END@/g, "");
}

function sanitizeContent(text) {
  if (!text) return "";
  return repairBrokenTermTokens(
    sanitizeMarkdownSource(
      String(text)
        .replace(/ThinkingBlock\([\s\S]*?\)\s*/g, "")
        .replace(/ThinkingBlock\([\s\S]*$/g, "")
        .trim()
    )
  );
}

function sanitizeMarkdownSource(text) {
  if (!text) return "";
  const terms = [];
  let out = String(text);

  out = out.replace(/<term\s+id="([^"]+)"[^>]*>([\s\S]*?)<\/term>/gi, (_, id, label) => {
    terms.push({ id, label: label.trim() });
    return `@@TERMPROT${terms.length - 1}@@`;
  });

  out = out.replace(/<a\s+href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi, (_, url, label) => {
    const clean = label.replace(/<[^>]+>/g, "").trim();
    return clean ? `[${clean}](${url})` : url;
  });

  out = out.replace(/<style[\s\S]*?<\/style>/gi, "");
  out = out.replace(/<script[\s\S]*?<\/script>/gi, "");
  out = out.replace(/<!--[\s\S]*?-->/g, "");
  out = out.replace(/<br\s*\/?>/gi, "\n");
  out = out.replace(/<a\s+href=["'][^"'\n>]*["']?[^>\n]*/gi, "");
  out = out.replace(/<\/a>/gi, "");
  out = out.replace(/<\/?[a-z][^>]*>/gi, "");
  out = out.replace(/\{[^{}]*(?:color|font|margin|padding|display)\s*:[^{}]+\}/gi, "");

  out = out.replace(/@@TERMPROT(\d+)@@/g, (_, i) => {
    const term = terms[Number(i)];
    return term ? `<term id="${term.id}">${term.label}</term>` : "";
  });

  out = out
    .split("\n")
    .filter((line) => {
      const t = line.trim();
      if (!t) return true;
      if (/^[-*]\s*<a\s/i.test(t)) return false;
      if (/^[-*]\s*\[.+\]\(https?:\/\//.test(t) && /<a\s/i.test(t)) return false;
      if (/^\s*<\/?[a-z]/i.test(t)) return false;
      if (/hreflang=/i.test(t)) return false;
      return true;
    })
    .join("\n");

  out = out.replace(/Stop\s*\/?\s*Limit:\s*(?=Stop|Limit|\$)/gi, "Stop / Limit: ");
  out = out.replace(/\n{3,}/g, "\n\n");
  return out.trim();
}

function scrubRenderedHtml(html) {
  if (!html) return "";
  let out = String(html);
  const allowed = /^(h[1-4]|p|ul|ol|li|strong|em|code|pre|a|span|table|thead|tbody|tr|th|td|div|details|summary|button|time|br)$/i;

  out = out.replace(/\s+style\s*=\s*("[^"]*"|'[^']*')/gi, "");
  out = out.replace(/\s+on[a-z]+\s*=\s*("[^"]*"|'[^']*')/gi, "");
  out = out.replace(/<\/?([a-z0-9-]+)(\s[^>]*)?>/gi, (match, tag) => (allowed.test(tag) ? match.replace(/\s+style\s*=\s*("[^"]*"|'[^']*')/gi, "") : ""));
  out = out.replace(/&lt;\/?[a-z][^&]*&gt;/gi, "");
  out = out.replace(/&lt;a\s+href=[^&]*&gt;/gi, "");
  out = out.replace(/<a\s+href=["'][^"']*["'][^>]*>\s*<\/a>/gi, "");
  out = spaceGluedBold(out);
  out = spaceGluedEmDash(out);
  return out;
}

// LLM output routinely glues an em-dash used as a CLAUSE SEPARATOR straight onto
// the surrounding words or onto a closing bold label ("affected—", "impact—",
// "—beta", "<strong>Tickers affected</strong>—"). We run this on the FINAL HTML,
// after "**" has become <strong>, so tags, attributes, hrefs and code can be
// protected and left untouched. A single space is inserted on the glued side(s).
// Preserved intact: tight numeric ranges (digit—digit, e.g. "2024—2025"), any
// em-dash inside code (<pre>/<code>), and any em-dash inside a tag/attribute.
function spaceGluedEmDash(html) {
  if (!html || html.indexOf("\u2014") === -1) return html;
  // A closing inline tag glued to an em-dash ("</strong>—" → "</strong> —").
  let out = html.replace(/(<\/(?:strong|em|code|span|a|b|i)>)\u2014/g, "$1 \u2014");
  // Shield code spans/blocks and every tag (with its attributes) so only em-dashes
  // sitting in visible text nodes are touched.
  const slots = [];
  const protect = (m) => {
    slots.push(m);
    return `\u0000${slots.length - 1}\u0000`;
  };
  out = out
    .replace(/<pre[\s\S]*?<\/pre>/gi, protect)
    .replace(/<code[\s\S]*?<\/code>/gi, protect)
    .replace(/<[^>]+>/g, protect);
  // Left glue: a word char immediately before an em-dash gains a space, unless it
  // is a tight digit—digit range.
  out = out.replace(/([A-Za-z0-9%)\]])\u2014(\d?)/g, (m, left, nextDigit) =>
    /\d/.test(left) && nextDigit ? m : `${left} \u2014${nextDigit}`
  );
  // Right glue: a word char immediately after an em-dash gains a space, unless it
  // is a tight digit—digit range.
  out = out.replace(/(\d?)\u2014([A-Za-z0-9(\[])/g, (m, prevDigit, right) =>
    prevDigit && /\d/.test(right) ? m : `${prevDigit}\u2014 ${right}`
  );
  return out.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[Number(i)]);
}

// LLM output sometimes glues bold runs directly onto adjacent words
// ("word**bold**word", "positioning.**[link]", "your**live"). We run this on
// the final HTML — after `**` has become <strong> — so the boundaries are
// unambiguous: insert a single space between a word/period and an opening
// <strong>, and between a closing </strong> and a following word/bracket. This
// never touches URLs, hrefs, or legitimate already-spaced markdown.
function spaceGluedBold(html) {
  if (!html || html.indexOf("<strong>") === -1) return html;
  return html
    .replace(/([A-Za-z0-9.,)])(<strong>)/g, "$1 $2")
    .replace(/(<\/strong>)([A-Za-z0-9([])/g, "$1 $2");
}

/** @deprecated use sanitizeMarkdownSource */
function normalizeHtmlLegacies(text) {
  return sanitizeMarkdownSource(text);
}

function stripPortfolioDisplaySections(text) {
  return String(text || "")
    .replace(/```mm-meta[\s\S]*?```/gi, "")
    .replace(/^## Quant Actions\s*\n[\s\S]*?(?=^## |\Z)/im, "")
    .trim();
}

function parsePortfolioTickerSections(content) {
  portfolioTickerSections = {};
  if (!content) return;
  let src = stripPortfolioDisplaySections(sanitizeContent(content));
  src = src.replace(/^## Portfolio Pulse\s*\n/i, "");
  const re = /^####\s+([A-Z][A-Z0-9.\-]{0,12})\s*$/gm;
  const matches = [...src.matchAll(re)];
  if (!matches.length) return;
  for (let i = 0; i < matches.length; i++) {
    const ticker = matches[i][1].toUpperCase();
    const start = matches[i].index + matches[i][0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index : src.length;
    let body = src.slice(start, end).trim();
    body = body.replace(/^### Portfolio-level metrics[\s\S]*/im, "").trim();
    body = cleanPortfolioTickerBody(body);
    if (ticker && body) portfolioTickerSections[ticker] = body;
  }
}

function cleanPortfolioTickerBody(body) {
  return String(body || "")
    .split("\n")
    .filter((line) => {
      const t = line.trim();
      if (!t) return true;
      if (/^[-*]\s*\[.+\]\(https?:\/\//.test(t)) return false;
      if (/^<a\s+href=/i.test(t)) return false;
      if (/·\s*(Reuters|Bloomberg|CNBC|Fierce|TechCrunch)/i.test(t) && /https?:\/\//.test(t)) return false;
      return true;
    })
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function stopLimitForTicker(ticker) {
  const positions = portfolioAnalysis?.positions || portfolioAnalysis?.meta?.positions || [];
  const hit = positions.find((p) => p.ticker?.toUpperCase() === ticker.toUpperCase());
  return hit?.stop_limit || "";
}

function extractStopLimitFromBody(body) {
  let text = String(body || "");
  let stopLimit = "";
  const lineMatch = text.match(/^Stop\s*\/?\s*Limit:\s*(.+)$/im);
  if (lineMatch) {
    stopLimit = lineMatch[1].trim();
    text = text.replace(/^Stop\s*\/?\s*Limit:\s*.+$/im, "").trim();
  }
  text = text.replace(/\nStop\s*\/?\s*Limit:\s*.+$/im, "").trim();
  return { body: text, stopLimit };
}

function wrapMoneyAmounts(html) {
  if (!html) return "";
  return html.replace(
    /\$(\d[\d,]*(?:\.\d{1,2})?)/g,
    (_, amount) => `<span class="price-amt"><span class="price-currency">$</span>${amount}</span>`
  );
}

function mdPortfolio(text) {
  return scrubRenderedHtml(wrapMoneyAmounts(md(text)));
}

function renderTickerAnalysisHtml(body, stopLimitMeta = "") {
  const extracted = extractStopLimitFromBody(body);
  let stopLimit = stopLimitMeta || extracted.stopLimit;
  let html = mdPortfolio(extracted.body);
  if (stopLimit) {
    html += `<div class="stop-limit-block"><p class="stop-limit-label">Stop / Limit</p><p class="stop-limit-text">${wrapMoneyAmounts(inlineMd(stopLimit))}</p></div>`;
  }
  return html;
}

function formatMoneyPlain(n, digits = 2) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function formatReturnPct(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

// A missing/zero live quote can't yield a trustworthy return, so treat it as
// unknown (null) rather than a bogus -100%. Shared by the sort and the row
// render so both agree on which holdings count as "priced" vs "—".
function holdingReturnPct(h) {
  const rawRet = h.return_pct ?? h.returnPct;
  const quoteMissing = h.price == null || Number(h.price) === 0;
  if (rawRet == null || Number.isNaN(Number(rawRet)) || quoteMissing) return null;
  return Number(rawRet);
}

function renderPortfolioHoldingsTable() {
  const wrap = $("portfolio-holdings-wrap");
  const tbody = $("portfolio-holdings-body");
  const hint = $("portfolio-holdings-hint");
  if (!wrap || !tbody) return;
  const sourceHoldings = portfolio?.holdings || [];
  if (!sourceHoldings.length) {
    wrap.classList.add("hidden");
    hint?.classList.add("hidden");
    return;
  }
  // Sort a copy (never mutate portfolio.holdings) by return % descending —
  // biggest winners first, biggest losers last. Rows with an unknown return
  // ("—") sort to the very bottom. Array.prototype.sort is stable, so equal
  // returns (and the trailing "—" group) keep their original order.
  const holdings = sourceHoldings
    .map((h) => ({ h, ret: holdingReturnPct(h) }))
    .sort((a, b) => {
      if (a.ret == null && b.ret == null) return 0;
      if (a.ret == null) return 1;
      if (b.ret == null) return -1;
      return b.ret - a.ret;
    })
    .map((entry) => entry.h);
  wrap.classList.remove("hidden");
  const hasSections = Object.keys(portfolioTickerSections).length > 0;
  hint?.classList.toggle("hidden", !hasSections);
  tbody.innerHTML = holdings
    .map((h) => {
      const ticker = String(h.ticker || "").toUpperCase();
      const shares =
        h.shares != null
          ? (() => {
              const v = Number(h.shares);
              if (Number.isInteger(v) || Math.abs(v - Math.round(v)) < 0.0001) {
                return Math.round(v).toLocaleString();
              }
              return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
            })()
          : "—";
      const price =
        h.price != null
          ? `<span class="price-amt"><span class="price-currency">$</span>${Number(h.price).toFixed(2)}</span>`
          : `<span class="holding-table-muted">—</span>`;
      const value =
        h.value != null
          ? `<span class="price-amt"><span class="price-currency">$</span>${Number(h.value).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>`
          : `<span class="holding-table-muted">—</span>`;
      const ret = holdingReturnPct(h);
      const retClass = ret == null ? "pill-neutral" : ret >= 0 ? "pill-up" : "pill-down";
      const retText = formatReturnPct(ret);
      const clickable = hasSections && portfolioTickerSections[ticker];
      return `<tr class="holding-table-row${clickable ? " holding-table-row--clickable" : ""}" data-ticker="${escapeHtml(ticker)}"${clickable ? ' tabindex="0" role="button"' : ""}>
        <td class="holding-table-ticker-cell">
          <div class="holding-table-ticker-wrap">
            <span class="holding-table-logo">${stockLogoHtml(ticker, h.logo_url)}</span>
            <span class="holding-table-ticker">${escapeHtml(ticker)}</span>
          </div>
        </td>
        <td class="holding-table-num">${escapeHtml(shares)}</td>
        <td class="holding-table-num">${price}</td>
        <td class="holding-table-num holding-table-value">${value}</td>
        <td class="holding-table-num holding-table-return"><span class="return-pill ${retClass}">${escapeHtml(retText)}</span></td>
      </tr>`;
    })
    .join("");
  attachLogoFallbacks(tbody);
  preloadLogos(holdings.map((h) => h.ticker));
}

function openHoldingModal(ticker) {
  const sym = String(ticker || "").toUpperCase();
  const body = portfolioTickerSections[sym];
  if (!body) return;
  const holding = (portfolio?.holdings || []).find((h) => h.ticker?.toUpperCase() === sym);
  activeHoldingModalTicker = sym;
  const modal = $("holding-modal");
  $("holding-modal-title").textContent = sym;
  $("holding-modal-sub").textContent = holding?.name || holding?.company || "";
  const avatar = $("holding-modal-avatar");
  if (avatar) {
    avatar.innerHTML = stockLogoHtml(sym, holding?.logo_url);
    attachLogoFallbacks(avatar);
  }
  const article = $("holding-modal-body");
  article.innerHTML = renderTickerAnalysisHtml(body, stopLimitForTicker(sym));
  attachGlossaryHandlers(article);
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("holding-modal-open");
  holdingModalPrevFocus = document.activeElement;
  bindButtonPressFeedback(modal);
  modal.querySelector(".holding-modal-close")?.focus({ preventScroll: true });
}

function closeHoldingModal() {
  activeHoldingModalTicker = null;
  const modal = $("holding-modal");
  modal?.classList.add("hidden");
  modal?.setAttribute("aria-hidden", "true");
  document.body.classList.remove("holding-modal-open");
  if (holdingModalPrevFocus?.focus) {
    holdingModalPrevFocus.focus({ preventScroll: true });
  }
  holdingModalPrevFocus = null;
}

function attachHoldingModalHandlers() {
  document.querySelectorAll("[data-close-holding-modal]").forEach((el) => {
    el.addEventListener("click", closeHoldingModal);
  });
  $("portfolio-holdings-table")?.addEventListener("click", (e) => {
    const row = e.target.closest(".holding-table-row--clickable");
    if (row?.dataset.ticker) openHoldingModal(row.dataset.ticker);
  });
  $("portfolio-holdings-table")?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest(".holding-table-row--clickable");
    if (!row?.dataset.ticker) return;
    e.preventDefault();
    openHoldingModal(row.dataset.ticker);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && activeHoldingModalTicker) closeHoldingModal();
  });
  $("holding-modal")?.addEventListener("keydown", (e) => {
    const modal = $("holding-modal");
    if (e.key !== "Tab" || modal?.classList.contains("hidden")) return;
    const focusable = modal.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    const list = [...focusable].filter((el) => el.offsetParent !== null);
    if (list.length < 2) return;
    const first = list[0];
    const last = list[list.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
}

function stripTradeSections(text) {
  return sanitizeContent(text)
    .replace(/\*\*Trade Plan:\*\*[^\n]*(\n(?!\n|#)[^\n]*)*/gi, "")
    .replace(/^#{1,3}\s*Trade Plan[^\n]*\n([\s\S]*?)(?=\n#{1,3}\s|\n\*\*[A-Z]|$)/gim, "");
}

function termToken(id, label) {
  return `@@TERM[${id}]${label}@END@`;
}

function processTermTags(text) {
  return text.replace(/<term id="([^"]+)">([^<]*)<\/term>/gi, (_, id, label) => termToken(id, label));
}

function termHtml(id, label) {
  const upper = id.toUpperCase();
  // Prefer the exact key, then the upper-cased acronym form. Keep the canonical
  // GLOSSARY casing for the popover header so worded phrases read "Information
  // Ratio" rather than shouting "INFORMATION RATIO".
  const canonical = GLOSSARY[id] ? id : GLOSSARY[upper] ? upper : id;
  const def = GLOSSARY[canonical] || `${id} — financial metric used in equity analysis.`;
  return `<span class="glossary-term" data-term="${escapeHtml(canonical)}" data-def="${escapeHtml(def)}" tabindex="0">${escapeHtml(label)}</span>`;
}

async function preloadLogos(tickers) {
  const unique = [...new Set((tickers || []).map((t) => String(t).toUpperCase()))].filter((t) => t && !_logoReady.has(t));
  if (!unique.length) return;
  await Promise.all(
    unique.map(
      (t) =>
        new Promise((resolve) => {
          _logoReady.add(t);
          const img = new Image();
          img.onload = img.onerror = () => resolve();
          img.src = `${API}/logo/${encodeURIComponent(t)}`;
        })
    )
  );
}

function logoSrc(ticker, logoUrl) {
  return `${API}/logo/${encodeURIComponent(ticker.toUpperCase())}`;
}

function stockLogoHtml(ticker, logoUrl) {
  const initials = escapeHtml(ticker.slice(0, 2).toUpperCase());
  const src = logoSrc(ticker, logoUrl);
  // The monogram fallback is a self-contained circular avatar badge that lives in
  // the markup from the start (hidden while the logo image is present). When the
  // logo 404s the image is dropped and the badge is revealed, so the monogram is
  // ALWAYS its own avatar element — never inline text glued next to the ticker
  // symbol (e.g. "LM" beside "LMND").
  return `<div class="holding-avatar" aria-hidden="true" data-fallback="${initials}">
    <span class="holding-fallback" hidden>${initials}</span>
    <img class="holding-logo" src="${escapeHtml(src)}" alt="" loading="eager" decoding="async" />
  </div>`;
}

function attachLogoFallbacks(root = document) {
  root.querySelectorAll(".holding-logo:not([data-fallback-bound])").forEach((img) => {
    img.dataset.fallbackBound = "1";
    img.addEventListener(
      "error",
      () => {
        const wrap = img.closest(".holding-avatar");
        if (!wrap) return;
        img.remove();
        // Reveal the monogram badge already present in the markup; only create it
        // if a legacy avatar without one is encountered.
        let span = wrap.querySelector(".holding-fallback");
        if (!span) {
          span = document.createElement("span");
          span.className = "holding-fallback";
          span.textContent = wrap.dataset.fallback || "??";
          wrap.appendChild(span);
        }
        span.hidden = false;
      },
      { once: true }
    );
  });
}

function parseError(text) {
  if (!text) return OFFLINE_MSG;
  try {
    const j = JSON.parse(text);
    if (j.detail) return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
  } catch {
    /* plain text */
  }
  return text.length > 200 ? `${text.slice(0, 200)}…` : text;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isNetworkError(err) {
  const msg = String(err?.message || err || "").toLowerCase();
  return (
    err instanceof TypeError ||
    msg.includes("failed to fetch") ||
    msg.includes("networkerror") ||
    msg.includes("network request failed") ||
    msg.includes("load failed")
  );
}

function isRetryableHttpStatus(status) {
  return status === 502 || status === 503 || status === 504;
}

function humanizeMessage(raw) {
  if (raw == null || raw === "") return "";
  let msg = String(raw).replace(/\*\*/g, "").trim();
  msg = msg.replace(/127\.0\.0\.1:\d+/g, "").replace(/\s{2,}/g, " ").trim();

  const lower = msg.toLowerCase();
  if (!msg || lower === "failed to fetch" || lower === "unhealthy" || lower === "request failed") {
    return OFFLINE_MSG;
  }
  if (lower.includes("failed to fetch") || lower.includes("networkerror") || lower.includes("load failed")) {
    return OFFLINE_MSG;
  }
  if (/timed out waiting/i.test(msg)) {
    return "This is taking longer than expected — tap Retry or try again in a moment.";
  }
  if (/backend reconnecting/i.test(msg)) return RECONNECT_MSG;
  if (/backend busy/i.test(msg)) return RETRY_BUSY_MSG;
  if (/backend offline|local service|not responding/i.test(msg)) return OFFLINE_MSG;
  if (/already_running|already running/i.test(msg)) return "Already working on that — hang tight.";
  if (/could not start brief/i.test(msg)) return "Couldn't start your brief — try again.";
  if (/could not start picks|picks generation/i.test(msg)) return "Couldn't load today's picks — try again.";
  if (/could not start analysis/i.test(msg)) return "Couldn't run portfolio analysis — try again.";
  if (/could not start explore/i.test(msg)) return "Couldn't run that exploration — try again.";
  if (/brief generation failed/i.test(msg)) return "Your brief didn't finish — try again.";
  if (/portfolio analysis failed/i.test(msg)) return "Portfolio analysis didn't finish — try again.";
  if (/picks generation failed/i.test(msg)) return "Today's picks didn't finish — try again.";
  if (/explore failed/i.test(msg)) return "That exploration didn't finish — try again.";
  if (/finished without (content|results)/i.test(msg)) return "Something went wrong — nothing came back. Try again.";
  if (/model returned empty/i.test(msg)) return "Nothing came back this time — try again.";
  if (/no robinhood data/i.test(msg)) return "No Robinhood holdings found — connect your account and try again.";
  if (/robinhood sync failed/i.test(msg)) return "Couldn't update your Robinhood holdings.";
  if (/using saved robinhood snapshot|live sync unavailable/i.test(msg)) {
    return "Using your last saved holdings — live update wasn't available.";
  }
  if (/setup required/i.test(msg)) return msg.replace(/^setup required:?/i, "Setup needed:").trim();
  if (/api key rejected/i.test(msg)) return msg.replace(/^api key rejected:?/i, "API key issue:").trim();
  if (/enter a sector/i.test(msg)) return "Type a sector or theme to explore — like semiconductors or energy.";
  if (/tap retry or run the action again/i.test(msg)) {
    return "This is taking longer than expected — tap Retry or try again in a moment.";
  }
  return msg;
}

function formatUserError(err) {
  if (!err) return OFFLINE_MSG;
  const msg = String(err.message || err);
  if (msg.includes("reconnecting")) return RECONNECT_MSG;
  if (isNetworkError(err) || msg === "Failed to fetch") {
    return `${OFFLINE_MSG}. ${OFFLINE_HINT}`;
  }
  return humanizeMessage(msg);
}

function humanizeProgressMessage(msg) {
  if (!msg) return "";
  const m = String(msg);
  if (/researching markets/i.test(m)) return "Scanning today's headlines…";
  if (/composing brief/i.test(m)) return "Writing your morning brief…";
  if (/generating today'?s picks/i.test(m)) return "Ranking today's ideas…";
  if (/analyzing portfolio/i.test(m)) return "Reviewing your holdings…";
  if (/exploring/i.test(m)) return m.replace(/^Exploring/i, "Researching");
  if (/using cached/i.test(m)) return "Loading saved copy…";
  if (/backend reconnecting/i.test(m)) return RECONNECT_MSG;
  if (/starting/i.test(m)) return m.replace(/Starting…?/i, "Getting started…");
  return humanizeMessage(m) || m;
}

function setBackendOnline(online) {
  backendOnline = online;
  const banner = $("backend-error");
  const dot = $("live-dot");
  if (banner) {
    banner.classList.toggle("hidden", online);
    if (!online && !banner.textContent.trim()) {
      banner.textContent = `${OFFLINE_MSG}. ${OFFLINE_HINT}`;
    }
  }
  if (dot) {
    dot.classList.toggle("online", online);
    dot.setAttribute("aria-label", online ? "Connected to Market Morning" : "Offline — cannot reach Market Morning");
  }
  setOfflineEmptyCopy();
  updatePortfolioEmptyState();
}

async function request(path, init = {}, opts = {}) {
  const method = (init.method || "GET").toUpperCase();
  const maxAttempts = opts.retries ?? (method === "GET" ? 6 : 5);
  let lastErr;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const res = await fetch(`${API}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      });
      if (!res.ok) {
        const err = new Error(humanizeMessage(parseError(await res.text()) || res.statusText));
        err.status = res.status;
        if (isRetryableHttpStatus(res.status) && attempt < maxAttempts - 1) {
          lastErr = err;
          setBackendOnline(false);
          $("backend-error").textContent = RETRY_BUSY_MSG;
          opts.onRetry?.(attempt + 1, maxAttempts);
          await sleep(NETWORK_RETRY_DELAYS_MS[Math.min(attempt, NETWORK_RETRY_DELAYS_MS.length - 1)]);
          continue;
        }
        throw err;
      }
      setBackendOnline(true);
      return await res.json();
    } catch (err) {
      lastErr = err;
      if (!isNetworkError(err)) throw err;
      if (attempt >= maxAttempts - 1) break;
      setBackendOnline(false);
      $("backend-error").textContent = RECONNECT_MSG;
      opts.onRetry?.(attempt + 1, maxAttempts);
      await sleep(NETWORK_RETRY_DELAYS_MS[Math.min(attempt, NETWORK_RETRY_DELAYS_MS.length - 1)]);
    }
  }
  throw new Error(formatUserError(lastErr));
}

async function pollJob(progressPath, onProgress, maxIter = 1200) {
  let consecutiveNetworkFailures = 0;
  const maxNetworkFailures = 40;

  for (let i = 0; i < maxIter; i++) {
    try {
      const job = await request(progressPath, {}, {
        retries: 6,
        onRetry: (n, max) => {
          onProgress({
            running: true,
            progress: undefined,
            message: RECONNECT_MSG,
          });
        },
      });
      consecutiveNetworkFailures = 0;
      onProgress(job);
      if (job.error) throw new Error(humanizeMessage(job.error));
      if (job.done) return job;
    } catch (err) {
      if (isNetworkError(err) && consecutiveNetworkFailures < maxNetworkFailures) {
        consecutiveNetworkFailures++;
        onProgress({
          running: true,
          progress: undefined,
          message: RECONNECT_MSG,
        });
        await sleep(
          NETWORK_RETRY_DELAYS_MS[Math.min(consecutiveNetworkFailures - 1, NETWORK_RETRY_DELAYS_MS.length - 1)]
        );
        i--;
        continue;
      }
      throw err instanceof Error ? err : new Error(formatUserError(err));
    }
    await sleep(350);
  }
  throw new Error("This is taking longer than expected — tap Retry or try again in a moment.");
}

async function pingBackend() {
  try {
    const res = await fetch(`${API}/health`, { method: "GET", cache: "no-store" });
    if (!res.ok) throw new Error("unhealthy");
    healthInfo = await res.json();
    setBackendOnline(true);
    updateVersionLine();
    return true;
  } catch {
    healthInfo = null;
    setBackendOnline(false);
    return false;
  }
}

// Footer/brand line shows the frontend build; when the backend /health reports
// its own version (a sibling adds it), surface it too so a version skew is
// visible. Defensive: silently keeps the base line if /health omits it.
function updateVersionLine() {
  const el = $("brand-sub");
  if (!el) return;
  let text = `Your portfolio, clarified · v${APP_VERSION}`;
  const be = healthInfo?.version ?? healthInfo?.app_version;
  if (be && String(be) !== APP_VERSION) text += ` · engine ${String(be)}`;
  el.textContent = text;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Some RSS titles (e.g. Fierce Biotech) embed literal anchor HTML and a
// trailing " - Publisher" suffix. Extract the plain text (inert parse, no
// script/resource execution) and drop the publisher suffix for clean display.
// Callers must still escapeHtml() the result before inserting into markup.
function cleanHeadlineTitle(raw, publisher) {
  let text = String(raw || "");
  if (/[<&]/.test(text)) {
    try {
      const doc = new DOMParser().parseFromString(text, "text/html");
      text = doc.body.textContent || "";
    } catch {
      text = text.replace(/<[^>]*>/g, "");
    }
  }
  text = text.replace(/\s+/g, " ").trim();
  const pub = String(publisher || "").trim();
  if (pub) {
    const re = new RegExp(`\\s*[-–—]\\s*${pub.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`, "i");
    text = text.replace(re, "").trim();
  }
  return text;
}

function normalizeEmphasisMarkers(text) {
  return String(text)
    // Trim spaces that sit INSIDE emphasis markers only — never the prose space
    // that separates a bold run from the following word/link. An opening "** "
    // is preceded by start/space/open-punct; a closing " **" is followed by
    // end/space/close-punct. Collapsing arbitrary spaces around "**" (the old
    // behavior) ate the space in "**label:** [link]" → "label:[link]".
    .replace(/(^|[\s(>\[])\*\*[ \t]+(?=\S)/g, "$1**")
    .replace(/(?<=\S)[ \t]+\*\*(?=$|[\s).,;:!?\]])/g, "**")
    .replace(/\*\s+\*(?=\S)/g, "**")
    .replace(/(?<=\S)\*\s+\*/g, "**");
}

function applyInlineEmphasis(html) {
  let out = html;
  for (let pass = 0; pass < 4; pass++) {
    const next = out.replace(/\*\*\s*([^*\n<>]+?)\s*\*\*/g, "<strong>$1</strong>");
    if (next === out) break;
    out = next;
  }
  out = out.replace(/(?<!\*)\*(?!\*)([^*\n<>]+?)\*(?!\*)/g, "<strong>$1</strong>");
  out = out.replace(/__\s*([^_\n<>]+?)\s*__/g, "<strong>$1</strong>");
  return out;
}

function cleanupStrayAsterisks(html) {
  if (!html || !html.includes("*")) return html;
  return html
    .replace(/\*\*([^*\n<>]+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*\s+\*/g, "")
    .replace(/\*\*(?=\s|:|,|\.|\)|$)/g, "")
    .replace(/(?<=\s|^|\()(\*\*)(?=\S)/g, "");
}

function inlineMd(text) {
  // If we're not already inside a document-level render (md()), open a local
  // dedup scope so a single standalone string still tags each term once.
  const ownSeen = _glossarySeen == null;
  if (ownSeen) _glossarySeen = new Set();
  try {
    return inlineMdInner(text);
  } finally {
    if (ownSeen) _glossarySeen = null;
  }
}

function inlineMdInner(text) {
  let prepared = normalizeEmphasisMarkers(processTermTags(sanitizeMarkdownSource(text)));
  const protectedTokens = [];
  const protect = (match) => {
    const slot = protectedTokens.length;
    protectedTokens.push(match);
    return `@@TERMSLOT${slot}@@`;
  };
  // Shield already-tagged terms, markdown links, bare URLs, and inline code from
  // glossary matching so a term is never underlined inside a URL, headline, or
  // code span (which would also corrupt the link/href).
  prepared = prepared.replace(/@+TERM\[[^\]]+\][^@]+@END@/g, protect);
  // Shield URLs and inline code BEFORE the colon fix-up below so "://", URL
  // ports, and code-span colons are never touched. Markdown links stay visible
  // for one more step so "label:[link]" can gain its space.
  prepared = prepared.replace(/https?:\/\/[^\s)]+/g, protect);
  prepared = prepared.replace(/`[^`]+`/g, protect);
  // Guarantee a space after a colon glued to the next word/link in prose. Only
  // fires when the char before ":" is a letter/quote/asterisk and the char
  // after starts a word / "[" / "(" — so "://", times/ratios (10:30, 3:1), and
  // already-shielded code/URLs are left untouched.
  prepared = prepared.replace(/(?<=[A-Za-z"'\u2018\u2019*]):(?=[A-Za-z0-9[(])/g, ": ");
  // Same fix for a bold label whose colon sits just inside the closing "**"
  // ("**Thesis:**You" → "**Thesis:** You"). The already-spaced form
  // ("**risk:** [link]") is left alone because "**" is followed by a space.
  prepared = prepared.replace(/:\*\*(?=[A-Za-z0-9[(])/g, ":** ");
  prepared = prepared.replace(/\[[^\]]*\]\([^)]+\)/g, protect);

  const keys = Object.keys(GLOSSARY).sort((a, b) => b.length - a.length);
  const canonicalByLower = new Map(keys.map((k) => [k.toLowerCase(), k]));
  // Acronyms/symbols (RSI, ATR, P/E, HHI, MA20…) match case-sensitively so a
  // stray lowercase run in prose or a slug is never underlined and tickers stay
  // clean. Worded phrases ("residual alpha", "Information Ratio") match
  // case-insensitively so both "Beta" and "beta" get tagged.
  const wordedKeys = keys.filter((k) => /[a-z]/.test(k));
  const acronymKeys = keys.filter((k) => !/[a-z]/.test(k));
  const tagPass = (list, flags) => {
    if (!list.length) return;
    const alt = list.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
    const re = new RegExp(`(?<![A-Za-z0-9</])(${alt})(?![A-Za-z0-9>/])`, flags);
    prepared = prepared.replace(re, (_, m) => termToken(canonicalByLower.get(m.toLowerCase()) || m, m));
  };
  // Worded phrases first (longest alternatives win, so multi-word terms beat any
  // acronym substring), then shield those tokens before the acronym pass runs so
  // a short key can't dive inside a phrase already tagged.
  tagPass(wordedKeys, "gi");
  prepared = prepared.replace(/@+TERM\[[^\]]+\][^@]+@END@/g, protect);
  tagPass(acronymKeys, "g");

  // Restore shielded tokens. A shielded token can itself contain another
  // placeholder (e.g. a <term> tag wrapped in `inline code` is shielded once as
  // a term token and again as the enclosing code span, and a markdown link can
  // hold a shielded URL), so a single pass would strand the inner
  // @@TERMSLOT@@. Loop until no placeholder survives, bounded by the token
  // count so a stray literal can never spin forever.
  for (let pass = 0; pass <= protectedTokens.length && prepared.includes("@@TERMSLOT"); pass++) {
    prepared = prepared.replace(/@@TERMSLOT(\d+)@@/g, (_, slot) =>
      protectedTokens[Number(slot)] != null ? protectedTokens[Number(slot)] : ""
    );
  }
  // Belt-and-suspenders: never let a placeholder artifact reach the user.
  prepared = prepared.replace(/@@TERMSLOT\d+@@/g, "");
  const html = applyInlineEmphasis(escapeHtml(prepared))
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) => {
      // `url` was already HTML-escaped exactly once by escapeHtml() above (the
      // markdown link is shielded through that pass and restored just before it),
      // so re-escaping via safeExternalHref() would double-encode ampersands
      // ("&amp;" → "&amp;amp;") and mangle query-string links. Gate the scheme
      // here without re-escaping so the href keeps a single, valid "&amp;".
      const href = url.trim();
      return /^https?:\/\//i.test(href)
        ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : label;
    })
    .replace(/@+TERM\[([^\]]+)\]([^@]+)@END@/g, (_, id, label) => {
      // First occurrence per document gets tagged; later ones render as plain
      // (already-escaped) text. label is escaped at this stage, so return it
      // verbatim for repeats.
      const key = String(id).toLowerCase();
      if (_glossarySeen) {
        if (_glossarySeen.has(key)) return label;
        _glossarySeen.add(key);
      }
      return termHtml(id, label);
    });
  return scrubRenderedHtml(scrubTermArtifacts(cleanupStrayAsterisks(html)));
}

function isTableLine(line) {
  const t = line.trim();
  return t.startsWith("|") && t.includes("|");
}

function isTableSep(line) {
  return /^\|?\s*:?-{2,}/.test(line.trim());
}

function renderTableCards(head, body) {
  if (!body.length) return "";
  const cards = body.map((row) => {
    const title = row[0] || "—";
    const stats = head.slice(1).map((label, i) =>
      `<div class="player-stat"><span class="player-stat-label">${inlineMd(label)}</span><span class="player-stat-value">${inlineMd(row[i + 1] || "—")}</span></div>`
    ).join("");
    return `<div class="player-card"><div class="player-card-title">${inlineMd(title)}</div>${stats}</div>`;
  });
  return `<div class="player-cards">${cards.join("")}</div>`;
}

function renderTable(lines, cardMode = false) {
  const rows = lines
    .filter((l) => !isTableSep(l))
    .map((l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim()));
  if (!rows.length) return "";
  const [head, ...body] = rows;
  if (cardMode || head.length > 3) return renderTableCards(head, body);
  let html = '<div class="table-wrap"><table><thead><tr>';
  head.forEach((c) => { html += `<th>${inlineMd(c)}</th>`; });
  html += "</tr></thead><tbody>";
  body.forEach((row) => {
    html += "<tr>";
    row.forEach((c) => { html += `<td>${inlineMd(c)}</td>`; });
    html += "</tr>";
  });
  html += "</tbody></table></div>";
  return html;
}

function normalizeMarkdownHeadings(src) {
  return src.replace(/^[\t\uFEFF\u200B]*#{4,6}[\t ]+(.+?)[\t ]*$/gm, (_, title) => `@@H4[${title.trim()}]@@`);
}

function parseHeadingLine(line) {
  const token = line.match(/^@@H4\[([^\]]+)\]@@$/);
  if (token) return { level: 4, text: token[1] };
  const trimmed = line.trim();
  const m = trimmed.match(/^(#{1,6})\s+(.+)$/);
  if (!m) return null;
  return { level: m[1].length, text: m[2].trim() };
}

function md(text, opts = {}) {
  if (!text) return "";
  // Open one glossary-dedup scope for the whole document so a term underlined in
  // an early paragraph isn't re-underlined in every later block.
  const prevSeen = _glossarySeen;
  _glossarySeen = new Set();
  try {
    return mdInner(text, opts);
  } finally {
    _glossarySeen = prevSeen;
  }
}

function mdInner(text, opts = {}) {
  let src = normalizeMarkdownHeadings(stripTradeSections(sanitizeMarkdownSource(text)).replace(/\r\n/g, "\n"));
  // Models often glue an ordered-list marker straight onto a bold title
  // ("1.**Trim...**"), which lacks the space `/^\d+\. /` needs — so it renders
  // as a plain paragraph with a non-bold literal "1.". Insert the missing space
  // (only when the char after the dot is a non-digit, so decimals like "3.5"
  // are untouched) so it becomes a real <ol><li> and the CSS counter can bold
  // the index to match the bold title.
  src = src.replace(/^(\s*\d+)\.(?=[^\s\d])/gm, "$1. ");
  const fenced = [];
  const stripped = src.replace(/```[\w]*\n?([\s\S]*?)```/g, (_, code) => {
    const i = fenced.length;
    fenced.push(`<pre class="code-block"><code>${escapeHtml(code.trim())}</code></pre>`);
    return `\n@@FENCE${i}@@\n`;
  });

  const lines = stripped.split("\n");
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^@@FENCE(\d+)@@$/);
    if (fence) {
      blocks.push(fenced[Number(fence[1])]);
      i++;
      continue;
    }

    if (isTableLine(line) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const tableLines = [];
      while (i < lines.length && isTableLine(lines[i])) {
        tableLines.push(lines[i]);
        i++;
      }
      blocks.push(renderTable(tableLines, opts.cardTables));
      continue;
    }

    const heading = parseHeadingLine(line);
    if (heading) {
      const { level, text: title } = heading;
      if (level === 1) blocks.push(`<h1>${inlineMd(title)}</h1>`);
      else if (level === 2) blocks.push(`<h2>${inlineMd(title)}</h2>`);
      else if (level === 3) blocks.push(`<h3>${inlineMd(title)}</h3>`);
      else blocks.push(`<h4 class="ticker-heading">${inlineMd(title)}</h4>`);
      i++;
      continue;
    }
    if (/^[-*] /.test(line)) {
      const items = [];
      while (i < lines.length) {
        if (/^[-*] /.test(lines[i])) {
          items.push(`<li>${inlineMd(lines[i].replace(/^[-*] /, ""))}</li>`);
          i++;
        } else if (lines[i].trim() === "" && /^[-*] /.test(lines[i + 1] || "")) {
          // blank line between items (loose list) — stay in the same <ul>
          i++;
        } else {
          break;
        }
      }
      blocks.push(`<ul>${items.join("")}</ul>`);
      continue;
    }
    if (/^\d+\. /.test(line)) {
      const items = [];
      while (i < lines.length) {
        if (/^\d+\. /.test(lines[i])) {
          items.push(`<li>${inlineMd(lines[i].replace(/^\d+\. /, ""))}</li>`);
          i++;
        } else if (lines[i].trim() === "" && /^\d+\. /.test(lines[i + 1] || "")) {
          // blank line between items (loose list) — keep one <ol> so numbering
          // continues 1, 2, 3 instead of restarting a new list at 1 each time
          i++;
        } else {
          break;
        }
      }
      blocks.push(`<ol>${items.join("")}</ol>`);
      continue;
    }
    if (line.trim() === "" || /^---+$/.test(line.trim())) {
      i++;
      continue;
    }

    const para = [];
    while (
      i < lines.length
      && lines[i].trim() !== ""
      && !/^---+$/.test(lines[i].trim())
      && !/^@@FENCE\d+@@$/.test(lines[i])
      && !parseHeadingLine(lines[i])
      && !/^#{1,6}\s/.test(lines[i].trim())
      && !/^[-*] /.test(lines[i])
      && !/^\d+\. /.test(lines[i])
      && !(isTableLine(lines[i]) && i + 1 < lines.length && isTableSep(lines[i + 1]))
    ) {
      para.push(lines[i]);
      i++;
    }
    if (para.length) blocks.push(`<p>${inlineMd(para.join(" "))}</p>`);
  }

  return scrubRenderedHtml(scrubTermArtifacts(cleanupStrayAsterisks(cleanupStrayMarkdownHeaders(blocks.join("\n")))));
}

function cleanupStrayMarkdownHeaders(html) {
  return scrubTermArtifacts(
    html
      .replace(/<p>\s*#{4,6}\s*([^<]+?)<\/p>/gi, '<h4 class="ticker-heading">$1</h4>')
      .replace(/(?:^|\n)\s*#{4,6}\s+([A-Z][A-Z0-9.\-]{0,12})\s*(?=\n|$)/g, '\n<h4 class="ticker-heading">$1</h4>\n')
  );
}

function wrapBriefSections(html) {
  const chunks = html.split(/(?=<h2>)/).filter((c) => c.trim());
  if (!chunks.some((c) => c.startsWith("<h2>"))) return html;

  let intro = "";
  const sectionChunks = [];
  for (const chunk of chunks) {
    if (chunk.startsWith("<h2>")) sectionChunks.push(chunk);
    else intro += chunk;
  }
  if (!sectionChunks.length) return html;

  const nav = [];
  const sections = [];
  sectionChunks.forEach((part, idx) => {
    const titleMatch = part.match(/^<h2>(.*?)<\/h2>/);
    const titleRaw = titleMatch ? titleMatch[1] : `Section ${idx + 1}`;
    const title = titleRaw.replace(/<[^>]+>/g, "");
    const id = `brief-sec-${idx}`;
    const body = titleMatch ? part.slice(titleMatch[0].length) : part;
    const isOvernight = /overnight|pre-market|market open/i.test(title);
    nav.push(`<button type="button" class="brief-nav-btn" data-brief-jump="${id}">${title}</button>`);
    sections.push(`<details class="brief-section" id="${id}"${isOvernight ? " open" : ""}>
      <summary>${titleRaw}</summary>
      <div class="brief-section-body">${wrapBriefSubsections(body)}</div>
    </details>`);
  });

  return scrubTermArtifacts(
    `${intro}<nav class="brief-nav" aria-label="Brief sections">${nav.join("")}</nav><div class="brief-sections-wrap">${sections.join("")}</div>`
  );
}

function wrapBriefSubsections(bodyHtml) {
  if (!bodyHtml?.includes("<h3>")) return scrubTermArtifacts(bodyHtml || "");
  const chunks = bodyHtml.split(/(?=<h3>)/).filter((c) => c.trim());
  let intro = "";
  const subs = [];
  for (const chunk of chunks) {
    if (!chunk.startsWith("<h3>")) {
      intro += chunk;
      continue;
    }
    const titleMatch = chunk.match(/^<h3>(.*?)<\/h3>/);
    const titleRaw = titleMatch ? titleMatch[1] : "Topic";
    const rest = titleMatch ? chunk.slice(titleMatch[0].length) : chunk;
    subs.push(
      `<details class="brief-subsection"><summary>${titleRaw}</summary><div class="brief-subsection-body">${rest}</div></details>`
    );
  }
  return scrubTermArtifacts(intro + subs.join(""));
}

function normalizeBriefTitles(text) {
  return String(text || "").replace(
    /International Opportunities\s*&\s*Geopolitical Trades/gi,
    "Geopolitical Trades"
  );
}

function mdBrief(text) {
  return scrubRenderedHtml(wrapBriefSections(md(normalizeBriefTitles(text))));
}

function mdExplore(text) {
  return scrubRenderedHtml(wrapExploreSections(md(text, { cardTables: true })));
}

function wrapExploreSections(html) {
  if (!html?.includes("<h2>")) return html;
  const chunks = html.split(/(?=<h2>)/).filter((c) => c.trim());
  if (!chunks.some((c) => c.startsWith("<h2>"))) return html;
  return `<div class="explore-sections">${chunks
    .map((part) => `<section class="explore-section">${part}</section>`)
    .join("")}</div>`;
}

function attachBriefNavHandlers(root) {
  root?.querySelectorAll("[data-brief-jump]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sec = document.getElementById(btn.dataset.briefJump);
      if (!sec) return;
      // Kill any in-flight tab-switch scroll-restore loop BEFORE we jump, so a
      // stale saved scrollTop can never re-assert itself a frame later and snap
      // the user back to the top after this intentional nav jump.
      cancelScrollRestore();
      sec.open = true;
      safeScrollIntoView(sec, { block: "nearest" });
      root.querySelectorAll(".brief-nav-btn").forEach((b) => b.classList.toggle("active", b === btn));
    });
  });
  attachBriefToggleGuards(root);
}

// Expanding/collapsing a brief <details> must happen in place. In the WKWebView
// a summary click can bounce the main scroller to the top (content reflow +
// focus on the summary). Snapshot the scroll offset the instant the user
// presses a summary and re-assert it right after the native toggle so the
// section just opens/closes without moving the page. Nav-driven opens are not
// guarded here because those intentionally scroll the section into view.
function attachBriefToggleGuards(root) {
  root?.querySelectorAll("details.brief-section, details.brief-subsection").forEach((d) => {
    if (d.dataset.toggleGuard) return;
    d.dataset.toggleGuard = "1";
    const summary = d.querySelector(":scope > summary");
    if (!summary) return;
    let pendingTop = null;
    const capture = () => {
      const main = getMainScroller();
      pendingTop = main ? main.scrollTop : null;
      // Abort any in-flight tab-switch scroll-restore loop the instant the user
      // touches a summary, BEFORE the collapse/expand reflow runs — so the retry
      // loop can never fight the reflow or re-assert a stale position.
      cancelScrollRestore();
    };
    summary.addEventListener("pointerdown", capture);
    summary.addEventListener("mousedown", capture);
    summary.addEventListener("touchstart", capture, { passive: true });
    summary.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") capture();
    });
    d.addEventListener("toggle", () => {
      if (pendingTop == null) return;
      const target = pendingTop;
      pendingTop = null;
      const main = getMainScroller();
      if (!main) return;
      // Stop any in-flight scroll-restore loop so it can't fight this.
      cancelScrollRestore();
      if (Math.abs(main.scrollTop - target) > 1) main.scrollTop = target;
      requestAnimationFrame(() => {
        const m = getMainScroller();
        if (m && Math.abs(m.scrollTop - target) > 1) m.scrollTop = target;
      });
    });
  });
}

function updateMiniBriefCta(show) {
  const btn = $("btn-mini-brief");
  if (!btn) return;
  const hasMini = Boolean($("content-mini-brief").innerHTML.trim());
  btn.classList.toggle("hidden", !show || hasMini);
}

// The late-day mini brief is a single awaited POST (no progress job), so show an
// indeterminate animated bar for the duration of the await and hide it on
// success or error.
function setMiniBriefLoading(on) {
  const el = $("mini-brief-hydrate");
  if (el) el.classList.toggle("hidden", !on);
}

function todayIso() {
  return new Date().toLocaleDateString("en-CA");
}

function briefHydrateLabel(data) {
  if (data?.has_today && data.today?.mini_brief) {
    return "Pulling up today's brief and late-day update…";
  }
  if (data?.has_today) return "Pulling up today's brief…";
  return "Checking for today's brief…";
}

function setBriefHydrateLoading(on, label = "") {
  const el = $("brief-hydrate");
  if (!el) return;
  el.classList.toggle("hidden", !on);
  const lbl = $("brief-hydrate-label");
  if (lbl && label) lbl.textContent = label;
  if (on) $("empty-brief").classList.add("hidden");
}

function fadePanelEl(el) {
  if (!el || el.classList.contains("hidden")) return;
  el.classList.remove("panel-fade-in");
  void el.offsetWidth;
  el.classList.add("panel-fade-in");
}

function fadeBriefEl(el) {
  fadePanelEl(el);
}

function readBriefCache() {
  try {
    const raw = localStorage.getItem(BRIEF_CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    if (cached.date !== todayIso() || !cached.landing?.has_today) return null;
    return cached.landing;
  } catch {
    return null;
  }
}

function cacheBriefLanding(data) {
  if (!data?.has_today) return;
  try {
    localStorage.setItem(BRIEF_CACHE_KEY, JSON.stringify({ date: todayIso(), landing: data }));
  } catch {
    /* quota / private mode */
  }
}

function initBriefPanelState() {
  $("empty-brief").classList.add("hidden");
  const cached = readBriefCache();
  if (cached) {
    applyBriefLanding(cached, { fade: true });
    return;
  }
  setBriefHydrateLoading(true, "Checking for today's brief…");
}

function picksHasToday() {
  return Boolean($("content-picks").innerHTML.trim());
}

function readPicksCache() {
  try {
    const raw = localStorage.getItem(PICKS_CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw);
    if (cached.date !== todayIso() || !cached.content) return null;
    return cached.content;
  } catch {
    return null;
  }
}

function cachePicksContent(content) {
  if (!content?.trim()) return;
  picksCache = content;
  try {
    localStorage.setItem(PICKS_CACHE_KEY, JSON.stringify({ date: todayIso(), content }));
  } catch {
    /* ignore */
  }
}

function setPicksHydrateLoading(on, label = "Loading today's picks…") {
  const el = $("picks-hydrate");
  if (!el) return;
  el.classList.toggle("hidden", !on);
  const lbl = $("picks-hydrate-label");
  if (lbl && label) lbl.textContent = label;
  if (on) {
    $("picks-empty").classList.add("hidden");
  }
}

function showPicksEmptyState(show) {
  $("picks-empty").classList.toggle("hidden", !show);
  $("btn-picks").classList.toggle("hidden", !show);
}

function applyPicksContent(content, opts = {}) {
  const { fade = false } = opts;
  const text = sanitizeContent(typeof content === "string" ? content : content?.content || "");
  const el = $("content-picks");
  setPicksHydrateLoading(false);

  if (!text) {
    el.innerHTML = "";
    el.classList.add("hidden");
    showPicksEmptyState(true);
    $("btn-refresh-picks").classList.add("hidden");
    if (tab === "picks") refreshPanelUI();
    return false;
  }

  el.innerHTML = md(text);
  el.classList.remove("hidden");
  $("picks-empty").classList.add("hidden");
  $("btn-picks").classList.add("hidden");
  $("btn-refresh-picks").classList.remove("hidden");
  cachePicksContent(text);
  attachGlossaryHandlers(el);
  renderWatchlistAdds(picksMeta);
  if (fade) fadePanelEl(el);
  if (tab === "picks") refreshPanelUI();
  return true;
}

function initPicksPanelState() {
  $("picks-empty").classList.add("hidden");
  loadPicksCached();
}

function loadExploreStore() {
  try {
    const raw = localStorage.getItem(EXPLORE_STORE_KEY);
    if (!raw) return [];
    return JSON.parse(raw);
  } catch {
    return [];
  }
}

function saveExploreToStore(market, content) {
  const key = market.trim().toLowerCase();
  if (!key || !content?.trim()) return;
  exploreCache[key] = content;
  const items = loadExploreStore().filter((i) => i.market.toLowerCase() !== key);
  items.unshift({ market: market.trim(), content, date: todayIso(), ts: Date.now() });
  try {
    localStorage.setItem(EXPLORE_STORE_KEY, JSON.stringify(items.slice(0, 24)));
  } catch {
    /* ignore */
  }
  renderExplorePastList();
}

function hydrateExploreCache() {
  loadExploreStore().forEach((item) => {
    if (item.market && item.content) {
      exploreCache[item.market.toLowerCase()] = item.content;
    }
  });
}

function clampMainScroll() {
  const main = getMainScroller();
  if (!main) return;
  const maxScroll = Math.max(0, main.scrollHeight - main.clientHeight);
  if (main.scrollTop > maxScroll) main.scrollTop = maxScroll;
}

function updatePortfolioScrollMode() {
  const main = getMainScroller();
  if (!main) return;
  const onActions = tab === "portfolio" && portfolioSubTab === "actions";
  main.classList.toggle("main--portfolio-actions", onActions);
  main.querySelector(".main-scroll-buffer")?.classList.toggle("hidden", onActions);
}

function setPortfolioSubTab(next) {
  const main = getMainScroller();
  // Only an ACTUAL subtab change should ever move the scroll. This function is
  // also invoked as a side effect of updatePortfolioEmptyState() on every
  // panel refresh / Robinhood sync / 25s backend ping — with next === current.
  // Re-asserting a stale saved scrollTop on those re-renders was yanking the
  // user (on ANY tab, since .main is shared) back to an old position, so a
  // no-op switch must leave the scroll exactly where it is.
  const switching = portfolioSubTab !== next;
  if (main && switching) {
    portfolioScrollState[portfolioSubTab].scrollTop = main.scrollTop;
    portfolioScrollState[portfolioSubTab].firstVisit = false;
  }
  portfolioSubTab = next;
  document.querySelectorAll("[data-portfolio-sub]").forEach((b) => {
    const active = b.dataset.portfolioSub === portfolioSubTab;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  });
  $("portfolio-analysis-pane")?.classList.toggle("hidden", portfolioSubTab !== "analysis");
  $("portfolio-actions-pane")?.classList.toggle("hidden", portfolioSubTab !== "actions");
  updatePortfolioScrollMode();
  if (!switching) return;
  requestAnimationFrame(() => {
    if (!main) return;
    const state = portfolioScrollState[portfolioSubTab];
    if (state.firstVisit) {
      state.firstVisit = false;
      main.scrollTop = 0;
    } else {
      applyScrollWithRetry(state.scrollTop);
    }
    clampMainScroll();
  });
}

function setExploreSubTab(next) {
  exploreSubTab = next;
  document.querySelectorAll("[data-explore-sub]").forEach((b) => {
    const active = b.dataset.exploreSub === exploreSubTab;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  });
  $("explore-main-pane").classList.toggle("hidden", exploreSubTab !== "explore");
  $("explore-past-pane").classList.toggle("hidden", exploreSubTab !== "past");
  if (exploreSubTab === "past") renderExplorePastList();
}

function renderExplorePastList() {
  const list = $("explore-past-list");
  const empty = $("explore-past-empty");
  const items = loadExploreStore();
  if (!items.length) {
    list.innerHTML = "";
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");
  list.innerHTML = items
    .map(
      (item) =>
        `<button type="button" class="explore-past-item" data-explore-past="${escapeHtml(item.market)}">
          <span class="explore-past-title">${escapeHtml(item.market)}</span>
          <span class="explore-past-date">${escapeHtml(formatBriefDate(item.date))}</span>
        </button>`
    )
    .join("");
  bindButtonPressFeedback(list);
  list.querySelectorAll("[data-explore-past]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setExploreSubTab("explore");
      $("explore-input").value = btn.dataset.explorePast;
      showExploreContent(exploreCache[btn.dataset.explorePast.toLowerCase()] || "", {
        fade: true,
        cached: true,
        date: loadExploreStore().find((i) => i.market.toLowerCase() === btn.dataset.explorePast.toLowerCase())?.date,
      });
      scrollExploreToSheet();
    });
  });
}

function showExploreContent(content, opts = {}) {
  const text = sanitizeContent(content);
  const el = $("content-explore");
  el.innerHTML = text ? mdExplore(text) : "";
  el.classList.toggle("hidden", !text);
  const badge = $("explore-cache-badge");
  if (badge) {
    if (opts.cached && text) {
      const when = opts.date ? formatBriefDate(opts.date) : "earlier";
      badge.textContent = `Saved from ${when}`;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
      badge.textContent = "";
    }
  }
  if (text) {
    attachGlossaryHandlers(el);
    if (opts.fade) fadePanelEl(el);
  }
  if (tab !== "explore") setTab("explore");
  else refreshPanelUI();
}

function formatBriefDate(iso) {
  try {
    const d = new Date(`${iso}T12:00:00`);
    return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function setPortfolioLoading(on, pct = 0, label = "") {
  $("portfolio-loading").classList.toggle("hidden", !on);
  const fill = $("portfolio-progress-fill");
  if (fill) fill.style.width = on ? `${Math.min(100, Math.max(0, pct))}%` : "0%";
  const lbl = $("portfolio-loading-label");
  if (lbl) lbl.textContent = label || (on ? "Reviewing your holdings…" : "");
}

function setExploreLoading(on, pct = 0, label = "") {
  $("explore-loading").classList.toggle("hidden", !on);
  const fill = $("explore-progress-fill");
  if (fill) fill.style.width = on ? `${Math.min(100, Math.max(0, pct))}%` : "0%";
  const lbl = $("explore-loading-label");
  if (lbl) lbl.textContent = label || (on ? "Researching that market…" : "");
}

function setPicksProgress(on, pct = 0, label = "") {
  if (!on) {
    setPicksHydrateLoading(false);
    const fill = $("picks-hydrate")?.querySelector(".brief-hydrate-fill");
    if (fill) fill.classList.remove("progress-mode");
    return;
  }
  setPicksHydrateLoading(true, label || "Finding today's best ideas…");
  const fill = $("picks-hydrate")?.querySelector(".brief-hydrate-fill");
  if (fill) {
    fill.classList.add("progress-mode");
    fill.style.width = `${Math.min(100, Math.max(8, pct))}%`;
  }
}

function setBriefLoading(on, pct = 0, label = "") {
  $("loading").classList.toggle("hidden", !on);
  const fill = $("progress-fill");
  if (fill) fill.style.width = on ? `${Math.min(100, Math.max(0, pct))}%` : "0%";
  const lbl = $("loading-label");
  if (lbl && label) lbl.textContent = label;
  else if (lbl && on) lbl.textContent = "Putting together your morning brief…";
  if (tab === "brief" && briefSubTab === "today") {
    $("brief-recap").classList.toggle("hidden", on || briefHasToday() || !$("brief-recap").innerHTML);
    $("empty-brief").classList.toggle("hidden", on || briefHasToday());
  }
}

async function waitForResearch(force = false) {
  await request(`/research/start?force=${force}`, { method: "POST" });
  for (let i = 0; i < 300; i++) {
    const p = await request("/research/progress");
    setBriefLoading(true, p.progress ?? 0, humanizeProgressMessage(p.message || "Scanning today's headlines…"));
    if (p.done && !p.running) return;
    await new Promise((r) => setTimeout(r, 350));
  }
}

function setButtonLoading(btn, on) {
  if (!btn) return;
  btn.classList.toggle("btn-loading", on);
  btn.setAttribute("aria-busy", on ? "true" : "false");
}

// Programmatic scrolls share the same single-flight token as the tab/subtab
// restore loop. Calling cancelScrollRestore() first kills any in-flight restore
// (or older animate) loop so a stale saved scrollTop can never be re-asserted a
// frame later and yank the page back — and each animation frame bails the instant
// the token changes (user scroll / newer tab-switch restore / newer programmatic
// scroll), so these never fight the user or a newer intent.
function animateMainScrollToTop(el, duration = 650, offset = 12) {
  const main = document.querySelector(".main");
  if (!el || !main) return;
  cancelScrollRestore();
  const token = _scrollRestoreToken;
  _scrollRestoreRaf = requestAnimationFrame(() => {
    if (token !== _scrollRestoreToken) { _scrollRestoreRaf = null; return; }
    const mainRect = main.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const target = main.scrollTop + (elRect.top - mainRect.top) - offset;
    const start = main.scrollTop;
    const change = target - start;
    if (Math.abs(change) < 2) { _scrollRestoreRaf = null; return; }
    const t0 = performance.now();
    const step = (now) => {
      if (token !== _scrollRestoreToken) { _scrollRestoreRaf = null; return; }
      const p = Math.min(1, (now - t0) / duration);
      const eased = 1 - (1 - p) ** 3;
      main.scrollTop = start + change * eased;
      if (p < 1) _scrollRestoreRaf = requestAnimationFrame(step);
      else _scrollRestoreRaf = null;
    };
    _scrollRestoreRaf = requestAnimationFrame(step);
  });
}

function animateMainScrollToCenter(el, duration = 400) {
  const main = document.querySelector(".main");
  if (!el || !main) return;
  cancelScrollRestore();
  const token = _scrollRestoreToken;
  _scrollRestoreRaf = requestAnimationFrame(() => {
    if (token !== _scrollRestoreToken) { _scrollRestoreRaf = null; return; }
    const mainRect = main.getBoundingClientRect();
    const elRect = el.getBoundingClientRect();
    const elCenter = elRect.top + elRect.height / 2;
    const mainCenter = mainRect.top + mainRect.height / 2;
    const target = main.scrollTop + (elCenter - mainCenter);
    const start = main.scrollTop;
    const change = target - start;
    if (Math.abs(change) < 2) { _scrollRestoreRaf = null; return; }
    const t0 = performance.now();
    const step = (now) => {
      if (token !== _scrollRestoreToken) { _scrollRestoreRaf = null; return; }
      const p = Math.min(1, (now - t0) / duration);
      const eased = 1 - (1 - p) ** 3;
      main.scrollTop = start + change * eased;
      if (p < 1) _scrollRestoreRaf = requestAnimationFrame(step);
      else _scrollRestoreRaf = null;
    };
    _scrollRestoreRaf = requestAnimationFrame(step);
  });
}

function scrollPanelTo(el) {
  animateMainScrollToCenter(el, 400);
}

function scrollExploreToSheet() {
  const sheet = document.querySelector(".sheet-explore");
  if (!sheet) return;
  animateMainScrollToCenter(sheet, 420);
}

function scrollPortfolioToAnalysis() {
  const target = $("portfolio-sheet") || $("portfolio-holdings-wrap");
  if (!target) return;
  animateMainScrollToTop(target, 650, 12);
}

function bindButtonPressFeedback(root = document) {
  root.querySelectorAll(".btn, .chip, .mini-brief-cta, .subtab, .tab").forEach((btn) => {
    if (btn.dataset.pressBound) return;
    btn.dataset.pressBound = "1";
    btn.addEventListener("pointerdown", () => {
      if (!btn.disabled && !btn.classList.contains("btn-loading")) {
        btn.classList.add("btn-pressed");
      }
    });
    const release = () => btn.classList.remove("btn-pressed");
    btn.addEventListener("pointerup", release);
    btn.addEventListener("pointerleave", release);
    btn.addEventListener("pointercancel", release);
  });
}

function setExploreControlsLoading(on) {
  setButtonLoading($("btn-explore"), on);
  document.querySelectorAll(".chip-explore").forEach((chip) => setButtonLoading(chip, on));
}

function cachePortfolio(data) {
  try {
    localStorage.setItem(PORTFOLIO_CACHE_KEY, JSON.stringify(data));
  } catch {
    /* quota / private mode */
  }
}

function hydratePortfolioCache() {
  try {
    const raw = localStorage.getItem(PORTFOLIO_CACHE_KEY);
    if (!raw) return;
    portfolio = JSON.parse(raw);
    renderHero();
  } catch {
    /* ignore corrupt cache */
  }
}

function readExploreLandingCache() {
  try {
    const raw = localStorage.getItem(EXPLORE_LANDING_KEY);
    if (!raw) return null;
    return JSON.parse(raw).data;
  } catch {
    return null;
  }
}

function cacheExploreLanding(data) {
  try {
    localStorage.setItem(EXPLORE_LANDING_KEY, JSON.stringify({ ts: Date.now(), data }));
  } catch {
    /* ignore */
  }
}

function renderExploreLandingData(data) {
  if (!data) return;
  const quick = $("explore-quick-markets");
  const markets = (data.suggested_markets || [])
    .map(
      (m) =>
        `<button type="button" class="chip chip-explore" data-explore-run="${escapeHtml(m)}">${escapeHtml(m)}</button>`
    )
    .join("");
  quick.innerHTML = `<p class="section-label">Quick explore</p><div class="chip-row">${markets}</div>`;
  quick.querySelectorAll("[data-explore-run]").forEach((chip) => {
    chip.addEventListener("click", () => {
      loadExplore(chip.dataset.exploreRun);
    });
  });
  bindButtonPressFeedback(quick);

  const headlinesEl = $("explore-headlines");
  const headlines = (data.headlines || []).slice(0, 6);
  if (headlines.length) {
    headlinesEl.classList.remove("hidden");
    headlinesEl.innerHTML =
      `<p class="section-label">In the news</p><ul class="landing-list landing-links">` +
      headlines
        .map((h) => {
          const label = escapeHtml(cleanHeadlineTitle(h.title, h.publisher));
          const pub = escapeHtml(h.publisher || "");
          const href = safeExternalHref(h.link);
          const anchor = href
            ? `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
            : label;
          return `<li>${anchor} <span class="landing-muted">· ${pub}</span></li>`;
        })
        .join("") +
      `</ul>`;
  }
}

function formatTimestamp(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function renderSyncStatus(info = {}) {
  const el = $("sync-status");
  if (!el) return;
  const { state, message, synced_at: syncedAt, source, stale, reason } = info;
  let text = message || "";
  let cls = "sync-status";
  if (state === "syncing") {
    text = "Updating your Robinhood holdings…";
  } else if (state === "ok") {
    cls += " sync-ok";
    const when = formatTimestamp(syncedAt);
    text = when ? `Holdings updated · ${when}` : "Holdings updated";
    if (stale) text += " · using last saved copy";
  } else if (state === "skipped") {
    cls += " sync-warn";
    text =
      reason === "cooldown" && syncedAt
        ? `Holdings are up to date · last updated ${formatTimestamp(syncedAt)}`
        : "Holdings are already up to date";
  } else if (state === "error") {
    cls += " sync-error";
    text = humanizeMessage(message) || "Couldn't update your Robinhood holdings";
  } else if (!text) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.className = cls;
  el.textContent = text;
  el.classList.remove("hidden");
}

function invalidatePortfolioAnalysis() {
  portfolioAnalysis = null;
  portfolioTickerSections = {};
  closeHoldingModal();
  const el = $("content-portfolio");
  if (el) {
    el.innerHTML = "";
    el.classList.add("hidden");
  }
  $("btn-refresh-portfolio-analysis")?.classList.add("hidden");
  renderPortfolioActions([]);
  renderPortfolioHoldingsTable();
}

async function syncRobinhoodPortfolio(force = false) {
  renderSyncStatus({ state: "syncing" });
  try {
    const result = await request(`/portfolio/sync-robinhood?force=${force}`, { method: "POST" });
    if (result.synced) invalidatePortfolioAnalysis();
    if (result.portfolio) {
      portfolio = result.portfolio;
      cachePortfolio(portfolio);
      renderHero();
    } else {
      await refreshPortfolio();
    }
    if (result.skipped) {
      renderSyncStatus({ state: "skipped", reason: result.reason, synced_at: result.last_sync_at });
    } else if (result.synced) {
      renderSyncStatus({
        state: "ok",
        synced_at: result.synced_at,
        source: result.source,
        stale: result.stale,
      });
      if (result.stale && result.error) {
        showToast("Using your last saved holdings — live update wasn't available.", "warn");
      }
    } else {
      renderSyncStatus({ state: "error", message: result.error || "No Robinhood holdings found" });
    }
    updatePortfolioEmptyState();
    return result;
  } catch (e) {
    renderSyncStatus({ state: "error", message: formatUserError(e) });
    throw e;
  }
}

let holdingsRefreshing = false;

async function refreshHoldingsLive() {
  if (holdingsRefreshing) return;
  holdingsRefreshing = true;
  const btn = $("btn-refresh-holdings");
  setButtonLoading(btn, true);
  setError("", { tab: "portfolio" });
  try {
    await syncRobinhoodPortfolio(true);
    await refreshPortfolio();
    renderHero();
    renderPortfolioHoldingsTable();
    showToast("Holdings refreshed from Robinhood");
  } catch (e) {
    setError(e, { tab: "portfolio", toast: true, retry: refreshHoldingsLive });
  } finally {
    setButtonLoading(btn, false);
    holdingsRefreshing = false;
  }
}

function updatePortfolioEmptyState() {
  const empty = $("portfolio-empty");
  const subtabs = $("portfolio-subtabs");
  const analysisPane = $("portfolio-analysis-pane");
  const actionsPane = $("portfolio-actions-pane");
  const sheet = $("portfolio-sheet");
  const block = $("portfolio-analysis-block");
  if (!empty || !sheet) return;
  const holdings = portfolio?.holdings?.length || 0;
  if (!holdings) {
    empty.classList.remove("hidden");
    subtabs?.classList.add("hidden");
    analysisPane?.classList.add("hidden");
    actionsPane?.classList.add("hidden");
    sheet.classList.add("hidden");
    block?.classList.add("hidden");
    $("portfolio-empty-title").textContent = "No holdings yet";
    $("portfolio-empty-desc").textContent = backendOnline
      ? "Connect Robinhood to pull in your positions, then run analysis."
      : `${OFFLINE_MSG}. ${OFFLINE_HINT}`;
    return;
  }
  empty.classList.add("hidden");
  subtabs?.classList.remove("hidden");
  sheet.classList.remove("hidden");
  block?.classList.remove("hidden");
  renderPortfolioHoldingsTable();
  setPortfolioSubTab(portfolioSubTab);
}

function setOfflineEmptyCopy() {
  const offlineDesc = `${OFFLINE_MSG}. ${OFFLINE_HINT}`;
  const briefDesc = $("empty-brief-desc");
  if (briefDesc && !backendOnline && !briefHasToday() && $("loading").classList.contains("hidden")) {
    briefDesc.textContent = offlineDesc;
  }
  const picksDesc = $("picks-empty-desc");
  if (picksDesc && !backendOnline && !picksHasToday()) picksDesc.textContent = offlineDesc;
}

function renderWatchlistAdds(meta) {
  const panel = $("watchlist-adds");
  const adds = meta?.watchlist_adds || meta?.meta?.watchlist_adds || [];
  if (!panel) return;
  if (!adds.length) {
    panel.classList.add("hidden");
    panel.innerHTML = "";
    return;
  }
  panel.classList.remove("hidden");
  const rows = adds.slice(0, 3);
  panel.innerHTML =
    `<p class="section-label">Worth watching</p>` +
    `<ul class="watchlist-adds-list">` +
    rows
      .map((item) => {
        const ticker = String(item.ticker || "").toUpperCase();
        const reason = item.reason || "";
        const onList = watchlistTickers.has(ticker) || watchlistPending.has(ticker);
        return `<li>
          <span class="watch-add-logo">${stockLogoHtml(ticker, item.logo_url)}</span>
          <div class="watch-add-body">
            <div class="watch-add-ticker">${escapeHtml(ticker)}</div>
            ${reason ? `<div class="watch-reason">${inlineMd(reason)}</div>` : ""}
          </div>
          <button type="button" class="btn watch-add-btn${onList ? " watch-add-btn--added" : ""}" data-pick-ticker="${escapeHtml(ticker)}"${onList ? " disabled" : ""}>${onList ? "Added" : "Add"}</button>
        </li>`;
      })
      .join("") +
    `</ul>`;
  panel.querySelectorAll("[data-pick-ticker]").forEach((btn) => {
    btn.addEventListener("click", () => addWatch(btn.dataset.pickTicker, "", "picks", { switchToWatchlist: false }));
  });
  attachLogoFallbacks(panel);
  preloadLogos(rows.map((item) => item.ticker));
  bindButtonPressFeedback(panel);
}

function setError(msg, opts = {}) {
  const text = msg instanceof Error ? formatUserError(msg) : msg ? formatUserError({ message: String(msg) }) : "";
  const tabKey = opts.tab || tab;
  if (opts.retry) tabRetryFns[tabKey] = opts.retry;
  else if (!text) tabRetryFns[tabKey] = null;
  else if (!opts.keepRetry) tabRetryFns[tabKey] = null;

  if (!text) {
    tabErrors[tabKey] = "";
    if (tabKey === tab) renderTabError();
    return;
  }
  tabErrors[tabKey] = text;
  if (tabKey === tab) renderTabError();
  if (opts.toast) showToast(text, "error");
}

function renderTabError() {
  const el = $("error");
  const textEl = $("error-text");
  const retryBtn = $("btn-error-retry");
  const text = tabErrors[tab] || "";
  errorRetryFn = tabRetryFns[tab] || null;
  if (!text) {
    el.classList.add("hidden");
    if (textEl) textEl.textContent = "";
    retryBtn?.classList.add("hidden");
    return;
  }
  const wasHidden = el.classList.contains("hidden");
  if (textEl) textEl.textContent = text;
  else el.textContent = text;
  el.classList.remove("hidden");
  if (retryBtn) {
    retryBtn.classList.toggle("hidden", !errorRetryFn);
  }
  if (wasHidden && (tab === "portfolio" || tab === "picks" || tab === "brief" || tab === "explore")) {
    safeScrollIntoView(el, { block: "nearest" });
  }
}

function clearErrorOnTabSwitch() {
  /* per-tab errors persist — restore on tab enter */
}

let _toastTimer = null;
function showToast(message, kind = "ok") {
  const el = $("toast");
  if (!el || !message) return;
  el.textContent = message;
  el.className = `toast toast-${kind}`;
  el.classList.remove("hidden");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.add("hidden"), kind === "error" ? 3600 : 2600);
}

function setPicksSubTab(next) {
  picksSubTab = next;
  document.querySelectorAll("[data-picks-sub]").forEach((b) => {
    const active = b.dataset.picksSub === picksSubTab;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  });
  $("picks-today-pane").classList.toggle("hidden", picksSubTab !== "today");
  $("picks-watch-pane").classList.toggle("hidden", picksSubTab !== "watchlist");
  if (picksSubTab === "watchlist") refreshWatchlist();
}

function setBriefSubTab(next) {
  briefSubTab = next;
  document.querySelectorAll("[data-brief-sub]").forEach((b) => {
    const active = b.dataset.briefSub === briefSubTab;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  });
  const onToday = briefSubTab === "today";
  const onArchive = briefSubTab === "archive";
  const hasToday = briefHasToday();
  const loading = !$("loading").classList.contains("hidden");
  const hydrating = !$("brief-hydrate").classList.contains("hidden");

  $("brief-archive-pane").classList.toggle("hidden", !onArchive);
  $("brief-basis")?.classList.toggle("hidden", !onToday || !hasToday);
  $("content-brief").classList.toggle("hidden", !onToday || !hasToday);
  $("brief-hydrate").classList.toggle("hidden", !onToday || !hydrating);
  $("brief-meta").classList.toggle("hidden", !onToday || !hasToday);
  updateMiniBriefCta(onToday && hasToday);
  $("content-mini-brief").classList.toggle(
    "hidden",
    !onToday || !$("content-mini-brief").innerHTML
  );
  $("empty-brief").classList.toggle("hidden", onArchive || hasToday || loading || hydrating);
  $("brief-recap").classList.toggle(
    "hidden",
    onArchive || hasToday || loading || !$("brief-recap").innerHTML
  );
  $("loading").classList.toggle("hidden", onArchive || !loading);

  if (onArchive && !$("archive-date-list").children.length) {
    loadArchiveDates();
  }
}

function briefHasToday() {
  return $("content-brief").innerHTML.length > 0;
}

function renderArchiveDateList(dates, selected) {
  const el = $("archive-date-list");
  if (!dates?.length) {
    el.innerHTML = '<p class="landing-muted">No past briefs yet.</p>';
    return;
  }
  archiveSelectedDate = selected || dates[0];
  el.innerHTML = dates
    .map(
      (d) =>
        `<button type="button" class="archive-date-btn${d === archiveSelectedDate ? " active" : ""}" data-archive-date="${escapeHtml(d)}" role="radio" aria-checked="${d === archiveSelectedDate ? "true" : "false"}">${escapeHtml(formatBriefDate(d))}</button>`
    )
    .join("");
  el.querySelectorAll("[data-archive-date]").forEach((btn) => {
    btn.addEventListener("click", () => {
      archiveSelectedDate = btn.dataset.archiveDate;
      el.querySelectorAll(".archive-date-btn").forEach((b) => {
        const checked = b.dataset.archiveDate === archiveSelectedDate;
        b.classList.toggle("active", checked);
        b.setAttribute("aria-checked", checked ? "true" : "false");
      });
      loadArchiveBrief(archiveSelectedDate);
    });
  });
}

function refreshPanelUI() {
  if (tab === "brief") {
    const hasBrief = briefHasToday();
    const onToday = briefSubTab === "today";
    const loading = !$("loading").classList.contains("hidden");
    const hydrating = !$("brief-hydrate").classList.contains("hidden");
    $("empty-brief").classList.toggle("hidden", hasBrief || loading || hydrating || !onToday);
    $("btn-brief").classList.toggle("hidden", hasBrief || loading);
    $("brief-hydrate").classList.toggle("hidden", !onToday || !hydrating);
    $("brief-meta").classList.toggle("hidden", !hasBrief || !onToday);
    updateMiniBriefCta(hasBrief && onToday);
  }

  if (tab === "picks" && picksSubTab === "today") {
    const hasPicks = picksHasToday();
    const hydrating = !$("picks-hydrate").classList.contains("hidden");
    $("picks-empty").classList.toggle("hidden", hasPicks || hydrating);
    $("btn-picks").classList.toggle("hidden", hasPicks || hydrating);
    $("btn-refresh-picks").classList.toggle("hidden", !hasPicks);
  }

  if (tab === "portfolio") {
    updatePortfolioEmptyState();
  }

  updatePortfolioScrollMode();
  renderTabError();
  updateHero();
}

function setTab(next) {
  const changed = next !== tab;
  if (changed && activeHoldingModalTicker) closeHoldingModal();
  if (changed) saveTabScroll(tab);
  tab = next;
  document.querySelectorAll(".tab").forEach((b) => {
    const active = b.dataset.tab === tab;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", active ? "true" : "false");
  });

  $("panel-brief").classList.toggle("hidden", tab !== "brief");
  $("panel-picks").classList.toggle("hidden", tab !== "picks");
  $("panel-explore").classList.toggle("hidden", tab !== "explore");
  $("panel-portfolio").classList.toggle("hidden", tab !== "portfolio");

  refreshPanelUI();

  if (changed) {
    requestAnimationFrame(() => restoreTabScroll(tab));
  }
}

function showTabContent(source, text, options = {}) {
  const content = sanitizeContent(typeof text === "string" ? text : text?.content || "");
  const el = $(CONTENT_IDS[source]);
  if (!el) return;
  if (source === "brief" || source === "explore") {
    el.innerHTML = source === "brief" ? mdBrief(content) : mdExplore(content);
    el.classList.toggle("hidden", !content);
  } else if (source === "portfolio") {
    el.innerHTML = "";
    el.classList.add("hidden");
  } else {
    el.innerHTML = md(content);
    el.classList.toggle("hidden", !content);
  }

  if (source === "brief") {
    $("empty-brief").classList.add("hidden");
    $("btn-brief").classList.add("hidden");
    $("brief-recap").classList.add("hidden");
    $("brief-tabs").classList.remove("hidden");
    updateMiniBriefCta(true);
    setBriefSubTab("today");
    attachBriefNavHandlers(el);
  }
  if (source === "explore") {
    // Explore uses wrapExploreSections and emits no data-brief-jump anchors,
    // so there is nothing for attachBriefNavHandlers to bind here.
  }
  if (source === "picks") {
    if (content) {
      cachePicksContent(content);
      $("picks-empty").classList.add("hidden");
      $("btn-picks").classList.add("hidden");
      $("btn-refresh-picks").classList.remove("hidden");
      renderWatchlistAdds(picksMeta);
      fadePanelEl(el);
    } else {
      el.innerHTML = "";
      el.classList.add("hidden");
      showPicksEmptyState(true);
      setError("Nothing came back this time — try again.", { tab: "picks" });
    }
  }
  if (source === "portfolio") {
    if (typeof text === "object" && text !== null && !Array.isArray(text)) {
      portfolioAnalysis = text;
    }
    parsePortfolioTickerSections(content);
    el.innerHTML = "";
    el.classList.add("hidden");
    $("btn-refresh-portfolio-analysis").classList.remove("hidden");
    renderPortfolioHoldingsTable();
    renderPortfolioActions(portfolioAnalysis?.actions || text?.actions || []);
    updatePortfolioEmptyState();
    if (options.scrollToAnalysis) {
      requestAnimationFrame(() => scrollPortfolioToAnalysis());
    }
  }
  attachGlossaryHandlers(el);
  refreshPanelUI();
}

function updateHero() {
  renderHero();
}

function renderHero() {
  if (!portfolio?.holdings?.length) {
    $("hero").classList.add("hidden");
    return;
  }
  $("hero").classList.remove("hidden");

  const equity = portfolio.totals.value;
  const totalAcct = portfolio.totals.total_account_value;
  $("total-value").innerHTML = `<span class="price-amt"><span class="price-currency">$</span>${equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>`;

  const cashEl = $("hero-cash");
  const cash = portfolio.totals?.cash ?? portfolio.account?.cash;
  const pending = portfolio.totals?.pending_deposits ?? portfolio.account?.pending_deposits;
  const parts = [];
  if (cash != null && cash > 0) parts.push(`$${Number(cash).toLocaleString(undefined, { maximumFractionDigits: 0 })} liquid cash`);
  if (pending && pending > 0) parts.push(`$${Number(pending).toLocaleString(undefined, { maximumFractionDigits: 0 })} pending`);
  if (totalAcct && totalAcct > equity) {
    parts.push(`$${Number(totalAcct).toLocaleString(undefined, { maximumFractionDigits: 0 })} total account`);
  }
  if (parts.length) {
    cashEl.textContent = parts.join(" · ");
    cashEl.classList.remove("hidden");
  } else {
    cashEl.classList.add("hidden");
  }

  const ret = portfolio.totals.return_pct;
  const retEl = $("total-return");
  retEl.textContent = `${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`;
  retEl.className = `pill ${ret >= 0 ? "pill-up" : "pill-down"}`;
  $("position-count").textContent = `${portfolio.holdings.length} position${portfolio.holdings.length !== 1 ? "s" : ""}`;
  updatePortfolioEmptyState();
}

function renderPortfolioActions(actions) {
  const panel = $("portfolio-actions");
  const list = $("actions-list");
  const empty = $("actions-empty");
  const sorted = [...(actions || [])]
    .sort((a, b) => (a.severity || 99) - (b.severity || 99))
    .slice(0, 4);
  if (!sorted.length) {
    panel?.classList.add("hidden");
    list.innerHTML = "";
    empty?.classList.remove("hidden");
    if (portfolioSubTab === "actions") requestAnimationFrame(clampMainScroll);
    return;
  }
  empty?.classList.add("hidden");
  panel?.classList.remove("hidden");
  list.innerHTML = sorted
    .map((a) => {
      const sev = a.severity || "?";
      return `<li class="action-item severity-${sev}">
        <span class="action-sev">${escapeHtml(String(sev))}</span>
        <div class="action-body">
          <div class="action-label">${inlineMd(a.label || "Action")}</div>
          <div class="action-detail">${inlineMd(a.detail || "")}</div>
        </div>
      </li>`;
    })
    .join("");
  attachGlossaryHandlers(list);
  if (portfolioSubTab === "actions") {
    requestAnimationFrame(clampMainScroll);
  }
}

async function refreshPortfolio() {
  try {
    portfolio = await request("/portfolio");
    cachePortfolio(portfolio);
    renderHero();
  } catch (e) {
    if (!portfolio) setError(e, { tab: "portfolio" });
  }
  updateHero();
}

let glossaryHideTimer = null;
let glossaryActiveEl = null;
let _glossaryPopBound = false;

// Keep the popover open while the pointer is inside it, so long (now scrollable)
// definitions can actually be read without the tooltip vanishing.
function bindGlossaryPopover() {
  if (_glossaryPopBound) return;
  const pop = $("glossary-popover");
  if (!pop) return;
  _glossaryPopBound = true;
  pop.addEventListener("mouseenter", () => clearTimeout(glossaryHideTimer));
  pop.addEventListener("mouseleave", hideGlossary);
}

function attachGlossaryHandlers(root) {
  if (!root) return;
  bindGlossaryPopover();
  root.querySelectorAll(".glossary-term").forEach((el) => {
    if (el.dataset.glossaryBound) return;
    el.dataset.glossaryBound = "1";
    // Hover/focus are enhancements; tap/click is the authoritative toggle so
    // touch users get a reliable open/close (and tap-away/Escape dismissal).
    el.addEventListener("mouseenter", showGlossary);
    el.addEventListener("focus", showGlossary);
    el.addEventListener("mouseleave", hideGlossary);
    el.addEventListener("blur", hideGlossary);
    el.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleGlossary(e);
    });
  });
}

function toggleGlossary(e) {
  const el = e.currentTarget;
  const pop = $("glossary-popover");
  const open = pop && !pop.classList.contains("hidden") && glossaryActiveEl === el;
  if (open) hideGlossaryNow();
  else showGlossary(e);
}

function showGlossary(e) {
  clearTimeout(glossaryHideTimer);
  const el = e.currentTarget;
  const pop = $("glossary-popover");
  glossaryActiveEl = el;
  const term = el.dataset.term || el.textContent;
  const def = el.dataset.def || GLOSSARY[term] || "";
  pop.innerHTML = `<strong>${escapeHtml(term)}</strong>${escapeHtml(def)}`;
  pop.classList.remove("hidden");
  requestAnimationFrame(() => {
    pop.classList.add("visible");
    const rect = el.getBoundingClientRect();
    pop.style.left = `${Math.min(Math.max(8, rect.left), window.innerWidth - 296)}px`;
    let top = rect.bottom + 8;
    const popRect = pop.getBoundingClientRect();
    if (top + popRect.height > window.innerHeight - 8) {
      top = Math.max(8, rect.top - popRect.height - 8);
    }
    pop.style.top = `${top}px`;
  });
}

function hideGlossary() {
  const pop = $("glossary-popover");
  if (!pop || pop.classList.contains("hidden")) return;
  pop.classList.remove("visible");
  glossaryHideTimer = setTimeout(() => {
    pop.classList.add("hidden");
    glossaryActiveEl = null;
  }, prefersReducedMotion() ? 0 : 200);
}

function hideGlossaryNow() {
  const pop = $("glossary-popover");
  if (!pop) return;
  clearTimeout(glossaryHideTimer);
  pop.classList.remove("visible");
  pop.classList.add("hidden");
  glossaryActiveEl = null;
}

function renderBriefRecap(synopses) {
  const el = $("brief-recap");
  if (!synopses?.length) {
    el.innerHTML = "";
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");
  el.innerHTML =
    `<p class="section-label">Recent mornings</p>` +
    synopses
      .map((s) => {
        const text = sanitizeContent(s.synopsis || "");
        const body = text ? md(text) : "";
        return `<div class="recap-day">
        <time datetime="${escapeHtml(s.brief_date)}">${escapeHtml(formatBriefDate(s.brief_date))}</time>
        ${body}
      </div>`;
      })
      .join("");
  attachGlossaryHandlers(el);
}

function applyBriefLanding(data, opts = {}) {
  const { fade = false } = opts;
  const hadBrief = briefHasToday();

  setBriefHydrateLoading(false);

  if (data.has_today && data.today?.content) {
    briefLandingMeta = data.today;
    const updated = formatTimestamp(data.today.created_at);
    $("brief-updated").textContent = updated ? `Last updated ${updated}` : "";
    $("content-brief").innerHTML = mdBrief(data.today.content);
    $("content-brief").classList.remove("hidden");
    $("empty-brief").classList.add("hidden");
    $("btn-brief").classList.add("hidden");
    $("brief-recap").classList.add("hidden");
    $("brief-tabs").classList.remove("hidden");
    updateMiniBriefCta(true);
    $("loading").classList.add("hidden");
    const mini = data.today.mini_brief;
    if (mini) {
      $("content-mini-brief").innerHTML =
        `<p class="mini-brief-label">Late-day update</p>${md(mini)}`;
      $("content-mini-brief").classList.remove("hidden");
      updateMiniBriefCta(true);
    } else {
      $("content-mini-brief").classList.add("hidden");
      $("content-mini-brief").innerHTML = "";
    }
    attachGlossaryHandlers($("content-brief"));
    attachGlossaryHandlers($("content-mini-brief"));
    attachBriefNavHandlers($("content-brief"));
    setBriefSubTab("today");
    if (fade && !hadBrief) {
      fadeBriefEl($("brief-tabs"));
      fadeBriefEl($("content-mini-brief"));
      fadeBriefEl($("content-brief"));
    }
  } else {
    briefLandingMeta = null;
    $("brief-updated").textContent = "";
    $("content-brief").innerHTML = "";
    $("content-brief").classList.add("hidden");
    updateMiniBriefCta(false);
    $("content-mini-brief").classList.add("hidden");
    renderBriefRecap(data.synopses || []);
    $("empty-brief").classList.remove("hidden");
    $("btn-brief").classList.remove("hidden");
    if ((data.synopses || []).length) $("brief-tabs").classList.remove("hidden");
    if (fade) fadeBriefEl($("empty-brief"));
  }
  if ((data.archive_dates || []).length) {
    renderArchiveDateList(data.archive_dates, archiveSelectedDate);
  }
  if (tab === "brief") refreshPanelUI();
}

async function loadBriefLanding() {
  const cached = readBriefCache();
  if (!briefHasToday()) {
    setBriefHydrateLoading(true, briefHydrateLabel(cached || {}));
  }
  try {
    const data = await request("/brief/recap");
    cacheBriefLanding(data);
    const hadBrief = briefHasToday();
    applyBriefLanding(data, { fade: !hadBrief });
  } catch {
    if (!briefHasToday()) {
      setBriefHydrateLoading(false);
      $("empty-brief").classList.remove("hidden");
      if (!backendOnline) setOfflineEmptyCopy();
    }
  }
}

async function loadArchiveDates() {
  try {
    const { dates } = await request("/brief/archive/dates");
    renderArchiveDateList(dates || [], dates?.[0]);
    if (dates?.length) await loadArchiveBrief(dates[0]);
  } catch {
    /* ignore */
  }
}

async function loadArchiveBrief(date) {
  if (!date) return;
  archiveSelectedDate = date;
  const el = $("content-archive");
  el.classList.add("hidden");
  try {
    const row = await request(`/brief/archive/${encodeURIComponent(date)}`);
    el.innerHTML = mdBrief(row.content || "");
    el.classList.remove("hidden");
    attachGlossaryHandlers(el);
    attachBriefNavHandlers(el);
    fadePanelEl(el);
  } catch (e) {
    setError(e, { tab: "brief" });
  }
}

async function loadMiniBrief() {
  if (miniBriefLoading) return;
  miniBriefLoading = true;
  const btn = $("btn-mini-brief");
  setButtonLoading(btn, true);
  setMiniBriefLoading(true);
  setError("", { tab: "brief" });
  try {
    const data = await request("/brief/mini", { method: "POST" });
    $("content-mini-brief").innerHTML =
      `<p class="mini-brief-label">Late-day update</p>${md(data.content || "")}`;
    $("content-mini-brief").classList.remove("hidden");
    fadeBriefEl($("content-mini-brief"));
    attachGlossaryHandlers($("content-mini-brief"));
    updateMiniBriefCta(true);
    showToast("Late-day update is ready");
    try {
      const landing = await request("/brief/recap");
      cacheBriefLanding(landing);
    } catch {
      /* ignore cache refresh */
    }
  } catch (e) {
    setError(e, { tab: "brief", toast: true });
  } finally {
    setMiniBriefLoading(false);
    setButtonLoading(btn, false);
    miniBriefLoading = false;
  }
}

async function loadPicksYesterday() {
  try {
    const { yesterday } = await request("/picks/landing");
    yesterdayPicksData = yesterday;
    yesterdayPicksExpanded = false;
    renderPicksYesterday();
  } catch {
    yesterdayPicksData = null;
    $("picks-yesterday").classList.add("hidden");
  }
}

function renderPicksYesterday() {
  const wrap = $("picks-yesterday");
  const body = $("picks-yesterday-body");
  const moreBtn = $("btn-picks-yesterday-more");
  const data = yesterdayPicksData;
  if (!data?.preview && !data?.synopsis) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  const labelDate = data.pick_date ? formatBriefDate(data.pick_date) : "Previous session";
  if (yesterdayPicksExpanded && data.content) {
    body.innerHTML =
      `<p class="section-label">Yesterday's top picks · ${escapeHtml(labelDate)}</p>` +
      `<div class="picks-yesterday-full prose">${md(data.content)}</div>`;
    moreBtn.classList.add("hidden");
    attachGlossaryHandlers(body);
    fadePanelEl(body);
    return;
  }
  const preview = sanitizeContent(data.preview || data.synopsis || "");
  body.innerHTML =
    `<p class="section-label">Yesterday's top picks · ${escapeHtml(labelDate)}</p>` +
    `<p class="landing-body">${inlineMd(preview)}</p>`;
  attachGlossaryHandlers(body);
  const showMore = Boolean(data.content && data.content.length > preview.length) || Boolean(data.truncated);
  moreBtn.classList.toggle("hidden", !showMore);
  moreBtn.textContent = "See yesterday's full picks";
}

async function loadPicksCached() {
  if (picksHasToday()) return;
  const cached = readPicksCache();
  if (cached) {
    applyPicksContent(cached, { fade: true });
    return;
  }
  setPicksHydrateLoading(true, "Loading today's picks…");
  try {
    const data = await request("/picks/today");
    if (data.cached && data.content?.trim()) {
      picksMeta = data;
      applyPicksContent(data.content, { fade: true });
    } else {
      setPicksHydrateLoading(false);
      showPicksEmptyState(true);
      if (!backendOnline) setOfflineEmptyCopy();
    }
  } catch {
    setPicksHydrateLoading(false);
    showPicksEmptyState(true);
    if (!backendOnline) setOfflineEmptyCopy();
  }
}

async function loadExploreLanding() {
  const cached = readExploreLandingCache();
  if (cached) renderExploreLandingData(cached);
  try {
    const data = await request("/explore/landing");
    cacheExploreLanding(data);
    renderExploreLandingData(data);
  } catch {
    if (!cached && !$("explore-quick-markets").innerHTML.trim()) {
      $("explore-quick-markets").innerHTML =
        `<p class="section-label">Quick explore</p><p class="landing-muted">Headlines aren't available right now — try again in a moment.</p>`;
    }
  }
}

async function refreshWatchlist() {
  try {
    const { items } = await request("/watchlist");
    watchlistTickers.clear();
    items.forEach((w) => watchlistTickers.add(w.ticker.toUpperCase()));
    preloadLogos(items.map((w) => w.ticker));
    const list = $("watchlist-list");
    if (!items.length) {
      list.innerHTML = '<li class="watchlist-empty">Your watchlist is empty.</li>';
      return;
    }
    list.innerHTML = items
      .map(
        (w) => `<li>
        ${stockLogoHtml(w.ticker, w.logo_url)}
        <div class="holding-body">
          <div class="holding-ticker">${escapeHtml(w.name || w.ticker)} <span class="watch-ticker-tag">(${escapeHtml(w.ticker)})</span></div>
          <div class="holding-sub">${w.price != null ? `$${Number(w.price).toFixed(2)}` : "—"}${w.notes ? ` · ${escapeHtml(w.notes)}` : ""}</div>
        </div>
        <button type="button" class="btn-remove" data-ticker="${escapeHtml(w.ticker)}" title="Remove">×</button>
      </li>`
      )
      .join("");
    attachLogoFallbacks(list);
  } catch (e) {
    setError(e, { tab: "picks" });
  }
}

let watchSearchTimer = null;

function formatPrice(p) {
  if (p == null) return "—";
  return `$${Number(p).toFixed(2)}`;
}

function formatProjection(pct) {
  if (pct == null) return "—";
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}% est.`;
}

function renderSearchResults(results) {
  const el = $("watch-search-results");
  if (!results.length) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  el.classList.remove("hidden");
  el.innerHTML = results
    .map((r) => {
      const sym = r.ticker.toUpperCase();
      const onList = watchlistTickers.has(sym) || watchlistPending.has(sym);
      const buy = r.buy_score != null ? `${r.buy_score}% buy` : "—";
      return `<button type="button" class="search-result${onList ? " search-result-added" : ""}" data-pick-ticker="${escapeHtml(r.ticker)}"${onList ? " disabled" : ""}>
        ${stockLogoHtml(r.ticker, r.logo_url)}
        <div class="search-result-body">
          <div class="search-name">${escapeHtml(r.name)} <span class="search-ticker">(${escapeHtml(r.ticker)})</span></div>
          <div class="search-metrics">
            <span>${formatPrice(r.price)}</span>
            <span>${formatProjection(r.projection_pct)}</span>
            <span class="search-buy">${escapeHtml(buy)}</span>
          </div>
        </div>
        <span class="search-add-label">${onList ? "Added" : "Add"}</span>
      </button>`;
    })
    .join("");
  attachLogoFallbacks(el);
}

async function runWatchSearch() {
  const q = $("watch-search").value.trim();
  if (q.length < 1) {
    renderSearchResults([]);
    return;
  }
  try {
    const { results } = await request(`/symbols/search?q=${encodeURIComponent(q)}&limit=8&lite=true`);
    renderSearchResults(results || []);
    preloadLogos((results || []).map((r) => r.ticker));
  } catch {
    renderSearchResults([]);
  }
}

function addWatch(ticker, notes = "", source = "manual", opts = {}) {
  const sym = ticker.toUpperCase();
  if (watchlistTickers.has(sym) || watchlistPending.has(sym)) {
    if (!opts.silent) showToast(`${sym} is already on your watchlist`);
    return;
  }
  watchlistPending.add(sym);

  const btn = document.querySelector(`[data-pick-ticker="${sym}"]`);
  if (btn) {
    btn.disabled = true;
    btn.classList.add("search-result-added");
    const lbl = btn.querySelector(".search-add-label");
    if (lbl) lbl.textContent = "Added";
  }

  showToast(`${sym} added to your watchlist`);
  setError("", { tab: "picks" });
  watchlistTickers.add(sym);

  if (opts.clearSearch) {
    $("watch-search").value = "";
    renderSearchResults([]);
  }

  request("/watchlist", {
    method: "POST",
    body: JSON.stringify({ ticker: sym, notes, source }),
  })
    .then(() => {
      if (opts.switchToWatchlist) setPicksSubTab("watchlist");
      refreshWatchlist();
    })
    .catch((e) => {
      watchlistTickers.delete(sym);
      watchlistPending.delete(sym);
      if (btn) {
        btn.disabled = false;
        btn.classList.remove("search-result-added");
        const lbl = btn.querySelector(".search-add-label");
        if (lbl) lbl.textContent = "Add";
      }
      setError(e, { tab: "picks", toast: true });
    })
    .finally(() => watchlistPending.delete(sym));
}

async function removeWatch(ticker) {
  try {
    await request(`/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" });
    await refreshWatchlist();
  } catch (e) {
    setError(e);
  }
}

async function loadBrief(force = false) {
  if (briefGenerating) return;
  setTab("brief");
  setBriefSubTab("today");

  if (!force) {
    try {
      const landing = await request("/brief/recap");
      if (landing.has_today && landing.today?.content) {
        applyBriefLanding(landing);
        return;
      }
    } catch {
      /* continue to generate */
    }
  }

  briefGenerating = true;
  setButtonLoading($("btn-brief"), true);
  setBriefLoading(true, 5, "Getting started…");
  $("empty-brief").classList.add("hidden");
  $("brief-recap").classList.add("hidden");
  try {
    const start = await request(`/brief/start?force=${force}`, { method: "POST" });
    if (start.cached) {
      const job = await request("/brief/compose-progress");
      const content = job.result?.content || "";
      if (content.trim()) showTabContent("brief", content);
      await loadBriefLanding();
      return;
    }
    if (!start.started) {
      const running = await request("/brief/compose-progress");
      if (running.done && running.result?.content?.trim()) {
        showTabContent("brief", running.result.content);
        await loadBriefLanding();
        return;
      }
      if (!running.running) {
        throw new Error(humanizeMessage(running.error || running.message || "Couldn't start your brief — try again."));
      }
    }
    const job = await pollJob("/brief/compose-progress", (j) => {
      setBriefLoading(true, j.progress ?? 0, humanizeProgressMessage(j.message || "Writing your morning brief…"));
    });
    const content = job.result?.content || "";
    if (content.trim()) {
      showTabContent("brief", content);
      pingGenerationDone("brief");
    } else {
      throw new Error(humanizeMessage(job.error || job.message || "Your brief didn't finish — try again."));
    }
    refreshPortfolio();
    await loadBriefLanding();
  } catch (e) {
    setError(e, { tab: "brief", retry: () => loadBrief(force) });
    await loadBriefLanding();
  } finally {
    setBriefLoading(false);
    setButtonLoading($("btn-brief"), false);
    briefGenerating = false;
  }
}

async function loadPicks(force = false) {
  if (picksLoading) return;
  setTab("picks");
  setPicksSubTab("today");

  if (!force) {
    const cached = readPicksCache() || picksCache;
    if (cached?.trim()) {
      applyPicksContent(cached, { fade: false });
      return;
    }
  }

  picksLoading = true;
  const btn = force ? $("btn-refresh-picks") : $("btn-picks");
  setButtonLoading(btn, true);
  $("content-picks").classList.add("hidden");
  setPicksProgress(true, 5, force ? "Refreshing today's picks…" : "Finding today's best ideas…");
  try {
    const start = await request(`/picks/start?force=${force}`, { method: "POST" });
    if (start.cached) {
      const job = await request("/picks/progress");
      const content = sanitizeContent(job.result?.content || "");
      if (content) {
        picksMeta = job.result;
        applyPicksContent(content, { fade: true });
        return;
      }
    }
    if (!start.started) {
      const job = await request("/picks/progress");
      if (job.done && job.result?.content?.trim()) {
        picksMeta = job.result;
        applyPicksContent(sanitizeContent(job.result.content), { fade: true });
        return;
      }
      if (!job.running) {
        throw new Error(humanizeMessage(job.error || job.message || "Couldn't load today's picks — try again."));
      }
    }
    const job = await pollJob("/picks/progress", (j) => {
      setPicksProgress(true, j.progress ?? 0, humanizeProgressMessage(j.message || "Ranking today's ideas…"));
    });
    const content = sanitizeContent(job.result?.content || "");
    if (!content) throw new Error("Today's picks didn't come through — try again.");
    if (content.startsWith("**Setup required:**") || content.startsWith("**API key rejected:**")) {
      throw new Error(humanizeMessage(content.replace(/\*\*/g, "").split("\n")[0]));
    }
    picksMeta = job.result;
    applyPicksContent(content, { fade: true });
    pingGenerationDone("picks");
  } catch (e) {
    setPicksProgress(false);
    showPicksEmptyState(true);
    setError(e, { tab: "picks", retry: () => loadPicks(force) });
  } finally {
    setPicksProgress(false);
    setButtonLoading(btn, false);
    picksLoading = false;
  }
}

async function loadPortfolioAnalysisCached() {
  try {
    const data = await request("/portfolio/analysis?force=false");
    if (data?.content?.trim()) {
      portfolioAnalysis = data;
      showTabContent("portfolio", data);
    }
  } catch {
    /* no cached analysis yet */
  }
}

async function loadPortfolioAnalysis(force = false) {
  if (portfolioAnalysisRunning) return;

  if (!force && portfolioAnalysis?.content?.trim()) {
    setTab("portfolio");
    showTabContent("portfolio", portfolioAnalysis);
    return;
  }

  portfolioAnalysisRunning = true;
  setTab("portfolio");
  setPortfolioSubTab("analysis");
  const btn = force ? $("btn-refresh-portfolio-analysis") : $("btn-portfolio-analysis");
  setButtonLoading(btn, true);
  setPortfolioLoading(true, 5, "Getting started…");
  $("content-portfolio").classList.add("hidden");
  requestAnimationFrame(() => scrollPortfolioToAnalysis());
  try {
    const start = await request(`/portfolio/analysis/start?force=${force}`, { method: "POST" });
    if (start.cached) {
      const job = await request("/portfolio/analysis/progress");
      if (job.result?.content?.trim()) {
        portfolioAnalysis = job.result;
        showTabContent("portfolio", job.result, { scrollToAnalysis: true });
        return;
      }
    }
    if (!start.started) {
      const running = await request("/portfolio/analysis/progress");
      if (running.done && running.result?.content?.trim()) {
        portfolioAnalysis = running.result;
        showTabContent("portfolio", running.result, { scrollToAnalysis: true });
        return;
      }
      if (!running.running) {
        throw new Error(humanizeMessage(running.error || running.message || "Couldn't run portfolio analysis — try again."));
      }
    }
    const job = await pollJob("/portfolio/analysis/progress", (j) => {
      setPortfolioLoading(true, j.progress ?? 0, humanizeProgressMessage(j.message || "Reviewing your holdings…"));
    });
    if (job.result?.content?.trim()) {
      portfolioAnalysis = job.result;
      showTabContent("portfolio", job.result, { scrollToAnalysis: true });
      pingGenerationDone("portfolio");
    } else {
      throw new Error(humanizeMessage(job.error || job.message || "Portfolio analysis didn't finish — try again."));
    }
    refreshPortfolio();
  } catch (e) {
    setError(e, { tab: "portfolio", retry: () => loadPortfolioAnalysis(force) });
  } finally {
    setPortfolioLoading(false);
    setButtonLoading(btn, false);
    portfolioAnalysisRunning = false;
    updatePortfolioEmptyState();
  }
}

async function resumeBriefJobIfNeeded() {
  if (briefGenerating) return;
  try {
    const job = await request("/brief/compose-progress");
    if (!job.running) return;
    briefGenerating = true;
    setBriefLoading(true, job.progress ?? 0, humanizeProgressMessage(job.message || "Writing your morning brief…"));
    const done = await pollJob("/brief/compose-progress", (j) => {
      setBriefLoading(true, j.progress ?? 0, humanizeProgressMessage(j.message || "Writing your morning brief…"));
    });
    if (done.result?.content?.trim()) {
      if (tab === "brief") showTabContent("brief", done.result.content);
      await loadBriefLanding();
      pingGenerationDone("brief");
    } else if (done.error) {
      setError(done.error, { tab: "brief", retry: resumeBriefJobIfNeeded });
    }
  } catch (e) {
    setError(e || new Error("Your brief didn't finish — try again."), { tab: "brief", retry: resumeBriefJobIfNeeded });
  } finally {
    briefGenerating = false;
    setBriefLoading(false);
  }
}

async function resumePortfolioJobIfNeeded() {
  if (portfolioAnalysisRunning) return;
  try {
    const job = await request("/portfolio/analysis/progress");
    if (!job.running) return;
    portfolioAnalysisRunning = true;
    setPortfolioLoading(true, job.progress ?? 0, humanizeProgressMessage(job.message || "Reviewing your holdings…"));
    const done = await pollJob("/portfolio/analysis/progress", (j) => {
      setPortfolioLoading(true, j.progress ?? 0, humanizeProgressMessage(j.message || "Reviewing your holdings…"));
    });
    if (done.result?.content?.trim()) {
      portfolioAnalysis = done.result;
      if (tab === "portfolio") showTabContent("portfolio", done.result, { scrollToAnalysis: true });
      pingGenerationDone("portfolio");
    } else if (done.error) {
      setError(done.error, { tab: "portfolio", retry: resumePortfolioJobIfNeeded });
    }
  } catch (e) {
    setError(e || new Error("Portfolio analysis didn't finish — try again."), {
      tab: "portfolio",
      retry: resumePortfolioJobIfNeeded,
    });
  } finally {
    portfolioAnalysisRunning = false;
    setPortfolioLoading(false);
  }
}

async function resumePicksJobIfNeeded() {
  if (picksLoading) return;
  try {
    const job = await request("/picks/progress");
    if (!job.running) return;
    picksLoading = true;
    setPicksProgress(true, job.progress ?? 0, humanizeProgressMessage(job.message || "Ranking today's ideas…"));
    const done = await pollJob("/picks/progress", (j) => {
      setPicksProgress(true, j.progress ?? 0, humanizeProgressMessage(j.message || "Ranking today's ideas…"));
    });
    const content = sanitizeContent(done.result?.content || "");
    if (content) {
      picksMeta = done.result;
      if (tab === "picks") applyPicksContent(content, { fade: true });
      pingGenerationDone("picks");
    } else if (done.error) {
      setError(done.error, { tab: "picks", retry: resumePicksJobIfNeeded });
      if (tab === "picks") showPicksEmptyState(true);
    }
  } catch (e) {
    setError(e || new Error("Today's picks didn't finish — try again."), { tab: "picks", retry: resumePicksJobIfNeeded });
    if (tab === "picks") showPicksEmptyState(true);
  } finally {
    picksLoading = false;
    setPicksProgress(false);
  }
}

async function loadExplore(marketOverride) {
  if (exploreRunning) return;
  const q = (typeof marketOverride === "string" ? marketOverride : $("explore-input").value).trim();
  if (!q) {
    setError("Type a sector or theme to explore — like semiconductors or energy.", { tab: "explore" });
    scrollExploreToSheet();
    return;
  }
  $("explore-input").value = q;
  setTab("explore");
  setExploreSubTab("explore");
  requestAnimationFrame(() => scrollExploreToSheet());

  const cacheKey = q.toLowerCase();
  if (exploreCache[cacheKey]) {
    const item = loadExploreStore().find((i) => i.market.toLowerCase() === cacheKey);
    showExploreContent(exploreCache[cacheKey], { fade: true, cached: true, date: item?.date });
    return;
  }

  exploreRunning = true;
  $("content-explore").classList.add("hidden");
  setExploreControlsLoading(true);
  setExploreLoading(true, 8, `Researching ${q}…`);

  try {
    const start = await request("/explore/start", {
      method: "POST",
      body: JSON.stringify({ market: q }),
    });
    if (!start.started) {
      const running = await request("/explore/progress");
      if (!running.running && running.done && running.result?.content) {
        const content = sanitizeContent(running.result.content);
        saveExploreToStore(q, content);
        showExploreContent(content, { fade: true });
        return;
      }
      if (running.running) {
        /* join in-progress job */
      } else {
        throw new Error("Couldn't run that exploration — try again.");
      }
    }
    const job = await pollJob("/explore/progress", (j) => {
      setExploreLoading(true, j.progress ?? 0, humanizeProgressMessage(j.message || `Researching ${q}…`));
    });
    if (job.error) throw new Error(humanizeMessage(job.error));
    const content = sanitizeContent(job.result?.content || "");
    if (!content) {
      throw new Error("That exploration didn't come through — try again.");
    }
    saveExploreToStore(q, content);
    setExploreLoading(true, 100, "Ready");
    showExploreContent(content, { fade: true, cached: false });
    pingGenerationDone("explore");
  } catch (e) {
    setError(e || new Error("That exploration didn't finish — try again."), { tab: "explore", retry: () => loadExplore(q) });
    setExploreLoading(false);
  } finally {
    setExploreLoading(false);
    setExploreControlsLoading(false);
    exploreRunning = false;
  }
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    const t = btn.dataset.tab;
    const switched = t !== tab;
    setTab(t);
    if (t === "brief") {
      if (switched) loadBriefLanding();
      resumeBriefJobIfNeeded();
    }
    if (t === "explore") {
      if (switched) {
        if (!readExploreLandingCache()) loadExploreLanding();
        else if (!$("explore-quick-markets").innerHTML.trim()) renderExploreLandingData(readExploreLandingCache());
      }
      renderExplorePastList();
    }
    if (t === "portfolio") {
      if (switched) {
        if (!portfolio) refreshPortfolio();
        else renderHero();
      }
      resumePortfolioJobIfNeeded();
      if (portfolioAnalysis?.content?.trim()) {
        parsePortfolioTickerSections(portfolioAnalysis.content);
        renderPortfolioHoldingsTable();
        renderPortfolioActions(portfolioAnalysis?.actions || []);
        $("btn-refresh-portfolio-analysis").classList.remove("hidden");
      } else if (switched) {
        loadPortfolioAnalysisCached();
      }
    }
    if (t === "picks") {
      if (switched) {
        loadPicksYesterday();
        if (!picksHasToday()) loadPicksCached();
      }
      resumePicksJobIfNeeded();
      if (switched || picksSubTab === "watchlist") refreshWatchlist();
    }
  });
});

document.querySelectorAll("[data-picks-sub]").forEach((btn) => {
  btn.addEventListener("click", () => setPicksSubTab(btn.dataset.picksSub));
});

document.querySelectorAll("[data-brief-sub]").forEach((btn) => {
  btn.addEventListener("click", () => setBriefSubTab(btn.dataset.briefSub));
});

document.querySelectorAll("[data-explore-sub]").forEach((btn) => {
  btn.addEventListener("click", () => setExploreSubTab(btn.dataset.exploreSub));
});

document.querySelectorAll("[data-portfolio-sub]").forEach((btn) => {
  btn.addEventListener("click", () => setPortfolioSubTab(btn.dataset.portfolioSub));
});

$("btn-picks-yesterday-more")?.addEventListener("click", () => {
  yesterdayPicksExpanded = true;
  renderPicksYesterday();
});

$("btn-brief").addEventListener("click", () => loadBrief(true));
$("btn-refresh-brief")?.addEventListener("click", () => loadBrief(true));
$("btn-mini-brief").addEventListener("click", loadMiniBrief);
$("btn-picks").addEventListener("click", () => loadPicks(true));
$("btn-refresh-picks").addEventListener("click", () => loadPicks(true));
$("btn-portfolio-analysis").addEventListener("click", () => loadPortfolioAnalysis(false));
$("btn-refresh-portfolio-analysis").addEventListener("click", () => loadPortfolioAnalysis(true));
$("btn-actions-run-analysis")?.addEventListener("click", () => {
  setPortfolioSubTab("analysis");
  loadPortfolioAnalysis(false);
});
$("btn-sync-robinhood")?.addEventListener("click", () => {
  syncRobinhoodPortfolio(true).catch((e) => setError(e, { tab: "portfolio", toast: true }));
});
$("btn-refresh-holdings")?.addEventListener("click", refreshHoldingsLive);
$("btn-error-retry")?.addEventListener("click", () => {
  if (errorRetryFn) errorRetryFn();
});
$("btn-explore").addEventListener("click", () => loadExplore());
$("explore-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") loadExplore();
});

$("watchlist-list").addEventListener("click", (e) => {
  const rm = e.target.closest(".btn-remove");
  if (rm) {
    e.preventDefault();
    e.stopPropagation();
    const ticker = rm.getAttribute("data-ticker");
    if (ticker) removeWatch(ticker);
  }
});

$("watch-search-results").addEventListener("click", (e) => {
  const pick = e.target.closest("[data-pick-ticker]");
  if (!pick || pick.disabled) return;
  const ticker = pick.getAttribute("data-pick-ticker");
  if (ticker) addWatch(ticker, "", "search", { clearSearch: true });
});

$("watch-search").addEventListener("input", () => {
  clearTimeout(watchSearchTimer);
  watchSearchTimer = setTimeout(runWatchSearch, 220);
});

$("watch-search").addEventListener("keydown", (e) => {
  if (e.key === "Escape") renderSearchResults([]);
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".symbol-search")) renderSearchResults([]);
});

// Tap-away: any click outside a glossary term and outside the popover dismisses
// it. Term clicks stopPropagation (they toggle) and popover-internal clicks are
// preserved so definitions stay readable/scrollable.
document.addEventListener("click", (e) => {
  if (e.target.closest(".glossary-term") || e.target.closest("#glossary-popover")) return;
  hideGlossaryNow();
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || activeHoldingModalTicker) return;
  hideGlossaryNow();
});

hydratePortfolioCache();
hydrateExploreCache();
const _exploreLandingCached = readExploreLandingCache();
if (_exploreLandingCached) renderExploreLandingData(_exploreLandingCached);
initBriefPanelState();
initPicksPanelState();
bindButtonPressFeedback();
attachHoldingModalHandlers();

(async function init() {
  const healthP = (async () => {
    if (await pingBackend()) return;
    for (let i = 0; i < 5; i++) {
      await sleep(800);
      if (await pingBackend()) return;
    }
  })();

  const portfolioP = refreshPortfolio();

  const syncP = syncRobinhoodPortfolio(false).catch(() => {});

  await Promise.all([healthP, portfolioP, syncP]);
  setInterval(pingBackend, 25000);
  request("/research/start", { method: "POST" }).catch(() => {});
  refreshWatchlist();
  loadBriefLanding();
  loadPicksYesterday();
  loadExploreLanding();
  resumePortfolioJobIfNeeded();
  resumePicksJobIfNeeded();
  resumeBriefJobIfNeeded();
  bindButtonPressFeedback($("explore-quick-markets"));
})();

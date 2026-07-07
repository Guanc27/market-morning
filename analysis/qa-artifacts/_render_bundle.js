var _glossarySeen = null;

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

function mdBrief(text) {
  return scrubRenderedHtml(wrapBriefSections(md(normalizeBriefTitles(text))));
}

function mdExplore(text) {
  return scrubRenderedHtml(wrapExploreSections(md(text, { cardTables: true })));
}

function mdPortfolio(text) {
  return scrubRenderedHtml(wrapMoneyAmounts(md(text)));
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
  // Unordered analog of the ordered-list fix above: models also glue a bullet
  // marker straight onto bold ("-**MRK**— …" / "+**MRK**"), which lacks the
  // space `/^[-*] /` needs — so the whole run collapses into one <p> with
  // literal leading dashes instead of a <ul>. Insert the missing space (and
  // canonicalize the marker to "- ") only when the marker is glued to a bold
  // run (** / __) or a word, so "- item" bullets, "-5%" negatives, em-dashes,
  // and "---" rules stay untouched. "*" is intentionally excluded: a leading
  // "*"/"**" is emphasis syntax, so normalizing it would corrupt real bold.
  src = src.replace(/^(\s*)[-+](?=\*\*|__|[A-Za-z])/gm, "$1- ");
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

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
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

function spaceGluedBold(html) {
  if (!html || html.indexOf("<strong>") === -1) return html;
  return html
    .replace(/([A-Za-z0-9.,)])(<strong>)/g, "$1 $2")
    .replace(/(<\/strong>)([A-Za-z0-9([])/g, "$1 $2");
}

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

function wrapMoneyAmounts(html) {
  if (!html) return "";
  return html.replace(
    /\$(\d[\d,]*(?:\.\d{1,2})?)/g,
    (_, amount) => `<span class="price-amt"><span class="price-currency">$</span>${amount}</span>`
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

function wrapExploreSections(html) {
  if (!html?.includes("<h2>")) return html;
  const chunks = html.split(/(?=<h2>)/).filter((c) => c.trim());
  if (!chunks.some((c) => c.startsWith("<h2>"))) return html;
  return `<div class="explore-sections">${chunks
    .map((part) => `<section class="explore-section">${part}</section>`)
    .join("")}</div>`;
}

function normalizeBriefTitles(text) {
  return String(text || "").replace(
    /International Opportunities\s*&\s*Geopolitical Trades/gi,
    "Geopolitical Trades"
  );
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

function isTableLine(line) {
  const t = line.trim();
  return t.startsWith("|") && t.includes("|");
}

function isTableSep(line) {
  return /^\|?\s*:?-{2,}/.test(line.trim());
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

function cleanupStrayMarkdownHeaders(html) {
  return scrubTermArtifacts(
    html
      .replace(/<p>\s*#{4,6}\s*([^<]+?)<\/p>/gi, '<h4 class="ticker-heading">$1</h4>')
      .replace(/(?:^|\n)\s*#{4,6}\s+([A-Z][A-Z0-9.\-]{0,12})\s*(?=\n|$)/g, '\n<h4 class="ticker-heading">$1</h4>\n')
  );
}

function stripTradeSections(text) {
  return sanitizeContent(text)
    .replace(/\*\*Trade Plan:\*\*[^\n]*(\n(?!\n|#)[^\n]*)*/gi, "")
    .replace(/^#{1,3}\s*Trade Plan[^\n]*\n([\s\S]*?)(?=\n#{1,3}\s|\n\*\*[A-Z]|$)/gim, "");
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

function processTermTags(text) {
  return text.replace(/<term id="([^"]+)">([^<]*)<\/term>/gi, (_, id, label) => termToken(id, label));
}

function termToken(id, label) {
  return `@@TERM[${id}]${label}@END@`;
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
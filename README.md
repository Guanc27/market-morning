# Market Morning

Chrome side-panel extension + local Python backend for AI-powered morning market briefs, portfolio analysis, and stock research.

Inspired by **Minna Bank** (minimal B&W, high contrast, one-task-per-screen) and **Sumeria** (soft grain texture). Built for **Robinhood** investors (US equities & ETFs).

## Features

1. **Morning Brief** — Auto-runs on first open each day: portfolio performance, ~10 min market read, recommended actions
2. **Top 5 Picks** — AI-screened stocks with metrics from [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit)
3. **Explore Market** — Deep-dive any sector/theme (e.g. "semiconductors")
4. **Portfolio Memory** — Tell it what you bought/sold in plain English; it remembers. CSV import from Robinhood supported.

## Quick start

### 1. Add your Anthropic API key

```bash
cp backend/.env.example backend/.env
# Edit backend/.env → set ANTHROPIC_API_KEY=sk-ant-...
# Or keep MOCK_MODE=1 for demo data (no API key needed)
```

Optional: set `FMP_API_KEY` for richer fundamentals (FinanceToolkit). Without it, Yahoo Finance is used.

### 2. Start the backend (pick one)

**Set-and-forget (recommended — no terminal after this):**

```bash
chmod +x scripts/install-launchagent.sh
./scripts/install-launchagent.sh
```

Runs on every login, restarts if it crashes. Uninstall: `./scripts/uninstall-launchagent.sh`

**Dev mode (terminal must stay open):**

```bash
chmod +x scripts/dev.sh
./scripts/dev.sh
```

Tampermonkey / userscripts **cannot** run the Python backend — they only run JS inside web pages. The extension talks to a local server on port 8742, which must be started separately (LaunchAgent above) or hosted in the cloud.

### 3. Load in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select `extension/dist`
4. **Pin** the extension icon to your toolbar (puzzle piece → pin)
5. Click the icon to open the side panel

**Keep the panel on startup:** Chrome blocks extensions from auto-opening the side panel without a click (security policy). Best workarounds:
- **Pin the panel** — open it once, then click the **pin icon** in Chrome's side panel header (stays open across tabs)
- **Keyboard shortcut** — `Alt+M` (Mac: `Cmd+Shift+M`), or set your own at `chrome://extensions/shortcuts`

## Portfolio updates (natural language)

In the **Portfolio** tab, type things like:

- `Bought 10 shares of AAPL at 185`
- `Sold all my TSLA`
- `Added 5 NVDA, cost basis around 120`

The backend parses via Claude and updates its internal portfolio database.

## Architecture

```
extension/          Chrome MV3 side panel (React + Vite)
backend/            FastAPI + FinanceToolkit + Anthropic
  app/finance.py    Market data & metrics (Yahoo Finance fallback)
  app/ai.py         Claude summaries & NL portfolio parsing
  app/db.py         SQLite portfolio + memory + daily briefs
```

## FinanceToolkit note

[FinancePortfolio](https://github.com/JerBouma/FinancePortfolio) is still pre-release on PyPI, so this MVP implements portfolio tracking directly and uses **FinanceToolkit** for ratios, performance, and risk metrics — the same library FinancePortfolio integrates with.

## Disclaimer

This is informational software, not financial advice. Always verify data and decisions independently.

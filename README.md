# Hosted SaaS standalone app — see docs/SUBSCRIPTIONS.md and scripts/run-saas.sh

A menu bar sun icon opens a floating panel with your equity snapshot, sector brief, top picks, market explore, and quant portfolio analytics. A local Python backend on `127.0.0.1:8742` handles market data, Robinhood sync, and Claude summaries.

Inspired by **Minna Bank** (minimal, high contrast) and **Sumeria** (soft grain, dark green palette). Built for **Robinhood** investors (US equities & ETFs).

**Requires macOS 13+**

## Features

| Tab | What you get |
|-----|----------------|
| **Brief** | Daily sector-wide morning brief + optional late-day update |
| **Picks** | AI-screened top picks with fundamentals from [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) |
| **Explore** | Deep-dive any sector or theme (e.g. semiconductors, biotech) |
| **Portfolio** | Live quant analysis from synced Robinhood holdings — technicals, fundamentals, ranked actions |

Holdings sync from Robinhood via MCP when configured. Portfolio analysis runs on demand and caches locally.

## Hosted SaaS (standalone web app)

Market Morning can run as a **subscription-hosted web app** with tiered access (portfolio AI + picks = premium). See [docs/SUBSCRIPTIONS.md](docs/SUBSCRIPTIONS.md) for pricing rationale vs Claude Pro / DIY API.

```bash
# Set ANTHROPIC_API_KEY in backend/.env (platform key — you pay inference)
export SAAS_MODE=1
./scripts/run-saas.sh
# Open http://localhost:8742/app
```

Docker: `docker compose up --build`

| Tier | Price | Highlights |
|------|-------|------------|
| **Reader** | Free | Daily brief (shared), holdings view, picks preview |
| **Investor** | $22/mo | Daily picks, 4× portfolio AI/mo, Robinhood sync |
| **Active Trader** | $49/mo | Daily portfolio AI, unlimited explore |

Mac app local mode (`SAAS_MODE=0`) is unchanged — users bring their own Anthropic key.

## Quick start

### 1. Clone and configure

```bash
git clone git@github.com:Guanc27/market-morning.git
cd market-morning

cp backend/.env.example backend/.env
# Edit backend/.env → set ANTHROPIC_API_KEY=sk-ant-...
# Or MOCK_MODE=1 for demo data (no API key)
```

Optional in `.env`:

- `FMP_API_KEY` — richer fundamentals (otherwise Yahoo Finance)
- `ROBINHOOD_SYNC_PROXY_URL` — local MCP bridge for live holdings sync (see `scripts/robinhood-mcp-bridge.py`)

### 2. Build the Mac app

```bash
xcode-select --install   # once, if you don't have Xcode CLT

chmod +x scripts/build-mac-app.sh
./scripts/build-mac-app.sh

open "dist/mac-app/Market Morning.app"
```

First launch:

- **Sun icon** appears in the menu bar
- Click it (or **⌘⇧M**) to open the panel
- The app starts the backend automatically if nothing is on port **8742**

### 3. Backend on login (optional)

For faster startup without relying on the app to spawn uvicorn:

```bash
chmod +x scripts/install-launchagent.sh
./scripts/install-launchagent.sh
```

Uninstall: `./scripts/uninstall-launchagent.sh`

Dev mode (terminal stays open): `./scripts/dev.sh`

## Project layout

```
mac-app/              Native shell (menu bar, floating panel, WKWebView)
extension/dist/       UI bundle loaded inside the Mac app
backend/              FastAPI + FinanceToolkit + Anthropic + SQLite
  app/finance.py      Market data & metrics
  app/ai.py           Briefs, picks, explore, portfolio analysis
  app/db.py           SQLite cache (briefs, analysis, holdings)
scripts/              Build, LaunchAgent, Robinhood MCP helpers
```

After build, `dist/mac-app/backend` symlinks to `../../backend`. If you move the `.app`:

```bash
export MM_BACKEND_DIR=/path/to/market-morning/backend
```

Or keep a `backend/` folder as a sibling of the `.app`.

## FinanceToolkit note

[FinancePortfolio](https://github.com/JerBouma/FinancePortfolio) is still pre-release on PyPI. This project tracks holdings directly and uses **FinanceToolkit** for ratios, performance, and risk metrics.

## Disclaimer

Informational software only — not financial advice. Verify data and decisions independently.

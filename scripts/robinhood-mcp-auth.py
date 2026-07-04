#!/usr/bin/env python3
"""One-time Robinhood MCP login — saves OAuth tokens for the bridge."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / "backend" / ".venv" / "bin" / "python3"

# Re-exec with project venv when user runs `python3 scripts/...` from system Python.
if VENV_PY.exists() and Path(sys.executable).resolve() != VENV_PY.resolve():
    os.execv(str(VENV_PY), [str(VENV_PY), *sys.argv])

sys.path.insert(0, str(ROOT / "backend"))

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from app.robinhood_mcp_oauth import FileTokenStorage, MCP_URL, build_oauth_provider


async def main() -> None:
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        raise SystemExit(
            "Missing dependencies. Run:\n"
            "  backend/.venv/bin/pip install -r backend/requirements.txt\n"
            "Or use: ./scripts/robinhood-mcp-auth.sh"
        ) from None

    storage = FileTokenStorage()
    oauth = build_oauth_provider(storage)

    print("Market Morning — Robinhood MCP login")
    print(f"Server: {MCP_URL}")
    if storage.has_tokens():
        print("Existing tokens found — will refresh if expired.\n")
    else:
        print("First-time setup — browser will open for Robinhood login.\n")

    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(create_mcp_http_client(auth=oauth))
        read, write, _ = await stack.enter_async_context(streamable_http_client(MCP_URL, http_client=client))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        result = await session.call_tool("get_accounts", arguments={})
        block = result.content[0]
        text = block.text if hasattr(block, "text") else str(block)
        data = json.loads(text)
        accounts = data.get("data", {}).get("accounts") or []
        print(f"Connected — {len(accounts)} account(s) visible.")
        default = next((a for a in accounts if a.get("is_default")), accounts[0] if accounts else None)
        if default:
            num = default.get("account_number", "")
            print(f"Default account: ••••{num[-4:] if len(num) >= 4 else num}")

    print(f"\nTokens saved to {storage.path}")
    print("Restart bridge:")
    print("  launchctl kickstart -k gui/$(id -u)/com.market-morning.robinhood-bridge")


if __name__ == "__main__":
    asyncio.run(main())

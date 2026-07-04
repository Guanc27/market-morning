#!/usr/bin/env python3
"""Local Robinhood MCP bridge — OAuth via saved tokens (Python 3.10+)."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client
except ImportError as exc:
    raise SystemExit(
        "MCP SDK required: cd backend && .venv/bin/pip install -r requirements.txt"
    ) from exc

from app.robinhood_mcp_oauth import FileTokenStorage, MCP_URL, build_oauth_provider

_session: ClientSession | None = None
_stack: AsyncExitStack | None = None
_lock = asyncio.Lock()
_storage = FileTokenStorage()
_ready = False


async def _connect() -> ClientSession:
    global _session, _stack, _ready
    if _session is not None:
        return _session
    if not _storage.has_tokens():
        raise RuntimeError(
            "Robinhood not connected. Run: ./scripts/robinhood-mcp-auth.sh"
        )
    stack = AsyncExitStack()
    oauth = build_oauth_provider(_storage)
    client = await stack.enter_async_context(create_mcp_http_client(auth=oauth))
    read, write, _ = await stack.enter_async_context(streamable_http_client(MCP_URL, http_client=client))
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    _session = session
    _stack = stack
    _ready = True
    return session


async def _disconnect() -> None:
    global _session, _stack, _ready
    if _stack:
        await _stack.aclose()
    _session = None
    _stack = None
    _ready = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await _connect()
        print("Robinhood MCP bridge ready (authenticated)")
    except Exception as exc:
        print(f"Robinhood MCP bridge waiting for auth: {exc}")
    yield
    await _disconnect()


app = FastAPI(title="Robinhood MCP Bridge", version="0.3.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mcp": MCP_URL,
        "authenticated": _ready,
        "tokens_saved": _storage.has_tokens(),
    }


@app.post("/tools/{tool_name}")
async def call_tool(tool_name: str, body: dict[str, Any]) -> dict[str, Any]:
    async with _lock:
        try:
            session = await _connect()
            result = await session.call_tool(tool_name, arguments=body)
            if not result.content:
                return {}
            block = result.content[0]
            text = block.text if hasattr(block, "text") else str(block)
            return json.loads(text)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc


def main() -> None:
    print(f"Robinhood MCP bridge → http://127.0.0.1:8743")
    if not _storage.has_tokens():
        print("Run once: ./scripts/robinhood-mcp-auth.sh")
    uvicorn.run(app, host="127.0.0.1", port=8743, log_level="info")


if __name__ == "__main__":
    main()

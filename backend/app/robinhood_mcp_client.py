"""Minimal Robinhood MCP client (direct HTTP or local sync proxy)."""

from __future__ import annotations

import json
from typing import Any

import httpx


class RobinhoodMcpClient:
    def __init__(self, url: str, token: str = "", proxy_url: str = "") -> None:
        self.url = url.rstrip("/")
        self.token = token.strip()
        self.proxy_url = proxy_url.rstrip("/")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.proxy_url:
            return await self._call_proxy(name, arguments)
        return await self._call_direct(name, arguments)

    async def _call_proxy(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{self.proxy_url}/tools/{name}",
                json=arguments,
            )
            res.raise_for_status()
            data = res.json()
            if isinstance(data, dict) and "error" in data:
                raise RuntimeError(data["error"])
            return data

    async def _call_direct(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.token:
            raise RuntimeError("ROBINHOOD_MCP_ACCESS_TOKEN not configured")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        init_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "market-morning", "version": "0.1.0"},
            },
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            init_res = await client.post(self.url, headers=headers, json=init_body)
            init_res.raise_for_status()
            session_id = init_res.headers.get("mcp-session-id", "")

            req_headers = dict(headers)
            if session_id:
                req_headers["mcp-session-id"] = session_id

            await client.post(
                self.url,
                headers=req_headers,
                json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            )

            call_body = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
            call_res = await client.post(self.url, headers=req_headers, json=call_body)
            call_res.raise_for_status()
            payload = _parse_mcp_response(call_res)
            if payload.get("isError"):
                raise RuntimeError(str(payload.get("content")))
            text_blocks = payload.get("content") or []
            if not text_blocks:
                return {}
            text = text_blocks[0].get("text") if isinstance(text_blocks[0], dict) else str(text_blocks[0])
            return json.loads(text)


def _parse_mcp_response(res: httpx.Response) -> dict[str, Any]:
    content_type = res.headers.get("content-type", "")
    if "application/json" in content_type:
        body = res.json()
        if "result" in body:
            return body["result"]
        if "error" in body:
            raise RuntimeError(body["error"].get("message", "MCP error"))
        return body
    # SSE fallback
    for line in res.text.splitlines():
        if line.startswith("data:"):
            chunk = json.loads(line[5:].strip())
            if "result" in chunk:
                return chunk["result"]
            if "error" in chunk:
                raise RuntimeError(chunk["error"].get("message", "MCP error"))
    raise RuntimeError("Empty MCP response")

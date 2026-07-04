"""Robinhood MCP OAuth — file token storage + browser login flow."""

from __future__ import annotations

import asyncio
import json
import webbrowser
from pathlib import Path
from typing import Any

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

TOKEN_FILE = Path(__file__).resolve().parent.parent / "data" / "robinhood_mcp_oauth.json"
MCP_URL = "https://agent.robinhood.com/mcp/trading"
REDIRECT_URI = "http://127.0.0.1:8787/callback"
CALLBACK_PORT = 8787


class FileTokenStorage:
    def __init__(self, path: Path = TOKEN_FILE) -> None:
        self.path = path

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n")
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._read().get("tokens")
        return OAuthToken.model_validate(raw) if raw else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        data = self._read()
        data["tokens"] = tokens.model_dump(mode="json")
        self._write(data)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._read().get("client_info")
        return OAuthClientInformationFull.model_validate(raw) if raw else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        data = self._read()
        data["client_info"] = client_info.model_dump(mode="json")
        self._write(data)

    def has_tokens(self) -> bool:
        raw = self._read().get("tokens")
        return bool(raw and raw.get("access_token"))


async def _redirect_handler(url: str) -> None:
    print(f"\nOpening browser for Robinhood login…")
    print(f"If it doesn't open: {url}\n")
    webbrowser.open(url)


async def _callback_handler() -> tuple[str, str | None]:
    from aiohttp import web

    result: dict[str, str | None] = {"code": None, "state": None}
    event = asyncio.Event()

    async def handle(request: web.Request) -> web.Response:
        params = request.rel_url.query
        result["code"] = params.get("code")
        result["state"] = params.get("state")
        event.set()
        return web.Response(
            text="<html><body><h2>Market Morning connected to Robinhood.</h2>"
            "<p>You can close this tab and return to the terminal.</p></body></html>",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/callback", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", CALLBACK_PORT)
    await site.start()
    print(f"Waiting for Robinhood callback on {REDIRECT_URI} …")
    try:
        await asyncio.wait_for(event.wait(), timeout=300)
    finally:
        await runner.cleanup()
    if not result["code"]:
        raise RuntimeError("No authorization code received")
    return result["code"], result["state"]


def build_oauth_provider(storage: FileTokenStorage | None = None) -> OAuthClientProvider:
    storage = storage or FileTokenStorage()
    metadata = OAuthClientMetadata(
        redirect_uris=[AnyUrl(REDIRECT_URI)],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        client_name="Market Morning",
    )
    return OAuthClientProvider(
        server_url=MCP_URL,
        client_metadata=metadata,
        storage=storage,
        redirect_handler=_redirect_handler,
        callback_handler=_callback_handler,
    )

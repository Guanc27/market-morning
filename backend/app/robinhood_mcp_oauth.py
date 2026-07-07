"""Robinhood MCP OAuth — macOS Keychain token storage + browser login flow.

OAuth tokens carry trading scope, so they live in the login Keychain (via the
`security` CLI, no extra Python dependency) rather than a plaintext file. Any
pre-existing plaintext token file is migrated into the Keychain on first use and
then deleted. The class is still named ``FileTokenStorage`` for import
compatibility with the bridge / auth scripts.
"""

from __future__ import annotations

import asyncio
import json
import webbrowser
from pathlib import Path
from typing import Any

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

from app import keychain

# Legacy plaintext location — kept only so we can migrate it into the Keychain.
TOKEN_FILE = Path(__file__).resolve().parent.parent / "data" / "robinhood_mcp_oauth.json"
KEYCHAIN_SERVICE = "market-morning-robinhood"
KEYCHAIN_ACCOUNT = "oauth"
MCP_URL = "https://agent.robinhood.com/mcp/trading"
REDIRECT_URI = "http://127.0.0.1:8787/callback"
CALLBACK_PORT = 8787


class FileTokenStorage:
    """Keychain-backed OAuth token store (name retained for compatibility)."""

    def __init__(self, path: Path = TOKEN_FILE) -> None:
        # ``path`` is the legacy plaintext file — retained only for migration and
        # for the auth script's status message.
        self.path = path
        self._migrate_plaintext()

    def _migrate_plaintext(self) -> None:
        """Move any existing plaintext token file into the Keychain, then delete it.

        The plaintext file is deleted ONLY after the Keychain write is verified by
        reading it back — so a Keychain failure can never orphan the only copy of
        the token.
        """
        if keychain.get_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT):
            # Already in the Keychain — remove any lingering plaintext copy.
            self._remove_plaintext()
            return
        if not self.path.exists():
            return
        try:
            parsed = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        # Store as single-line JSON: the `security` CLI's `-w` reader returns a hex
        # blob (not the text) when the stored secret contains newlines, so a
        # pretty-printed (indented) file must be re-serialized compactly.
        secret = json.dumps(parsed)
        if keychain.set_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, secret):
            if keychain.get_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT):
                self._remove_plaintext()

    def _remove_plaintext(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass

    def _read(self) -> dict[str, Any]:
        raw = keychain.get_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        if not raw:
            # Fallback: if the Keychain is unavailable/empty but a plaintext file
            # still exists (e.g. a failed migration), keep auth working rather than
            # lose the token. Migration deletes the file once the Keychain holds it.
            if self.path.exists():
                try:
                    return json.loads(self.path.read_text())
                except (OSError, json.JSONDecodeError):
                    return {}
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        keychain.set_generic_password(
            KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, json.dumps(data)
        )

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

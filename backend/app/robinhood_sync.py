"""Robinhood portfolio sync — MCP (when configured) or local snapshot fallback."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.db import Database

SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "robinhood_positions.json"
SYNC_STATE = Path(__file__).resolve().parent.parent / "data" / "robinhood_sync_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_sync_state() -> dict[str, Any]:
    if not SYNC_STATE.exists():
        return {}
    try:
        return json.loads(SYNC_STATE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_sync_state(state: dict[str, Any]) -> None:
    SYNC_STATE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE.write_text(json.dumps(state, indent=2))


def _cooldown_active(force: bool) -> bool:
    if force:
        return False
    state = _read_sync_state()
    last = state.get("last_sync_at")
    if not last:
        return False
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return elapsed < settings.robinhood_sync_cooldown_seconds
    except ValueError:
        return False


def _parse_positions(raw: dict[str, Any]) -> list[dict[str, Any]]:
    positions = raw.get("data", {}).get("positions") or raw.get("positions") or []
    holdings: list[dict[str, Any]] = []
    for pos in positions:
        if not pos:
            continue
        qty = float(pos.get("quantity") or 0)
        if qty <= 0:
            continue
        avg = pos.get("average_buy_price")
        if avg is None:
            continue
        holdings.append({
            "ticker": str(pos["symbol"]).upper(),
            "shares": qty,
            "avg_cost": float(avg),
            "notes": "robinhood",
        })
    return holdings


def _parse_quotes(raw: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Map symbol -> {price, prev_close} from get_equity_quotes.

    The broker is the authoritative price source; captured at sync time so a
    holding whose flaky live quote (yfinance/FMP) later fails still has a real,
    as-of-last-sync price/value to display instead of "—".
    """
    results = raw.get("data", {}).get("results") or raw.get("results") or []
    out: dict[str, dict[str, float]] = {}
    for entry in results:
        quote = (entry or {}).get("quote") or {}
        symbol = quote.get("symbol")
        if not symbol:
            continue
        price = _to_float(quote.get("last_trade_price")) or _to_float(quote.get("last_non_reg_trade_price"))
        if not price or price <= 0:
            continue
        prev = _to_float(quote.get("adjusted_previous_close")) or _to_float(quote.get("previous_close"))
        row: dict[str, float] = {"price": price}
        if prev and prev > 0:
            row["prev_close"] = prev
        out[str(symbol).upper()] = row
    return out


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _enrich_holdings_with_quotes(
    holdings: list[dict[str, Any]], quotes: dict[str, dict[str, float]]
) -> None:
    """Attach broker price / market_value / change_pct to each snapshot holding."""
    for h in holdings:
        q = quotes.get(str(h.get("ticker", "")).upper())
        if not q:
            continue
        price = q.get("price")
        if not price or price <= 0:
            continue
        shares = float(h.get("shares") or 0)
        h["price"] = round(price, 2)
        h["market_value"] = round(price * shares, 2)
        prev = q.get("prev_close")
        if prev and prev > 0:
            h["change_pct"] = round((price - prev) / prev * 100, 2)


def _parse_account(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("data") or raw
    bp = data.get("buying_power") or {}
    buying_power = bp.get("buying_power") if isinstance(bp, dict) else bp
    return {
        "cash": float(data.get("cash") or 0),
        "buying_power": float(buying_power or data.get("cash") or 0),
        "pending_deposits": float(data.get("pending_deposits") or 0),
        "total_account_value": float(data.get("total_value") or 0),
        "equity_value": float(data.get("equity_value") or 0),
        "currency": data.get("currency") or "USD",
    }


def _pick_account(accounts_raw: dict[str, Any]) -> str | None:
    accounts = accounts_raw.get("data", {}).get("accounts") or accounts_raw.get("accounts") or []
    if settings.robinhood_account_number:
        return settings.robinhood_account_number
    active = [a for a in accounts if a and not a.get("deactivated")]
    for a in active:
        if a.get("is_default"):
            return a.get("account_number")
    for a in active:
        if a.get("brokerage_account_type") == "individual" and not a.get("agentic_allowed"):
            return a.get("account_number")
    return active[0].get("account_number") if active else None


async def _fetch_via_mcp() -> dict[str, Any] | None:
    if not settings.robinhood_mcp_access_token and not settings.robinhood_sync_proxy_url:
        return None
    from app.robinhood_mcp_client import RobinhoodMcpClient

    client = RobinhoodMcpClient(
        url=settings.robinhood_mcp_url,
        token=settings.robinhood_mcp_access_token,
        proxy_url=settings.robinhood_sync_proxy_url,
    )
    accounts = await client.call_tool("get_accounts", {})
    account_number = _pick_account(accounts)
    if not account_number:
        raise RuntimeError("No Robinhood account found")
    positions = await client.call_tool("get_equity_positions", {"account_number": account_number})
    portfolio = await client.call_tool("get_portfolio", {"account_number": account_number})
    holdings = _parse_positions(positions)
    # Capture authoritative broker prices per position so the display can fall
    # back to real, as-of-last-sync values when the flaky live quote provider
    # (yfinance/FMP) can't resolve a ticker. Never fail the sync over quotes.
    if holdings:
        try:
            quotes = await client.call_tool(
                "get_equity_quotes", {"symbols": [h["ticker"] for h in holdings]}
            )
            _enrich_holdings_with_quotes(holdings, _parse_quotes(quotes))
        except Exception:
            pass
    return {
        "account_number": account_number,
        "holdings": holdings,
        "account": _parse_account(portfolio),
        "source": "mcp",
    }


def _load_snapshot() -> dict[str, Any] | None:
    if not SNAPSHOT.exists():
        return None
    try:
        return json.loads(SNAPSHOT.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_snapshot(payload: dict[str, Any]) -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "account_id": payload.get("account_number", "individual-default"),
        "synced_at": datetime.now(timezone.utc).date().isoformat(),
        "account": payload.get("account") or {},
        "holdings": payload.get("holdings") or [],
    }
    SNAPSHOT.write_text(json.dumps(out, indent=2) + "\n")


async def _apply_holdings(db: Database, holdings: list[dict[str, Any]]) -> int:
    existing = {h["ticker"] for h in await db.get_holdings()}
    incoming = {h["ticker"] for h in holdings}
    for ticker in existing - incoming:
        await db.remove_holding(ticker)
    for h in holdings:
        await db.upsert_holding(h["ticker"], h["shares"], h["avg_cost"], h.get("notes", "robinhood"))
    return len(holdings)


async def sync_robinhood(db: Database, force: bool = False) -> dict[str, Any]:
    if settings.mock_mode:
        return {"skipped": True, "reason": "mock_mode"}

    if _cooldown_active(force):
        state = _read_sync_state()
        return {
            "skipped": True,
            "reason": "cooldown",
            "last_sync_at": state.get("last_sync_at"),
            "cooldown_seconds": settings.robinhood_sync_cooldown_seconds,
            "source": state.get("source"),
        }

    source = "snapshot"
    payload: dict[str, Any] | None = None
    error: str | None = None

    try:
        payload = await _fetch_via_mcp()
        if payload:
            source = "mcp"
    except Exception as exc:
        error = str(exc)

    if not payload:
        snap = _load_snapshot()
        if snap and snap.get("holdings"):
            payload = {
                "account_number": snap.get("account_id"),
                "holdings": snap.get("holdings", []),
                "account": snap.get("account") or {},
                "source": "snapshot",
            }
            source = "snapshot"

    if not payload or not payload.get("holdings"):
        return {
            "skipped": True,
            "reason": "no_data",
            "error": error,
        }

    if source == "mcp":
        _save_snapshot(payload)

    count = await _apply_holdings(db, payload["holdings"])
    state = {
        "last_sync_at": _now_iso(),
        "source": source,
        "holdings": count,
        "account_number": payload.get("account_number"),
    }
    _write_sync_state(state)

    return {
        "synced": True,
        "source": source,
        "holdings": count,
        "account_number": payload.get("account_number"),
        "synced_at": state["last_sync_at"],
        "stale": source == "snapshot" and bool(error),
        "error": error if source == "snapshot" and error else None,
    }

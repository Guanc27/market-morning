#!/usr/bin/env python3
"""Replace local portfolio DB with holdings from backend/data/robinhood_positions.json."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import settings
from app.db import Database

SNAPSHOT = ROOT / "backend" / "data" / "robinhood_positions.json"


async def main() -> None:
    if not SNAPSHOT.exists():
        raise SystemExit(f"Missing snapshot: {SNAPSHOT}")
    data = json.loads(SNAPSHOT.read_text())
    holdings = data.get("holdings", [])
    db_path = ROOT / "backend" / "data" / "market_morning.db"
    db = Database(db_path)

    for h in await db.get_holdings():
        await db.remove_holding(h["ticker"])
    for h in holdings:
        await db.upsert_holding(
            h["ticker"], float(h["shares"]), float(h["avg_cost"]), h.get("notes", "robinhood")
        )
    print(f"Synced {len(holdings)} holdings from Robinhood snapshot.")


if __name__ == "__main__":
    asyncio.run(main())

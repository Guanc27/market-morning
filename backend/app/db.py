from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiosqlite

from app.ai_sanitize import markdown_plain_excerpt, synopsis_looks_like_markdown

SCHEMA = """
CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    shares REAL NOT NULL,
    avg_cost REAL NOT NULL,
    notes TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(ticker)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    shares REAL NOT NULL,
    price REAL,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    meta_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS portfolio_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    meta_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS portfolio_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry TEXT NOT NULL,
    parsed_action TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    notes TEXT DEFAULT '',
    source TEXT DEFAULT 'manual',
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pick_date TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    synopsis TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    meta_json TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chosen_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL,
    label TEXT NOT NULL,
    detail TEXT DEFAULT '',
    tickers TEXT DEFAULT '[]',
    action_type TEXT DEFAULT '',
    source TEXT DEFAULT 'brief',
    chosen_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialized = False

    async def _ensure_schema(self, db: aiosqlite.Connection) -> None:
        if not self._initialized:
            await db.executescript(SCHEMA)
            await db.commit()
            await self._migrate(db)
            self._initialized = True

    async def _migrate(self, db: aiosqlite.Connection) -> None:
        cols = await db.execute_fetchall("PRAGMA table_info(daily_briefs)")
        names = {c[1] for c in cols}
        if "meta_json" not in names:
            await db.execute("ALTER TABLE daily_briefs ADD COLUMN meta_json TEXT DEFAULT '{}'")
            await db.commit()
        tables = await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_picks'"
        )
        if not tables:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_picks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pick_date TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    synopsis TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    meta_json TEXT DEFAULT '{}'
                )
                """
            )
            await db.commit()

    async def _with_db(self, fn: Callable[[aiosqlite.Connection], Awaitable[Any]]) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(str(self.path), timeout=30.0)
        db.row_factory = aiosqlite.Row
        try:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=30000")
            await self._ensure_schema(db)
            return await fn(db)
        finally:
            await db.close()

    async def save_portfolio_analysis(self, content: str, meta: dict[str, Any] | None = None) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(meta or {})

        async def _run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO portfolio_analyses (analysis_date, content, created_at, meta_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(analysis_date) DO UPDATE SET
                    content=excluded.content,
                    created_at=excluded.created_at,
                    meta_json=excluded.meta_json
                """,
                (today, content, now, meta_json),
            )
            await db.commit()

        await self._with_db(_run)

    async def get_portfolio_analysis(self) -> dict[str, Any] | None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async def _run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                "SELECT content, created_at, meta_json FROM portfolio_analyses WHERE analysis_date = ?",
                (today,),
            )
            if not rows:
                return None
            row = dict(rows[0])
            meta = {}
            try:
                meta = json.loads(row.get("meta_json") or "{}")
            except json.JSONDecodeError:
                pass
            return {
                "content": row["content"],
                "created_at": row["created_at"],
                "actions": meta.get("actions", []),
                "positions": meta.get("positions", []),
            }

        return await self._with_db(_run)

    async def backfill_portfolio_analysis_content(
        self, transform: Callable[[str], str]
    ) -> int:
        """Rewrite stored portfolio analysis rows when transform changes content."""

        async def _run(db: aiosqlite.Connection) -> int:
            rows = await db.execute_fetchall(
                "SELECT analysis_date, content FROM portfolio_analyses"
            )
            updated = 0
            for row in rows:
                old = row["content"] or ""
                new = transform(old)
                if new != old:
                    await db.execute(
                        "UPDATE portfolio_analyses SET content = ? WHERE analysis_date = ?",
                        (new, row["analysis_date"]),
                    )
                    updated += 1
            if updated:
                await db.commit()
            return updated

        return await self._with_db(_run)

    async def get_holdings(self) -> list[dict[str, Any]]:
        async def run(db: aiosqlite.Connection) -> list[dict[str, Any]]:
            rows = await db.execute_fetchall(
                "SELECT ticker, shares, avg_cost, notes, updated_at FROM holdings ORDER BY ticker"
            )
            return [dict(r) for r in rows]

        return await self._with_db(run)

    async def upsert_holding(
        self, ticker: str, shares: float, avg_cost: float, notes: str = ""
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        ticker = ticker.upper().strip()

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO holdings (ticker, shares, avg_cost, notes, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    shares = excluded.shares,
                    avg_cost = excluded.avg_cost,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (ticker, shares, avg_cost, notes, now),
            )
            await db.commit()

        await self._with_db(run)
        return {"ticker": ticker, "shares": shares, "avg_cost": avg_cost, "notes": notes}

    async def remove_holding(self, ticker: str) -> bool:
        async def run(db: aiosqlite.Connection) -> bool:
            cur = await db.execute("DELETE FROM holdings WHERE ticker = ?", (ticker.upper(),))
            await db.commit()
            return cur.rowcount > 0

        return await self._with_db(run)

    async def add_transaction(
        self, ticker: str, action: str, shares: float, price: float | None, notes: str = ""
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO transactions (ticker, action, shares, price, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ticker.upper(), action, shares, price, notes, now),
            )
            await db.commit()

        await self._with_db(run)

    async def add_memory(self, entry: str, parsed_action: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                "INSERT INTO portfolio_memory (entry, parsed_action, created_at) VALUES (?, ?, ?)",
                (entry, parsed_action, now),
            )
            await db.commit()

        await self._with_db(run)

    async def get_memory(self, limit: int = 20) -> list[dict[str, Any]]:
        async def run(db: aiosqlite.Connection) -> list[dict[str, Any]]:
            rows = await db.execute_fetchall(
                "SELECT entry, parsed_action, created_at FROM portfolio_memory ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in rows]

        return await self._with_db(run)

    async def get_brief_for_today(self) -> dict[str, Any] | None:
        today = datetime.now(timezone.utc).date().isoformat()

        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                "SELECT brief_date, content, created_at FROM daily_briefs WHERE brief_date = ?",
                (today,),
            )
            if not rows:
                return None
            return dict(rows[0])

        return await self._with_db(run)

    async def save_brief(self, content: str, meta: dict[str, Any] | None = None) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(meta or {})

        async def run(db: aiosqlite.Connection) -> None:
            existing = await db.execute_fetchall(
                "SELECT meta_json FROM daily_briefs WHERE brief_date = ?", (today,)
            )
            if existing and meta is not None:
                try:
                    prior = json.loads(existing[0][0] or "{}")
                except json.JSONDecodeError:
                    prior = {}
                merged = {**prior, **meta}
                meta_json_local = json.dumps(merged)
            else:
                meta_json_local = meta_json
            await db.execute(
                """
                INSERT INTO daily_briefs (brief_date, content, created_at, meta_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(brief_date) DO UPDATE SET
                    content = excluded.content,
                    created_at = excluded.created_at,
                    meta_json = excluded.meta_json
                """,
                (today, content, now, meta_json_local),
            )
            await db.commit()

        await self._with_db(run)

    async def get_brief_for_today_full(self) -> dict[str, Any] | None:
        today = datetime.now(timezone.utc).date().isoformat()

        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                "SELECT brief_date, content, created_at, meta_json FROM daily_briefs WHERE brief_date = ?",
                (today,),
            )
            if not rows:
                return None
            row = dict(rows[0])
            try:
                row["meta"] = json.loads(row.pop("meta_json", "{}") or "{}")
            except json.JSONDecodeError:
                row["meta"] = {}
            return row

        return await self._with_db(run)

    async def patch_brief_meta(self, brief_date: str, meta_patch: dict[str, Any]) -> None:
        async def run(db: aiosqlite.Connection) -> None:
            rows = await db.execute_fetchall(
                "SELECT meta_json FROM daily_briefs WHERE brief_date = ?",
                (brief_date,),
            )
            if not rows:
                return
            try:
                meta = json.loads(rows[0][0] or "{}")
            except json.JSONDecodeError:
                meta = {}
            meta.update(meta_patch)
            await db.execute(
                "UPDATE daily_briefs SET meta_json = ? WHERE brief_date = ?",
                (json.dumps(meta), brief_date),
            )
            await db.commit()

        await self._with_db(run)

    def _resolve_brief_synopsis(self, meta: dict[str, Any], content: str) -> str:
        synopsis = (meta or {}).get("synopsis") or ""
        if synopsis and not synopsis_looks_like_markdown(synopsis):
            return synopsis
        if content:
            return markdown_plain_excerpt(content)
        return synopsis

    async def get_recent_brief_synopses(self, limit: int = 3, exclude_today: bool = True) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).date().isoformat()

        async def run(db: aiosqlite.Connection) -> list[dict[str, Any]]:
            if exclude_today:
                rows = await db.execute_fetchall(
                    """
                    SELECT brief_date, content, created_at, meta_json FROM daily_briefs
                    WHERE brief_date != ?
                    ORDER BY brief_date DESC LIMIT ?
                    """,
                    (today, limit),
                )
            else:
                rows = await db.execute_fetchall(
                    """
                    SELECT brief_date, content, created_at, meta_json FROM daily_briefs
                    ORDER BY brief_date DESC LIMIT ?
                    """,
                    (limit,),
                )
            out = []
            for r in rows:
                row = dict(r)
                meta = {}
                try:
                    meta = json.loads(row.pop("meta_json", "{}") or "{}")
                except json.JSONDecodeError:
                    pass
                content = row.get("content") or ""
                synopsis = self._resolve_brief_synopsis(meta, content)
                if synopsis and synopsis != (meta.get("synopsis") or ""):
                    meta["synopsis"] = synopsis
                    await db.execute(
                        "UPDATE daily_briefs SET meta_json = ? WHERE brief_date = ?",
                        (json.dumps(meta), row["brief_date"]),
                    )
                out.append({
                    "brief_date": row["brief_date"],
                    "synopsis": synopsis,
                    "created_at": row["created_at"],
                })
            if out:
                await db.commit()
            return out

        return await self._with_db(run)

    async def list_brief_archive_dates(self) -> list[str]:
        async def run(db: aiosqlite.Connection) -> list[str]:
            rows = await db.execute_fetchall(
                "SELECT brief_date FROM daily_briefs ORDER BY brief_date DESC"
            )
            return [dict(r)["brief_date"] for r in rows]

        return await self._with_db(run)

    async def list_all_brief_dates(self) -> list[str]:
        return await self.list_brief_archive_dates()

    async def get_brief_by_date(self, brief_date: str) -> dict[str, Any] | None:
        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                "SELECT brief_date, content, created_at, meta_json FROM daily_briefs WHERE brief_date = ?",
                (brief_date,),
            )
            if not rows:
                return None
            row = dict(rows[0])
            try:
                row["meta"] = json.loads(row.pop("meta_json", "{}") or "{}")
            except json.JSONDecodeError:
                row["meta"] = {}
            return row

        return await self._with_db(run)

    async def get_watchlist(self) -> list[dict[str, Any]]:
        async def run(db: aiosqlite.Connection) -> list[dict[str, Any]]:
            rows = await db.execute_fetchall(
                "SELECT ticker, notes, source, added_at FROM watchlist ORDER BY ticker"
            )
            return [dict(r) for r in rows]

        return await self._with_db(run)

    async def add_watchlist(self, ticker: str, notes: str = "", source: str = "manual") -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        ticker = ticker.upper().strip()
        memory_entry = f"Added {ticker} to watchlist"
        memory_parsed = json.dumps({"watchlist": ticker, "source": source})

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO watchlist (ticker, notes, source, added_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    notes = excluded.notes,
                    source = excluded.source,
                    added_at = excluded.added_at
                """,
                (ticker, notes, source, now),
            )
            await db.execute(
                "INSERT INTO portfolio_memory (entry, parsed_action, created_at) VALUES (?, ?, ?)",
                (memory_entry, memory_parsed, now),
            )
            await db.commit()

        await self._with_db(run)
        return {"ticker": ticker, "notes": notes, "source": source, "added_at": now}

    async def save_picks(self, content: str, synopsis: str = "", meta: dict[str, Any] | None = None) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(meta or {})

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO daily_picks (pick_date, content, synopsis, created_at, meta_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(pick_date) DO UPDATE SET
                    content = excluded.content,
                    synopsis = excluded.synopsis,
                    created_at = excluded.created_at,
                    meta_json = excluded.meta_json
                """,
                (today, content, synopsis, now, meta_json),
            )
            await db.commit()

        await self._with_db(run)

    async def get_picks_by_date(self, pick_date: str) -> dict[str, Any] | None:
        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                "SELECT pick_date, content, synopsis, created_at, meta_json FROM daily_picks WHERE pick_date = ?",
                (pick_date,),
            )
            if not rows:
                return None
            row = dict(rows[0])
            try:
                row["meta"] = json.loads(row.pop("meta_json", "{}") or "{}")
            except json.JSONDecodeError:
                row["meta"] = {}
            return row

        return await self._with_db(run)

    async def get_yesterday_picks_preview(self, max_items: int = 3) -> dict[str, Any] | None:
        from datetime import timedelta

        yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
        row = await self.get_picks_by_date(yesterday)
        if not row:
            async def run(db: aiosqlite.Connection) -> list[dict[str, Any]]:
                rows = await db.execute_fetchall(
                    "SELECT pick_date, content, synopsis FROM daily_picks ORDER BY pick_date DESC LIMIT 1"
                )
                return [dict(r) for r in rows]

            fallback = await self._with_db(run)
            if not fallback:
                return None
            row = fallback[0]

        content = row.get("content") or ""
        synopsis = row.get("synopsis") or ""
        if not synopsis or synopsis_looks_like_markdown(synopsis):
            synopsis = markdown_plain_excerpt(content, max_chars=900) if content else synopsis
        return {
            "pick_date": row.get("pick_date"),
            "synopsis": synopsis,
            "preview": synopsis[:900] + ("…" if len(synopsis) > 900 else ""),
            "content": content,
            "truncated": len(synopsis) > 900 or (len(content) > 900 if content else False),
        }

    async def save_mini_brief(self, mini: str) -> None:
        today = datetime.now(timezone.utc).date().isoformat()
        row = await self.get_brief_for_today_full()
        meta = (row or {}).get("meta") or {}
        meta["mini_brief"] = mini
        meta["mini_brief_at"] = datetime.now(timezone.utc).isoformat()
        if row:
            await self.save_brief(row["content"], meta)
        else:
            await self.save_brief(mini, meta)

    async def get_brief_landing(self) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        today_row = await self.get_brief_for_today_full()
        synopses = await self.get_recent_brief_synopses(limit=3, exclude_today=True)
        dates = await self.list_brief_archive_dates()
        mini = None
        if today_row:
            mini = (today_row.get("meta") or {}).get("mini_brief")
            meta = today_row.get("meta") or {}
            synopsis = self._resolve_brief_synopsis(meta, today_row.get("content") or "")
            if synopsis and synopsis != (meta.get("synopsis") or ""):
                await self.patch_brief_meta(today_row["brief_date"], {"synopsis": synopsis})
        else:
            synopsis = ""
        return {
            "has_today": bool(today_row),
            "today": {
                "brief_date": today_row["brief_date"],
                "content": today_row["content"],
                "synopsis": synopsis,
                "mini_brief": mini,
                "created_at": today_row.get("created_at"),
            } if today_row else None,
            "synopses": synopses,
            "archive_dates": dates,
        }

    async def remove_watchlist(self, ticker: str) -> bool:
        async def run(db: aiosqlite.Connection) -> bool:
            cur = await db.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
            await db.commit()
            return cur.rowcount > 0

        return await self._with_db(run)

    async def record_chosen_action(
        self,
        action_id: str,
        label: str,
        detail: str = "",
        tickers: list[str] | None = None,
        action_type: str = "",
        source: str = "brief",
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        tickers_json = json.dumps(tickers or [])

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO chosen_actions (action_id, label, detail, tickers, action_type, source, chosen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (action_id, label, detail, tickers_json, action_type, source, now),
            )
            await db.execute(
                "INSERT INTO portfolio_memory (entry, parsed_action, created_at) VALUES (?, ?, ?)",
                (
                    f"Chose action: {label}",
                    json.dumps({"action_id": action_id, "tickers": tickers or [], "type": action_type}),
                    now,
                ),
            )
            await db.commit()

        await self._with_db(run)
        return {
            "action_id": action_id,
            "label": label,
            "detail": detail,
            "tickers": tickers or [],
            "action_type": action_type,
            "source": source,
            "chosen_at": now,
        }

    async def get_chosen_actions(self, limit: int = 30) -> list[dict[str, Any]]:
        async def run(db: aiosqlite.Connection) -> list[dict[str, Any]]:
            rows = await db.execute_fetchall(
                """
                SELECT action_id, label, detail, tickers, action_type, source, chosen_at
                FROM chosen_actions ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            )
            out = []
            for r in rows:
                d = dict(r)
                try:
                    d["tickers"] = json.loads(d.get("tickers") or "[]")
                except json.JSONDecodeError:
                    d["tickers"] = []
                out.append(d)
            return out

        return await self._with_db(run)

    async def clear_brief_for_today(self) -> None:
        today = datetime.now(timezone.utc).date().isoformat()

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute("DELETE FROM daily_briefs WHERE brief_date = ?", (today,))
            await db.commit()

        await self._with_db(run)

    async def export_state(self) -> str:
        holdings = await self.get_holdings()
        memory = await self.get_memory(50)
        return json.dumps({"holdings": holdings, "memory": memory}, indent=2)

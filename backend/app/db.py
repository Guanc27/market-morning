from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiosqlite

from app.tenant import get_tenant_user_id

from app.ai_sanitize import markdown_plain_excerpt, synopsis_looks_like_markdown


def _resolve_user_id(user_id: int | None) -> int:
    if user_id is not None:
        return user_id
    return get_tenant_user_id()

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

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER PRIMARY KEY,
    tier TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'active',
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    stripe_price_id TEXT,
    current_period_end INTEGER,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_usage_user_period ON usage_events(user_id, event_type, created_at);
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

        # Multi-tenant SaaS columns (default user_id=1 preserves Mac app data)
        tenant_tables = [
            "holdings",
            "portfolio_analyses",
            "watchlist",
            "portfolio_memory",
            "chosen_actions",
            "daily_picks",
        ]
        for table in tenant_tables:
            cols = await db.execute_fetchall(f"PRAGMA table_info({table})")
            names = {c[1] for c in cols}
            if "user_id" not in names:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
                await db.commit()

        # Rebuild holdings/watchlist for per-user uniqueness (was ticker-only)
        await self._rebuild_holdings_if_needed(db)
        await self._rebuild_watchlist_if_needed(db)
        await self._rebuild_portfolio_analyses_if_needed(db)

        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_picks_user_date ON daily_picks(user_id, pick_date)"
        )
        await db.commit()

        rows = await db.execute_fetchall("SELECT id FROM users WHERE id = 1")
        if not rows:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                """
                INSERT INTO users (id, email, password_hash, display_name, created_at)
                VALUES (1, 'local@market-morning.local', '', 'Local User', ?)
                """,
                (now,),
            )
            await db.execute(
                """
                INSERT OR IGNORE INTO subscriptions (user_id, tier, status, updated_at)
                VALUES (1, 'desk', 'active', ?)
                """,
                (now,),
            )
            await db.commit()

    async def _rebuild_holdings_if_needed(self, db: aiosqlite.Connection) -> None:
        indexes = await db.execute_fetchall("PRAGMA index_list(holdings)")
        has_composite = False
        for idx in indexes:
            name = idx[1]
            if not name:
                continue
            cols = await db.execute_fetchall(f"PRAGMA index_info({name})")
            col_names = [c[2] for c in cols]
            if col_names == ["user_id", "ticker"] and idx[2]:  # unique
                has_composite = True
                break
        if has_composite:
            return
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS holdings_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                ticker TEXT NOT NULL,
                shares REAL NOT NULL,
                avg_cost REAL NOT NULL,
                notes TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, ticker)
            );
            INSERT OR IGNORE INTO holdings_v2 (user_id, ticker, shares, avg_cost, notes, updated_at)
                SELECT COALESCE(user_id, 1), ticker, shares, avg_cost, notes, updated_at FROM holdings;
            DROP TABLE holdings;
            ALTER TABLE holdings_v2 RENAME TO holdings;
            """
        )
        await db.commit()

    async def _rebuild_watchlist_if_needed(self, db: aiosqlite.Connection) -> None:
        indexes = await db.execute_fetchall("PRAGMA index_list(watchlist)")
        has_composite = False
        for idx in indexes:
            name = idx[1]
            if not name:
                continue
            cols = await db.execute_fetchall(f"PRAGMA index_info({name})")
            col_names = [c[2] for c in cols]
            if col_names == ["user_id", "ticker"] and idx[2]:
                has_composite = True
                break
        if has_composite:
            return
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS watchlist_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                ticker TEXT NOT NULL,
                notes TEXT DEFAULT '',
                source TEXT DEFAULT 'manual',
                added_at TEXT NOT NULL,
                UNIQUE(user_id, ticker)
            );
            INSERT OR IGNORE INTO watchlist_v2 (user_id, ticker, notes, source, added_at)
                SELECT COALESCE(user_id, 1), ticker, notes, source, added_at FROM watchlist;
            DROP TABLE watchlist;
            ALTER TABLE watchlist_v2 RENAME TO watchlist;
            """
        )
        await db.commit()

    async def _rebuild_portfolio_analyses_if_needed(self, db: aiosqlite.Connection) -> None:
        indexes = await db.execute_fetchall("PRAGMA index_list(portfolio_analyses)")
        has_composite = False
        for idx in indexes:
            name = idx[1]
            if not name:
                continue
            cols = await db.execute_fetchall(f"PRAGMA index_info({name})")
            col_names = [c[2] for c in cols]
            if col_names == ["user_id", "analysis_date"] and idx[2]:
                has_composite = True
                break
        if has_composite:
            return
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS portfolio_analyses_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                analysis_date TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                meta_json TEXT DEFAULT '{}',
                UNIQUE(user_id, analysis_date)
            );
            INSERT OR IGNORE INTO portfolio_analyses_v2 (user_id, analysis_date, content, created_at, meta_json)
                SELECT COALESCE(user_id, 1), analysis_date, content, created_at, meta_json FROM portfolio_analyses;
            DROP TABLE portfolio_analyses;
            ALTER TABLE portfolio_analyses_v2 RENAME TO portfolio_analyses;
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

    async def save_portfolio_analysis(
        self, content: str, meta: dict[str, Any] | None = None, *, user_id: int | None = None
    ) -> None:
        uid = _resolve_user_id(user_id)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(meta or {})

        async def _run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO portfolio_analyses (analysis_date, content, created_at, meta_json, user_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, analysis_date) DO UPDATE SET
                    content=excluded.content,
                    created_at=excluded.created_at,
                    meta_json=excluded.meta_json
                """,
                (today, content, now, meta_json, uid),
            )
            await db.commit()

        await self._with_db(_run)

    async def get_portfolio_analysis(self, user_id: int | None = None) -> dict[str, Any] | None:
        uid = _resolve_user_id(user_id)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async def _run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                """
                SELECT content, created_at, meta_json FROM portfolio_analyses
                WHERE analysis_date = ? AND user_id = ?
                """,
                (today, uid),
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

    async def clear_portfolio_analysis(self, analysis_date: str | None = None, *, user_id: int | None = None) -> None:
        uid = _resolve_user_id(user_id)
        day = analysis_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        async def _run(db: aiosqlite.Connection) -> None:
            await db.execute(
                "DELETE FROM portfolio_analyses WHERE analysis_date = ? AND user_id = ?",
                (day, uid),
            )
            await db.commit()

        await self._with_db(_run)

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

    async def get_holdings(self, user_id: int | None = None) -> list[dict[str, Any]]:
        uid = _resolve_user_id(user_id)
        async def run(db: aiosqlite.Connection) -> list[dict[str, Any]]:
            rows = await db.execute_fetchall(
                """
                SELECT ticker, shares, avg_cost, notes, updated_at
                FROM holdings WHERE user_id = ? ORDER BY ticker
                """,
                (uid,),
            )
            return [dict(r) for r in rows]

        return await self._with_db(run)

    async def upsert_holding(
        self, ticker: str, shares: float, avg_cost: float, notes: str = "", *, user_id: int | None = None
    ) -> dict[str, Any]:
        uid = _resolve_user_id(user_id)
        now = datetime.now(timezone.utc).isoformat()
        ticker = ticker.upper().strip()

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO holdings (ticker, shares, avg_cost, notes, updated_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, ticker) DO UPDATE SET
                    shares = excluded.shares,
                    avg_cost = excluded.avg_cost,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (ticker, shares, avg_cost, notes, now, uid),
            )
            await db.commit()

        await self._with_db(run)
        return {"ticker": ticker, "shares": shares, "avg_cost": avg_cost, "notes": notes}

    async def remove_holding(self, ticker: str, *, user_id: int | None = None) -> bool:
        uid = _resolve_user_id(user_id)
        async def run(db: aiosqlite.Connection) -> bool:
            cur = await db.execute(
                "DELETE FROM holdings WHERE ticker = ? AND user_id = ?",
                (ticker.upper(), uid),
            )
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

    async def get_watchlist(self, user_id: int | None = None) -> list[dict[str, Any]]:
        uid = _resolve_user_id(user_id)
        async def run(db: aiosqlite.Connection) -> list[dict[str, Any]]:
            rows = await db.execute_fetchall(
                """
                SELECT ticker, notes, source, added_at FROM watchlist
                WHERE user_id = ? ORDER BY ticker
                """,
                (uid,),
            )
            return [dict(r) for r in rows]

        return await self._with_db(run)

    async def add_watchlist(
        self, ticker: str, notes: str = "", source: str = "manual", *, user_id: int | None = None
    ) -> dict[str, Any]:
        uid = _resolve_user_id(user_id)
        now = datetime.now(timezone.utc).isoformat()
        ticker = ticker.upper().strip()
        memory_entry = f"Added {ticker} to watchlist"
        memory_parsed = json.dumps({"watchlist": ticker, "source": source})

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO watchlist (ticker, notes, source, added_at, user_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, ticker) DO UPDATE SET
                    notes = excluded.notes,
                    source = excluded.source,
                    added_at = excluded.added_at
                """,
                (ticker, notes, source, now, uid),
            )
            await db.execute(
                """
                INSERT INTO portfolio_memory (entry, parsed_action, created_at, user_id)
                VALUES (?, ?, ?, ?)
                """,
                (memory_entry, memory_parsed, now, uid),
            )
            await db.commit()

        await self._with_db(run)
        return {"ticker": ticker, "notes": notes, "source": source, "added_at": now}

    async def save_picks(
        self,
        content: str,
        synopsis: str = "",
        meta: dict[str, Any] | None = None,
        *,
        user_id: int | None = None,
    ) -> None:
        uid = _resolve_user_id(user_id)
        today = datetime.now(timezone.utc).date().isoformat()
        now = datetime.now(timezone.utc).isoformat()
        meta_json = json.dumps(meta or {})

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO daily_picks (pick_date, content, synopsis, created_at, meta_json, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, pick_date) DO UPDATE SET
                    content = excluded.content,
                    synopsis = excluded.synopsis,
                    created_at = excluded.created_at,
                    meta_json = excluded.meta_json
                """,
                (today, content, synopsis, now, meta_json, uid),
            )
            await db.commit()

        await self._with_db(run)

    async def get_picks_by_date(self, pick_date: str, user_id: int | None = None) -> dict[str, Any] | None:
        uid = _resolve_user_id(user_id)
        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                """
                SELECT pick_date, content, synopsis, created_at, meta_json
                FROM daily_picks WHERE pick_date = ? AND user_id = ?
                """,
                (pick_date, uid),
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

    async def remove_watchlist(self, ticker: str, *, user_id: int | None = None) -> bool:
        uid = _resolve_user_id(user_id)
        async def run(db: aiosqlite.Connection) -> bool:
            cur = await db.execute(
                "DELETE FROM watchlist WHERE ticker = ? AND user_id = ?",
                (ticker.upper(), uid),
            )
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

    async def export_state(self, user_id: int | None = None) -> str:
        uid = _resolve_user_id(user_id)
        holdings = await self.get_holdings(uid)
        memory = await self.get_memory(50)
        return json.dumps({"holdings": holdings, "memory": memory}, indent=2)

    # --- SaaS: users, subscriptions, usage -----------------------------------

    async def create_user(self, email: str, password_hash: str, display_name: str = "") -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        email = email.strip().lower()

        async def run(db: aiosqlite.Connection) -> dict[str, Any]:
            cur = await db.execute(
                """
                INSERT INTO users (email, password_hash, display_name, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (email, password_hash, display_name or email.split("@")[0], now),
            )
            await db.commit()
            user_id = cur.lastrowid
            await db.execute(
                """
                INSERT INTO subscriptions (user_id, tier, status, updated_at)
                VALUES (?, 'free', 'active', ?)
                """,
                (user_id, now),
            )
            await db.commit()
            return {"id": user_id, "email": email, "display_name": display_name, "created_at": now}

        return await self._with_db(run)

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                "SELECT id, email, password_hash, display_name, created_at FROM users WHERE email = ?",
                (email.strip().lower(),),
            )
            return dict(rows[0]) if rows else None

        return await self._with_db(run)

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                "SELECT id, email, display_name, created_at FROM users WHERE id = ?",
                (user_id,),
            )
            return dict(rows[0]) if rows else None

        return await self._with_db(run)

    async def touch_user_login(self, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, user_id))
            await db.commit()

        await self._with_db(run)

    async def get_user_subscription(self, user_id: int) -> dict[str, Any] | None:
        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                """
                SELECT user_id, tier, status, stripe_customer_id, stripe_subscription_id,
                       stripe_price_id, current_period_end, updated_at
                FROM subscriptions WHERE user_id = ?
                """,
                (user_id,),
            )
            return dict(rows[0]) if rows else None

        return await self._with_db(run)

    async def get_subscription_by_stripe_id(self, stripe_subscription_id: str) -> dict[str, Any] | None:
        async def run(db: aiosqlite.Connection) -> dict[str, Any] | None:
            rows = await db.execute_fetchall(
                "SELECT user_id, tier, status FROM subscriptions WHERE stripe_subscription_id = ?",
                (stripe_subscription_id,),
            )
            return dict(rows[0]) if rows else None

        return await self._with_db(run)

    async def upsert_subscription(
        self,
        user_id: int,
        *,
        tier: str | None = None,
        status: str | None = None,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        stripe_price_id: str | None = None,
        current_period_end: int | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = await self.get_user_subscription(user_id)

        async def run(db: aiosqlite.Connection) -> None:
            if not existing:
                await db.execute(
                    """
                    INSERT INTO subscriptions
                    (user_id, tier, status, stripe_customer_id, stripe_subscription_id,
                     stripe_price_id, current_period_end, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        tier or "free",
                        status or "active",
                        stripe_customer_id,
                        stripe_subscription_id,
                        stripe_price_id,
                        current_period_end,
                        now,
                    ),
                )
            else:
                await db.execute(
                    """
                    UPDATE subscriptions SET
                        tier = COALESCE(?, tier),
                        status = COALESCE(?, status),
                        stripe_customer_id = COALESCE(?, stripe_customer_id),
                        stripe_subscription_id = COALESCE(?, stripe_subscription_id),
                        stripe_price_id = COALESCE(?, stripe_price_id),
                        current_period_end = COALESCE(?, current_period_end),
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        tier,
                        status,
                        stripe_customer_id,
                        stripe_subscription_id,
                        stripe_price_id,
                        current_period_end,
                        now,
                        user_id,
                    ),
                )
            await db.commit()

        await self._with_db(run)

    async def record_usage(self, user_id: int, event_type: str) -> None:
        now = datetime.now(timezone.utc).isoformat()

        async def run(db: aiosqlite.Connection) -> None:
            await db.execute(
                "INSERT INTO usage_events (user_id, event_type, created_at) VALUES (?, ?, ?)",
                (user_id, event_type, now),
            )
            await db.commit()

        await self._with_db(run)

    async def get_usage_count(
        self, user_id: int, event_type: str, period_key: str, *, period: str = "month"
    ) -> int:
        async def run(db: aiosqlite.Connection) -> int:
            if period == "day":
                rows = await db.execute_fetchall(
                    """
                    SELECT COUNT(*) AS c FROM usage_events
                    WHERE user_id = ? AND event_type = ? AND created_at LIKE ?
                    """,
                    (user_id, event_type, f"{period_key}%"),
                )
            else:
                rows = await db.execute_fetchall(
                    """
                    SELECT COUNT(*) AS c FROM usage_events
                    WHERE user_id = ? AND event_type = ? AND created_at LIKE ?
                    """,
                    (user_id, event_type, f"{period_key}%"),
                )
            return int(rows[0][0]) if rows else 0

        return await self._with_db(run)

    async def get_usage_counts(
        self, user_id: int, period_key: str, *, period: str = "month"
    ) -> dict[str, int]:
        event_types = [
            "brief_regen",
            "picks",
            "picks_refresh",
            "portfolio_analysis",
            "portfolio_analysis_refresh",
            "explore",
            "late_day",
        ]
        out: dict[str, int] = {}
        for et in event_types:
            out[et] = await self.get_usage_count(user_id, et, period_key, period=period)
        return out

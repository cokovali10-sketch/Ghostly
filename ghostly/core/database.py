from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiosqlite


DB_PATH = Path(__file__).parent.parent / "ghostly_data.db"


class Database:
    """Async SQLite database manager for Ghostly analytics."""

    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def __aenter__(self) -> "Database":
        await self.connect()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._db

    async def init_db(self) -> None:
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sites (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                domain      TEXT NOT NULL UNIQUE,
                name        TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                is_active   INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS pageviews (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                visitor_id  TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                url         TEXT NOT NULL,
                path        TEXT NOT NULL DEFAULT '/',
                title       TEXT NOT NULL DEFAULT '',
                referrer    TEXT NOT NULL DEFAULT '',
                language    TEXT NOT NULL DEFAULT '',
                screen_size TEXT NOT NULL DEFAULT '',
                ip_address  TEXT NOT NULL DEFAULT '',
                country     TEXT NOT NULL DEFAULT '',
                browser     TEXT NOT NULL DEFAULT '',
                os          TEXT NOT NULL DEFAULT '',
                device_type TEXT NOT NULL DEFAULT 'desktop',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS visitors (
                id          TEXT PRIMARY KEY,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                ip_address  TEXT NOT NULL DEFAULT '',
                user_agent  TEXT NOT NULL DEFAULT '',
                country     TEXT NOT NULL DEFAULT '',
                first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                visits      INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id          TEXT PRIMARY KEY,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                visitor_id  TEXT NOT NULL,
                started_at  TEXT NOT NULL DEFAULT (datetime('now')),
                ended_at    TEXT,
                page_count  INTEGER NOT NULL DEFAULT 1,
                referrer    TEXT NOT NULL DEFAULT '',
                browser     TEXT NOT NULL DEFAULT '',
                os          TEXT NOT NULL DEFAULT '',
                device_type TEXT NOT NULL DEFAULT 'desktop',
                country     TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                visitor_id  TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                name        TEXT NOT NULL,
                url         TEXT NOT NULL DEFAULT '',
                meta        TEXT NOT NULL DEFAULT '{}',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS referrers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                url         TEXT NOT NULL,
                domain      TEXT NOT NULL DEFAULT '',
                visits      INTEGER NOT NULL DEFAULT 1,
                last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(site_id, url)
            );

            CREATE TABLE IF NOT EXISTS devices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                device_type TEXT NOT NULL,
                visits      INTEGER NOT NULL DEFAULT 1,
                last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(site_id, device_type)
            );

            CREATE TABLE IF NOT EXISTS browsers (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                browser     TEXT NOT NULL,
                visits      INTEGER NOT NULL DEFAULT 1,
                last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(site_id, browser)
            );

            CREATE TABLE IF NOT EXISTS countries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                country     TEXT NOT NULL,
                visits      INTEGER NOT NULL DEFAULT 1,
                last_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(site_id, country)
            );

            CREATE INDEX IF NOT EXISTS idx_pageviews_site_id ON pageviews(site_id);
            CREATE INDEX IF NOT EXISTS idx_pageviews_created_at ON pageviews(created_at);
            CREATE INDEX IF NOT EXISTS idx_pageviews_path ON pageviews(path);
            CREATE INDEX IF NOT EXISTS idx_pageviews_visitor_id ON pageviews(visitor_id);
            CREATE INDEX IF NOT EXISTS idx_visitors_site_id ON visitors(site_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_site_id ON sessions(site_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_visitor_id ON sessions(visitor_id);
            CREATE INDEX IF NOT EXISTS idx_events_site_id ON events(site_id);
            CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
            CREATE INDEX IF NOT EXISTS idx_referrers_site_id ON referrers(site_id);
        """)

    # ── inserts ──────────────────────────────────────────────────────────

    async def insert_pageview(
        self,
        *,
        site_id: int,
        visitor_id: str,
        session_id: str,
        url: str,
        path: str,
        title: str = "",
        referrer: str = "",
        language: str = "",
        screen_size: str = "",
        ip_address: str = "",
        country: str = "",
        browser: str = "",
        os: str = "",
        device_type: str = "desktop",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO pageviews
               (site_id, visitor_id, session_id, url, path, title,
                referrer, language, screen_size, ip_address, country,
                browser, os, device_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                site_id, visitor_id, session_id, url, path, title,
                referrer, language, screen_size, ip_address, country,
                browser, os, device_type,
            ),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def insert_event(
        self,
        *,
        site_id: int,
        visitor_id: str,
        session_id: str,
        name: str,
        url: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO events (site_id, visitor_id, session_id, name, url, meta)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (site_id, visitor_id, session_id, name, url, json.dumps(meta or {})),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    # ── query helpers ────────────────────────────────────────────────────

    async def _fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        cursor = await self.db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def _fetch_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        cursor = await self.db.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None

    # ── stats ────────────────────────────────────────────────────────────

    async def get_site_stats(self, site_id: int, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        total = await self._fetch_one(
            "SELECT COUNT(*) AS total FROM pageviews WHERE site_id=? AND created_at>=?",
            (site_id, since),
        )
        unique = await self._fetch_one(
            "SELECT COUNT(DISTINCT visitor_id) AS unique_visitors FROM pageviews WHERE site_id=? AND created_at>=?",
            (site_id, since),
        )
        sessions = await self._fetch_one(
            "SELECT COUNT(DISTINCT session_id) AS total_sessions FROM pageviews WHERE site_id=? AND created_at>=?",
            (site_id, since),
        )
        avg_time = await self._fetch_one(
            """SELECT AVG(julianday(ended_at) - julianday(started_at)) * 86400 AS avg_seconds
               FROM sessions WHERE site_id=? AND ended_at IS NOT NULL AND started_at>=?""",
            (site_id, since),
        )
        bounce = await self._fetch_one(
            """SELECT COUNT(*) AS bounced
               FROM sessions WHERE site_id=? AND page_count = 1 AND started_at>=?""",
            (site_id, since),
        )
        total_sessions = sessions["total_sessions"] if sessions else 0
        bounced_count = bounce["bounced"] if bounce else 0
        return {
            "total_pageviews": total["total"] if total else 0,
            "unique_visitors": unique["unique_visitors"] if unique else 0,
            "total_sessions": total_sessions,
            "avg_session_seconds": round(avg_time["avg_seconds"] or 0, 1) if avg_time else 0,
            "bounce_rate": round(bounced_count / total_sessions * 100, 1) if total_sessions else 0,
        }

    async def get_page_stats(self, site_id: int, days: int = 30, limit: int = 50) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self._fetch_all(
            """SELECT path, COUNT(*) AS views, COUNT(DISTINCT visitor_id) AS unique_visitors
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY path ORDER BY views DESC LIMIT ?""",
            (site_id, since, limit),
        )

    async def get_visitor_stats(self, site_id: int, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        returning = await self._fetch_one(
            "SELECT COUNT(*) AS returning FROM visitors WHERE site_id=? AND visits > 1 AND last_seen>=?",
            (site_id, since),
        )
        total = await self._fetch_one(
            "SELECT COUNT(*) AS total FROM visitors WHERE site_id=? AND last_seen>=?",
            (site_id, since),
        )
        t = total["total"] if total else 0
        r = returning["returning"] if returning else 0
        return {
            "total_visitors": t,
            "returning_visitors": r,
            "new_visitors": t - r,
            "return_rate": round(r / t * 100, 1) if t else 0,
        }

    async def get_referrer_stats(self, site_id: int, days: int = 30, limit: int = 30) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self._fetch_all(
            """SELECT domain, url, SUM(visits) AS visits
               FROM referrers WHERE site_id=? AND last_seen>=?
               GROUP BY domain ORDER BY visits DESC LIMIT ?""",
            (site_id, since, limit),
        )

    async def get_device_stats(self, site_id: int, days: int = 30) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self._fetch_all(
            """SELECT device_type, COUNT(*) AS views
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY device_type ORDER BY views DESC""",
            (site_id, since),
        )

    async def get_browser_stats(self, site_id: int, days: int = 30) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self._fetch_all(
            """SELECT browser, COUNT(*) AS views
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY browser ORDER BY views DESC""",
            (site_id, since),
        )

    async def get_country_stats(self, site_id: int, days: int = 30, limit: int = 50) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self._fetch_all(
            """SELECT country, COUNT(*) AS views
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY country ORDER BY views DESC LIMIT ?""",
            (site_id, since, limit),
        )

    async def get_daily_stats(self, site_id: int, days: int = 30) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self._fetch_all(
            """SELECT date(created_at) AS day, COUNT(*) AS views, COUNT(DISTINCT visitor_id) AS unique_visitors
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY day ORDER BY day""",
            (site_id, since),
        )

    async def get_hourly_stats(self, site_id: int, days: int = 7) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self._fetch_all(
            """SELECT strftime('%H', created_at) AS hour, COUNT(*) AS views
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY hour ORDER BY hour""",
            (site_id, since),
        )

    async def get_retention(self, site_id: int, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = await self._fetch_all(
            """SELECT visitor_id, MIN(created_at) AS first_visit, MAX(created_at) AS last_visit,
                      COUNT(*) AS total_visits
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY visitor_id""",
            (site_id, since),
        )
        if not rows:
            return {"cohorts": [], "avg_visits_per_visitor": 0, "max_visits_per_visitor": 0}
        visits = [r["total_visits"] for r in rows]
        return {
            "total_visitors": len(rows),
            "avg_visits_per_visitor": round(sum(visits) / len(visits), 1),
            "max_visits_per_visitor": max(visits),
            "one_time_visitors": sum(1 for v in visits if v == 1),
            "repeat_visitors": sum(1 for v in visits if v > 1),
        }

    async def search(self, site_id: int, query: str, limit: int = 50) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        return await self._fetch_all(
            """SELECT DISTINCT path, title, COUNT(*) AS views
               FROM pageviews WHERE site_id=? AND (path LIKE ? OR title LIKE ?)
               GROUP BY path ORDER BY views DESC LIMIT ?""",
            (site_id, pattern, pattern, limit),
        )

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
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
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL DEFAULT 'viewer',
                is_active     INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until  TEXT,
                created_at    TEXT NOT NULL DEFAULT (datetime('now')),
                last_login    TEXT
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                id         TEXT PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token      TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action    TEXT NOT NULL,
                resource  TEXT NOT NULL DEFAULT '',
                details   TEXT NOT NULL DEFAULT '{}',
                ip        TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_api_keys (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name       TEXT NOT NULL DEFAULT '',
                key_hash   TEXT NOT NULL UNIQUE,
                permissions TEXT NOT NULL DEFAULT '["read"]',
                rate_limit INTEGER NOT NULL DEFAULT 1000,
                is_active  INTEGER NOT NULL DEFAULT 1,
                last_used  TEXT,
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS password_resets (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

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

            CREATE TABLE IF NOT EXISTS analytics_sessions (
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

            CREATE TABLE IF NOT EXISTS api_keys (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                name        TEXT NOT NULL DEFAULT '',
                key_hash    TEXT NOT NULL UNIQUE,
                permissions TEXT NOT NULL DEFAULT '["read"]',
                rate_limit  INTEGER NOT NULL DEFAULT 1000,
                is_active   INTEGER NOT NULL DEFAULT 1,
                last_used   TEXT,
                expires_at  TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id          INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                name             TEXT NOT NULL,
                alert_type       TEXT NOT NULL,
                threshold        REAL NOT NULL,
                window_minutes   INTEGER NOT NULL DEFAULT 5,
                cooldown_minutes INTEGER NOT NULL DEFAULT 30,
                status           TEXT NOT NULL DEFAULT 'active',
                metadata         TEXT NOT NULL DEFAULT '{}',
                last_triggered   TEXT,
                created_at       TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS alert_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id      INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
                site_id       INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                alert_type    TEXT NOT NULL,
                current_value REAL NOT NULL,
                threshold     REAL NOT NULL,
                triggered_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS funnels (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id      INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                name         TEXT NOT NULL,
                description  TEXT NOT NULL DEFAULT '',
                steps_config TEXT NOT NULL DEFAULT '[]',
                is_active    INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS funnel_steps (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                funnel_id   INTEGER NOT NULL REFERENCES funnels(id) ON DELETE CASCADE,
                step_order  INTEGER NOT NULL,
                name        TEXT NOT NULL,
                url_pattern TEXT NOT NULL DEFAULT '',
                match_type  TEXT NOT NULL DEFAULT 'prefix'
            );

            CREATE TABLE IF NOT EXISTS funnel_completions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                funnel_id   INTEGER NOT NULL REFERENCES funnels(id) ON DELETE CASCADE,
                visitor_id  TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                step_id     INTEGER NOT NULL REFERENCES funnel_steps(id) ON DELETE CASCADE,
                step_order  INTEGER NOT NULL,
                url         TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS goals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                goal_type   TEXT NOT NULL DEFAULT 'pageview',
                url_pattern TEXT NOT NULL DEFAULT '',
                match_type  TEXT NOT NULL DEFAULT 'prefix',
                is_active   INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS goal_completions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id     INTEGER NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                visitor_id  TEXT NOT NULL,
                session_id  TEXT NOT NULL,
                url         TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS exports (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                format      TEXT NOT NULL DEFAULT 'json',
                data_types  TEXT NOT NULL DEFAULT '[]',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS webhooks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                name        TEXT NOT NULL DEFAULT '',
                url         TEXT NOT NULL,
                events      TEXT NOT NULL DEFAULT '["pageview"]',
                is_active   INTEGER NOT NULL DEFAULT 1,
                secret      TEXT NOT NULL DEFAULT '',
                last_status INTEGER,
                last_error  TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
            CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(token);
            CREATE INDEX IF NOT EXISTS idx_audit_log_user_id ON audit_log(user_id);
            CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_user_api_keys_user_id ON user_api_keys(user_id);
            CREATE INDEX IF NOT EXISTS idx_user_api_keys_key_hash ON user_api_keys(key_hash);
            CREATE INDEX IF NOT EXISTS idx_password_resets_user_id ON password_resets(user_id);
            CREATE INDEX IF NOT EXISTS idx_password_resets_token ON password_resets(token_hash);
            CREATE INDEX IF NOT EXISTS idx_pageviews_site_id ON pageviews(site_id);
            CREATE INDEX IF NOT EXISTS idx_pageviews_created_at ON pageviews(created_at);
            CREATE INDEX IF NOT EXISTS idx_pageviews_path ON pageviews(path);
            CREATE INDEX IF NOT EXISTS idx_pageviews_visitor_id ON pageviews(visitor_id);
            CREATE INDEX IF NOT EXISTS idx_visitors_site_id ON visitors(site_id);
            CREATE INDEX IF NOT EXISTS idx_analytics_sessions_site_id ON analytics_sessions(site_id);
            CREATE INDEX IF NOT EXISTS idx_analytics_sessions_visitor_id ON analytics_sessions(visitor_id);
            CREATE INDEX IF NOT EXISTS idx_events_site_id ON events(site_id);
            CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
            CREATE INDEX IF NOT EXISTS idx_referrers_site_id ON referrers(site_id);
            CREATE INDEX IF NOT EXISTS idx_api_keys_site_id ON api_keys(site_id);
            CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
            CREATE INDEX IF NOT EXISTS idx_alerts_site_id ON alerts(site_id);
            CREATE INDEX IF NOT EXISTS idx_alert_history_site_id ON alert_history(site_id);
            CREATE INDEX IF NOT EXISTS idx_alert_history_alert_id ON alert_history(alert_id);
            CREATE INDEX IF NOT EXISTS idx_funnels_site_id ON funnels(site_id);
            CREATE INDEX IF NOT EXISTS idx_funnel_steps_funnel_id ON funnel_steps(funnel_id);
            CREATE INDEX IF NOT EXISTS idx_funnel_completions_funnel_id ON funnel_completions(funnel_id);
            CREATE INDEX IF NOT EXISTS idx_funnel_completions_visitor_id ON funnel_completions(visitor_id);
            CREATE INDEX IF NOT EXISTS idx_goals_site_id ON goals(site_id);
            CREATE INDEX IF NOT EXISTS idx_goal_completions_goal_id ON goal_completions(goal_id);
            CREATE INDEX IF NOT EXISTS idx_exports_site_id ON exports(site_id);
            CREATE INDEX IF NOT EXISTS idx_webhooks_site_id ON webhooks(site_id);

            CREATE TABLE IF NOT EXISTS email_config (
                id      INTEGER PRIMARY KEY CHECK (id = 1),
                config  TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS email_schedules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                recipients  TEXT NOT NULL DEFAULT '[]',
                cron_expr   TEXT NOT NULL DEFAULT '0 8 * * 1',
                days        INTEGER NOT NULL DEFAULT 7,
                is_active   INTEGER NOT NULL DEFAULT 1,
                last_sent   TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS heatmap_clicks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id          INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                visitor_id       TEXT NOT NULL DEFAULT '',
                page_url         TEXT NOT NULL DEFAULT '/',
                x                REAL NOT NULL DEFAULT 0,
                y                REAL NOT NULL DEFAULT 0,
                viewport_width   INTEGER NOT NULL DEFAULT 0,
                viewport_height  INTEGER NOT NULL DEFAULT 0,
                element_tag      TEXT NOT NULL DEFAULT '',
                element_id       TEXT NOT NULL DEFAULT '',
                element_classes  TEXT NOT NULL DEFAULT '',
                created_at       TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS themes (
                id         TEXT PRIMARY KEY,
                variables  TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS user_themes (
                user_id   TEXT PRIMARY KEY,
                theme_id  TEXT NOT NULL DEFAULT 'dark'
            );

            CREATE TABLE IF NOT EXISTS backups (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                filename         TEXT NOT NULL UNIQUE,
                original_size    INTEGER NOT NULL DEFAULT 0,
                compressed_size  INTEGER NOT NULL DEFAULT 0,
                compress         INTEGER NOT NULL DEFAULT 1,
                created_at       TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS visitor_locations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                visitor_id  TEXT NOT NULL,
                country     TEXT NOT NULL DEFAULT '',
                city        TEXT NOT NULL DEFAULT '',
                latitude    REAL,
                longitude   REAL,
                ip_address  TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS retention_cohorts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                visitor_id  TEXT NOT NULL,
                cohort_date TEXT NOT NULL,
                first_visit TEXT NOT NULL,
                last_visit  TEXT NOT NULL,
                visit_count INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ab_experiments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id     INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status      TEXT NOT NULL DEFAULT 'draft',
                traffic_pct REAL NOT NULL DEFAULT 100.0,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                ended_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS ab_variants (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id   INTEGER NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
                name            TEXT NOT NULL,
                weight          REAL NOT NULL DEFAULT 1.0,
                is_control      INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS ab_assignments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id   INTEGER NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
                variant_id      INTEGER NOT NULL REFERENCES ab_variants(id) ON DELETE CASCADE,
                visitor_id      TEXT NOT NULL,
                assigned_at     TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(experiment_id, visitor_id)
            );

            CREATE TABLE IF NOT EXISTS ab_conversions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id   INTEGER NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
                variant_id      INTEGER NOT NULL REFERENCES ab_variants(id) ON DELETE CASCADE,
                visitor_id      TEXT NOT NULL,
                event_name      TEXT NOT NULL DEFAULT '',
                value           REAL NOT NULL DEFAULT 0.0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_email_schedules_site_id ON email_schedules(site_id);
            CREATE INDEX IF NOT EXISTS idx_heatmap_clicks_site_id ON heatmap_clicks(site_id);
            CREATE INDEX IF NOT EXISTS idx_heatmap_clicks_page_url ON heatmap_clicks(page_url);
            CREATE INDEX IF NOT EXISTS idx_heatmap_clicks_created_at ON heatmap_clicks(created_at);
            CREATE INDEX IF NOT EXISTS idx_backups_created_at ON backups(created_at);
            CREATE INDEX IF NOT EXISTS idx_visitor_locations_site_id ON visitor_locations(site_id);
            CREATE INDEX IF NOT EXISTS idx_visitor_locations_country ON visitor_locations(country);
            CREATE INDEX IF NOT EXISTS idx_retention_cohorts_site_id ON retention_cohorts(site_id);
            CREATE INDEX IF NOT EXISTS idx_retention_cohorts_cohort_date ON retention_cohorts(cohort_date);
            CREATE INDEX IF NOT EXISTS idx_ab_experiments_site_id ON ab_experiments(site_id);
            CREATE INDEX IF NOT EXISTS idx_ab_variants_experiment_id ON ab_variants(experiment_id);
            CREATE INDEX IF NOT EXISTS idx_ab_assignments_experiment_id ON ab_assignments(experiment_id);
            CREATE INDEX IF NOT EXISTS idx_ab_assignments_visitor_id ON ab_assignments(visitor_id);
            CREATE INDEX IF NOT EXISTS idx_ab_conversions_experiment_id ON ab_conversions(experiment_id);

            CREATE TABLE IF NOT EXISTS organizations (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                name                  TEXT NOT NULL,
                plan                  TEXT NOT NULL DEFAULT 'free',
                subdomain             TEXT NOT NULL UNIQUE,
                owner_user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                is_active             INTEGER NOT NULL DEFAULT 1,
                max_sites             INTEGER NOT NULL DEFAULT 3,
                max_pageviews_monthly INTEGER NOT NULL DEFAULT 100000,
                max_team_members      INTEGER NOT NULL DEFAULT 2,
                max_api_keys          INTEGER NOT NULL DEFAULT 5,
                retention_days        INTEGER NOT NULL DEFAULT 30,
                billing_email         TEXT NOT NULL DEFAULT '',
                settings              TEXT NOT NULL DEFAULT '{}',
                created_at            TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at            TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS org_members (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id     INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role       TEXT NOT NULL DEFAULT 'viewer',
                invited_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                joined_at  TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(org_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS org_sites (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id  INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                site_id INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                UNIQUE(org_id, site_id)
            );

            CREATE TABLE IF NOT EXISTS usage_records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                usage_type  TEXT NOT NULL,
                amount      INTEGER NOT NULL DEFAULT 1,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS invoices (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                org_id          INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
                invoice_id      TEXT NOT NULL UNIQUE,
                amount          REAL NOT NULL DEFAULT 0,
                currency        TEXT NOT NULL DEFAULT 'USD',
                description     TEXT NOT NULL DEFAULT '',
                billing_period  TEXT NOT NULL DEFAULT 'monthly',
                status          TEXT NOT NULL DEFAULT 'pending',
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                name         TEXT PRIMARY KEY,
                cron_expr    TEXT NOT NULL DEFAULT '* * * * *',
                enabled      INTEGER NOT NULL DEFAULT 1,
                last_run     TEXT,
                next_run     TEXT,
                run_count    INTEGER NOT NULL DEFAULT 0,
                error_count  INTEGER NOT NULL DEFAULT 0,
                last_error   TEXT
            );

            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                cron_expr   TEXT NOT NULL,
                job_type    TEXT NOT NULL,
                config      TEXT NOT NULL DEFAULT '{}',
                org_id      INTEGER REFERENCES organizations(id) ON DELETE CASCADE,
                is_active   INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS job_run_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id      INTEGER NOT NULL REFERENCES scheduled_jobs(id) ON DELETE CASCADE,
                status      TEXT NOT NULL DEFAULT 'success',
                duration_ms REAL NOT NULL DEFAULT 0,
                error       TEXT,
                ran_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS search_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
                site_id       INTEGER REFERENCES sites(id) ON DELETE SET NULL,
                query         TEXT NOT NULL,
                results_count INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS realtime_snapshots (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id          INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                active_visitors  INTEGER NOT NULL DEFAULT 0,
                data             TEXT NOT NULL DEFAULT '{}',
                created_at       TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS daily_aggregates (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                site_id         INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
                aggregate_date  TEXT NOT NULL,
                data            TEXT NOT NULL DEFAULT '{}',
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(site_id, aggregate_date)
            );

            CREATE INDEX IF NOT EXISTS idx_organizations_subdomain ON organizations(subdomain);
            CREATE INDEX IF NOT EXISTS idx_organizations_owner ON organizations(owner_user_id);
            CREATE INDEX IF NOT EXISTS idx_org_members_org_id ON org_members(org_id);
            CREATE INDEX IF NOT EXISTS idx_org_members_user_id ON org_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_org_sites_org_id ON org_sites(org_id);
            CREATE INDEX IF NOT EXISTS idx_org_sites_site_id ON org_sites(site_id);
            CREATE INDEX IF NOT EXISTS idx_usage_records_org_id ON usage_records(org_id);
            CREATE INDEX IF NOT EXISTS idx_usage_records_type ON usage_records(usage_type);
            CREATE INDEX IF NOT EXISTS idx_invoices_org_id ON invoices(org_id);
            CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_org_id ON scheduled_jobs(org_id);
            CREATE INDEX IF NOT EXISTS idx_job_run_logs_job_id ON job_run_logs(job_id);
            CREATE INDEX IF NOT EXISTS idx_search_history_user_id ON search_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_search_history_site_id ON search_history(site_id);
            CREATE INDEX IF NOT EXISTS idx_search_history_query ON search_history(query);
            CREATE INDEX IF NOT EXISTS idx_realtime_snapshots_site_id ON realtime_snapshots(site_id);
            CREATE INDEX IF NOT EXISTS idx_realtime_snapshots_created_at ON realtime_snapshots(created_at);
            CREATE INDEX IF NOT EXISTS idx_daily_aggregates_site_id ON daily_aggregates(site_id);
            CREATE INDEX IF NOT EXISTS idx_daily_aggregates_date ON daily_aggregates(aggregate_date);
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

    # ── Users CRUD ────────────────────────────────────────────────────────

    async def create_user(
        self,
        email: str,
        password_hash: str,
        role: str = "viewer",
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)",
            (email, password_hash, role),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return await self._fetch_one(
            "SELECT id, email, password_hash, role, is_active, failed_attempts, locked_until, created_at, last_login FROM users WHERE email=?",
            (email,),
        )

    async def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        return await self._fetch_one(
            "SELECT id, email, role, is_active, created_at, last_login FROM users WHERE id=?",
            (user_id,),
        )

    async def get_user_full(self, user_id: int) -> dict[str, Any] | None:
        return await self._fetch_one(
            "SELECT id, email, password_hash, role, is_active, failed_attempts, locked_until, created_at, last_login FROM users WHERE id=?",
            (user_id,),
        )

    async def get_all_users(self) -> list[dict[str, Any]]:
        return await self._fetch_all(
            "SELECT id, email, role, is_active, created_at, last_login FROM users ORDER BY created_at DESC"
        )

    async def update_user(self, user_id: int, **kwargs: Any) -> bool:
        allowed = {"email", "password_hash", "role", "is_active", "failed_attempts", "locked_until", "last_login"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [user_id]
        await self.db.execute(f"UPDATE users SET {set_clause} WHERE id=?", values)
        await self.db.commit()
        return True

    async def delete_user(self, user_id: int) -> bool:
        result = await self.db.execute("DELETE FROM users WHERE id=?", (user_id,))
        await self.db.commit()
        return result.rowcount > 0

    # ── User Sessions CRUD ────────────────────────────────────────────────

    async def create_user_session(
        self,
        session_id: str,
        user_id: int,
        token: str,
        expires_at: str,
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO user_sessions (id, user_id, token, expires_at) VALUES (?, ?, ?, ?)",
            (session_id, user_id, token, expires_at),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_user_session(self, session_id: str) -> dict[str, Any] | None:
        return await self._fetch_one(
            "SELECT id, user_id, token, expires_at, created_at FROM user_sessions WHERE id=?",
            (session_id,),
        )

    async def get_user_sessions(self, user_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            "SELECT id, user_id, expires_at, created_at FROM user_sessions WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        )

    async def delete_user_session(self, session_id: str) -> bool:
        result = await self.db.execute("DELETE FROM user_sessions WHERE id=?", (session_id,))
        await self.db.commit()
        return result.rowcount > 0

    async def delete_user_sessions(self, user_id: int) -> int:
        result = await self.db.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
        await self.db.commit()
        return result.rowcount

    async def cleanup_expired_sessions(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        result = await self.db.execute(
            "DELETE FROM user_sessions WHERE expires_at < ?", (now,)
        )
        await self.db.commit()
        return result.rowcount

    # ── Audit Log ─────────────────────────────────────────────────────────

    async def log_audit(
        self,
        user_id: int | None,
        action: str,
        resource: str = "",
        details: dict[str, Any] | None = None,
        ip: str = "",
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO audit_log (user_id, action, resource, details, ip) VALUES (?, ?, ?, ?, ?)",
            (user_id, action, resource, json.dumps(details or {}), ip),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_audit_log(
        self,
        user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if user_id is not None:
            return await self._fetch_all(
                """SELECT al.id, al.user_id, u.email as user_email, al.action, al.resource,
                          al.details, al.ip, al.timestamp
                   FROM audit_log al LEFT JOIN users u ON al.user_id = u.id
                   WHERE al.user_id=? ORDER BY al.timestamp DESC LIMIT ? OFFSET ?""",
                (user_id, limit, offset),
            )
        return await self._fetch_all(
            """SELECT al.id, al.user_id, u.email as user_email, al.action, al.resource,
                      al.details, al.ip, al.timestamp
               FROM audit_log al LEFT JOIN users u ON al.user_id = u.id
               ORDER BY al.timestamp DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )

    # ── User API Keys CRUD ────────────────────────────────────────────────

    async def create_user_api_key(
        self,
        user_id: int,
        name: str,
        key_hash: str,
        permissions: str = '["read"]',
        rate_limit: int = 1000,
        expires_at: str | None = None,
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO user_api_keys (user_id, name, key_hash, permissions, rate_limit, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, name, key_hash, permissions, rate_limit, expires_at),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_user_api_keys(self, user_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, user_id, name, permissions, rate_limit, is_active,
                      last_used, expires_at, created_at
               FROM user_api_keys WHERE user_id=? ORDER BY created_at DESC""",
            (user_id,),
        )

    async def get_user_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        return await self._fetch_one(
            """SELECT id, user_id, name, permissions, rate_limit, is_active,
                      last_used, expires_at, created_at
               FROM user_api_keys WHERE key_hash=?""",
            (key_hash,),
        )

    async def get_user_api_key(self, key_id: int) -> dict[str, Any] | None:
        return await self._fetch_one(
            """SELECT id, user_id, name, permissions, rate_limit, is_active,
                      last_used, expires_at, created_at
               FROM user_api_keys WHERE id=?""",
            (key_id,),
        )

    async def delete_user_api_key(self, key_id: int) -> bool:
        result = await self.db.execute("DELETE FROM user_api_keys WHERE id=?", (key_id,))
        await self.db.commit()
        return result.rowcount > 0

    async def update_user_api_key_last_used(self, key_hash: str) -> None:
        await self.db.execute(
            "UPDATE user_api_keys SET last_used=datetime('now') WHERE key_hash=?",
            (key_hash,),
        )
        await self.db.commit()

    # ── Password Resets ───────────────────────────────────────────────────

    async def create_password_reset(
        self,
        user_id: int,
        token_hash: str,
        expires_at: str,
    ) -> int:
        await self.db.execute(
            "UPDATE password_resets SET used=1 WHERE user_id=? AND used=0",
            (user_id,),
        )
        cursor = await self.db.execute(
            "INSERT INTO password_resets (user_id, token_hash, expires_at) VALUES (?, ?, ?)",
            (user_id, token_hash, expires_at),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_password_reset(self, token_hash: str) -> dict[str, Any] | None:
        return await self._fetch_one(
            "SELECT id, user_id, token_hash, expires_at, used, created_at FROM password_resets WHERE token_hash=? AND used=0",
            (token_hash,),
        )

    async def use_password_reset(self, reset_id: int) -> bool:
        await self.db.execute(
            "UPDATE password_resets SET used=1 WHERE id=?", (reset_id,)
        )
        await self.db.commit()
        return True

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

    async def get_system_stats(self) -> dict[str, Any]:
        users = await self._fetch_one("SELECT COUNT(*) as total FROM users")
        active_users = await self._fetch_one("SELECT COUNT(*) as total FROM users WHERE is_active=1")
        sites = await self._fetch_one("SELECT COUNT(*) as total FROM sites")
        total_pageviews = await self._fetch_one("SELECT COUNT(*) as total FROM pageviews")
        api_keys = await self._fetch_one("SELECT COUNT(*) as total FROM user_api_keys WHERE is_active=1")
        sessions = await self._fetch_one("SELECT COUNT(*) as total FROM user_sessions")
        return {
            "total_users": users["total"] if users else 0,
            "active_users": active_users["total"] if active_users else 0,
            "total_sites": sites["total"] if sites else 0,
            "total_pageviews": total_pageviews["total"] if total_pageviews else 0,
            "active_api_keys": api_keys["total"] if api_keys else 0,
            "active_sessions": sessions["total"] if sessions else 0,
        }

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
               FROM analytics_sessions WHERE site_id=? AND ended_at IS NOT NULL AND started_at>=?""",
            (site_id, since),
        )
        bounce = await self._fetch_one(
            """SELECT COUNT(*) AS bounced
               FROM analytics_sessions WHERE site_id=? AND page_count = 1 AND started_at>=?""",
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

    # ── API Keys CRUD ──────────────────────────────────────────────────────

    async def create_api_key(
        self,
        site_id: int,
        name: str,
        key_hash: str,
        permissions: str = '["read"]',
        rate_limit: int = 1000,
        expires_at: str | None = None,
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO api_keys (site_id, name, key_hash, permissions, rate_limit, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (site_id, name, key_hash, permissions, rate_limit, expires_at),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_api_keys(self, site_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, site_id, name, permissions, rate_limit, is_active,
                      last_used, expires_at, created_at
               FROM api_keys WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )

    async def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        return await self._fetch_one(
            """SELECT id, site_id, name, permissions, rate_limit, is_active,
                      last_used, expires_at, created_at
               FROM api_keys WHERE key_hash=?""",
            (key_hash,),
        )

    async def delete_api_key(self, key_id: int) -> bool:
        result = await self.db.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
        await self.db.commit()
        return result.rowcount > 0

    # ── Alerts CRUD ────────────────────────────────────────────────────────

    async def create_alert(
        self,
        site_id: int,
        name: str,
        alert_type: str,
        threshold: float,
        window_minutes: int = 5,
        cooldown_minutes: int = 30,
        metadata: str = "{}",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO alerts (site_id, name, alert_type, threshold, window_minutes,
                                   cooldown_minutes, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (site_id, name, alert_type, threshold, window_minutes, cooldown_minutes, metadata),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_alerts(self, site_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, site_id, name, alert_type, threshold, window_minutes,
                      cooldown_minutes, status, metadata, last_triggered, created_at
               FROM alerts WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )

    async def get_alert(self, alert_id: int) -> dict[str, Any] | None:
        return await self._fetch_one(
            """SELECT id, site_id, name, alert_type, threshold, window_minutes,
                      cooldown_minutes, status, metadata, last_triggered, created_at
               FROM alerts WHERE id=?""",
            (alert_id,),
        )

    async def update_alert(self, alert_id: int, **kwargs: Any) -> bool:
        allowed = {"name", "threshold", "window_minutes", "cooldown_minutes", "status", "metadata"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [alert_id]
        await self.db.execute(f"UPDATE alerts SET {set_clause} WHERE id=?", values)
        await self.db.commit()
        return True

    async def delete_alert(self, alert_id: int) -> bool:
        result = await self.db.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
        await self.db.commit()
        return result.rowcount > 0

    async def get_active_alerts(self, site_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, site_id, name, alert_type, threshold, window_minutes,
                      cooldown_minutes, status, metadata, last_triggered
               FROM alerts WHERE site_id=? AND status IN ('active', 'triggered')""",
            (site_id,),
        )

    async def log_alert_trigger(
        self,
        alert_id: int,
        site_id: int,
        alert_type: str,
        current_value: float,
        threshold: float,
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO alert_history (alert_id, site_id, alert_type, current_value, threshold)
               VALUES (?, ?, ?, ?, ?)""",
            (alert_id, site_id, alert_type, current_value, threshold),
        )
        await self.db.execute(
            "UPDATE alerts SET last_triggered=datetime('now'), status='triggered' WHERE id=?",
            (alert_id,),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_alert_history(self, site_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT h.id, h.alert_id, a.name as alert_name, h.alert_type,
                      h.current_value, h.threshold, h.triggered_at
               FROM alert_history h
               LEFT JOIN alerts a ON h.alert_id = a.id
               WHERE h.site_id=?
               ORDER BY h.triggered_at DESC LIMIT ?""",
            (site_id, limit),
        )

    # ── Funnels CRUD ───────────────────────────────────────────────────────

    async def create_funnel(
        self,
        site_id: int,
        name: str,
        description: str = "",
        steps_config: str = "[]",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO funnels (site_id, name, description, steps_config)
               VALUES (?, ?, ?, ?)""",
            (site_id, name, description, steps_config),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_funnels(self, site_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, site_id, name, description, steps_config, is_active, created_at
               FROM funnels WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )

    async def get_funnel(self, funnel_id: int) -> dict[str, Any] | None:
        return await self._fetch_one(
            """SELECT id, site_id, name, description, steps_config, is_active, created_at
               FROM funnels WHERE id=?""",
            (funnel_id,),
        )

    async def delete_funnel(self, funnel_id: int) -> bool:
        await self.db.execute("DELETE FROM funnel_steps WHERE funnel_id=?", (funnel_id,))
        result = await self.db.execute("DELETE FROM funnels WHERE id=?", (funnel_id,))
        await self.db.commit()
        return result.rowcount > 0

    async def create_funnel_step(
        self,
        funnel_id: int,
        step_order: int,
        name: str,
        url_pattern: str = "",
        match_type: str = "prefix",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO funnel_steps (funnel_id, step_order, name, url_pattern, match_type)
               VALUES (?, ?, ?, ?, ?)""",
            (funnel_id, step_order, name, url_pattern, match_type),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_funnel_steps(self, funnel_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, funnel_id, step_order, name, url_pattern, match_type
               FROM funnel_steps WHERE funnel_id=? ORDER BY step_order""",
            (funnel_id,),
        )

    async def log_funnel_completion(
        self,
        funnel_id: int,
        visitor_id: str,
        session_id: str,
        step_id: int,
        step_order: int,
        url: str = "",
    ) -> int:
        existing = await self._fetch_one(
            """SELECT id FROM funnel_completions
               WHERE funnel_id=? AND visitor_id=? AND step_id=?""",
            (funnel_id, visitor_id, step_id),
        )
        if existing:
            return existing["id"]

        cursor = await self.db.execute(
            """INSERT INTO funnel_completions (funnel_id, visitor_id, session_id, step_id, step_order, url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (funnel_id, visitor_id, session_id, step_id, step_order, url),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_funnel_stats(self, funnel_id: int, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        steps = await self.get_funnel_steps(funnel_id)
        if not steps:
            return {"steps": [], "overall_conversion": 0}

        step_stats = []
        first_step_visitors = 0

        for idx, step in enumerate(steps):
            completions = await self._fetch_one(
                """SELECT COUNT(DISTINCT visitor_id) as count
                   FROM funnel_completions
                   WHERE funnel_id=? AND step_order=? AND created_at>=?""",
                (funnel_id, step["step_order"], since),
            )
            visitor_count = completions["count"] if completions else 0

            if idx == 0:
                first_step_visitors = visitor_count

            drop_off = 0
            conversion_rate = 0
            if idx > 0 and first_step_visitors > 0:
                conversion_rate = round((visitor_count / first_step_visitors) * 100, 2)
                prev_count = step_stats[idx - 1]["visitor_count"]
                if prev_count > 0:
                    drop_off = round(((prev_count - visitor_count) / prev_count) * 100, 2)

            step_stats.append({
                "step_order": step["step_order"],
                "name": step["name"],
                "visitor_count": visitor_count,
                "conversion_rate": conversion_rate,
                "drop_off_rate": drop_off,
            })

        overall_conversion = 0
        if first_step_visitors > 0 and step_stats:
            last_step_count = step_stats[-1]["visitor_count"]
            overall_conversion = round((last_step_count / first_step_visitors) * 100, 2)

        return {
            "steps": step_stats,
            "first_step_visitors": first_step_visitors,
            "overall_conversion": overall_conversion,
        }

    # ── Goals CRUD ─────────────────────────────────────────────────────────

    async def create_goal(
        self,
        site_id: int,
        name: str,
        goal_type: str = "pageview",
        url_pattern: str = "",
        match_type: str = "prefix",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO goals (site_id, name, goal_type, url_pattern, match_type)
               VALUES (?, ?, ?, ?, ?)""",
            (site_id, name, goal_type, url_pattern, match_type),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_goals(self, site_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, site_id, name, goal_type, url_pattern, match_type, is_active, created_at
               FROM goals WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )

    async def get_goal(self, goal_id: int) -> dict[str, Any] | None:
        return await self._fetch_one(
            """SELECT id, site_id, name, goal_type, url_pattern, match_type, is_active, created_at
               FROM goals WHERE id=?""",
            (goal_id,),
        )

    async def delete_goal(self, goal_id: int) -> bool:
        await self.db.execute("DELETE FROM goal_completions WHERE goal_id=?", (goal_id,))
        result = await self.db.execute("DELETE FROM goals WHERE id=?", (goal_id,))
        await self.db.commit()
        return result.rowcount > 0

    async def log_goal_completion(
        self,
        goal_id: int,
        visitor_id: str,
        session_id: str,
        url: str = "",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO goal_completions (goal_id, visitor_id, session_id, url)
               VALUES (?, ?, ?, ?)""",
            (goal_id, visitor_id, session_id, url),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_goal_stats(self, goal_id: int, days: int = 30) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        goal = await self.get_goal(goal_id)
        if not goal:
            return {}

        completions = await self._fetch_one(
            """SELECT COUNT(*) as total, COUNT(DISTINCT visitor_id) as unique_visitors
               FROM goal_completions WHERE goal_id=? AND completed_at>=?""",
            (goal_id, since),
        )

        daily = await self._fetch_all(
            """SELECT date(completed_at) as day, COUNT(*) as completions
               FROM goal_completions WHERE goal_id=? AND completed_at>=?
               GROUP BY day ORDER BY day""",
            (goal_id, since),
        )

        return {
            "goal": goal,
            "total_completions": completions["total"] if completions else 0,
            "unique_visitors": completions["unique_visitors"] if completions else 0,
            "daily_completions": daily,
        }

    # ── Exports CRUD ───────────────────────────────────────────────────────

    async def log_export(
        self,
        site_id: int,
        format: str,
        data_types: str = "[]",
    ) -> int:
        cursor = await self.db.execute(
            "INSERT INTO exports (site_id, format, data_types) VALUES (?, ?, ?)",
            (site_id, format, data_types),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_export_history(self, site_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, format, data_types, created_at
               FROM exports WHERE site_id=? ORDER BY created_at DESC LIMIT ?""",
            (site_id, limit),
        )

    # ── Webhooks CRUD ──────────────────────────────────────────────────────

    async def create_webhook(
        self,
        site_id: int,
        name: str,
        url: str,
        events: str = '["pageview"]',
        secret: str = "",
    ) -> int:
        cursor = await self.db.execute(
            """INSERT INTO webhooks (site_id, name, url, events, secret)
               VALUES (?, ?, ?, ?, ?)""",
            (site_id, name, url, events, secret),
        )
        await self.db.commit()
        return cursor.lastrowid or 0

    async def get_webhooks(self, site_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, site_id, name, url, events, is_active, last_status, created_at
               FROM webhooks WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )

    async def get_webhook(self, webhook_id: int) -> dict[str, Any] | None:
        return await self._fetch_one(
            """SELECT id, site_id, name, url, events, is_active, secret, last_status, last_error, created_at
               FROM webhooks WHERE id=?""",
            (webhook_id,),
        )

    async def delete_webhook(self, webhook_id: int) -> bool:
        result = await self.db.execute("DELETE FROM webhooks WHERE id=?", (webhook_id,))
        await self.db.commit()
        return result.rowcount > 0

    async def update_webhook_status(
        self,
        webhook_id: int,
        status: int,
        error: str | None = None,
    ) -> None:
        await self.db.execute(
            "UPDATE webhooks SET last_status=?, last_error=? WHERE id=?",
            (status, error, webhook_id),
        )
        await self.db.commit()

    async def get_active_webhooks(self, site_id: int) -> list[dict[str, Any]]:
        return await self._fetch_all(
            """SELECT id, site_id, name, url, events, secret
               FROM webhooks WHERE site_id=? AND is_active=1""",
            (site_id,),
        )

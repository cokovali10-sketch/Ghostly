from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

from ghostly.core.database import Database

logger = logging.getLogger("ghostly.scheduler")


def parse_cron(expr: str) -> dict[str, Any]:
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression: {expr}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "weekday": parts[4],
    }


def cron_matches(cron: dict[str, Any], dt: datetime) -> bool:
    checks = [
        (cron["minute"], dt.minute, 0, 59),
        (cron["hour"], dt.hour, 0, 23),
        (cron["day"], dt.day, 1, 31),
        (cron["month"], dt.month, 1, 12),
        (cron["weekday"], dt.isoweekday() % 7, 0, 6),
    ]
    for field, value, min_val, max_val in checks:
        if field == "*":
            continue
        if "/" in field:
            parts = field.split("/", 1)
            step = int(parts[1])
            if value % step != 0:
                return False
            continue
        if "-" in field:
            start, end = field.split("-", 1)
            if not (int(start) <= value <= int(end)):
                return False
            continue
        if "," in field:
            allowed = [int(x) for x in field.split(",")]
            if value not in allowed:
                return False
            continue
        if int(field) != value:
            return False
    return True


def next_cron_time(cron: dict[str, Any], after: datetime) -> datetime:
    candidate = after + timedelta(minutes=1)
    candidate = candidate.replace(second=0, microsecond=0)
    for _ in range(366 * 24 * 60):
        if cron_matches(cron, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    return after + timedelta(hours=1)


class TaskScheduler:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._tasks: dict[str, dict[str, Any]] = {}
        self._running = False
        self._task_handle: asyncio.Task[None] | None = None
        self._callbacks: dict[str, Callable[[], Awaitable[None]]] = {}
        self._tick_interval = 30

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self._load_tasks()
        self._task_handle = asyncio.create_task(self._run_loop())
        logger.info("Task scheduler started with %d registered tasks", len(self._tasks))

    async def stop(self) -> None:
        self._running = False
        if self._task_handle:
            self._task_handle.cancel()
            try:
                await self._task_handle
            except asyncio.CancelledError:
                pass
        logger.info("Task scheduler stopped")

    def register_task(self, name: str, callback: Callable[[], Awaitable[None]], cron_expr: str = "* * * * *", enabled: bool = True) -> None:
        cron = parse_cron(cron_expr)
        self._tasks[name] = {
            "name": name,
            "cron": cron,
            "cron_expr": cron_expr,
            "enabled": enabled,
            "last_run": None,
            "next_run": next_cron_time(cron, datetime.now(timezone.utc)),
            "run_count": 0,
            "error_count": 0,
            "last_error": None,
        }
        self._callbacks[name] = callback
        logger.info("Registered task '%s' with cron '%s'", name, cron_expr)

    def unregister_task(self, name: str) -> None:
        self._tasks.pop(name, None)
        self._callbacks.pop(name, None)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                for name, task in list(self._tasks.items()):
                    if not task["enabled"]:
                        continue
                    if task["next_run"] and now >= task["next_run"]:
                        await self._execute_task(name)
                        cron = task["cron"]
                        task["next_run"] = next_cron_time(cron, datetime.now(timezone.utc))
                        await self._save_task_state(name)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Scheduler loop error: %s", exc)
            await asyncio.sleep(self._tick_interval)

    async def _execute_task(self, name: str) -> None:
        task = self._tasks.get(name)
        callback = self._callbacks.get(name)
        if not task or not callback:
            return

        logger.info("Executing task '%s'", name)
        start = time.monotonic()
        try:
            await callback()
            elapsed = (time.monotonic() - start) * 1000
            task["last_run"] = datetime.now(timezone.utc).isoformat()
            task["run_count"] += 1
            task["last_error"] = None
            logger.info("Task '%s' completed in %.1fms", name, elapsed)
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            task["error_count"] += 1
            task["last_error"] = str(exc)
            logger.error("Task '%s' failed after %.1fms: %s", name, elapsed, exc)

    async def _load_tasks(self) -> None:
        rows = await self.db._fetch_all(
            "SELECT name, cron_expr, enabled, last_run, next_run, run_count, error_count, last_error FROM scheduled_tasks"
        )
        for row in rows:
            try:
                cron = parse_cron(row["cron_expr"])
                self._tasks[row["name"]] = {
                    "name": row["name"],
                    "cron": cron,
                    "cron_expr": row["cron_expr"],
                    "enabled": bool(row["enabled"]),
                    "last_run": row["last_run"],
                    "next_run": datetime.fromisoformat(row["next_run"]) if row["next_run"] else None,
                    "run_count": row["run_count"] or 0,
                    "error_count": row["error_count"] or 0,
                    "last_error": row["last_error"],
                }
            except Exception as exc:
                logger.warning("Failed to load task '%s': %s", row["name"], exc)

    async def _save_task_state(self, name: str) -> None:
        task = self._tasks.get(name)
        if not task:
            return
        await self.db.db.execute(
            """INSERT INTO scheduled_tasks (name, cron_expr, enabled, last_run, next_run, run_count, error_count, last_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   enabled=excluded.enabled, last_run=excluded.last_run,
                   next_run=excluded.next_run, run_count=excluded.run_count,
                   error_count=excluded.error_count, last_error=excluded.last_error""",
            (
                name, task["cron_expr"], int(task["enabled"]),
                task["last_run"],
                task["next_run"].isoformat() if task["next_run"] else None,
                task["run_count"], task["error_count"], task["last_error"],
            ),
        )
        await self.db.db.commit()

    def get_task_status(self, name: str) -> dict[str, Any] | None:
        task = self._tasks.get(name)
        if not task:
            return None
        return {
            "name": task["name"],
            "cron_expr": task["cron_expr"],
            "enabled": task["enabled"],
            "last_run": task["last_run"],
            "next_run": task["next_run"].isoformat() if task["next_run"] else None,
            "run_count": task["run_count"],
            "error_count": task["error_count"],
            "last_error": task["last_error"],
        }

    def get_all_tasks(self) -> list[dict[str, Any]]:
        return [self.get_task_status(name) for name in self._tasks]

    async def enable_task(self, name: str) -> bool:
        task = self._tasks.get(name)
        if not task:
            return False
        task["enabled"] = True
        task["next_run"] = next_cron_time(task["cron"], datetime.now(timezone.utc))
        await self._save_task_state(name)
        return True

    async def disable_task(self, name: str) -> bool:
        task = self._tasks.get(name)
        if not task:
            return False
        task["enabled"] = False
        await self._save_task_state(name)
        return True

    async def run_task_now(self, name: str) -> dict[str, Any]:
        if name not in self._tasks:
            return {"error": "Task not found"}
        await self._execute_task(name)
        return self.get_task_status(name) or {}

    async def add_scheduled_job(
        self,
        name: str,
        cron_expr: str,
        job_type: str,
        config: dict[str, Any] | None = None,
        org_id: int | None = None,
    ) -> int:
        cursor = await self.db.db.execute(
            """INSERT INTO scheduled_jobs (name, cron_expr, job_type, config, org_id, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, 1, datetime('now'))""",
            (name, cron_expr, job_type, json.dumps(config or {}), org_id),
        )
        await self.db.db.commit()
        return cursor.lastrowid or 0

    async def get_scheduled_jobs(self, org_id: int | None = None) -> list[dict[str, Any]]:
        if org_id:
            return await self.db._fetch_all(
                "SELECT * FROM scheduled_jobs WHERE org_id=? ORDER BY created_at DESC", (org_id,)
            )
        return await self.db._fetch_all("SELECT * FROM scheduled_jobs ORDER BY created_at DESC")

    async def update_scheduled_job(self, job_id: int, **kwargs: Any) -> bool:
        allowed = {"name", "cron_expr", "config", "is_active"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        if "config" in updates and isinstance(updates["config"], dict):
            updates["config"] = json.dumps(updates["config"])
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [job_id]
        await self.db.db.execute(f"UPDATE scheduled_jobs SET {set_clause} WHERE id=?", values)
        await self.db.db.commit()
        return True

    async def delete_scheduled_job(self, job_id: int) -> bool:
        result = await self.db.db.execute("DELETE FROM scheduled_jobs WHERE id=?", (job_id,))
        await self.db.db.commit()
        return result.rowcount > 0

    async def log_job_run(self, job_id: int, status: str, duration_ms: float = 0, error: str | None = None) -> int:
        cursor = await self.db.db.execute(
            """INSERT INTO job_run_logs (job_id, status, duration_ms, error, ran_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (job_id, status, duration_ms, error),
        )
        await self.db.db.commit()
        return cursor.lastrowid or 0

    async def get_job_logs(self, job_id: int, limit: int = 50) -> list[dict[str, Any]]:
        return await self.db._fetch_all(
            "SELECT * FROM job_run_logs WHERE job_id=? ORDER BY ran_at DESC LIMIT ?",
            (job_id, limit),
        )


class ReportGenerator:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def generate_site_report(self, site_id: int, days: int = 7) -> dict[str, Any]:
        from ghostly.core.aggregator import Aggregator
        aggregator = Aggregator(self.db)
        dashboard = await aggregator.get_dashboard(site_id, days)

        pages = await self.db.get_page_stats(site_id, days=days, limit=10)
        countries = await self.db.get_country_stats(site_id, days=days, limit=10)
        devices = await self.db.get_device_stats(site_id, days=days)
        referrers = await self.db.get_referrer_stats(site_id, days=days, limit=10)

        return {
            "site_id": site_id,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": dashboard,
            "top_pages": pages,
            "top_countries": countries,
            "devices": devices,
            "top_referrers": referrers,
        }

    async def generate_org_report(self, org_id: int, days: int = 7) -> dict[str, Any]:
        site_rows = await self.db._fetch_all(
            "SELECT site_id FROM org_sites WHERE org_id=?", (org_id,)
        )
        site_reports = []
        for row in site_rows:
            report = await self.generate_site_report(row["site_id"], days)
            site_reports.append(report)

        total_pageviews = sum(r["summary"].get("total_pageviews", 0) for r in site_reports)
        total_unique = sum(r["summary"].get("unique_visitors", 0) for r in site_reports)

        return {
            "org_id": org_id,
            "period_days": days,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_sites": len(site_reports),
            "total_pageviews": total_pageviews,
            "total_unique_visitors": total_unique,
            "sites": site_reports,
        }


class DataAggregator:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def aggregate_daily_stats(self, site_id: int, date: str | None = None) -> dict[str, Any]:
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        day_start = f"{date}T00:00:00"
        day_end = f"{date}T23:59:59"

        stats = await self.db._fetch_one(
            """SELECT COUNT(*) as pageviews, COUNT(DISTINCT visitor_id) as unique_visitors,
                      COUNT(DISTINCT session_id) as sessions
               FROM pageviews WHERE site_id=? AND created_at BETWEEN ? AND ?""",
            (site_id, day_start, day_end),
        )

        top_pages = await self.db._fetch_all(
            """SELECT path, COUNT(*) as views
               FROM pageviews WHERE site_id=? AND created_at BETWEEN ? AND ?
               GROUP BY path ORDER BY views DESC LIMIT 10""",
            (site_id, day_start, day_end),
        )

        countries = await self.db._fetch_all(
            """SELECT country, COUNT(*) as views
               FROM pageviews WHERE site_id=? AND country != '' AND created_at BETWEEN ? AND ?
               GROUP BY country ORDER BY views DESC LIMIT 20""",
            (site_id, day_start, day_end),
        )

        devices = await self.db._fetch_all(
            """SELECT device_type, COUNT(*) as views
               FROM pageviews WHERE site_id=? AND created_at BETWEEN ? AND ?
               GROUP BY device_type ORDER BY views DESC""",
            (site_id, day_start, day_end),
        )

        return {
            "site_id": site_id,
            "date": date,
            "pageviews": stats["pageviews"] if stats else 0,
            "unique_visitors": stats["unique_visitors"] if stats else 0,
            "sessions": stats["sessions"] if stats else 0,
            "top_pages": top_pages,
            "countries": countries,
            "devices": devices,
            "aggregated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def run_aggregation(self, site_id: int) -> dict[str, Any]:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

        today_stats = await self.aggregate_daily_stats(site_id, today)
        yesterday_stats = await self.aggregate_daily_stats(site_id, yesterday)

        await self.db.db.execute(
            """INSERT INTO daily_aggregates (site_id, aggregate_date, data, created_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(site_id, aggregate_date) DO UPDATE SET data=excluded.data""",
            (site_id, today, json.dumps(today_stats)),
        )
        await self.db.db.commit()

        return {"today": today_stats, "yesterday": yesterday_stats}


class DataCleanup:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def cleanup_old_pageviews(self, retention_days: int = 90) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        result = await self.db.db.execute(
            "DELETE FROM pageviews WHERE created_at < ?", (cutoff,)
        )
        await self.db.db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old pageviews (retention: %d days)", deleted, retention_days)
        return deleted

    async def cleanup_old_events(self, retention_days: int = 90) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        result = await self.db.db.execute(
            "DELETE FROM events WHERE created_at < ?", (cutoff,)
        )
        await self.db.db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old events", deleted)
        return deleted

    async def cleanup_old_sessions(self, retention_days: int = 90) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        result = await self.db.db.execute(
            "DELETE FROM analytics_sessions WHERE started_at < ?", (cutoff,)
        )
        await self.db.db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old sessions", deleted)
        return deleted

    async def cleanup_old_heatmap_clicks(self, retention_days: int = 60) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        result = await self.db.db.execute(
            "DELETE FROM heatmap_clicks WHERE created_at < ?", (cutoff,)
        )
        await self.db.db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old heatmap clicks", deleted)
        return deleted

    async def cleanup_old_realtime_snapshots(self, retention_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        result = await self.db.db.execute(
            "DELETE FROM realtime_snapshots WHERE created_at < ?", (cutoff,)
        )
        await self.db.db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old realtime snapshots", deleted)
        return deleted

    async def cleanup_old_search_history(self, retention_days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        result = await self.db.db.execute(
            "DELETE FROM search_history WHERE created_at < ?", (cutoff,)
        )
        await self.db.db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old search history entries", deleted)
        return deleted

    async def cleanup_expired_sessions(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        result = await self.db.db.execute(
            "DELETE FROM user_sessions WHERE expires_at < ?", (now,)
        )
        await self.db.db.commit()
        return result.rowcount

    async def run_full_cleanup(self, retention_days: int = 90) -> dict[str, Any]:
        results = {}
        results["pageviews"] = await self.cleanup_old_pageviews(retention_days)
        results["events"] = await self.cleanup_old_events(retention_days)
        results["sessions"] = await self.cleanup_old_sessions(retention_days)
        results["heatmap_clicks"] = await self.cleanup_old_heatmap_clicks(60)
        results["realtime_snapshots"] = await self.cleanup_old_realtime_snapshots(7)
        results["search_history"] = await self.cleanup_old_search_history(30)
        results["expired_sessions"] = await self.cleanup_expired_sessions()
        total = sum(results.values())
        logger.info("Full cleanup completed: %d total records removed", total)
        return results


class EmailReportSender:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def send_scheduled_reports(self) -> dict[str, Any]:
        from ghostly.core.email import EmailReporter
        reporter = EmailReporter(self.db)
        await reporter.load_config()

        schedules = await reporter.get_schedules()
        sent = 0
        failed = 0
        results = []

        for schedule in schedules:
            if not schedule.get("is_active"):
                continue

            last_sent = schedule.get("last_sent")
            cron_expr = schedule.get("cron_expr", "0 8 * * 1")
            try:
                cron = parse_cron(cron_expr)
                now = datetime.now(timezone.utc)
                if last_sent:
                    last_dt = datetime.fromisoformat(last_sent)
                    if (now - last_dt).total_seconds() < 86400:
                        continue
            except Exception:
                pass

            site_id = schedule.get("site_id")
            recipients = json.loads(schedule.get("recipients", "[]")) if isinstance(schedule.get("recipients"), str) else schedule.get("recipients", [])
            days = schedule.get("days", 7)

            if not recipients or not site_id:
                continue

            try:
                result = await reporter.send_report(site_id, recipients, days=days)
                sent += 1
                results.append({"site_id": site_id, "status": "sent", "recipients": len(recipients)})
            except Exception as exc:
                failed += 1
                results.append({"site_id": site_id, "status": "failed", "error": str(exc)})
                logger.error("Failed to send scheduled report for site %s: %s", site_id, exc)

        return {"sent": sent, "failed": failed, "details": results}

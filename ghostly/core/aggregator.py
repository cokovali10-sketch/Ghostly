from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .database import Database
# --- константы вынесены FORGE refactor ---
CONST_7 = 7



class Aggregator:
    """Higher-level analytics aggregation and comparison utilities."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _iso_ago(days: int, hours: int = 0) -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=days, hours=hours)
        return dt.isoformat()

    # ── daily / hourly aggregation ───────────────────────────────────────

    async def aggregate_daily(self, site_id: int, days: int = 90) -> dict[str, Any]:
        raw = await self.db.get_daily_stats(site_id, days)
        if not raw:
            return {"days": [], "total_views": 0, "total_unique": 0}
        total_views = sum(r["views"] for r in raw)
        total_unique = sum(r["unique_visitors"] for r in raw)
        return {
            "days": raw,
            "total_views": total_views,
            "total_unique": total_unique,
            "avg_daily_views": round(total_views / len(raw), 1),
            "avg_daily_unique": round(total_unique / len(raw), 1),
        }

    async def aggregate_hourly(self, site_id: int, days: int = CONST_7) -> dict[str, Any]:
        raw = await self.db.get_hourly_stats(site_id, days)
        hours_map = {f"{h:02d}": 0 for h in range(24)}
        for row in raw:
            hours_map[row["hour"]] = row["views"]
        peak = max(hours_map, key=hours_map.get)  # type: ignore[arg-type]
        return {
            "hours": hours_map,
            "peak_hour": peak,
            "total_views": sum(hours_map.values()),
        }

    # ── real-time ────────────────────────────────────────────────────────

    async def get_realtime_stats(self, site_id: int) -> dict[str, Any]:
        five_min_ago = self._iso_ago(0, hours=0, days=0) - timedelta(minutes=5)
        since = five_min_ago.isoformat()
        cursor = await self.db.db.execute(
            """SELECT COUNT(DISTINCT visitor_id) AS active_visitors,
                      COUNT(*) AS pageviews_last_5m
               FROM pageviews WHERE site_id=? AND created_at>=?""",
            (site_id, since),
        )
        row = await cursor.fetchone()
        row_dict = dict(row) if row else {"active_visitors": 0, "pageviews_last_5m": 0}

        cursor2 = await self.db.db.execute(
            """SELECT path, COUNT(*) AS views
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY path ORDER BY views DESC LIMIT 5""",
            (site_id, since),
        )
        top_pages = [dict(r) for r in await cursor2.fetchall()]

        cursor3 = await self.db.db.execute(
            """SELECT country, COUNT(*) AS views
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY country ORDER BY views DESC LIMIT 10""",
            (site_id, since),
        )
        top_countries = [dict(r) for r in await cursor3.fetchall()]

        return {
            "active_visitors": row_dict["active_visitors"],
            "pageviews_last_5m": row_dict["pageviews_last_5m"],
            "top_pages_realtime": top_pages,
            "top_countries_realtime": top_countries,
        }

    # ── trends (this week vs last week) ──────────────────────────────────

    async def get_trends(self, site_id: int) -> dict[str, Any]:
        this_week = self._iso_ago(days=CONST_7)
        last_week_start = self._iso_ago(days=14)
        last_week_end = self._iso_ago(days=CONST_7)

        this_row = await self.db._fetch_one(
            """SELECT COUNT(*) AS views, COUNT(DISTINCT visitor_id) AS unique_visitors
               FROM pageviews WHERE site_id=? AND created_at>=?""",
            (site_id, this_week),
        )
        last_row = await self.db._fetch_one(
            """SELECT COUNT(*) AS views, COUNT(DISTINCT visitor_id) AS unique_visitors
               FROM pageviews WHERE site_id=? AND created_at>=? AND created_at<?""",
            (site_id, last_week_start, last_week_end),
        )

        t_views = this_row["views"] if this_row else 0
        l_views = last_row["views"] if last_row else 0
        t_unique = this_row["unique_visitors"] if this_row else 0
        l_unique = last_row["unique_visitors"] if last_row else 0

        def pct_change(cur: int, prev: int) -> float:
            if prev == 0:
                return 100.0 if cur > 0 else 0.0
            return round((cur - prev) / prev * 100, 1)

        return {
            "this_week": {"views": t_views, "unique_visitors": t_unique},
            "last_week": {"views": l_views, "unique_visitors": l_unique},
            "views_change_pct": pct_change(t_views, l_views),
            "visitors_change_pct": pct_change(t_unique, l_unique),
        }

    # ── comparison (arbitrary date ranges) ───────────────────────────────

    async def get_comparison(
        self,
        site_id: int,
        start_a: str,
        end_a: str,
        start_b: str,
        end_b: str,
    ) -> dict[str, Any]:
        async def _range_stats(start: str, end: str) -> dict[str, int]:
            views = await self.db._fetch_one(
                """SELECT COUNT(*) AS views, COUNT(DISTINCT visitor_id) AS unique_visitors
                   FROM pageviews WHERE site_id=? AND created_at>=? AND created_at<?""",
                (site_id, start, end),
            )
            return {
                "views": views["views"] if views else 0,
                "unique_visitors": views["unique_visitors"] if views else 0,
            }

        a = await _range_stats(start_a, end_a)
        b = await _range_stats(start_b, end_b)

        def pct(cur: int, prev: int) -> float:
            if prev == 0:
                return 100.0 if cur > 0 else 0.0
            return round((cur - prev) / prev * 100, 1)

        return {
            "period_a": a,
            "period_b": b,
            "views_change_pct": pct(a["views"], b["views"]),
            "visitors_change_pct": pct(a["unique_visitors"], b["unique_visitors"]),
        }

    # ── combined dashboard payload ───────────────────────────────────────

    async def get_dashboard(self, site_id: int, days: int = 30) -> dict[str, Any]:
        stats, pages, referrers, devices, browsers, countries, daily, hourly, trends, realtime = (
            await self.db.get_site_stats(site_id, days),
            await self.db.get_page_stats(site_id, days),
            await self.db.get_referrer_stats(site_id, days),
            await self.db.get_device_stats(site_id, days),
            await self.db.get_browser_stats(site_id, days),
            await self.db.get_country_stats(site_id, days),
            await self.db.get_daily_stats(site_id, days),
            await self.db.get_hourly_stats(site_id, days),
            await self.get_trends(site_id),
            await self.get_realtime_stats(site_id),
        )
        return {
            "stats": stats,
            "top_pages": pages,
            "top_referrers": referrers,
            "devices": devices,
            "browsers": browsers,
            "countries": countries,
            "daily": daily,
            "hourly": hourly,
            "trends": trends,
            "realtime": realtime,
        }

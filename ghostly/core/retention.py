from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .database import Database

logger = logging.getLogger("ghostly.retention")


class RetentionAnalyzer:
    """Analyzes user retention, cohort behavior, and churn rates."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_daily_retention(
        self, site_id: int, days: int = 30
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        visitors = await self.db._fetch_all(
            """SELECT visitor_id, MIN(date(created_at)) AS first_visit,
                      MAX(date(created_at)) AS last_visit, COUNT(*) AS total_visits
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY visitor_id""",
            (site_id, since),
        )
        if not visitors:
            return []

        daily_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for v in visitors:
            daily_map[v["first_visit"]].append(v)

        today = datetime.now(timezone.utc).date()
        retention_data = []
        for cohort_date_str, cohort_visitors in sorted(daily_map.items()):
            cohort_date = datetime.strptime(cohort_date_str, "%Y-%m-%d").date()
            cohort_size = len(cohort_visitors)
            if cohort_size == 0:
                continue

            day_retention = []
            for day_offset in range(0, (today - cohort_date).days + 1):
                check_date = (cohort_date + timedelta(days=day_offset)).isoformat()
                retained = sum(
                    1 for v in cohort_visitors
                    if v["last_visit"] >= check_date and v["first_visit"] <= check_date
                )
                retention_rate = round(retained / cohort_size * 100, 2) if cohort_size else 0
                day_retention.append({
                    "day": day_offset,
                    "retained": retained,
                    "retention_rate": retention_rate,
                })

            retention_data.append({
                "cohort_date": cohort_date_str,
                "cohort_size": cohort_size,
                "daily_retention": day_retention,
            })

        return retention_data

    async def get_weekly_retention(
        self, site_id: int, weeks: int = 12
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()
        visitors = await self.db._fetch_all(
            """SELECT visitor_id, MIN(date(created_at)) AS first_visit,
                      MAX(date(created_at)) AS last_visit, COUNT(*) AS total_visits
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY visitor_id""",
            (site_id, since),
        )
        if not visitors:
            return []

        weekly_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for v in visitors:
            cohort_date = datetime.strptime(v["first_visit"], "%Y-%m-%d").date()
            week_start = cohort_date - timedelta(days=cohort_date.weekday())
            weekly_map[week_start.isoformat()].append(v)

        today = datetime.now(timezone.utc).date()
        this_week_start = today - timedelta(days=today.weekday())
        retention_data = []

        for cohort_week_str, cohort_visitors in sorted(weekly_map.items()):
            cohort_week = datetime.strptime(cohort_week_str, "%Y-%m-%d").date()
            cohort_size = len(cohort_visitors)
            if cohort_size == 0:
                continue

            weeks_since = (this_week_start - cohort_week).days // 7
            week_retention = []
            for week_offset in range(0, weeks_since + 1):
                check_week_start = cohort_week + timedelta(weeks=week_offset)
                check_week_end = check_week_start + timedelta(days=6)
                retained = sum(
                    1 for v in cohort_visitors
                    if v["last_visit"] >= check_week_start.isoformat()
                    and v["first_visit"] <= check_week_end.isoformat()
                )
                retention_rate = round(retained / cohort_size * 100, 2) if cohort_size else 0
                week_retention.append({
                    "week": week_offset,
                    "retained": retained,
                    "retention_rate": retention_rate,
                })

            retention_data.append({
                "cohort_week": cohort_week_str,
                "cohort_size": cohort_size,
                "weekly_retention": week_retention,
            })

        return retention_data

    async def get_monthly_retention(
        self, site_id: int, months: int = 12
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=months * 31)).isoformat()
        visitors = await self.db._fetch_all(
            """SELECT visitor_id, MIN(date(created_at)) AS first_visit,
                      MAX(date(created_at)) AS last_visit, COUNT(*) AS total_visits
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY visitor_id""",
            (site_id, since),
        )
        if not visitors:
            return []

        monthly_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for v in visitors:
            cohort_month = v["first_visit"][:7]
            monthly_map[cohort_month].append(v)

        today = datetime.now(timezone.utc).date()
        this_month = today.strftime("%Y-%m")
        retention_data = []

        for cohort_month_str, cohort_visitors in sorted(monthly_map.items()):
            cohort_size = len(cohort_visitors)
            if cohort_size == 0:
                continue

            cohort_month_date = datetime.strptime(cohort_month_str, "%Y-%m").date()
            this_month_date = datetime.strptime(this_month, "%Y-%m").date()
            months_since = (this_month_date.year - cohort_month_date.year) * 12 + (
                this_month_date.month - cohort_month_date.month
            )

            month_retention = []
            for month_offset in range(0, months_since + 1):
                m = (cohort_month_date.month + month_offset - 1) % 12 + 1
                y = cohort_month_date.year + (cohort_month_date.month + month_offset - 1) // 12
                check_month = f"{y:04d}-{m:02d}"
                retained = sum(
                    1 for v in cohort_visitors
                    if v["last_visit"][:7] >= check_month and v["first_visit"][:7] <= check_month
                )
                retention_rate = round(retained / cohort_size * 100, 2) if cohort_size else 0
                month_retention.append({
                    "month": month_offset,
                    "retained": retained,
                    "retention_rate": retention_rate,
                })

            retention_data.append({
                "cohort_month": cohort_month_str,
                "cohort_size": cohort_size,
                "monthly_retention": month_retention,
            })

        return retention_data

    async def get_cohort_analysis(
        self, site_id: int, days: int = 90, group_by: str = "week"
    ) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        visitors = await self.db._fetch_all(
            """SELECT visitor_id, MIN(date(created_at)) AS first_visit,
                      MAX(date(created_at)) AS last_visit, COUNT(*) AS total_visits
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY visitor_id""",
            (site_id, since),
        )
        if not visitors:
            return {"cohorts": [], "summary": {}, "group_by": group_by}

        cohorts: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for v in visitors:
            if group_by == "week":
                cohort_date = datetime.strptime(v["first_visit"], "%Y-%m-%d").date()
                week_start = cohort_date - timedelta(days=cohort_date.weekday())
                key = week_start.isoformat()
            elif group_by == "month":
                key = v["first_visit"][:7]
            else:
                key = v["first_visit"]
            cohorts[key].append(v)

        cohort_stats = []
        for cohort_key, cohort_visitors in sorted(cohorts.items()):
            cohort_size = len(cohort_visitors)
            visit_counts = [v["total_visits"] for v in cohort_visitors]
            returning = sum(1 for v in visit_counts if v > 1)

            avg_visits = round(sum(visit_counts) / cohort_size, 2) if cohort_size else 0
            return_rate = round(returning / cohort_size * 100, 2) if cohort_size else 0

            cohort_stats.append({
                "cohort": cohort_key,
                "cohort_size": cohort_size,
                "returning_visitors": returning,
                "return_rate": return_rate,
                "avg_visits_per_visitor": avg_visits,
            })

        total_visitors = sum(c["cohort_size"] for c in cohort_stats)
        total_returning = sum(c["returning_visitors"] for c in cohort_stats)

        return {
            "cohorts": cohort_stats,
            "summary": {
                "total_visitors": total_visitors,
                "total_returning": total_returning,
                "overall_return_rate": round(total_returning / total_visitors * 100, 2) if total_visitors else 0,
            },
            "group_by": group_by,
        }

    async def get_churn_rate(
        self, site_id: int, days: int = 30, inactive_days: int = 30
    ) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=inactive_days)).isoformat()

        total_visitors = await self.db._fetch_one(
            """SELECT COUNT(DISTINCT visitor_id) AS count
               FROM pageviews WHERE site_id=? AND created_at>=?""",
            (site_id, since),
        )
        total = total_visitors["count"] if total_visitors else 0

        active_visitors = await self.db._fetch_one(
            """SELECT COUNT(DISTINCT visitor_id) AS count
               FROM pageviews WHERE site_id=? AND created_at>=? AND created_at>=?""",
            (site_id, since, cutoff),
        )
        active = active_visitors["count"] if active_visitors else 0

        churned = total - active
        churn_rate = round(churned / total * 100, 2) if total else 0

        monthly_churn = []
        for month_offset in range(3):
            month_start = (datetime.now(timezone.utc) - timedelta(days=30 * (month_offset + 1))).isoformat()
            month_end = (datetime.now(timezone.utc) - timedelta(days=30 * month_offset)).isoformat()
            month_active = await self.db._fetch_one(
                """SELECT COUNT(DISTINCT visitor_id) AS count
                   FROM pageviews WHERE site_id=? AND created_at>=? AND created_at<?""",
                (site_id, month_start, month_end),
            )
            month_total = await self.db._fetch_one(
                """SELECT COUNT(DISTINCT visitor_id) AS count
                   FROM pageviews WHERE site_id=? AND created_at>=?""",
                (site_id, month_start),
            )
            ma = month_active["count"] if month_active else 0
            mt = month_total["count"] if month_total else 0
            mc = mt - ma
            monthly_churn.append({
                "period": f"{month_offset * 30}-{(month_offset + 1) * 30} days ago",
                "total_visitors": mt,
                "active_visitors": ma,
                "churned_visitors": mc,
                "churn_rate": round(mc / mt * 100, 2) if mt else 0,
            })

        return {
            "period_days": days,
            "inactive_threshold_days": inactive_days,
            "total_visitors": total,
            "active_visitors": active,
            "churned_visitors": churned,
            "churn_rate": churn_rate,
            "monthly_trend": monthly_churn,
        }

    async def get_return_visitor_stats(
        self, site_id: int, days: int = 30
    ) -> dict[str, Any]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        visitors = await self.db._fetch_all(
            """SELECT visitor_id, COUNT(*) AS total_visits,
                      MIN(date(created_at)) AS first_visit,
                      MAX(date(created_at)) AS last_visit
               FROM pageviews WHERE site_id=? AND created_at>=?
               GROUP BY visitor_id""",
            (site_id, since),
        )
        if not visitors:
            return {
                "total_visitors": 0,
                "new_visitors": 0,
                "returning_visitors": 0,
                "frequency_distribution": {},
            }

        total = len(visitors)
        new = sum(1 for v in visitors if v["total_visits"] == 1)
        returning = total - new

        freq_dist: dict[str, int] = defaultdict(int)
        for v in visitors:
            count = v["total_visits"]
            if count == 1:
                freq_dist["1 visit"] += 1
            elif count <= 5:
                freq_dist["2-5 visits"] += 1
            elif count <= 10:
                freq_dist["6-10 visits"] += 1
            elif count <= 25:
                freq_dist["11-25 visits"] += 1
            else:
                freq_dist["25+ visits"] += 1

        visit_counts = [v["total_visits"] for v in visitors]
        avg_visits = round(sum(visit_counts) / total, 2) if total else 0

        return {
            "total_visitors": total,
            "new_visitors": new,
            "returning_visitors": returning,
            "new_visitor_pct": round(new / total * 100, 2) if total else 0,
            "returning_visitor_pct": round(returning / total * 100, 2) if total else 0,
            "avg_visits_per_visitor": avg_visits,
            "frequency_distribution": dict(freq_dist),
        }

    async def get_retention_summary(self, site_id: int, days: int = 30) -> dict[str, Any]:
        return_visitor_stats = await self.get_return_visitor_stats(site_id, days)
        churn_data = await self.get_churn_rate(site_id, days)
        cohort_data = await self.get_cohort_analysis(site_id, days, group_by="week")

        return {
            "period_days": days,
            "visitor_stats": return_visitor_stats,
            "churn": churn_data,
            "cohort_summary": cohort_data.get("summary", {}),
        }
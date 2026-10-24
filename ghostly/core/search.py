from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ghostly.core.database import Database
# --- константы вынесены FORGE refactor ---
CONST_30 = 30
CONST_50 = 50


logger = logging.getLogger("ghostly.search")


class SearchEngine:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def search(
        self,
        site_id: int,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = CONST_50,
        offset: int = 0,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        filters = filters or {}
        results: list[dict[str, Any]] = []
        total = 0

        page_results, page_total = await self._search_pages(site_id, query, filters, limit, offset)
        results.extend(page_results)
        total += page_total

        event_results, event_total = await self._search_events(site_id, query, filters, limit, offset)
        results.extend(event_results)
        total += event_total

        visitor_results, visitor_total = await self._search_visitors(site_id, query, filters, limit, offset)
        results.extend(visitor_results)
        total += visitor_total

        results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        results = results[:limit]

        if user_id and query.strip():
            await self._log_search(user_id, site_id, query, len(results))

        return {
            "query": query,
            "filters": filters,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def _search_pages(
        self, site_id: int, query: str, filters: dict[str, Any], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        conditions = ["site_id = ?"]
        params: list[Any] = [site_id]

        if query.strip():
            pattern = f"%{query}%"
            conditions.append("(path LIKE ? OR title LIKE ? OR url LIKE ?)")
            params.extend([pattern, pattern, pattern])

        if "start_date" in filters:
            conditions.append("created_at >= ?")
            params.append(filters["start_date"])
        if "end_date" in filters:
            conditions.append("created_at <= ?")
            params.append(filters["end_date"])
        if "country" in filters:
            conditions.append("country = ?")
            params.append(filters["country"])
        if "device_type" in filters:
            conditions.append("device_type = ?")
            params.append(filters["device_type"])
        if "path" in filters:
            conditions.append("path LIKE ?")
            params.append(f"%{filters['path']}%")

        where = " AND ".join(conditions)

        count_row = await self.db._fetch_one(
            f"SELECT COUNT(DISTINCT path) as total FROM pageviews WHERE {where}",
            tuple(params),
        )
        total = count_row["total"] if count_row else 0

        rows = await self.db._fetch_all(
            f"""SELECT DISTINCT path, title, url, COUNT(*) as views,
                       COUNT(DISTINCT visitor_id) as unique_visitors,
                       MAX(created_at) as last_seen, MIN(created_at) as first_seen
                FROM pageviews WHERE {where}
                GROUP BY path
                ORDER BY views DESC
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        )

        results = []
        for row in rows:
            relevance = self._calculate_relevance(query, row.get("path", ""), row.get("title", ""))
            results.append({
                "type": "page",
                "path": row["path"],
                "title": row.get("title", ""),
                "url": row.get("url", ""),
                "views": row["views"],
                "unique_visitors": row["unique_visitors"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "relevance": relevance,
            })

        return results, total

    async def _search_events(
        self, site_id: int, query: str, filters: dict[str, Any], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        conditions = ["site_id = ?"]
        params: list[Any] = [site_id]

        if query.strip():
            pattern = f"%{query}%"
            conditions.append("(name LIKE ? OR url LIKE ? OR meta LIKE ?)")
            params.extend([pattern, pattern, pattern])

        if "start_date" in filters:
            conditions.append("created_at >= ?")
            params.append(filters["start_date"])
        if "end_date" in filters:
            conditions.append("created_at <= ?")
            params.append(filters["end_date"])

        where = " AND ".join(conditions)

        count_row = await self.db._fetch_one(
            f"SELECT COUNT(*) as total FROM events WHERE {where}",
            tuple(params),
        )
        total = count_row["total"] if count_row else 0

        rows = await self.db._fetch_all(
            f"""SELECT id, name, url, meta, visitor_id, created_at
                FROM events WHERE {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        )

        results = []
        for row in rows:
            relevance = self._calculate_relevance(query, row.get("name", ""), row.get("url", ""))
            results.append({
                "type": "event",
                "id": row["id"],
                "name": row["name"],
                "url": row.get("url", ""),
                "meta": json.loads(row.get("meta") or "{}"),
                "visitor_id": row.get("visitor_id", ""),
                "created_at": row["created_at"],
                "relevance": relevance,
            })

        return results, total

    async def _search_visitors(
        self, site_id: int, query: str, filters: dict[str, Any], limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        conditions = ["v.site_id = ?"]
        params: list[Any] = [site_id]

        if query.strip():
            pattern = f"%{query}%"
            conditions.append("(v.id LIKE ? OR v.country LIKE ? OR v.ip_address LIKE ?)")
            params.extend([pattern, pattern, pattern])

        if "country" in filters:
            conditions.append("v.country = ?")
            params.append(filters["country"])

        where = " AND ".join(conditions)

        count_row = await self.db._fetch_one(
            f"SELECT COUNT(*) as total FROM visitors v WHERE {where}",
            tuple(params),
        )
        total = count_row["total"] if count_row else 0

        rows = await self.db._fetch_all(
            f"""SELECT v.id, v.country, v.first_seen, v.last_seen, v.visits
                FROM visitors v WHERE {where}
                ORDER BY v.last_seen DESC
                LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        )

        results = []
        for row in rows:
            relevance = self._calculate_relevance(query, row.get("id", ""), row.get("country", ""))
            results.append({
                "type": "visitor",
                "visitor_id": row["id"],
                "country": row.get("country", ""),
                "visits": row["visits"],
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
                "relevance": relevance,
            })

        return results, total

    async def autocomplete(
        self, site_id: int, prefix: str, limit: int = 10
    ) -> list[dict[str, str]]:
        if not prefix.strip():
            return []

        pattern = f"{prefix}%"
        pages = await self.db._fetch_all(
            """SELECT DISTINCT path, title
               FROM pageviews WHERE site_id=? AND (path LIKE ? OR title LIKE ?)
               ORDER BY path
               LIMIT ?""",
            (site_id, pattern, pattern, limit),
        )

        suggestions = []
        seen = set()
        for page in pages:
            text = page.get("path", "")
            if text and text not in seen:
                seen.add(text)
                suggestions.append({
                    "text": text,
                    "label": page.get("title", "") or text,
                    "type": "page",
                })

        event_names = await self.db._fetch_all(
            """SELECT DISTINCT name
               FROM events WHERE site_id=? AND name LIKE ?
               LIMIT ?""",
            (site_id, pattern, limit),
        )
        for ev in event_names:
            name = ev.get("name", "")
            if name and name not in seen:
                seen.add(name)
                suggestions.append({
                    "text": name,
                    "label": name,
                    "type": "event",
                })

        countries = await self.db._fetch_all(
            """SELECT DISTINCT country
               FROM pageviews WHERE site_id=? AND country LIKE ? AND country != ''
               LIMIT ?""",
            (site_id, pattern, limit),
        )
        for c in countries:
            country = c.get("country", "")
            if country and country not in seen:
                seen.add(country)
                suggestions.append({
                    "text": country,
                    "label": country,
                    "type": "country",
                })

        return suggestions[:limit]

    async def get_search_suggestions(
        self, site_id: int, query: str, limit: int = 5
    ) -> list[str]:
        if not query.strip():
            return []

        recent = await self.db._fetch_all(
            """SELECT DISTINCT query
               FROM search_history WHERE site_id=? AND query LIKE ?
               ORDER BY created_at DESC LIMIT ?""",
            (site_id, f"{query}%", limit),
        )
        return [r["query"] for r in recent]

    async def get_popular_searches(
        self, site_id: int, days: int = CONST_30, limit: int = 10
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self.db._fetch_all(
            """SELECT query, COUNT(*) as count, MAX(created_at) as last_searched
               FROM search_history WHERE site_id=? AND created_at>=?
               GROUP BY query ORDER BY count DESC LIMIT ?""",
            (site_id, since, limit),
        )

    async def get_search_history(
        self, user_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        return await self.db._fetch_all(
            """SELECT id, query, site_id, results_count, created_at
               FROM search_history WHERE user_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        )

    async def _log_search(
        self, user_id: int, site_id: int, query: str, results_count: int
    ) -> None:
        try:
            await self.db.db.execute(
                """INSERT INTO search_history (user_id, site_id, query, results_count, created_at)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                (user_id, site_id, query, results_count),
            )
            await self.db.db.commit()
        except Exception as exc:
            logger.warning("Failed to log search: %s", exc)

    async def advanced_search(
        self,
        site_id: int,
        query: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        country: str | None = None,
        device_type: str | None = None,
        browser: str | None = None,
        referrer: str | None = None,
        page_pattern: str | None = None,
        event_name: str | None = None,
        min_views: int | None = None,
        sort_by: str = "relevance",
        sort_order: str = "desc",
        limit: int = CONST_50,
        offset: int = 0,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        filters = {}
        if date_from:
            filters["start_date"] = date_from
        if date_to:
            filters["end_date"] = date_to
        if country:
            filters["country"] = country
        if device_type:
            filters["device_type"] = device_type
        if page_pattern:
            filters["path"] = page_pattern

        result = await self.search(
            site_id=site_id,
            query=query,
            filters=filters,
            limit=limit,
            offset=offset,
            user_id=user_id,
        )

        filtered = result["results"]

        if browser:
            filtered = [r for r in filtered if r.get("type") != "page" or True]
        if referrer:
            filtered = [r for r in filtered if r.get("type") != "page" or True]
        if event_name:
            filtered = [r for r in filtered if r.get("type") != "event" or r.get("name") == event_name]
        if min_views is not None:
            filtered = [r for r in filtered if r.get("views", 0) >= min_views]

        reverse = sort_order == "desc"
        if sort_by == "date":
            filtered.sort(key=lambda x: x.get("last_seen") or x.get("created_at") or "", reverse=reverse)
        elif sort_by == "views":
            filtered.sort(key=lambda x: x.get("views", 0), reverse=reverse)
        elif sort_by == "relevance":
            filtered.sort(key=lambda x: x.get("relevance", 0), reverse=reverse)

        result["results"] = filtered[:limit]
        return result

    def _calculate_relevance(self, query: str, text1: str, text2: str) -> float:
        if not query.strip():
            return 0.0

        query_lower = query.lower()
        score = 0.0

        for text in [text1, text2]:
            text_lower = text.lower()
            if query_lower == text_lower:
                score += 100.0
            elif text_lower.startswith(query_lower):
                score += 80.0
            elif query_lower in text_lower:
                score += 60.0
            elif any(w in text_lower for w in query_lower.split()):
                score += CONST_30

        words = query_lower.split()
        for word in words:
            if word in text1.lower():
                score += 10.0
            if word in text2.lower():
                score += 10.0

        return round(score, 2)

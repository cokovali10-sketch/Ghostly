from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .database import Database
# --- константы вынесены FORGE refactor ---
CONST_30 = 30


logger = logging.getLogger("ghostly.goals")


class GoalManager:
    """Manages goal definitions and completion tracking."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_goal(
        self,
        site_id: int,
        name: str,
        goal_type: str = "pageview",
        url_pattern: str = "",
        match_type: str = "prefix",
    ) -> dict[str, Any]:
        """Create a new goal for a site.

        Args:
            site_id: The site ID.
            name: Human-readable goal name.
            goal_type: Type of goal - 'pageview', 'event', or 'custom'.
            url_pattern: URL pattern to match for pageview goals.
            match_type: How to match URLs - 'exact', 'prefix', or 'contains'.
        """
        valid_types = {"pageview", "event", "custom"}
        if goal_type not in valid_types:
            raise ValueError(f"Invalid goal type: {goal_type}. Must be one of {valid_types}")

        valid_match = {"exact", "prefix", "contains"}
        if match_type not in valid_match:
            raise ValueError(f"Invalid match type: {match_type}. Must be one of {valid_match}")

        cursor = await self.db.db.execute(
            """INSERT INTO goals (site_id, name, goal_type, url_pattern, match_type)
               VALUES (?, ?, ?, ?, ?)""",
            (site_id, name, goal_type, url_pattern, match_type),
        )
        await self.db.db.commit()
        goal_id = cursor.lastrowid or 0

        logger.info("Created goal %d for site %d: %s", goal_id, site_id, name)

        return {
            "id": goal_id,
            "site_id": site_id,
            "name": name,
            "goal_type": goal_type,
            "url_pattern": url_pattern,
            "match_type": match_type,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_goals(self, site_id: int) -> list[dict[str, Any]]:
        """Get all goals for a site."""
        return await self.db._fetch_all(
            """SELECT id, site_id, name, goal_type, url_pattern, match_type, is_active, created_at
               FROM goals WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )

    async def get_goal(self, goal_id: int) -> dict[str, Any] | None:
        """Get a specific goal by ID."""
        return await self.db._fetch_one(
            """SELECT id, site_id, name, goal_type, url_pattern, match_type, is_active, created_at
               FROM goals WHERE id=?""",
            (goal_id,),
        )

    async def update_goal(self, goal_id: int, **kwargs: Any) -> bool:
        """Update goal fields."""
        allowed = {"name", "goal_type", "url_pattern", "match_type", "is_active"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [goal_id]
        await self.db.db.execute(f"UPDATE goals SET {set_clause} WHERE id=?", values)
        await self.db.db.commit()
        return True

    async def delete_goal(self, goal_id: int) -> bool:
        """Delete a goal and its completions."""
        await self.db.db.execute("DELETE FROM goal_completions WHERE goal_id=?", (goal_id,))
        result = await self.db.db.execute("DELETE FROM goals WHERE id=?", (goal_id,))
        await self.db.db.commit()
        return result.rowcount > 0

    async def check_url_match(self, url: str, goal: dict[str, Any]) -> bool:
        """Check if a URL matches a goal's pattern."""
        pattern = goal.get("url_pattern", "")
        match_type = goal.get("match_type", "prefix")

        if not pattern:
            return False

        if match_type == "exact":
            return url == pattern
        elif match_type == "prefix":
            return url.startswith(pattern)
        elif match_type == "contains":
            return pattern in url
        return False

    async def track_goal_completion(
        self,
        goal_id: int,
        visitor_id: str,
        session_id: str,
        url: str = "",
    ) -> dict[str, Any]:
        """Record a visitor completing a goal."""
        goal = await self.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if not goal["is_active"]:
            return {"status": "skipped", "reason": "goal_inactive"}

        cursor = await self.db.db.execute(
            """INSERT INTO goal_completions (goal_id, visitor_id, session_id, url)
               VALUES (?, ?, ?, ?)""",
            (goal_id, visitor_id, session_id, url),
        )
        await self.db.db.commit()
        completion_id = cursor.lastrowid or 0

        logger.info(
            "Goal %d completed by visitor %s (completion %d)",
            goal_id, visitor_id[:16], completion_id,
        )

        return {
            "status": "recorded",
            "completion_id": completion_id,
            "goal_id": goal_id,
            "goal_name": goal["name"],
        }

    async def get_goal_stats(self, goal_id: int, days: int = CONST_30) -> dict[str, Any]:
        """Calculate goal completion statistics."""
        goal = await self.get_goal(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        since = datetime.now(timezone.utc).isoformat()

        completions = await self.db._fetch_one(
            """SELECT COUNT(*) as total, COUNT(DISTINCT visitor_id) as unique_visitors
               FROM goal_completions WHERE goal_id=? AND completed_at>=?""",
            (goal_id, since),
        )

        daily = await self.db._fetch_all(
            """SELECT date(completed_at) as day, COUNT(*) as completions,
                      COUNT(DISTINCT visitor_id) as unique_visitors
               FROM goal_completions WHERE goal_id=? AND completed_at>=?
               GROUP BY day ORDER BY day""",
            (goal_id, since),
        )

        return {
            "goal": goal,
            "period_days": days,
            "total_completions": completions["total"] if completions else 0,
            "unique_visitors": completions["unique_visitors"] if completions else 0,
            "daily_completions": daily,
        }

    async def get_all_goals_stats(self, site_id: int, days: int = CONST_30) -> list[dict[str, Any]]:
        """Get stats for all goals on a site."""
        goals = await self.get_goals(site_id)
        results = []
        for goal in goals:
            try:
                stats = await self.get_goal_stats(goal["id"], days)
                results.append(stats)
            except ValueError:
                continue
        return results

    async def process_pageview_for_goals(
        self,
        site_id: int,
        visitor_id: str,
        session_id: str,
        url: str,
    ) -> list[dict[str, Any]]:
        """Process a pageview against all active goals for a site.

        Returns list of matched goal completions.
        """
        goals = await self.db._fetch_all(
            """SELECT id, name, goal_type, url_pattern, match_type
               FROM goals WHERE site_id=? AND is_active=1 AND goal_type='pageview'""",
            (site_id,),
        )

        results = []
        for goal in goals:
            matched = await self.check_url_match(url, goal)
            if matched:
                try:
                    result = await self.track_goal_completion(
                        goal_id=goal["id"],
                        visitor_id=visitor_id,
                        session_id=session_id,
                        url=url,
                    )
                    results.append(result)
                except ValueError as exc:
                    logger.warning("Failed to track goal %d: %s", goal["id"], exc)

        return results

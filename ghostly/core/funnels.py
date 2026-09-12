from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from .database import Database

logger = logging.getLogger("ghostly.funnels")


class FunnelManager:
    """Manages funnel definitions and conversion tracking."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def create_funnel(
        self,
        site_id: int,
        name: str,
        steps: list[dict[str, Any]],
        description: str = "",
    ) -> dict[str, Any]:
        """Create a new funnel with ordered steps.

        Each step should have:
            - name: Step name
            - url_pattern: URL pattern to match (exact, prefix, or regex)
            - match_type: 'exact', 'prefix', or 'contains'
        """
        cursor = await self.db.db.execute(
            """INSERT INTO funnels (site_id, name, description, steps_config, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (site_id, name, description, json.dumps(steps)),
        )
        await self.db.db.commit()
        funnel_id = cursor.lastrowid or 0

        for idx, step in enumerate(steps):
            await self.db.db.execute(
                """INSERT INTO funnel_steps (funnel_id, step_order, name, url_pattern, match_type)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    funnel_id,
                    idx + 1,
                    step.get("name", f"Step {idx + 1}"),
                    step.get("url_pattern", ""),
                    step.get("match_type", "prefix"),
                ),
            )
        await self.db.db.commit()

        logger.info("Created funnel %d for site %d: %s", funnel_id, site_id, name)

        return {
            "id": funnel_id,
            "site_id": site_id,
            "name": name,
            "description": description,
            "steps": steps,
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_funnels(self, site_id: int) -> list[dict[str, Any]]:
        """Get all funnels for a site."""
        funnels = await self.db._fetch_all(
            """SELECT id, site_id, name, description, steps_config, is_active, created_at
               FROM funnels WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )

        for funnel in funnels:
            if isinstance(funnel.get("steps_config"), str):
                funnel["steps"] = json.loads(funnel["steps_config"])
            else:
                funnel["steps"] = []

        return funnels

    async def get_funnel(self, funnel_id: int) -> dict[str, Any] | None:
        """Get a specific funnel by ID."""
        funnel = await self.db._fetch_one(
            """SELECT id, site_id, name, description, steps_config, is_active, created_at
               FROM funnels WHERE id=?""",
            (funnel_id,),
        )

        if funnel:
            if isinstance(funnel.get("steps_config"), str):
                funnel["steps"] = json.loads(funnel["steps_config"])
            else:
                funnel["steps"] = []

            funnel["step_details"] = await self.db._fetch_all(
                """SELECT id, step_order, name, url_pattern, match_type
                   FROM funnel_steps WHERE funnel_id=? ORDER BY step_order""",
                (funnel_id,),
            )

        return funnel

    async def delete_funnel(self, funnel_id: int) -> bool:
        """Delete a funnel and its steps."""
        await self.db.db.execute("DELETE FROM funnel_steps WHERE funnel_id=?", (funnel_id,))
        result = await self.db.db.execute("DELETE FROM funnels WHERE id=?", (funnel_id,))
        await self.db.db.commit()
        return result.rowcount > 0

    async def track_funnel_completion(
        self,
        funnel_id: int,
        visitor_id: str,
        session_id: str,
        step_index: int,
        url: str = "",
    ) -> dict[str, Any]:
        """Track a visitor completing a funnel step."""
        funnel = await self.get_funnel(funnel_id)
        if not funnel:
            raise ValueError(f"Funnel {funnel_id} not found")

        steps = funnel.get("step_details", [])
        if step_index < 0 or step_index >= len(steps):
            raise ValueError(f"Invalid step index {step_index} for funnel with {len(steps)} steps")

        step = steps[step_index]

        existing = await self.db._fetch_one(
            """SELECT id FROM funnel_completions
               WHERE funnel_id=? AND visitor_id=? AND step_id=?""",
            (funnel_id, visitor_id, step["id"]),
        )

        if existing:
            return {"status": "already_recorded", "completion_id": existing["id"]}

        cursor = await self.db.db.execute(
            """INSERT INTO funnel_completions (funnel_id, visitor_id, session_id, step_id, step_order, url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (funnel_id, visitor_id, session_id, step["id"], step["step_order"], url),
        )
        await self.db.db.commit()
        completion_id = cursor.lastrowid or 0

        return {
            "status": "recorded",
            "completion_id": completion_id,
            "step_index": step_index,
            "step_name": step["name"],
        }

    async def get_funnel_stats(self, funnel_id: int, days: int = 30) -> dict[str, Any]:
        """Calculate funnel conversion statistics."""
        funnel = await self.get_funnel(funnel_id)
        if not funnel:
            raise ValueError(f"Funnel {funnel_id} not found")

        steps = funnel.get("step_details", [])
        if not steps:
            return {"funnel": funnel, "steps": [], "overall_conversion": 0}

        since = datetime.now(timezone.utc).isoformat()
        site_id = funnel["site_id"]

        step_stats = []
        first_step_visitors = 0

        for idx, step in enumerate(steps):
            completions = await self.db._fetch_one(
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
            "funnel_id": funnel_id,
            "funnel_name": funnel["name"],
            "period_days": days,
            "steps": step_stats,
            "first_step_visitors": first_step_visitors,
            "overall_conversion": overall_conversion,
            "total_completions": step_stats[-1]["visitor_count"] if step_stats else 0,
        }

    async def check_url_match(self, url: str, steps: list[dict[str, Any]]) -> int | None:
        """Check if a URL matches any funnel step. Returns step index or None."""
        import re

        for idx, step in enumerate(steps):
            pattern = step.get("url_pattern", "")
            match_type = step.get("match_type", "prefix")

            if not pattern:
                continue

            if match_type == "exact":
                if url == pattern:
                    return idx
            elif match_type == "prefix":
                if url.startswith(pattern):
                    return idx
            elif match_type == "contains":
                if pattern in url:
                    return idx
            elif match_type == "regex":
                try:
                    if re.search(pattern, url):
                        return idx
                except re.error:
                    continue

        return None

    async def process_pageview_for_funnels(
        self,
        site_id: int,
        visitor_id: str,
        session_id: str,
        url: str,
    ) -> list[dict[str, Any]]:
        """Process a pageview against all active funnels for a site.

        Returns list of matched funnel completions.
        """
        funnels = await self.db._fetch_all(
            """SELECT id, steps_config FROM funnels WHERE site_id=? AND is_active=1""",
            (site_id,),
        )

        results = []
        for funnel_row in funnels:
            funnel_id = funnel_row["id"]
            steps = json.loads(funnel_row["steps_config"]) if isinstance(funnel_row["steps_config"], str) else []

            step_index = await self.check_url_match(url, steps)
            if step_index is not None:
                try:
                    result = await self.track_funnel_completion(
                        funnel_id=funnel_id,
                        visitor_id=visitor_id,
                        session_id=session_id,
                        step_index=step_index,
                        url=url,
                    )
                    result["funnel_id"] = funnel_id
                    results.append(result)
                except ValueError as exc:
                    logger.warning("Failed to track funnel %d: %s", funnel_id, exc)

        return results

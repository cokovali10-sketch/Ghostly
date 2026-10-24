from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .database import Database
# --- константы вынесены FORGE refactor ---
CONST_20 = 20
CONST_30 = 30
CONST_50000 = 50000


logger = logging.getLogger("ghostly.heatmap")

GRID_SIZE = CONST_20
SECTION_COLS = 5
SECTION_ROWS = 4


class HeatmapCollector:
    """Collects and aggregates click position data for heatmap visualization."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def record_click(
        self,
        site_id: int,
        *,
        visitor_id: str,
        page_url: str,
        x: float,
        y: float,
        viewport_width: int = 0,
        viewport_height: int = 0,
        element_tag: str = "",
        element_id: str = "",
        element_classes: str = "",
    ) -> int:
        cursor = await self.db.db.execute(
            """INSERT INTO heatmap_clicks
               (site_id, visitor_id, page_url, x, y, viewport_width, viewport_height,
                element_tag, element_id, element_classes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                site_id, visitor_id, page_url, x, y,
                viewport_width, viewport_height,
                element_tag, element_id, element_classes,
            ),
        )
        await self.db.db.commit()
        return cursor.lastrowid or 0

    async def get_clicks(
        self,
        site_id: int,
        *,
        page_url: str | None = None,
        days: int = CONST_30,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        if page_url:
            return await self.db._fetch_all(
                """SELECT x, y, page_url, viewport_width, viewport_height,
                          element_tag, element_id, created_at
                   FROM heatmap_clicks
                   WHERE site_id=? AND page_url=? AND created_at>=?
                   ORDER BY created_at DESC LIMIT ?""",
                (site_id, page_url, since, limit),
            )
        return await self.db._fetch_all(
            """SELECT x, y, page_url, viewport_width, viewport_height,
                      element_tag, element_id, created_at
               FROM heatmap_clicks
               WHERE site_id=? AND created_at>=?
               ORDER BY created_at DESC LIMIT ?""",
            (site_id, since, limit),
        )

    async def generate_grid_data(
        self,
        site_id: int,
        *,
        page_url: str | None = None,
        days: int = CONST_30,
        grid_size: int = GRID_SIZE,
    ) -> dict[str, Any]:
        clicks = await self.get_clicks(site_id, page_url=page_url, days=days, limit=CONST_50000)

        if not clicks:
            return {"grid": [], "total_clicks": 0, "grid_size": grid_size, "pages": []}

        grid: dict[tuple[int, int], int] = defaultdict(int)
        pages: set[str] = set()

        for click in clicks:
            x = click.get("x", 0)
            y = click.get("y", 0)
            gx = int(x // grid_size)
            gy = int(y // grid_size)
            grid[(gx, gy)] += 1
            pages.add(click.get("page_url", ""))

        grid_data = [
            {"x": gx, "y": gy, "count": count}
            for (gx, gy), count in grid.items()
        ]

        return {
            "grid": grid_data,
            "total_clicks": len(clicks),
            "grid_size": grid_size,
            "pages": sorted(pages),
        }

    async def generate_section_data(
        self,
        site_id: int,
        *,
        page_url: str | None = None,
        days: int = CONST_30,
    ) -> dict[str, Any]:
        clicks = await self.get_clicks(site_id, page_url=page_url, days=days, limit=CONST_50000)

        if not clicks:
            return {"sections": [], "total_clicks": 0}

        max_x = max((c.get("x", 0) for c in clicks), default=1) or 1
        max_y = max((c.get("y", 0) for c in clicks), default=1) or 1

        sections: dict[tuple[int, int], int] = defaultdict(int)
        col_width = max_x / SECTION_COLS
        row_height = max_y / SECTION_ROWS

        for click in clicks:
            x = click.get("x", 0)
            y = click.get("y", 0)
            col = min(int(x / col_width) if col_width > 0 else 0, SECTION_COLS - 1)
            row = min(int(y / row_height) if row_height > 0 else 0, SECTION_ROWS - 1)
            sections[(col, row)] += 1

        section_data = []
        for col in range(SECTION_COLS):
            for row in range(SECTION_ROWS):
                count = sections.get((col, row), 0)
                section_data.append({
                    "col": col,
                    "row": row,
                    "label": f"{chr(65 + col)}{row + 1}",
                    "count": count,
                })

        return {
            "sections": section_data,
            "total_clicks": len(clicks),
            "grid_cols": SECTION_COLS,
            "grid_rows": SECTION_ROWS,
        }

    async def get_click_element_stats(
        self,
        site_id: int,
        *,
        page_url: str | None = None,
        days: int = CONST_30,
        limit: int = CONST_20,
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        where = "site_id=? AND created_at>=?"
        params: list[Any] = [site_id, since]
        if page_url:
            where += " AND page_url=?"
            params.append(page_url)

        rows = await self.db._fetch_all(
            f"""SELECT element_tag, element_id, element_classes, COUNT(*) as clicks
                FROM heatmap_clicks
                WHERE {where} AND element_tag != ''
                GROUP BY element_tag, element_id, element_classes
                ORDER BY clicks DESC LIMIT ?""",
            (*params, limit),
        )
        return rows

    async def get_page_click_counts(
        self,
        site_id: int,
        days: int = CONST_30,
        limit: int = CONST_30,
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return await self.db._fetch_all(
            """SELECT page_url, COUNT(*) as clicks, COUNT(DISTINCT visitor_id) as unique_visitors
               FROM heatmap_clicks
               WHERE site_id=? AND created_at>=?
               GROUP BY page_url ORDER BY clicks DESC LIMIT ?""",
            (site_id, since, limit),
        )

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any

from .database import Database

logger = logging.getLogger("ghostly.export")


class ExportManager:
    """Handles exporting analytics data to CSV, JSON, and HTML reports."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def export_site_data(
        self,
        site_id: int,
        format: str = "json",
        start_date: str | None = None,
        end_date: str | None = None,
        data_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export site data in the specified format.

        Args:
            site_id: The site ID to export data for.
            format: Output format - 'csv', 'json', or 'html'.
            start_date: ISO format start date for filtering.
            end_date: ISO format end date for filtering.
            data_types: List of data types to export (pageviews, visitors, sessions, events).

        Returns:
            Dict with 'content' (string data), 'content_type', and 'filename'.
        """
        if data_types is None:
            data_types = ["pageviews", "visitors", "sessions", "events"]

        site = await self.db._fetch_one("SELECT id, domain, name FROM sites WHERE id=?", (site_id,))
        if not site:
            raise ValueError(f"Site {site_id} not found")

        date_filter = ""
        params: list[Any] = [site_id]

        if start_date:
            date_filter += " AND created_at >= ?"
            params.append(start_date)
        if end_date:
            date_filter += " AND created_at <= ?"
            params.append(end_date)

        export_data: dict[str, list[dict[str, Any]]] = {}

        if "pageviews" in data_types:
            rows = await self.db._fetch_all(
                f"""SELECT id, visitor_id, session_id, url, path, title, referrer,
                           language, screen_size, country, browser, os, device_type, created_at
                    FROM pageviews WHERE site_id=? {date_filter}
                    ORDER BY created_at DESC""",
                tuple(params),
            )
            export_data["pageviews"] = rows

        if "visitors" in data_types:
            rows = await self.db._fetch_all(
                f"""SELECT id, ip_address, country, first_seen, last_seen, visits
                    FROM visitors WHERE site_id=? {date_filter.replace('created_at', 'last_seen') if date_filter else ''}
                    ORDER BY last_seen DESC""",
                tuple(params),
            )
            export_data["visitors"] = rows

        if "sessions" in data_types:
            rows = await self.db._fetch_all(
                f"""SELECT id, visitor_id, started_at, ended_at, page_count, referrer,
                           browser, os, device_type, country
                    FROM sessions WHERE site_id=? {date_filter.replace('created_at', 'started_at') if date_filter else ''}
                    ORDER BY started_at DESC""",
                tuple(params),
            )
            export_data["sessions"] = rows

        if "events" in data_types:
            rows = await self.db._fetch_all(
                f"""SELECT id, visitor_id, session_id, name, url, meta, created_at
                    FROM events WHERE site_id=? {date_filter}
                    ORDER BY created_at DESC""",
                tuple(params),
            )
            export_data["events"] = rows

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        domain = site["domain"].replace(".", "_")
        filename = f"ghostly_{domain}_{timestamp}"

        if format == "csv":
            content = self._to_csv(export_data)
            return {
                "content": content,
                "content_type": "text/csv",
                "filename": f"{filename}.csv",
            }
        elif format == "html":
            content = self._to_html(export_data, site)
            return {
                "content": content,
                "content_type": "text/html",
                "filename": f"{filename}.html",
            }
        else:
            content = json.dumps(export_data, indent=2, default=str)
            return {
                "content": content,
                "content_type": "application/json",
                "filename": f"{filename}.json",
            }

    def _to_csv(self, data: dict[str, list[dict[str, Any]]]) -> str:
        """Convert export data to CSV format."""
        output = io.StringIO()

        for data_type, rows in data.items():
            if not rows:
                continue

            output.write(f"=== {data_type.upper()} ===\n")
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            output.write("\n")

        return output.getvalue()

    def _to_html(self, data: dict[str, list[dict[str, Any]]], site: dict[str, Any]) -> str:
        """Convert export data to HTML report format."""
        html_parts = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "  <meta charset='UTF-8'>",
            "  <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
            f"  <title>Ghostly Report - {site['domain']}</title>",
            "  <style>",
            "    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; background: #f5f5f5; }",
            "    h1 { color: #1a1a2e; border-bottom: 3px solid #6c63ff; padding-bottom: 10px; }",
            "    h2 { color: #16213e; margin-top: 30px; }",
            "    table { border-collapse: collapse; width: 100%; margin: 20px 0; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }",
            "    th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }",
            "    th { background: #6c63ff; color: white; }",
            "    tr:nth-child(even) { background: #f9f9f9; }",
            "    .summary { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin: 20px 0; }",
            "    .meta { color: #666; font-size: 0.9em; }",
            "  </style>",
            "</head>",
            "<body>",
            f"  <h1>Ghostly Analytics Report</h1>",
            f"  <div class='summary'>",
            f"    <p><strong>Site:</strong> {site['domain']} ({site['name']})</p>",
            f"    <p><strong>Generated:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>",
            f"  </div>",
        ]

        for data_type, rows in data.items():
            html_parts.append(f"  <h2>{data_type.replace('_', ' ').title()}</h2>")

            if not rows:
                html_parts.append("  <p>No data available for this section.</p>")
                continue

            html_parts.append("  <table>")
            html_parts.append("    <thead><tr>")
            for key in rows[0].keys():
                html_parts.append(f"      <th>{key}</th>")
            html_parts.append("    </tr></thead>")
            html_parts.append("    <tbody>")

            for row in rows[:500]:
                html_parts.append("    <tr>")
                for value in row.values():
                    html_parts.append(f"      <td>{value}</td>")
                html_parts.append("    </tr>")

            html_parts.append("    </tbody>")
            html_parts.append("  </table>")

            if len(rows) > 500:
                html_parts.append(f"  <p class='meta'>Showing 500 of {len(rows)} records.</p>")

        html_parts.extend([
            "  <footer class='meta' style='margin-top: 40px; text-align: center;'>",
            "    Generated by Ghostly Analytics",
            "  </footer>",
            "</body>",
            "</html>",
        ])

        return "\n".join(html_parts)

    async def get_export_history(self, site_id: int) -> list[dict[str, Any]]:
        """Get export history for a site."""
        return await self.db._fetch_all(
            """SELECT id, format, data_types, created_at
               FROM exports WHERE site_id=? ORDER BY created_at DESC LIMIT 50""",
            (site_id,),
        )

    async def log_export(
        self,
        site_id: int,
        format: str,
        data_types: list[str],
    ) -> int:
        """Log an export operation."""
        cursor = await self.db.db.execute(
            "INSERT INTO exports (site_id, format, data_types) VALUES (?, ?, ?)",
            (site_id, format, json.dumps(data_types)),
        )
        await self.db.db.commit()
        return cursor.lastrowid or 0

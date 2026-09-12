from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from .database import Database

logger = logging.getLogger("ghostly.email")


class EmailReporter:
    """Sends daily/weekly/monthly HTML analytics reports via email."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._config: dict[str, Any] = {}
        self._schedules: dict[str, dict[str, Any]] = {}

    async def load_config(self) -> None:
        row = await self.db._fetch_one("SELECT config FROM email_config WHERE id=1")
        if row:
            try:
                self._config = json.loads(row["config"])
            except (json.JSONDecodeError, TypeError):
                self._config = {}

    async def save_config(self, config: dict[str, Any]) -> None:
        self._config = config
        await self.db.db.execute(
            """INSERT INTO email_config (id, config) VALUES (1, ?)
               ON CONFLICT(id) DO UPDATE SET config=excluded.config""",
            (json.dumps(config),),
        )
        await self.db.db.commit()

    def get_config(self) -> dict[str, Any]:
        return {k: v for k, v in self._config.items() if k != "password"}

    def _smtp_connect(self) -> smtplib.SMTP:
        cfg = self._config
        host = cfg.get("host", "")
        port = int(cfg.get("port", 587))
        user = cfg.get("user", "")
        password = cfg.get("password", "")
        use_tls = cfg.get("use_tls", True)

        if not host:
            raise ValueError("SMTP host not configured")

        if use_tls:
            context = ssl.create_default_context()
            server = smtplib.SMTP(host, port, timeout=15)
            server.starttls(context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=15)

        if user and password:
            server.login(user, password)

        return server

    def _build_html_report(
        self,
        site: dict[str, Any],
        stats: dict[str, Any],
        visitor_stats: dict[str, Any],
        pages: list[dict[str, Any]],
        daily: list[dict[str, Any]],
        period_label: str,
    ) -> str:
        domain = site.get("domain", "unknown")
        name = site.get("name", domain)
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        top_pages_rows = ""
        for i, p in enumerate(pages[:10], 1):
            top_pages_rows += f"""
            <tr>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{i}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;">{p.get('path', '/')}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{p.get('views', 0)}</td>
              <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;">{p.get('unique_visitors', 0)}</td>
            </tr>"""

        chart_points = ""
        max_views = max((d.get("views", 0) for d in daily), default=1) or 1
        bar_width = max(1, 600 // max(len(daily), 1))
        for d in daily:
            h = int((d.get("views", 0) / max_views) * 100)
            chart_points += f'<div style="display:inline-block;width:{bar_width}px;height:{h}px;background:#6366f1;margin:0 1px;vertical-align:bottom;border-radius:2px 2px 0 0;" title="{d.get("day","")}: {d.get("views",0)}"></div>'

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f4f7;">
<div style="max-width:640px;margin:0 auto;padding:32px 16px;">
  <div style="background:#1e1b4b;border-radius:12px 12px 0 0;padding:24px 32px;">
    <h1 style="color:#fff;margin:0;font-size:22px;">👻 Ghostly Analytics Report</h1>
    <p style="color:#a5b4fc;margin:4px 0 0;font-size:13px;">{period_label} for <strong>{name}</strong> ({domain})</p>
  </div>

  <div style="background:#fff;padding:24px 32px;border:1px solid #e5e7eb;">
    <h2 style="margin:0 0 16px;font-size:16px;color:#1e1b4b;">Key Metrics</h2>
    <table style="width:100%;border-collapse:collapse;">
      <tr>
        <td style="padding:12px;background:#f9fafb;border-radius:8px;text-align:center;width:33%;">
          <div style="font-size:24px;font-weight:700;color:#6366f1;">{stats.get('total_pageviews', 0):,}</div>
          <div style="font-size:12px;color:#6b7280;">Pageviews</div>
        </td>
        <td style="width:16px;"></td>
        <td style="padding:12px;background:#f9fafb;border-radius:8px;text-align:center;width:33%;">
          <div style="font-size:24px;font-weight:700;color:#6366f1;">{visitor_stats.get('total_visitors', 0):,}</div>
          <div style="font-size:12px;color:#6b7280;">Visitors</div>
        </td>
        <td style="width:16px;"></td>
        <td style="padding:12px;background:#f9fafb;border-radius:8px;text-align:center;width:33%;">
          <div style="font-size:24px;font-weight:700;color:#6366f1;">{stats.get('total_sessions', 0):,}</div>
          <div style="font-size:12px;color:#6b7280;">Sessions</div>
        </td>
      </tr>
    </table>

    <table style="width:100%;border-collapse:collapse;margin-top:16px;">
      <tr>
        <td style="padding:12px;background:#f9fafb;border-radius:8px;text-align:center;width:33%;">
          <div style="font-size:20px;font-weight:700;color:#10b981;">{stats.get('avg_session_seconds', 0):.0f}s</div>
          <div style="font-size:12px;color:#6b7280;">Avg Session</div>
        </td>
        <td style="width:16px;"></td>
        <td style="padding:12px;background:#f9fafb;border-radius:8px;text-align:center;width:33%;">
          <div style="font-size:20px;font-weight:700;color:#f59e0b;">{stats.get('bounce_rate', 0):.1f}%</div>
          <div style="font-size:12px;color:#6b7280;">Bounce Rate</div>
        </td>
        <td style="width:16px;"></td>
        <td style="padding:12px;background:#f9fafb;border-radius:8px;text-align:center;width:33%;">
          <div style="font-size:20px;font-weight:700;color:#8b5cf6;">{visitor_stats.get('return_rate', 0):.1f}%</div>
          <div style="font-size:12px;color:#6b7280;">Return Rate</div>
        </td>
      </tr>
    </table>
  </div>

  <div style="background:#fff;padding:24px 32px;border:1px solid #e5e7eb;border-top:none;">
    <h2 style="margin:0 0 16px;font-size:16px;color:#1e1b4b;">Daily Traffic</h2>
    <div style="padding:16px 0 8px;border-bottom:1px solid #e5e7eb;">{chart_points}</div>
  </div>

  <div style="background:#fff;padding:24px 32px;border:1px solid #e5e7eb;border-top:none;">
    <h2 style="margin:0 0 16px;font-size:16px;color:#1e1b4b;">Top Pages</h2>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="text-align:left;">
          <th style="padding:8px 12px;border-bottom:2px solid #e5e7eb;color:#6b7280;">#</th>
          <th style="padding:8px 12px;border-bottom:2px solid #e5e7eb;color:#6b7280;">Page</th>
          <th style="padding:8px 12px;border-bottom:2px solid #e5e7eb;color:#6b7280;text-align:right;">Views</th>
          <th style="padding:8px 12px;border-bottom:2px solid #e5e7eb;color:#6b7280;text-align:right;">Unique</th>
        </tr>
      </thead>
      <tbody>{top_pages_rows}</tbody>
    </table>
  </div>

  <div style="background:#fff;padding:20px 32px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 12px 12px;text-align:center;">
    <p style="margin:0;color:#9ca3af;font-size:12px;">Generated by Ghostly Analytics &middot; {now_str}</p>
  </div>
</div>
</body>
</html>"""
        return html

    async def generate_report(
        self,
        site_id: int,
        days: int = 7,
    ) -> dict[str, Any]:
        site = await self.db._fetch_one("SELECT id, domain, name FROM sites WHERE id=?", (site_id,))
        if not site:
            raise ValueError(f"Site {site_id} not found")

        stats = await self.db.get_site_stats(site_id, days=days)
        visitor_stats = await self.db.get_visitor_stats(site_id, days=days)
        pages = await self.db.get_page_stats(site_id, days=days, limit=10)
        daily = await self.db.get_daily_stats(site_id, days=days)

        labels = {1: "Daily Report", 7: "Weekly Report", 30: "Monthly Report"}
        period_label = labels.get(days, f"{days}-Day Report")

        html = self._build_html_report(site, stats, visitor_stats, pages, daily, period_label)
        return {
            "site": site,
            "html": html,
            "period_days": days,
            "period_label": period_label,
            "stats": stats,
            "visitor_stats": visitor_stats,
        }

    async def send_report(
        self,
        site_id: int,
        recipients: list[str],
        days: int = 7,
        subject: str | None = None,
    ) -> dict[str, Any]:
        if not recipients:
            raise ValueError("No recipients specified")

        report = await self.generate_report(site_id, days)
        site = report["site"]

        if subject is None:
            subject = f"Ghostly Report - {site.get('name', site.get('domain', ''))} ({report['period_label']})"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._config.get("from_email", self._config.get("user", ""))
        msg["To"] = ", ".join(recipients)
        msg["X-Mailer"] = "Ghostly Analytics"

        msg.attach(MIMEText(report["html"], "html", "utf-8"))

        try:
            server = self._smtp_connect()
            server.sendmail(msg["From"], recipients, msg.as_string())
            server.quit()
            logger.info("Report sent to %d recipients for site %d", len(recipients), site_id)
            return {"ok": True, "recipients": len(recipients), "period_days": days}
        except Exception as exc:
            logger.error("Failed to send report: %s", exc)
            return {"ok": False, "error": str(exc)}

    async def get_schedules(self) -> list[dict[str, Any]]:
        rows = await self.db._fetch_all(
            "SELECT id, site_id, recipients, cron_expr, days, is_active, last_sent, created_at FROM email_schedules ORDER BY created_at DESC"
        )
        return rows

    async def create_schedule(
        self,
        site_id: int,
        recipients: list[str],
        cron_expr: str,
        days: int = 7,
    ) -> dict[str, Any]:
        if not self._validate_cron(cron_expr):
            raise ValueError(f"Invalid cron expression: {cron_expr}")

        recipients_str = json.dumps(recipients)
        cursor = await self.db.db.execute(
            """INSERT INTO email_schedules (site_id, recipients, cron_expr, days)
               VALUES (?, ?, ?, ?)""",
            (site_id, recipients_str, cron_expr, days),
        )
        await self.db.db.commit()
        schedule_id = cursor.lastrowid or 0

        self._schedules[str(schedule_id)] = {
            "site_id": site_id,
            "recipients": recipients,
            "cron_expr": cron_expr,
            "days": days,
        }

        return {"id": schedule_id, "site_id": site_id, "cron_expr": cron_expr, "days": days}

    async def delete_schedule(self, schedule_id: int) -> bool:
        result = await self.db.db.execute("DELETE FROM email_schedules WHERE id=?", (schedule_id,))
        await self.db.db.commit()
        self._schedules.pop(str(schedule_id), None)
        return result.rowcount > 0

    @staticmethod
    def _validate_cron(expr: str) -> bool:
        parts = expr.strip().split()
        if len(parts) != 5:
            return False
        ranges_spec = [
            (0, 59),
            (0, 23),
            (1, 31),
            (1, 12),
            (0, 7),
        ]
        for part, (lo, hi) in zip(parts, ranges_spec):
            if part == "*":
                continue
            if "/" in part:
                base, step = part.split("/", 1)
                if base != "*":
                    try:
                        v = int(base)
                        if not (lo <= v <= hi):
                            return False
                    except ValueError:
                        return False
                try:
                    s = int(step)
                    if s < 1:
                        return False
                except ValueError:
                    return False
                continue
            for token in part.split(","):
                if "-" in token:
                    a, b = token.split("-", 1)
                    try:
                        ai, bi = int(a), int(b)
                        if not (lo <= ai <= hi) or not (lo <= bi <= hi):
                            return False
                    except ValueError:
                        return False
                else:
                    try:
                        v = int(token)
                        if not (lo <= v <= hi):
                            return False
                    except ValueError:
                        return False
        return True

    async def should_send_now(self, schedule: dict[str, Any]) -> bool:
        now = datetime.now(timezone.utc)
        last_sent = schedule.get("last_sent")
        if not last_sent:
            return True
        try:
            last_dt = datetime.fromisoformat(last_sent)
        except (ValueError, TypeError):
            return True
        minutes_since = (now - last_dt).total_seconds() / 60
        days = schedule.get("days", 7)
        if days <= 1:
            return minutes_since >= 24 * 60
        elif days <= 7:
            return minutes_since >= 7 * 24 * 60
        else:
            return minutes_since >= 30 * 24 * 60

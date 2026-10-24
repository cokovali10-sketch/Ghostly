from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .database import Database
# --- константы вынесены FORGE refactor ---
CONST_30 = 30
CONST_60 = 60.0


logger = logging.getLogger("ghostly.alerts")


class AlertType(str, Enum):
    PAGEVIEWS_THRESHOLD = "pageviews_threshold"
    VISITOR_SPIKE = "visitor_spike"
    ERROR_RATE = "error_rate"


class AlertStatus(str, Enum):
    ACTIVE = "active"
    TRIGGERED = "triggered"
    SNOOZED = "snoozed"
    DISABLED = "disabled"


class AlertManager:
    """Manages analytics alerts and threshold monitoring."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._active_alerts: dict[int, dict[str, Any]] = {}
        self._last_check: dict[int, float] = {}
        self._check_interval: float = CONST_60

    async def create_alert(
        self,
        site_id: int,
        name: str,
        alert_type: str,
        threshold: float,
        window_minutes: int = 5,
        cooldown_minutes: int = CONST_30,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new alert for a site."""
        if alert_type not in [t.value for t in AlertType]:
            raise ValueError(f"Invalid alert type: {alert_type}")

        cursor = await self.db.db.execute(
            """INSERT INTO alerts (site_id, name, alert_type, threshold, window_minutes,
                                   cooldown_minutes, status, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                site_id,
                name,
                alert_type,
                threshold,
                window_minutes,
                cooldown_minutes,
                AlertStatus.ACTIVE.value,
                json.dumps(metadata or {}),
            ),
        )
        await self.db.db.commit()
        alert_id = cursor.lastrowid or 0

        alert = {
            "id": alert_id,
            "site_id": site_id,
            "name": name,
            "alert_type": alert_type,
            "threshold": threshold,
            "window_minutes": window_minutes,
            "cooldown_minutes": cooldown_minutes,
            "status": AlertStatus.ACTIVE.value,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._active_alerts[alert_id] = alert

        logger.info("Created alert %d for site %d: %s", alert_id, site_id, name)
        return alert

    async def get_alerts(self, site_id: int) -> list[dict[str, Any]]:
        """Get all alerts for a site."""
        rows = await self.db._fetch_all(
            """SELECT id, site_id, name, alert_type, threshold, window_minutes,
                      cooldown_minutes, status, metadata, last_triggered, created_at
               FROM alerts WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )
        return rows

    async def get_alert(self, alert_id: int) -> dict[str, Any] | None:
        """Get a specific alert by ID."""
        return await self.db._fetch_one(
            """SELECT id, site_id, name, alert_type, threshold, window_minutes,
                      cooldown_minutes, status, metadata, last_triggered, created_at
               FROM alerts WHERE id=?""",
            (alert_id,),
        )

    async def update_alert_status(self, alert_id: int, status: str) -> bool:
        """Update an alert's status."""
        if status not in [s.value for s in AlertStatus]:
            return False

        await self.db.db.execute(
            "UPDATE alerts SET status=? WHERE id=?",
            (status, alert_id),
        )
        await self.db.db.commit()

        if alert_id in self._active_alerts:
            self._active_alerts[alert_id]["status"] = status

        return True

    async def delete_alert(self, alert_id: int) -> bool:
        """Delete an alert."""
        result = await self.db.db.execute("DELETE FROM alerts WHERE id=?", (alert_id,))
        await self.db.db.commit()
        self._active_alerts.pop(alert_id, None)
        return result.rowcount > 0

    async def check_alerts(self, site_id: int, pageview_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Check all active alerts for a site against current data.

        Called on each pageview to see if any thresholds are breached.
        """
        triggered: list[dict[str, Any]] = []

        alerts = await self._fetch_active_alerts(site_id)

        for alert in alerts:
            alert_id = alert["id"]
            now = time.time()

            if now - self._last_check.get(alert_id, 0) < self._check_interval:
                continue

            self._last_check[alert_id] = now

            should_trigger = False
            current_value = 0.0

            if alert["alert_type"] == AlertType.PAGEVIEWS_THRESHOLD.value:
                current_value = await self._get_pageview_count(
                    site_id, alert["window_minutes"]
                )
                should_trigger = current_value >= alert["threshold"]

            elif alert["alert_type"] == AlertType.VISITOR_SPIKE.value:
                current_value = await self._get_visitor_count(
                    site_id, alert["window_minutes"]
                )
                should_trigger = current_value >= alert["threshold"]

            elif alert["alert_type"] == AlertType.ERROR_RATE.value:
                current_value = await self._get_error_rate(
                    site_id, alert["window_minutes"]
                )
                should_trigger = current_value >= alert["threshold"]

            if should_trigger:
                if await self._should_cooldown(alert):
                    continue

                triggered_alert = await self._trigger_alert(alert, current_value)
                triggered.append(triggered_alert)

        return triggered

    async def _fetch_active_alerts(self, site_id: int) -> list[dict[str, Any]]:
        """Fetch all active alerts for a site."""
        rows = await self._fetch_all(
            """SELECT id, site_id, name, alert_type, threshold, window_minutes,
                      cooldown_minutes, status, metadata, last_triggered
               FROM alerts WHERE site_id=? AND status IN (?, ?)""",
            (site_id, AlertStatus.ACTIVE.value, AlertStatus.TRIGGERED.value),
        )
        return rows

    async def _fetch_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Fetch all rows matching the query."""
        cursor = await self.db.db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def _get_pageview_count(self, site_id: int, window_minutes: int) -> float:
        """Get pageview count in the time window."""
        since = datetime.now(timezone.utc).isoformat()
        result = await self.db._fetch_one(
            """SELECT COUNT(*) as count FROM pageviews
               WHERE site_id=? AND created_at >= datetime(?, '-' || ? || ' minutes')""",
            (site_id, since, window_minutes),
        )
        return float(result["count"]) if result else 0.0

    async def _get_visitor_count(self, site_id: int, window_minutes: int) -> float:
        """Get unique visitor count in the time window."""
        since = datetime.now(timezone.utc).isoformat()
        result = await self.db._fetch_one(
            """SELECT COUNT(DISTINCT visitor_id) as count FROM pageviews
               WHERE site_id=? AND created_at >= datetime(?, '-' || ? || ' minutes')""",
            (site_id, since, window_minutes),
        )
        return float(result["count"]) if result else 0.0

    async def _get_error_rate(self, site_id: int, window_minutes: int) -> float:
        """Get error rate (events named 'error' or 'exception') in the time window."""
        since = datetime.now(timezone.utc).isoformat()
        errors = await self.db._fetch_one(
            """SELECT COUNT(*) as count FROM events
               WHERE site_id=? AND (name LIKE '%error%' OR name LIKE '%exception%')
               AND created_at >= datetime(?, '-' || ? || ' minutes')""",
            (site_id, since, window_minutes),
        )
        total = await self.db._fetch_one(
            """SELECT COUNT(*) as count FROM events
               WHERE site_id=? AND created_at >= datetime(?, '-' || ? || ' minutes')""",
            (site_id, since, window_minutes),
        )
        error_count = float(errors["count"]) if errors else 0.0
        total_count = float(total["count"]) if total else 1.0
        return (error_count / total_count) * 100 if total_count > 0 else 0.0

    async def _should_cooldown(self, alert: dict[str, Any]) -> bool:
        """Check if alert is in cooldown period."""
        last_triggered = alert.get("last_triggered")
        if not last_triggered:
            return False

        try:
            last_dt = datetime.fromisoformat(last_triggered)
            now = datetime.now(timezone.utc)
            cooldown = alert.get("cooldown_minutes", CONST_30)
            elapsed = (now - last_dt).total_seconds() / CONST_60
            return elapsed < cooldown
        except (ValueError, TypeError):
            return False

    async def _trigger_alert(self, alert: dict[str, Any], current_value: float) -> dict[str, Any]:
        """Trigger an alert and log it to history."""
        alert_id = alert["id"]
        now = datetime.now(timezone.utc).isoformat()

        await self.db.db.execute(
            "UPDATE alerts SET last_triggered=?, status=? WHERE id=?",
            (now, AlertStatus.TRIGGERED.value, alert_id),
        )

        await self.db.db.execute(
            """INSERT INTO alert_history (alert_id, site_id, alert_type, current_value, threshold, triggered_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (alert_id, alert["site_id"], alert["alert_type"], current_value, alert["threshold"], now),
        )
        await self.db.db.commit()

        triggered = {
            "alert_id": alert_id,
            "site_id": alert["site_id"],
            "name": alert["name"],
            "alert_type": alert["alert_type"],
            "current_value": current_value,
            "threshold": alert["threshold"],
            "triggered_at": now,
        }

        logger.warning(
            "Alert triggered: %s (site %d) - %s: %.1f >= %.1f",
            alert["name"], alert["site_id"], alert["alert_type"],
            current_value, alert["threshold"],
        )

        return triggered

    async def get_alert_history(self, site_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Get alert trigger history for a site."""
        return await self.db._fetch_all(
            """SELECT h.id, h.alert_id, a.name as alert_name, h.alert_type,
                      h.current_value, h.threshold, h.triggered_at
               FROM alert_history h
               LEFT JOIN alerts a ON h.alert_id = a.id
               WHERE h.site_id=?
               ORDER BY h.triggered_at DESC LIMIT ?""",
            (site_id, limit),
        )

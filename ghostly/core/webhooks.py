from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .database import Database

logger = logging.getLogger("ghostly.webhooks")


class WebhookManager:
    """Sends HTTP POST webhooks on analytics events with retry logic."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._max_retries = 3
        self._base_delay = 1.0

    async def fire_webhooks(
        self,
        site_id: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        webhooks = await self.db.get_active_webhooks(site_id)
        results = []

        for wh in webhooks:
            subscribed_events = self._parse_events(wh.get("events", "[]"))
            if event_type not in subscribed_events and "all" not in subscribed_events:
                continue

            result = await self._send_with_retry(wh, event_type, payload)
            results.append(result)

        return results

    async def _send_with_retry(
        self,
        webhook: dict[str, Any],
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        wh_id = webhook["id"]
        url = webhook["url"]
        secret = webhook.get("secret", "")

        body = {
            "event": event_type,
            "site_id": webhook.get("site_id"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": payload,
        }
        body_bytes = json.dumps(body, default=str).encode("utf-8")

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "Ghostly-Webhook/1.0",
            "X-Ghostly-Event": event_type,
            "X-Ghostly-Delivery": f"{wh_id}-{int(time.time())}",
        }

        if secret:
            signature = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
            headers["X-Ghostly-Signature"] = f"sha256={signature}"

        last_status = 0
        last_error: str | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        data=body_bytes,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        last_status = resp.status
                        if 200 <= resp.status < 300:
                            await self.db.update_webhook_status(wh_id, last_status)
                            self._log_delivery(wh_id, event_type, last_status, None)
                            return {
                                "webhook_id": wh_id,
                                "url": url,
                                "status": last_status,
                                "attempt": attempt,
                                "ok": True,
                            }
                        last_error = f"HTTP {resp.status}"
            except asyncio.TimeoutError:
                last_error = "timeout"
            except aiohttp.ClientError as exc:
                last_error = str(exc)
            except Exception as exc:
                last_error = str(exc)

            if attempt < self._max_retries:
                delay = self._base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Webhook %d attempt %d failed (%s), retrying in %.1fs",
                    wh_id, attempt, last_error, delay,
                )
                await asyncio.sleep(delay)

        await self.db.update_webhook_status(wh_id, last_status, last_error)
        self._log_delivery(wh_id, event_type, last_status, last_error)

        logger.error(
            "Webhook %d failed after %d attempts: %s",
            wh_id, self._max_retries, last_error,
        )

        return {
            "webhook_id": wh_id,
            "url": url,
            "status": last_status,
            "attempt": self._max_retries,
            "ok": False,
            "error": last_error,
        }

    def _parse_events(self, raw: str) -> list[str]:
        try:
            events = json.loads(raw)
            if isinstance(events, list):
                return [str(e) for e in events]
        except (json.JSONDecodeError, TypeError):
            pass
        return ["pageview"]

    def _log_delivery(
        self,
        webhook_id: int,
        event_type: str,
        status: int,
        error: str | None,
    ) -> None:
        logger.info(
            "Webhook %d delivery: event=%s status=%d error=%s",
            webhook_id, event_type, status, error,
        )

    async def get_delivery_history(
        self,
        site_id: int,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return await self.db._fetch_all(
            """SELECT id, site_id, name, url, events, last_status, last_error, created_at
               FROM webhooks WHERE site_id=? ORDER BY created_at DESC LIMIT ?""",
            (site_id, limit),
        )

    async def test_webhook(self, webhook_id: int) -> dict[str, Any]:
        webhook = await self.db.get_webhook(webhook_id)
        if not webhook:
            raise ValueError("Webhook not found")

        test_payload = {
            "test": True,
            "message": "Ghostly webhook test delivery",
            "webhook_id": webhook_id,
        }

        result = await self._send_with_retry(webhook, "test", test_payload)
        return result

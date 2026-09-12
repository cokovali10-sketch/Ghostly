from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from .database import Database

logger = logging.getLogger("ghostly.auth")


class AuthManager:
    """Manages API key authentication and rate limiting."""

    def __init__(self, db: Database, default_rate_limit: int = 1000) -> None:
        self.db = db
        self.default_rate_limit = default_rate_limit
        self._rate_limit_window: int = 3600
        self._request_counts: dict[str, list[float]] = {}

    def generate_api_key(self, prefix: str = "gh") -> str:
        """Generate a new API key with optional prefix."""
        random_part = secrets.token_hex(24)
        return f"{prefix}_{random_part}"

    def hash_api_key(self, api_key: str) -> str:
        """Hash an API key for storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    async def create_api_key(
        self,
        site_id: int,
        name: str,
        permissions: list[str] | None = None,
        rate_limit: int | None = None,
        expires_in_days: int | None = None,
    ) -> dict[str, Any]:
        """Create a new API key for a site."""
        api_key = self.generate_api_key()
        key_hash = self.hash_api_key(api_key)

        expires_at = None
        if expires_in_days:
            expires_dt = datetime.now(timezone.utc) + __import__("datetime").timedelta(days=expires_in_days)
            expires_at = expires_dt.isoformat()

        cursor = await self.db.db.execute(
            """INSERT INTO api_keys (site_id, name, key_hash, permissions, rate_limit, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                site_id,
                name,
                key_hash,
                json.dumps(permissions or ["read"]),
                rate_limit or self.default_rate_limit,
                expires_at,
            ),
        )
        await self.db.db.commit()
        key_id = cursor.lastrowid or 0

        logger.info("Created API key '%s' for site %d", name, site_id)

        return {
            "id": key_id,
            "site_id": site_id,
            "name": name,
            "api_key": api_key,
            "permissions": permissions or ["read"],
            "rate_limit": rate_limit or self.default_rate_limit,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def validate_api_key(self, api_key: str) -> dict[str, Any] | None:
        """Validate an API key and return its info."""
        key_hash = self.hash_api_key(api_key)

        key_info = await self.db._fetch_one(
            """SELECT id, site_id, name, permissions, rate_limit, expires_at, is_active
               FROM api_keys WHERE key_hash=?""",
            (key_hash,),
        )

        if not key_info:
            return None

        if not key_info["is_active"]:
            return None

        if key_info["expires_at"]:
            try:
                expires_dt = datetime.fromisoformat(key_info["expires_at"])
                if datetime.now(timezone.utc) > expires_dt:
                    await self._deactivate_key(key_info["id"])
                    return None
            except (ValueError, TypeError):
                pass

        return key_info

    async def check_rate_limit(self, api_key: str) -> dict[str, Any]:
        """Check if an API key has exceeded its rate limit.

        Returns dict with 'allowed', 'remaining', and 'reset_at'.
        """
        key_info = await self.validate_api_key(api_key)
        if not key_info:
            return {"allowed": False, "remaining": 0, "reset_at": 0, "error": "Invalid API key"}

        rate_limit = key_info["rate_limit"] or self.default_rate_limit
        key_id = str(key_info["id"])

        now = time.time()
        window_start = now - self._rate_limit_window

        if key_id not in self._request_counts:
            self._request_counts[key_id] = []

        self._request_counts[key_id] = [
            t for t in self._request_counts[key_id] if t > window_start
        ]

        current_count = len(self._request_counts[key_id])

        if current_count >= rate_limit:
            reset_at = int(self._request_counts[key_id][0] + self._rate_limit_window) if self._request_counts[key_id] else int(now + self._rate_limit_window)
            return {
                "allowed": False,
                "remaining": 0,
                "reset_at": reset_at,
                "error": "Rate limit exceeded",
            }

        self._request_counts[key_id].append(now)

        return {
            "allowed": True,
            "remaining": rate_limit - current_count - 1,
            "reset_at": int(window_start + self._rate_limit_window),
        }

    async def get_api_keys(self, site_id: int) -> list[dict[str, Any]]:
        """Get all API keys for a site."""
        return await self.db._fetch_all(
            """SELECT id, site_id, name, permissions, rate_limit, expires_at,
                      is_active, last_used, created_at
               FROM api_keys WHERE site_id=? ORDER BY created_at DESC""",
            (site_id,),
        )

    async def get_api_key(self, key_id: int) -> dict[str, Any] | None:
        """Get a specific API key by ID."""
        return await self.db._fetch_one(
            """SELECT id, site_id, name, permissions, rate_limit, expires_at,
                      is_active, last_used, created_at
               FROM api_keys WHERE id=?""",
            (key_id,),
        )

    async def revoke_api_key(self, key_id: int) -> bool:
        """Revoke (deactivate) an API key."""
        return await self._deactivate_key(key_id)

    async def _deactivate_key(self, key_id: int) -> bool:
        """Deactivate an API key."""
        result = await self.db.db.execute(
            "UPDATE api_keys SET is_active=0 WHERE id=?",
            (key_id,),
        )
        await self.db.db.commit()
        key_id_str = str(key_id)
        self._request_counts.pop(key_id_str, None)
        return result.rowcount > 0

    async def update_last_used(self, api_key: str) -> None:
        """Update the last_used timestamp for an API key."""
        key_hash = self.hash_api_key(api_key)
        await self.db.db.execute(
            "UPDATE api_keys SET last_used=datetime('now') WHERE key_hash=?",
            (key_hash,),
        )
        await self.db.db.commit()

    async def check_permission(self, api_key: str, required_permission: str) -> bool:
        """Check if an API key has the required permission."""
        key_info = await self.validate_api_key(api_key)
        if not key_info:
            return False

        permissions = json.loads(key_info["permissions"]) if isinstance(key_info["permissions"], str) else key_info["permissions"]
        return required_permission in permissions or "admin" in permissions

    def get_rate_limit_stats(self) -> dict[str, Any]:
        """Get rate limiting statistics."""
        active_keys = len(self._request_counts)
        total_requests = sum(len(counts) for counts in self._request_counts.values())
        return {
            "active_keys": active_keys,
            "total_requests_tracked": total_requests,
            "window_seconds": self._rate_limit_window,
            "default_rate_limit": self.default_rate_limit,
        }

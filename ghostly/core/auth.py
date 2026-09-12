from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from .database import Database

logger = logging.getLogger("ghostly.auth")

ROLES_HIERARCHY = {"admin": 3, "editor": 2, "viewer": 1}
DEFAULT_ACCESS_TOKEN_EXPIRY = 900
DEFAULT_REFRESH_TOKEN_EXPIRY = 604800
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 30


class AuthError(Exception):
    def __init__(self, message: str, status: int = 401) -> None:
        self.message = message
        self.status = status
        super().__init__(message)


class AuthManager:
    """Full JWT authentication with RBAC, sessions, rate limiting, and account lockout."""

    def __init__(
        self,
        db: Database,
        secret_key: str | None = None,
        access_token_expiry: int = DEFAULT_ACCESS_TOKEN_EXPIRY,
        refresh_token_expiry: int = DEFAULT_REFRESH_TOKEN_EXPIRY,
    ) -> None:
        self.db = db
        self.secret_key = secret_key or secrets.token_hex(32)
        self.access_token_expiry = access_token_expiry
        self.refresh_token_expiry = refresh_token_expiry
        self._rate_limit_window: int = 3600
        self._request_counts: dict[str, list[float]] = {}

    def hash_password(self, password: str) -> str:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except Exception:
            return False

    def generate_token(self, user_id: int, token_type: str = "access", role: str = "viewer") -> str:
        now = datetime.now(timezone.utc)
        if token_type == "access":
            expiry = now + timedelta(seconds=self.access_token_expiry)
        else:
            expiry = now + timedelta(seconds=self.refresh_token_expiry)

        payload = {
            "sub": user_id,
            "type": token_type,
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int(expiry.timestamp()),
            "jti": secrets.token_hex(16),
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    def decode_token(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            raise AuthError("Token has expired", 401)
        except jwt.InvalidTokenError:
            raise AuthError("Invalid token", 401)

    def _check_password_strength(self, password: str) -> str | None:
        if len(password) < 8:
            return "Password must be at least 8 characters"
        if not any(c.isupper() for c in password):
            return "Password must contain an uppercase letter"
        if not any(c.islower() for c in password):
            return "Password must contain a lowercase letter"
        if not any(c.isdigit() for c in password):
            return "Password must contain a digit"
        return None

    async def register(
        self,
        email: str,
        password: str,
        role: str = "viewer",
        ip: str = "",
    ) -> dict[str, Any]:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise AuthError("Invalid email address", 400)

        strength_error = self._check_password_strength(password)
        if strength_error:
            raise AuthError(strength_error, 400)

        if role not in ROLES_HIERARCHY:
            raise AuthError(f"Invalid role. Must be one of: {', '.join(ROLES_HIERARCHY.keys())}", 400)

        existing = await self.db.get_user_by_email(email)
        if existing:
            raise AuthError("Email already registered", 409)

        password_hash = self.hash_password(password)
        user_id = await self.db.create_user(email, password_hash, role)

        await self.db.log_audit(user_id, "register", "user", {"email": email}, ip)

        access_token = self.generate_token(user_id, "access", role)
        refresh_token = self.generate_token(user_id, "refresh", role)

        session_id = secrets.token_hex(16)
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=self.refresh_token_expiry)).isoformat()
        await self.db.create_user_session(session_id, user_id, refresh_token, expires_at)

        logger.info("User registered: %s (id=%d, role=%s)", email, user_id, role)

        return {
            "user": {"id": user_id, "email": email, "role": role},
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.access_token_expiry,
        }

    async def login(
        self,
        email: str,
        password: str,
        ip: str = "",
    ) -> dict[str, Any]:
        email = email.strip().lower()
        user = await self.db.get_user_by_email(email)

        if not user:
            await self.db.log_audit(None, "login_failed", "user", {"email": email, "reason": "not_found"}, ip)
            raise AuthError("Invalid email or password", 401)

        if not user["is_active"]:
            await self.db.log_audit(user["id"], "login_blocked", "user", {"reason": "account_disabled"}, ip)
            raise AuthError("Account is disabled", 403)

        if user["locked_until"]:
            try:
                locked_until = datetime.fromisoformat(user["locked_until"])
                if datetime.now(timezone.utc) < locked_until:
                    remaining = (locked_until - datetime.now(timezone.utc)).seconds // 60 + 1
                    raise AuthError(f"Account locked. Try again in {remaining} minutes", 423)
                else:
                    await self.db.update_user(user["id"], failed_attempts=0, locked_until=None)
            except (ValueError, TypeError):
                pass

        if not self.verify_password(password, user["password_hash"]):
            failed_attempts = user["failed_attempts"] + 1
            update: dict[str, Any] = {"failed_attempts": failed_attempts}
            if failed_attempts >= MAX_FAILED_ATTEMPTS:
                lockout_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                update["locked_until"] = lockout_until.isoformat()
                logger.warning("Account locked due to failed attempts: %s", email)
            await self.db.update_user(user["id"], **update)
            await self.db.log_audit(user["id"], "login_failed", "user", {"reason": "bad_password", "attempts": failed_attempts}, ip)
            raise AuthError("Invalid email or password", 401)

        await self.db.update_user(user["id"], failed_attempts=0, locked_until=None, last_login=datetime.now(timezone.utc).isoformat())

        access_token = self.generate_token(user["id"], "access", user["role"])
        refresh_token = self.generate_token(user["id"], "refresh", user["role"])

        session_id = secrets.token_hex(16)
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(seconds=self.refresh_token_expiry)).isoformat()
        await self.db.create_user_session(session_id, user["id"], refresh_token, expires_at)

        await self.db.log_audit(user["id"], "login", "user", {"email": email}, ip)

        logger.info("User logged in: %s (id=%d)", email, user["id"])

        return {
            "user": {"id": user["id"], "email": user["email"], "role": user["role"]},
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.access_token_expiry,
        }

    async def refresh_token(self, refresh_token: str, ip: str = "") -> dict[str, Any]:
        payload = self.decode_token(refresh_token)

        if payload.get("type") != "refresh":
            raise AuthError("Invalid token type", 401)

        user_id = payload["sub"]
        user = await self.db.get_user_full(user_id)

        if not user:
            raise AuthError("User not found", 401)

        if not user["is_active"]:
            raise AuthError("Account is disabled", 403)

        access_token = self.generate_token(user_id, "access", user["role"])
        new_refresh_token = self.generate_token(user_id, "refresh", user["role"])

        await self.db.log_audit(user_id, "token_refresh", "auth", {}, ip)

        return {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "expires_in": self.access_token_expiry,
        }

    async def logout(self, user_id: int, session_id: str | None = None, ip: str = "") -> None:
        if session_id:
            await self.db.delete_user_session(session_id)
        else:
            await self.db.delete_user_sessions(user_id)

        await self.db.log_audit(user_id, "logout", "auth", {"session_id": session_id}, ip)

    async def authenticate_request(self, request: Any) -> dict[str, Any]:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise AuthError("Missing or invalid Authorization header", 401)

        token = auth_header[7:]
        payload = self.decode_token(token)

        if payload.get("type") != "access":
            raise AuthError("Invalid token type", 401)

        user_id = payload["sub"]
        user = await self.db.get_user_by_id(user_id)

        if not user:
            raise AuthError("User not found", 401)

        if not user["is_active"]:
            raise AuthError("Account is disabled", 403)

        return {
            "user_id": user["id"],
            "email": user["email"],
            "role": user["role"],
        }

    def require_role(self, user_role: str, required_role: str) -> bool:
        user_level = ROLES_HIERARCHY.get(user_role, 0)
        required_level = ROLES_HIERARCHY.get(required_role, 0)
        return user_level >= required_level

    def require_admin(self, user_role: str) -> bool:
        return self.require_role(user_role, "admin")

    def require_editor(self, user_role: str) -> bool:
        return self.require_role(user_role, "editor")

    async def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
        ip: str = "",
    ) -> bool:
        user = await self.db.get_user_full(user_id)
        if not user:
            raise AuthError("User not found", 404)

        if not self.verify_password(current_password, user["password_hash"]):
            raise AuthError("Current password is incorrect", 401)

        strength_error = self._check_password_strength(new_password)
        if strength_error:
            raise AuthError(strength_error, 400)

        new_hash = self.hash_password(new_password)
        await self.db.update_user(user_id, password_hash=new_hash)

        await self.db.delete_user_sessions(user_id)
        await self.db.log_audit(user_id, "password_change", "user", {}, ip)

        logger.info("Password changed for user %d", user_id)
        return True

    async def request_password_reset(self, email: str, ip: str = "") -> str | None:
        email = email.strip().lower()
        user = await self.db.get_user_by_email(email)
        if not user:
            return None

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(hours=1)).isoformat()

        await self.db.create_password_reset(user["id"], token_hash, expires_at)
        await self.db.log_audit(user["id"], "password_reset_request", "user", {}, ip)

        logger.info("Password reset requested for %s", email)
        return token

    async def reset_password(
        self,
        token: str,
        new_password: str,
        ip: str = "",
    ) -> bool:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        reset = await self.db.get_password_reset(token_hash)

        if not reset:
            raise AuthError("Invalid or expired reset token", 400)

        try:
            expires_at = datetime.fromisoformat(reset["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                raise AuthError("Reset token has expired", 400)
        except (ValueError, TypeError):
            raise AuthError("Invalid reset token", 400)

        strength_error = self._check_password_strength(new_password)
        if strength_error:
            raise AuthError(strength_error, 400)

        new_hash = self.hash_password(new_password)
        await self.db.update_user(reset["user_id"], password_hash=new_hash)
        await self.db.use_password_reset(reset["id"])
        await self.db.delete_user_sessions(reset["user_id"])
        await self.db.log_audit(reset["user_id"], "password_reset", "user", {}, ip)

        logger.info("Password reset completed for user %d", reset["user_id"])
        return True

    async def create_api_key(
        self,
        user_id: int,
        name: str,
        permissions: list[str] | None = None,
        rate_limit: int = 1000,
        expires_in_days: int | None = None,
        ip: str = "",
    ) -> dict[str, Any]:
        api_key = f"gh_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        expires_at = None
        if expires_in_days:
            expires_dt = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
            expires_at = expires_dt.isoformat()

        key_id = await self.db.create_user_api_key(
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            permissions=json.dumps(permissions or ["read"]),
            rate_limit=rate_limit,
            expires_at=expires_at,
        )

        await self.db.log_audit(user_id, "api_key_create", "api_key", {"name": name, "id": key_id}, ip)

        logger.info("Created API key '%s' for user %d", name, user_id)

        return {
            "id": key_id,
            "user_id": user_id,
            "name": name,
            "api_key": api_key,
            "permissions": permissions or ["read"],
            "rate_limit": rate_limit,
            "expires_at": expires_at,
        }

    async def validate_api_key(self, api_key: str) -> dict[str, Any] | None:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_info = await self.db.get_user_api_key_by_hash(key_hash)

        if not key_info:
            return None

        if not key_info["is_active"]:
            return None

        if key_info["expires_at"]:
            try:
                expires_dt = datetime.fromisoformat(key_info["expires_at"])
                if datetime.now(timezone.utc) > expires_dt:
                    await self.db.delete_user_api_key(key_info["id"])
                    return None
            except (ValueError, TypeError):
                pass

        return key_info

    async def check_api_key_rate_limit(self, api_key: str) -> dict[str, Any]:
        key_info = await self.validate_api_key(api_key)
        if not key_info:
            return {"allowed": False, "remaining": 0, "reset_at": 0, "error": "Invalid API key"}

        rate_limit = key_info["rate_limit"] or 1000
        key_id = str(key_info["id"])

        now = time.time()
        window_start = now - self._rate_limit_window

        if key_id not in self._request_counts:
            self._request_counts[key_id] = []

        self._request_counts[key_id] = [t for t in self._request_counts[key_id] if t > window_start]

        current_count = len(self._request_counts[key_id])

        if current_count >= rate_limit:
            reset_at = int(self._request_counts[key_id][0] + self._rate_limit_window) if self._request_counts[key_id] else int(now + self._rate_limit_window)
            return {"allowed": False, "remaining": 0, "reset_at": reset_at, "error": "Rate limit exceeded"}

        self._request_counts[key_id].append(now)
        await self.db.update_user_api_key_last_used(key_hash)

        return {
            "allowed": True,
            "remaining": rate_limit - current_count - 1,
            "reset_at": int(window_start + self._rate_limit_window),
        }

    async def get_api_keys(self, user_id: int) -> list[dict[str, Any]]:
        return await self.db.get_user_api_keys(user_id)

    async def revoke_api_key(self, key_id: int, user_id: int | None = None, ip: str = "") -> bool:
        key = await self.db.get_user_api_key(key_id)
        if not key:
            return False
        if user_id and key["user_id"] != user_id:
            return False
        result = await self.db.delete_user_api_key(key_id)
        if result:
            await self.db.log_audit(user_id, "api_key_revoke", "api_key", {"key_id": key_id}, ip)
        return result

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        return await self.db.get_user_by_id(user_id)

    async def list_users(self) -> list[dict[str, Any]]:
        return await self.db.get_all_users()

    async def update_user_role(self, admin_id: int, target_user_id: int, new_role: str, ip: str = "") -> bool:
        if new_role not in ROLES_HIERARCHY:
            raise AuthError(f"Invalid role: {new_role}", 400)

        target = await self.db.get_user_by_id(target_user_id)
        if not target:
            raise AuthError("User not found", 404)

        await self.db.update_user(target_user_id, role=new_role)
        await self.db.log_audit(admin_id, "role_change", "user", {"target_user_id": target_user_id, "new_role": new_role}, ip)

        logger.info("User %d role changed to %s by admin %d", target_user_id, new_role, admin_id)
        return True

    async def deactivate_user(self, admin_id: int, target_user_id: int, ip: str = "") -> bool:
        target = await self.db.get_user_by_id(target_user_id)
        if not target:
            raise AuthError("User not found", 404)

        if target["role"] == "admin":
            admin_count = await self.db._fetch_one("SELECT COUNT(*) as c FROM users WHERE role='admin' AND is_active=1")
            if admin_count and admin_count["c"] <= 1:
                raise AuthError("Cannot deactivate the last admin", 400)

        await self.db.update_user(target_user_id, is_active=0)
        await self.db.delete_user_sessions(target_user_id)
        await self.db.log_audit(admin_id, "user_deactivate", "user", {"target_user_id": target_user_id}, ip)

        logger.info("User %d deactivated by admin %d", target_user_id, admin_id)
        return True

    async def activate_user(self, admin_id: int, target_user_id: int, ip: str = "") -> bool:
        target = await self.db.get_user_by_id(target_user_id)
        if not target:
            raise AuthError("User not found", 404)

        await self.db.update_user(target_user_id, is_active=1)
        await self.db.log_audit(admin_id, "user_activate", "user", {"target_user_id": target_user_id}, ip)

        logger.info("User %d activated by admin %d", target_user_id, admin_id)
        return True

    async def delete_user_account(self, admin_id: int, target_user_id: int, ip: str = "") -> bool:
        target = await self.db.get_user_by_id(target_user_id)
        if not target:
            raise AuthError("User not found", 404)

        if target["role"] == "admin":
            admin_count = await self.db._fetch_one("SELECT COUNT(*) as c FROM users WHERE role='admin' AND is_active=1")
            if admin_count and admin_count["c"] <= 1:
                raise AuthError("Cannot delete the last admin", 400)

        await self.db.delete_user(target_user_id)
        await self.db.log_audit(admin_id, "user_delete", "user", {"target_user_id": target_user_id, "email": target["email"]}, ip)

        logger.info("User %d deleted by admin %d", target_user_id, admin_id)
        return True

    async def get_audit_log(
        self,
        user_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self.db.get_audit_log(user_id=user_id, limit=limit, offset=offset)

    async def check_ip_rate_limit(self, ip: str, limit: int = 100) -> bool:
        now = time.time()
        window_start = now - self._rate_limit_window

        key = f"ip:{ip}"
        if key not in self._request_counts:
            self._request_counts[key] = []

        self._request_counts[key] = [t for t in self._request_counts[key] if t > window_start]

        if len(self._request_counts[key]) >= limit:
            return False

        self._request_counts[key].append(now)
        return True

    async def get_health_status(self) -> dict[str, Any]:
        try:
            await self.db.db.execute("SELECT 1")
            db_ok = True
        except Exception:
            db_ok = False

        stats = await self.db.get_system_stats()

        return {
            "status": "healthy" if db_ok else "degraded",
            "database": "connected" if db_ok else "disconnected",
            "stats": stats,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

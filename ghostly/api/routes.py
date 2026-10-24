from __future__ import annotations

import functools
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from aiohttp import web

from ghostly.core.ab_test import ABTestManager
from ghostly.core.alerts import AlertManager
from ghostly.core.auth import AuthManager, AuthError
from ghostly.core.database import Database
from ghostly.core.export import ExportManager
from ghostly.core.funnels import FunnelManager
from ghostly.core.geomap import GeoMapCollector
from ghostly.core.goals import GoalManager
from ghostly.core.retention import RetentionAnalyzer
# --- константы вынесены FORGE refactor ---
CONST_5 = 5
CONST_7 = 7
CONST_20 = 20
CONST_30 = 30
CONST_50 = 50
CONST_201 = 201
CONST_365 = 365
CONST_400 = 400
CONST_403 = 403
CONST_404 = 404
CONST_503 = 503
CONST_1000 = 1000


logger = logging.getLogger("ghostly.api")

routes = web.RouteTableDef()


def _json_response(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=json.dumps)


def _error(message: str, status: int = CONST_400) -> web.Response:
    return _json_response({"error": message}, status=status)


def _get_db(request: web.Request) -> Database:
    db = request.app.get("db")
    if db is None:
        raise web.HTTPInternalServerError(reason="Database not initialised")
    return db


def _get_auth(request: web.Request) -> AuthManager:
    auth = request.app.get("auth")
    if auth is None:
        raise web.HTTPInternalServerError(reason="Auth manager not initialised")
    return auth


def _get_user(request: web.Request) -> dict[str, Any]:
    user = request.get("user")
    if user is None:
        raise web.HTTPUnauthorized(reason="Authentication required")
    return user


def _parse_days(request: web.Request, default: int = CONST_30) -> int:
    raw = request.query.get("days")
    if raw is None:
        return default
    try:
        days = int(raw)
        return max(1, min(days, CONST_365))
    except ValueError:
        return default


def _parse_limit(request: web.Request, default: int = CONST_50) -> int:
    raw = request.query.get("limit")
    if raw is None:
        return default
    try:
        limit = int(raw)
        return max(1, min(limit, 500))
    except ValueError:
        return default


def _extract_domain(referrer: str) -> str:
    try:
        parsed = urlparse(referrer)
        return parsed.netloc or parsed.hostname or referrer
    except Exception:
        return referrer


def _hash_ip(ip: str, salt: str) -> str:
    return hashlib.sha256(f"{ip}{salt}".encode()).hexdigest()[:16]


def _get_client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.remote or "0.0.0.0"


def require_auth(handler):
    @functools.wraps(handler)
    async def wrapper(request: web.Request) -> web.Response:
        auth = _get_auth(request)
        try:
            user = await auth.authenticate_request(request)
            request["user"] = user
        except AuthError as exc:
            return _error(exc.message, exc.status)
        return await handler(request)
    return wrapper


def require_role(role: str):
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(request: web.Request) -> web.Response:
            auth = _get_auth(request)
            try:
                user = await auth.authenticate_request(request)
                request["user"] = user
            except AuthError as exc:
                return _error(exc.message, exc.status)

            if not auth.require_role(user["role"], role):
                return _error("Insufficient permissions", CONST_403)

            return await handler(request)
        return wrapper
    return decorator


# ── Global Health ────────────────────────────────────────────────────────


@routes.get("/health")
async def global_health(request: web.Request) -> web.Response:
    db = _get_db(request)
    try:
        await db.db.execute("SELECT 1")
        return _json_response({
            "status": "ok",
            "service": "ghostly",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return _json_response({"status": "error", "message": str(exc)}, status=CONST_503)


# ── Auth Endpoints ───────────────────────────────────────────────────────


@routes.post("/api/auth/register")
async def auth_register(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    role = body.get("role", "viewer")
    ip = _get_client_ip(request)

    if not email or not password:
        return _error("Missing 'email' or 'password'")

    try:
        result = await auth.register(email, password, role, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response(result, status=CONST_201)


@routes.post("/api/auth/login")
async def auth_login(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    ip = _get_client_ip(request)

    if not email or not password:
        return _error("Missing 'email' or 'password'")

    try:
        result = await auth.login(email, password, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response(result)


@routes.post("/api/auth/refresh")
@require_auth
async def auth_refresh(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    refresh_token = body.get("refresh_token") or ""
    ip = _get_client_ip(request)

    if not refresh_token:
        return _error("Missing 'refresh_token'")

    try:
        result = await auth.refresh_token(refresh_token, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response(result)


@routes.post("/api/auth/logout")
@require_auth
async def auth_logout(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    user = _get_user(request)
    ip = _get_client_ip(request)

    session_id = None
    try:
        body = await request.json()
        session_id = body.get("session_id")
    except Exception:
        pass

    await auth.logout(user["user_id"], session_id, ip)
    return _json_response({"ok": True})


@routes.get("/api/auth/me")
@require_auth
async def auth_me(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    user = _get_user(request)

    user_data = await auth.get_user(user["user_id"])
    if not user_data:
        return _error("User not found", CONST_404)

    return _json_response({"user": user_data})


@routes.put("/api/auth/password")
@require_auth
async def auth_change_password(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    user = _get_user(request)
    ip = _get_client_ip(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if not current_password or not new_password:
        return _error("Missing 'current_password' or 'new_password'")

    try:
        await auth.change_password(user["user_id"], current_password, new_password, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response({"ok": True})


@routes.post("/api/auth/password/reset/request")
async def auth_password_reset_request(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    email = (body.get("email") or "").strip()
    ip = _get_client_ip(request)

    if not email:
        return _error("Missing 'email'")

    token = await auth.request_password_reset(email, ip)

    return _json_response({
        "ok": True,
        "message": "If the email exists, a reset link has been sent",
    })


@routes.post("/api/auth/password/reset")
async def auth_password_reset(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    token = body.get("token") or ""
    new_password = body.get("new_password") or ""
    ip = _get_client_ip(request)

    if not token or not new_password:
        return _error("Missing 'token' or 'new_password'")

    try:
        await auth.reset_password(token, new_password, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response({"ok": True})


# ── User API Keys ────────────────────────────────────────────────────────


@routes.get("/api/auth/api-keys")
@require_auth
async def list_user_api_keys(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    user = _get_user(request)
    keys = await auth.get_api_keys(user["user_id"])
    return _json_response({"api_keys": keys})


@routes.post("/api/auth/api-keys")
@require_auth
async def create_user_api_key(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    user = _get_user(request)
    ip = _get_client_ip(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "unnamed").strip()
    permissions = body.get("permissions", ["read"])
    rate_limit = body.get("rate_limit", CONST_1000)
    expires_in_days = body.get("expires_in_days")

    try:
        key_data = await auth.create_api_key(
            user_id=user["user_id"],
            name=name,
            permissions=permissions,
            rate_limit=rate_limit,
            expires_in_days=expires_in_days,
            ip=ip,
        )
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response(key_data, status=CONST_201)


@routes.delete("/api/auth/api-keys/{id}")
@require_auth
async def delete_user_api_key(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    user = _get_user(request)
    ip = _get_client_ip(request)
    key_id = int(request.match_info["id"])

    deleted = await auth.revoke_api_key(key_id, user["user_id"], ip)
    if not deleted:
        return _error("API key not found", status=CONST_404)
    return _json_response({"ok": True})


# ── Admin Endpoints ──────────────────────────────────────────────────────


@routes.get("/api/admin/users")
@require_role("admin")
async def admin_list_users(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    users = await auth.list_users()
    return _json_response({"users": users})


@routes.delete("/api/admin/users/{id}")
@require_role("admin")
async def admin_delete_user(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    admin_user = _get_user(request)
    target_user_id = int(request.match_info["id"])
    ip = _get_client_ip(request)

    if admin_user["user_id"] == target_user_id:
        return _error("Cannot delete your own account", CONST_400)

    try:
        await auth.delete_user_account(admin_user["user_id"], target_user_id, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response({"ok": True})


@routes.put("/api/admin/users/{id}/role")
@require_role("admin")
async def admin_update_user_role(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    admin_user = _get_user(request)
    target_user_id = int(request.match_info["id"])
    ip = _get_client_ip(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    new_role = (body.get("role") or "").strip()
    if not new_role:
        return _error("Missing 'role'")

    try:
        await auth.update_user_role(admin_user["user_id"], target_user_id, new_role, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response({"ok": True})


@routes.put("/api/admin/users/{id}/activate")
@require_role("admin")
async def admin_activate_user(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    admin_user = _get_user(request)
    target_user_id = int(request.match_info["id"])
    ip = _get_client_ip(request)

    try:
        await auth.activate_user(admin_user["user_id"], target_user_id, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response({"ok": True})


@routes.put("/api/admin/users/{id}/deactivate")
@require_role("admin")
async def admin_deactivate_user(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    admin_user = _get_user(request)
    target_user_id = int(request.match_info["id"])
    ip = _get_client_ip(request)

    if admin_user["user_id"] == target_user_id:
        return _error("Cannot deactivate your own account", CONST_400)

    try:
        await auth.deactivate_user(admin_user["user_id"], target_user_id, ip)
    except AuthError as exc:
        return _error(exc.message, exc.status)

    return _json_response({"ok": True})


@routes.get("/api/admin/audit")
@require_role("admin")
async def admin_audit_log(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    limit = _parse_limit(request, default=100)
    offset_raw = request.query.get("offset", "0")
    try:
        offset = max(0, int(offset_raw))
    except ValueError:
        offset = 0

    log = await auth.get_audit_log(limit=limit, offset=offset)
    return _json_response({"audit_log": log, "limit": limit, "offset": offset})


@routes.get("/api/admin/health")
@require_role("admin")
async def admin_health(request: web.Request) -> web.Response:
    auth = _get_auth(request)
    status = await auth.get_health_status()
    return _json_response(status)


@routes.get("/api/admin/stats")
@require_role("admin")
async def admin_stats(request: web.Request) -> web.Response:
    db = _get_db(request)
    stats = await db.get_system_stats()
    return _json_response(stats)


# ── Health (site-level, kept for backward compat) ────────────────────────


@routes.get("/api/health")
async def health(request: web.Request) -> web.Response:
    db = _get_db(request)
    try:
        await db.db.execute("SELECT 1")
        return _json_response({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return _json_response({"status": "error", "message": str(exc)}, status=CONST_503)


# ── Tracking ────────────────────────────────────────────────────────────


@routes.post("/api/track")
async def track(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    domain = (body.get("domain") or "").strip().lower()
    if not domain:
        return _error("Missing 'domain' field")

    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE domain=? AND is_active=1", (domain,))
    if not site:
        return _error("Unknown site", status=CONST_404)

    site_id = site["id"]
    event_type = body.get("type", "pageview")

    visitor_id = body.get("visitor_id", "").strip()
    session_id = body.get("session_id", "").strip()
    url = body.get("url", "").strip()
    path = body.get("path", "/")
    title = body.get("title", "")
    referrer = body.get("referrer", "")
    language = body.get("language", "")
    screen_size = body.get("screen_size", "")
    browser = body.get("browser", "")
    os = body.get("os", "")
    device_type = body.get("device_type", "desktop")
    country = body.get("country", "")

    if not visitor_id:
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not ip:
            ip = request.remote or "0.0.0.0"
        visitor_id = _hash_ip(ip, str(site_id))
    if not session_id:
        session_id = visitor_id

    ip_address = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (request.remote or "")

    if event_type == "event":
        event_name = body.get("name", "").strip()
        if not event_name:
            return _error("Missing 'name' for event type")
        meta = body.get("meta", {})
        event_id = await db.insert_event(
            site_id=site_id,
            visitor_id=visitor_id,
            session_id=session_id,
            name=event_name,
            url=url,
            meta=meta if isinstance(meta, dict) else {},
        )
        return _json_response({"ok": True, "id": event_id}, status=CONST_201)

    pv_id = await db.insert_pageview(
        site_id=site_id,
        visitor_id=visitor_id,
        session_id=session_id,
        url=url,
        path=path,
        title=title,
        referrer=referrer,
        language=language,
        screen_size=screen_size,
        ip_address=ip_address,
        country=country,
        browser=browser,
        os=os,
        device_type=device_type,
    )

    if referrer:
        domain_ref = _extract_domain(referrer)
        try:
            await db.db.execute(
                """INSERT INTO referrers (site_id, url, domain, visits, last_seen)
                   VALUES (?, ?, ?, 1, datetime('now'))
                   ON CONFLICT(site_id, url) DO UPDATE SET
                       visits = visits + 1, last_seen = datetime('now')""",
                (site_id, referrer, domain_ref),
            )
        except Exception as exc:
            logger.warning("Failed to upsert referrer: %s", exc)

    for table, column in [("devices", "device_type"), ("browsers", "browser"), ("countries", "country")]:
        value = locals()[column]
        if value:
            try:
                await db.db.execute(
                    f"""INSERT INTO {table} (site_id, {column}, visits, last_seen)
                        VALUES (?, ?, 1, datetime('now'))
                        ON CONFLICT(site_id, {column}) DO UPDATE SET
                            visits = visits + 1, last_seen = datetime('now')""",
                    (site_id, value),
                )
            except Exception as exc:
                logger.warning("Failed to upsert %s: %s", table, exc)

    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        existing = await db._fetch_one(
            "SELECT id, page_count FROM analytics_sessions WHERE id=?",
            (session_id,),
        )
        if existing:
            await db.db.execute(
                "UPDATE analytics_sessions SET page_count = page_count + 1 WHERE id=?",
                (session_id,),
            )
        else:
            await db.db.execute(
                """INSERT INTO analytics_sessions (id, site_id, visitor_id, started_at, page_count, referrer, browser, os, device_type, country)
                   VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                (session_id, site_id, visitor_id, now_iso, referrer, browser, os, device_type, country),
            )

        existing_visitor = await db._fetch_one(
            "SELECT id FROM visitors WHERE id=? AND site_id=?",
            (visitor_id, site_id),
        )
        if existing_visitor:
            await db.db.execute(
                "UPDATE visitors SET last_seen=datetime('now'), visits=visits+1 WHERE id=? AND site_id=?",
                (visitor_id, site_id),
            )
        else:
            await db.db.execute(
                """INSERT INTO visitors (id, site_id, ip_address, user_agent, country, first_seen, last_seen, visits)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
                (visitor_id, site_id, ip_address, request.headers.get("User-Agent", ""), country, now_iso, now_iso),
            )

        await db.db.commit()
    except Exception as exc:
        logger.warning("Failed to update session/visitor: %s", exc)

    return _json_response({"ok": True, "id": pv_id}, status=CONST_201)


# ── Sites CRUD ──────────────────────────────────────────────────────────


@routes.get("/api/sites")
@require_auth
async def list_sites(request: web.Request) -> web.Response:
    db = _get_db(request)
    sites = await db._fetch_all(
        "SELECT id, domain, name, created_at, is_active FROM sites ORDER BY created_at DESC"
    )
    return _json_response({"sites": sites})


@routes.post("/api/sites")
@require_role("editor")
async def create_site(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    domain = (body.get("domain") or "").strip().lower()
    name = (body.get("name") or domain).strip()

    if not domain:
        return _error("Missing 'domain' field")

    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    clean_domain = parsed.netloc or parsed.hostname or domain
    clean_domain = clean_domain.lower().rstrip(".")

    db = _get_db(request)
    existing = await db._fetch_one("SELECT id FROM sites WHERE domain=?", (clean_domain,))
    if existing:
        return _error("Site with this domain already exists", status=409)

    cursor = await db.db.execute(
        "INSERT INTO sites (domain, name) VALUES (?, ?)",
        (clean_domain, name or clean_domain),
    )
    await db.db.commit()
    site_id = cursor.lastrowid

    user = _get_user(request)
    auth = _get_auth(request)
    await auth.db.log_audit(user["user_id"], "site_create", "site", {"site_id": site_id, "domain": clean_domain}, _get_client_ip(request))

    return _json_response(
        {"id": site_id, "domain": clean_domain, "name": name or clean_domain},
        status=CONST_201,
    )


@routes.delete("/api/sites/{id}")
@require_role("editor")
async def delete_site(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)
    await db.db.execute("DELETE FROM sites WHERE id=?", (site_id,))
    await db.db.commit()

    user = _get_user(request)
    auth = _get_auth(request)
    await auth.db.log_audit(user["user_id"], "site_delete", "site", {"site_id": site_id}, _get_client_ip(request))

    return _json_response({"ok": True})


# ── Site Stats ──────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/stats")
@require_auth
async def site_stats(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id, domain, name FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    stats = await db.get_site_stats(site_id, days=days)
    visitor_stats = await db.get_visitor_stats(site_id, days=days)

    return _json_response({
        "site": dict(site),
        "period_days": days,
        **stats,
        **visitor_stats,
    })


@routes.get("/api/sites/{id}/pages")
@require_auth
async def site_pages(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    pages = await db.get_page_stats(site_id, days=days, limit=limit)
    return _json_response({"pages": pages, "period_days": days})


@routes.get("/api/sites/{id}/referrers")
@require_auth
async def site_referrers(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=CONST_30)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    referrers = await db.get_referrer_stats(site_id, days=days, limit=limit)
    return _json_response({"referrers": referrers, "period_days": days})


@routes.get("/api/sites/{id}/devices")
@require_auth
async def site_devices(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    devices = await db.get_device_stats(site_id, days=days)
    return _json_response({"devices": devices, "period_days": days})


@routes.get("/api/sites/{id}/browsers")
@require_auth
async def site_browsers(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    browsers = await db.get_browser_stats(site_id, days=days)
    return _json_response({"browsers": browsers, "period_days": days})


@routes.get("/api/sites/{id}/countries")
@require_auth
async def site_countries(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=CONST_50)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    countries = await db.get_country_stats(site_id, days=days, limit=limit)
    return _json_response({"countries": countries, "period_days": days})


@routes.get("/api/sites/{id}/daily")
@require_auth
async def site_daily(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    daily = await db.get_daily_stats(site_id, days=days)
    return _json_response({"daily": daily, "period_days": days})


@routes.get("/api/sites/{id}/hourly")
@require_auth
async def site_hourly(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request, default=CONST_7)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    hourly = await db.get_hourly_stats(site_id, days=days)
    return _json_response({"hourly": hourly, "period_days": days})


@routes.get("/api/sites/{id}/realtime")
@require_auth
async def site_realtime(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    now = datetime.now(timezone.utc)
    five_min_ago = (now - timedelta(minutes=CONST_5)).isoformat()

    active = await db._fetch_one(
        """SELECT COUNT(DISTINCT visitor_id) AS active_visitors
           FROM pageviews WHERE site_id=? AND created_at>=?""",
        (site_id, five_min_ago),
    )

    page_views_5m = await db._fetch_one(
        "SELECT COUNT(*) AS views FROM pageviews WHERE site_id=? AND created_at>=?",
        (site_id, five_min_ago),
    )

    top_pages = await db._fetch_all(
        """SELECT path, COUNT(*) AS views
           FROM pageviews WHERE site_id=? AND created_at>=?
           GROUP BY path ORDER BY views DESC LIMIT 5""",
        (site_id, five_min_ago),
    )

    return _json_response({
        "active_visitors": active["active_visitors"] if active else 0,
        "page_views_5m": page_views_5m["views"] if page_views_5m else 0,
        "top_pages": top_pages,
    })


@routes.get("/api/sites/{id}/retention")
@require_auth
async def site_retention(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    retention = await db.get_retention(site_id, days=days)
    return _json_response({"retention": retention, "period_days": days})


# ── API Keys ────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/api-keys")
@require_auth
async def list_api_keys(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    auth = AuthManager(db)
    keys = await auth.get_api_keys(site_id)
    return _json_response({"api_keys": keys})


@routes.post("/api/sites/{id}/api-keys")
@require_role("editor")
async def create_api_key(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "unnamed").strip()
    permissions = body.get("permissions", ["read"])
    rate_limit = body.get("rate_limit", CONST_1000)
    expires_in_days = body.get("expires_in_days")

    auth = AuthManager(db)
    key_data = await auth.create_api_key(
        site_id=site_id,
        name=name,
        permissions=permissions,
        rate_limit=rate_limit,
        expires_in_days=expires_in_days,
    )
    return _json_response(key_data, status=CONST_201)


@routes.delete("/api/api-keys/{id}")
@require_auth
async def delete_api_key(request: web.Request) -> web.Response:
    key_id = int(request.match_info["id"])
    db = _get_db(request)

    auth = AuthManager(db)
    deleted = await auth.revoke_api_key(key_id)
    if not deleted:
        return _error("API key not found", status=CONST_404)
    return _json_response({"ok": True})


@routes.get("/api/api-keys/{id}")
@require_auth
async def get_api_key(request: web.Request) -> web.Response:
    key_id = int(request.match_info["id"])
    db = _get_db(request)

    auth = AuthManager(db)
    key = await auth.get_api_key(key_id)
    if not key:
        return _error("API key not found", status=CONST_404)
    return _json_response(key)


# ── Alerts ──────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/alerts")
@require_auth
async def list_alerts(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    alert_mgr = AlertManager(db)
    alerts = await alert_mgr.get_alerts(site_id)
    return _json_response({"alerts": alerts})


@routes.post("/api/sites/{id}/alerts")
@require_role("editor")
async def create_alert(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "").strip()
    alert_type = (body.get("alert_type") or "").strip()
    threshold = body.get("threshold", 0)
    window_minutes = body.get("window_minutes", CONST_5)
    cooldown_minutes = body.get("cooldown_minutes", CONST_30)
    metadata = body.get("metadata", {})

    if not name:
        return _error("Missing 'name' field")
    if not alert_type:
        return _error("Missing 'alert_type' field")

    alert_mgr = AlertManager(db)
    try:
        alert = await alert_mgr.create_alert(
            site_id=site_id,
            name=name,
            alert_type=alert_type,
            threshold=threshold,
            window_minutes=window_minutes,
            cooldown_minutes=cooldown_minutes,
            metadata=metadata,
        )
    except ValueError as exc:
        return _error(str(exc))

    return _json_response(alert, status=CONST_201)


@routes.get("/api/alerts/{id}")
@require_auth
async def get_alert(request: web.Request) -> web.Response:
    alert_id = int(request.match_info["id"])
    db = _get_db(request)

    alert_mgr = AlertManager(db)
    alert = await alert_mgr.get_alert(alert_id)
    if not alert:
        return _error("Alert not found", status=CONST_404)
    return _json_response(alert)


@routes.patch("/api/alerts/{id}")
@require_role("editor")
async def update_alert(request: web.Request) -> web.Response:
    alert_id = int(request.match_info["id"])
    db = _get_db(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    alert_mgr = AlertManager(db)
    alert = await alert_mgr.get_alert(alert_id)
    if not alert:
        return _error("Alert not found", status=CONST_404)

    updates = {}
    for key in ("name", "threshold", "window_minutes", "cooldown_minutes", "status", "metadata"):
        if key in body:
            updates[key] = body[key]

    if updates:
        await db.db.execute(
            "UPDATE alerts SET " + ", ".join(f"{k}=?" for k in updates) + " WHERE id=?",
            list(updates.values()) + [alert_id],
        )
        await db.db.commit()

    updated = await alert_mgr.get_alert(alert_id)
    return _json_response(updated)


@routes.delete("/api/alerts/{id}")
@require_role("editor")
async def delete_alert(request: web.Request) -> web.Response:
    alert_id = int(request.match_info["id"])
    db = _get_db(request)

    alert_mgr = AlertManager(db)
    deleted = await alert_mgr.delete_alert(alert_id)
    if not deleted:
        return _error("Alert not found", status=CONST_404)
    return _json_response({"ok": True})


@routes.get("/api/sites/{id}/alerts/history")
@require_auth
async def alert_history(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    limit = _parse_limit(request, default=CONST_50)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    alert_mgr = AlertManager(db)
    history = await alert_mgr.get_alert_history(site_id, limit=limit)
    return _json_response({"history": history})


# ── Funnels ─────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/funnels")
@require_auth
async def list_funnels(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    funnel_mgr = FunnelManager(db)
    funnels = await funnel_mgr.get_funnels(site_id)
    return _json_response({"funnels": funnels})


@routes.post("/api/sites/{id}/funnels")
@require_role("editor")
async def create_funnel(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    steps = body.get("steps", [])

    if not name:
        return _error("Missing 'name' field")
    if not steps:
        return _error("Missing 'steps' array")

    funnel_mgr = FunnelManager(db)
    funnel = await funnel_mgr.create_funnel(
        site_id=site_id,
        name=name,
        steps=steps,
        description=description,
    )
    return _json_response(funnel, status=CONST_201)


@routes.get("/api/funnels/{id}")
@require_auth
async def get_funnel(request: web.Request) -> web.Response:
    funnel_id = int(request.match_info["id"])
    db = _get_db(request)

    funnel_mgr = FunnelManager(db)
    funnel = await funnel_mgr.get_funnel(funnel_id)
    if not funnel:
        return _error("Funnel not found", status=CONST_404)
    return _json_response(funnel)


@routes.get("/api/funnels/{id}/stats")
@require_auth
async def funnel_stats(request: web.Request) -> web.Response:
    funnel_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    funnel_mgr = FunnelManager(db)
    try:
        stats = await funnel_mgr.get_funnel_stats(funnel_id, days=days)
    except ValueError as exc:
        return _error(str(exc), status=CONST_404)
    return _json_response(stats)


@routes.delete("/api/funnels/{id}")
@require_role("editor")
async def delete_funnel(request: web.Request) -> web.Response:
    funnel_id = int(request.match_info["id"])
    db = _get_db(request)

    funnel_mgr = FunnelManager(db)
    deleted = await funnel_mgr.delete_funnel(funnel_id)
    if not deleted:
        return _error("Funnel not found", status=CONST_404)
    return _json_response({"ok": True})


# ── Goals ───────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/goals")
@require_auth
async def list_goals(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    goal_mgr = GoalManager(db)
    goals = await goal_mgr.get_goals(site_id)
    return _json_response({"goals": goals})


@routes.post("/api/sites/{id}/goals")
@require_role("editor")
async def create_goal(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "").strip()
    goal_type = (body.get("goal_type") or "pageview").strip()
    url_pattern = (body.get("url_pattern") or "").strip()
    match_type = (body.get("match_type") or "prefix").strip()

    if not name:
        return _error("Missing 'name' field")

    goal_mgr = GoalManager(db)
    try:
        goal = await goal_mgr.create_goal(
            site_id=site_id,
            name=name,
            goal_type=goal_type,
            url_pattern=url_pattern,
            match_type=match_type,
        )
    except ValueError as exc:
        return _error(str(exc))

    return _json_response(goal, status=CONST_201)


@routes.get("/api/goals/{id}")
@require_auth
async def get_goal(request: web.Request) -> web.Response:
    goal_id = int(request.match_info["id"])
    db = _get_db(request)

    goal_mgr = GoalManager(db)
    goal = await goal_mgr.get_goal(goal_id)
    if not goal:
        return _error("Goal not found", status=CONST_404)
    return _json_response(goal)


@routes.get("/api/goals/{id}/stats")
@require_auth
async def goal_stats(request: web.Request) -> web.Response:
    goal_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    goal_mgr = GoalManager(db)
    try:
        stats = await goal_mgr.get_goal_stats(goal_id, days=days)
    except ValueError as exc:
        return _error(str(exc), status=CONST_404)
    return _json_response(stats)


@routes.delete("/api/goals/{id}")
@require_role("editor")
async def delete_goal(request: web.Request) -> web.Response:
    goal_id = int(request.match_info["id"])
    db = _get_db(request)

    goal_mgr = GoalManager(db)
    deleted = await goal_mgr.delete_goal(goal_id)
    if not deleted:
        return _error("Goal not found", status=CONST_404)
    return _json_response({"ok": True})


# ── Export ──────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/export")
@require_auth
async def export_data(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    format = request.query.get("format", "json")
    start_date = request.query.get("start_date")
    end_date = request.query.get("end_date")
    data_types_raw = request.query.get("data_types", "pageviews,visitors,sessions,events")

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    if format not in ("json", "csv", "html"):
        return _error("Invalid format. Must be json, csv, or html")

    data_types = [dt.strip() for dt in data_types_raw.split(",") if dt.strip()]

    export_mgr = ExportManager(db)
    try:
        result = await export_mgr.export_site_data(
            site_id=site_id,
            format=format,
            start_date=start_date,
            end_date=end_date,
            data_types=data_types,
        )
    except ValueError as exc:
        return _error(str(exc), status=CONST_404)

    await export_mgr.log_export(site_id, format, data_types)

    return web.Response(
        text=result["content"],
        content_type=result["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{result["filename"]}"',
        },
    )


@routes.get("/api/sites/{id}/export/history")
@require_auth
async def export_history(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    export_mgr = ExportManager(db)
    history = await export_mgr.get_export_history(site_id)
    return _json_response({"history": history})


# ── Dashboard ───────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/dashboard")
@require_auth
async def site_dashboard(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id, domain, name FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    from ghostly.core.aggregator import Aggregator
    aggregator = Aggregator(db)
    dashboard = await aggregator.get_dashboard(site_id, days)

    goal_mgr = GoalManager(db)
    goals = await goal_mgr.get_all_goals_stats(site_id, days)

    funnel_mgr = FunnelManager(db)
    funnels_raw = await funnel_mgr.get_funnels(site_id)
    funnels = []
    for f in funnels_raw:
        try:
            fstats = await funnel_mgr.get_funnel_stats(f["id"], days)
            funnels.append(fstats)
        except ValueError:
            continue

    return _json_response({
        "site": dict(site),
        "period_days": days,
        "dashboard": dashboard,
        "goals": goals,
        "funnels": funnels,
    })


# ── Webhooks ────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/webhooks")
@require_auth
async def list_webhooks(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    webhooks = await db.get_webhooks(site_id)
    return _json_response({"webhooks": webhooks})


@routes.post("/api/sites/{id}/webhooks")
@require_role("editor")
async def create_webhook(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    events = body.get("events", ["pageview"])
    secret = (body.get("secret") or "").strip()

    if not url:
        return _error("Missing 'url' field")

    webhook_id = await db.create_webhook(
        site_id=site_id,
        name=name,
        url=url,
        events=json.dumps(events) if isinstance(events, list) else events,
        secret=secret,
    )

    return _json_response({"id": webhook_id, "ok": True}, status=CONST_201)


@routes.delete("/api/webhooks/{id}")
@require_role("editor")
async def delete_webhook(request: web.Request) -> web.Response:
    webhook_id = int(request.match_info["id"])
    db = _get_db(request)

    deleted = await db.delete_webhook(webhook_id)
    if not deleted:
        return _error("Webhook not found", status=CONST_404)
    return _json_response({"ok": True})


# ── Email Reports ───────────────────────────────────────────────────────


@routes.get("/api/email/config")
@require_role("editor")
async def get_email_config(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    db = _get_db(request)
    reporter = EmailReporter(db)
    await reporter.load_config()
    return _json_response({"config": reporter.get_config()})


@routes.post("/api/email/config")
@require_role("editor")
async def save_email_config(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    db = _get_db(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    required = ["host", "port"]
    missing = [f for f in required if f not in body]
    if missing:
        return _error(f"Missing fields: {', '.join(missing)}")

    reporter = EmailReporter(db)
    await reporter.save_config(body)
    return _json_response({"ok": True})


@routes.post("/api/email/test")
@require_role("editor")
async def send_test_email(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    db = _get_db(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    recipients = body.get("recipients", [])
    site_id = body.get("site_id")
    if not recipients:
        return _error("Missing 'recipients' list")
    if not site_id:
        return _error("Missing 'site_id'")

    reporter = EmailReporter(db)
    await reporter.load_config()
    result = await reporter.send_report(int(site_id), recipients, days=CONST_7)
    return _json_response(result)


@routes.get("/api/sites/{id}/email/schedules")
@require_auth
async def list_email_schedules(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    reporter = EmailReporter(db)
    schedules = await reporter.get_schedules()
    site_schedules = [s for s in schedules if s.get("site_id") == site_id]
    return _json_response({"schedules": site_schedules})


@routes.post("/api/sites/{id}/email/schedules")
@require_role("editor")
async def create_email_schedule(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    recipients = body.get("recipients", [])
    cron_expr = body.get("cron_expr", "0 8 * * 1")
    days = body.get("days", CONST_7)

    if not recipients:
        return _error("Missing 'recipients' list")

    reporter = EmailReporter(db)
    try:
        schedule = await reporter.create_schedule(site_id, recipients, cron_expr, days)
    except ValueError as exc:
        return _error(str(exc))

    return _json_response(schedule, status=CONST_201)


@routes.delete("/api/email/schedules/{id}")
@require_role("editor")
async def delete_email_schedule(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    schedule_id = int(request.match_info["id"])
    db = _get_db(request)
    reporter = EmailReporter(db)
    deleted = await reporter.delete_schedule(schedule_id)
    if not deleted:
        return _error("Schedule not found", status=CONST_404)
    return _json_response({"ok": True})


@routes.post("/api/sites/{id}/email/send")
@require_role("editor")
async def send_report_now(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    recipients = body.get("recipients", [])
    days = body.get("days", CONST_7)

    if not recipients:
        return _error("Missing 'recipients' list")

    reporter = EmailReporter(db)
    await reporter.load_config()
    result = await reporter.send_report(site_id, recipients, days=days)
    return _json_response(result)


# ── Webhook Management ──────────────────────────────────────────────────


@routes.get("/api/sites/{id}/webhooks/history")
@require_auth
async def webhook_history(request: web.Request) -> web.Response:
    from ghostly.core.webhooks import WebhookManager
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    mgr = WebhookManager(db)
    history = await mgr.get_delivery_history(site_id)
    return _json_response({"history": history})


@routes.post("/api/webhooks/{id}/test")
@require_role("editor")
async def test_webhook(request: web.Request) -> web.Response:
    from ghostly.core.webhooks import WebhookManager
    webhook_id = int(request.match_info["id"])
    db = _get_db(request)
    mgr = WebhookManager(db)

    try:
        result = await mgr.test_webhook(webhook_id)
    except ValueError as exc:
        return _error(str(exc), status=CONST_404)

    return _json_response(result)


# ── Heatmap ─────────────────────────────────────────────────────────────


@routes.post("/api/sites/{id}/heatmap/click")
async def record_heatmap_click(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    x = body.get("x")
    y = body.get("y")
    if x is None or y is None:
        return _error("Missing 'x' or 'y' coordinates")

    collector = HeatmapCollector(db)
    click_id = await collector.record_click(
        site_id=site_id,
        visitor_id=body.get("visitor_id", ""),
        page_url=body.get("page_url", "/"),
        x=float(x),
        y=float(y),
        viewport_width=int(body.get("viewport_width", 0)),
        viewport_height=int(body.get("viewport_height", 0)),
        element_tag=body.get("element_tag", ""),
        element_id=body.get("element_id", ""),
        element_classes=body.get("element_classes", ""),
    )
    return _json_response({"ok": True, "id": click_id}, status=CONST_201)


@routes.get("/api/sites/{id}/heatmap/grid")
@require_auth
async def heatmap_grid(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    page_url = request.query.get("page_url")
    days = _parse_days(request)

    collector = HeatmapCollector(db)
    data = await collector.generate_grid_data(site_id, page_url=page_url, days=days)
    return _json_response(data)


@routes.get("/api/sites/{id}/heatmap/sections")
@require_auth
async def heatmap_sections(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    page_url = request.query.get("page_url")
    days = _parse_days(request)

    collector = HeatmapCollector(db)
    data = await collector.generate_section_data(site_id, page_url=page_url, days=days)
    return _json_response(data)


@routes.get("/api/sites/{id}/heatmap/elements")
@require_auth
async def heatmap_elements(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    page_url = request.query.get("page_url")
    days = _parse_days(request)

    collector = HeatmapCollector(db)
    elements = await collector.get_click_element_stats(site_id, page_url=page_url, days=days)
    return _json_response({"elements": elements})


@routes.get("/api/sites/{id}/heatmap/pages")
@require_auth
async def heatmap_pages(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    days = _parse_days(request)

    collector = HeatmapCollector(db)
    pages = await collector.get_page_click_counts(site_id, days=days)
    return _json_response({"pages": pages})


@routes.get("/api/sites/{id}/heatmap/clicks")
@require_auth
async def heatmap_clicks(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    page_url = request.query.get("page_url")
    days = _parse_days(request)

    collector = HeatmapCollector(db)
    clicks = await collector.get_clicks(site_id, page_url=page_url, days=days)
    return _json_response({"clicks": clicks, "total": len(clicks)})


# ── Themes ──────────────────────────────────────────────────────────────


@routes.get("/api/themes")
@require_auth
async def list_themes(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    db = _get_db(request)
    mgr = ThemeManager(db)
    themes = await mgr.get_themes()
    return _json_response({"themes": themes})


@routes.get("/api/themes/{id}")
@require_auth
async def get_theme(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    theme_id = request.match_info["id"]
    db = _get_db(request)
    mgr = ThemeManager(db)
    theme = await mgr.get_theme(theme_id)
    if not theme:
        return _error("Theme not found", status=CONST_404)
    return _json_response({"theme": theme})


@routes.post("/api/themes")
@require_role("editor")
async def create_theme(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    db = _get_db(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    theme_id = (body.get("id") or "").strip()
    variables = body.get("variables", {})

    if not theme_id:
        return _error("Missing 'id' field")

    mgr = ThemeManager(db)
    try:
        theme = await mgr.save_theme(theme_id, variables)
    except ValueError as exc:
        return _error(str(exc))

    return _json_response({"id": theme_id, "theme": theme}, status=CONST_201)


@routes.delete("/api/themes/{id}")
@require_role("editor")
async def delete_theme(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    theme_id = request.match_info["id"]
    db = _get_db(request)
    mgr = ThemeManager(db)
    try:
        deleted = await mgr.delete_theme(theme_id)
    except ValueError as exc:
        return _error(str(exc))
    if not deleted:
        return _error("Theme not found", status=CONST_404)
    return _json_response({"ok": True})


@routes.get("/api/themes/{id}/css")
@require_auth
async def get_theme_css(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    theme_id = request.match_info["id"]
    db = _get_db(request)
    mgr = ThemeManager(db)
    css = await mgr.get_theme_css(theme_id)
    return web.Response(text=css, content_type="text/css")


@routes.get("/api/users/{id}/theme")
@require_auth
async def get_user_theme(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    user_id = request.match_info["id"]
    db = _get_db(request)
    mgr = ThemeManager(db)
    theme_id = await mgr.get_user_theme(user_id)
    return _json_response({"theme_id": theme_id or "dark"})


@routes.post("/api/users/{id}/theme")
@require_auth
async def set_user_theme(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    user_id = request.match_info["id"]
    db = _get_db(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    theme_id = body.get("theme_id", "")
    if not theme_id:
        return _error("Missing 'theme_id'")

    mgr = ThemeManager(db)
    try:
        await mgr.set_user_theme(user_id, theme_id)
    except ValueError as exc:
        return _error(str(exc))

    return _json_response({"ok": True, "theme_id": theme_id})


# ── Plugins ─────────────────────────────────────────────────────────────


@routes.get("/api/plugins")
@require_auth
async def list_plugins(request: web.Request) -> web.Response:
    from ghostly.core.plugins import PluginManager
    db = _get_db(request)
    mgr = PluginManager(db)
    plugins = mgr.list_plugins()
    hooks = mgr.get_hook_count()
    return _json_response({"plugins": plugins, "hooks": hooks})


@routes.post("/api/plugins/reload")
@require_role("admin")
async def reload_plugins(request: web.Request) -> web.Response:
    from ghostly.core.plugins import PluginManager
    db = _get_db(request)
    mgr = PluginManager(db)
    await mgr.unload_all()
    count = await mgr.load_all_plugins()
    return _json_response({"ok": True, "loaded": count})


@routes.get("/api/plugins/{name}")
@require_auth
async def get_plugin(request: web.Request) -> web.Response:
    from ghostly.core.plugins import PluginManager
    name = request.match_info["name"]
    db = _get_db(request)
    mgr = PluginManager(db)
    plugin = mgr.get_plugin(name)
    if not plugin:
        return _error("Plugin not found", status=CONST_404)
    return _json_response({"plugin": plugin.to_dict()})


# ── Backup & Restore ────────────────────────────────────────────────────


@routes.get("/api/backups")
@require_auth
async def list_backups(request: web.Request) -> web.Response:
    from ghostly.core.backup import BackupManager
    db = _get_db(request)
    mgr = BackupManager(db)
    backups = await mgr.list_backups()
    return _json_response({"backups": backups})


@routes.post("/api/backups")
@require_role("admin")
async def create_backup(request: web.Request) -> web.Response:
    from ghostly.core.backup import BackupManager
    db = _get_db(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        body = {}

    name = body.get("name")
    compress = body.get("compress", True)

    mgr = BackupManager(db)
    result = await mgr.create_backup(name=name, compress=compress)
    return _json_response(result, status=CONST_201)


@routes.post("/api/backups/restore")
@require_role("admin")
async def restore_backup(request: web.Request) -> web.Response:
    from ghostly.core.backup import BackupManager
    db = _get_db(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    filename = body.get("filename", "")
    if not filename:
        return _error("Missing 'filename'")

    mgr = BackupManager(db)
    try:
        result = await mgr.restore_backup(filename)
    except FileNotFoundError as exc:
        return _error(str(exc), status=CONST_404)

    return _json_response(result)


@routes.delete("/api/backups/{filename}")
@require_role("admin")
async def delete_backup(request: web.Request) -> web.Response:
    from ghostly.core.backup import BackupManager
    filename = request.match_info["filename"]
    db = _get_db(request)
    mgr = BackupManager(db)
    deleted = await mgr.delete_backup(filename)
    if not deleted:
        return _error("Backup not found", status=CONST_404)
    return _json_response({"ok": True})


@routes.post("/api/backups/prune")
@require_role("admin")
async def prune_backups(request: web.Request) -> web.Response:
    from ghostly.core.backup import BackupManager
    db = _get_db(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        body = {}

    keep = body.get("keep", 10)

    mgr = BackupManager(db)
    pruned = await mgr.prune_old_backups(keep_count=keep)
    return _json_response({"ok": True, "pruned": pruned})


# ── Geographic Map ──────────────────────────────────────────────────────


@routes.post("/api/sites/{id}/geomap/location")
async def record_geo_location(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    visitor_id = (body.get("visitor_id") or "").strip()
    if not visitor_id:
        return _error("Missing 'visitor_id' field")

    collector = GeoMapCollector(db)
    location_id = await collector.record_visitor_location(
        site_id=site_id,
        visitor_id=visitor_id,
        country=body.get("country", ""),
        city=body.get("city", ""),
        latitude=body.get("latitude"),
        longitude=body.get("longitude"),
        ip_address=body.get("ip_address", ""),
    )
    return _json_response({"ok": True, "id": location_id}, status=CONST_201)


@routes.get("/api/sites/{id}/geomap/countries")
@require_auth
async def geomap_countries(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    collector = GeoMapCollector(db)
    countries = await collector.get_country_stats(site_id, days=days)
    return _json_response({"countries": countries, "period_days": days})


@routes.get("/api/sites/{id}/geomap/cities")
@require_auth
async def geomap_cities(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=100)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    collector = GeoMapCollector(db)
    cities = await collector.get_city_stats(site_id, days=days, limit=limit)
    return _json_response({"cities": cities, "period_days": days})


@routes.get("/api/sites/{id}/geomap/top-countries")
@require_auth
async def geomap_top_countries(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=10)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    collector = GeoMapCollector(db)
    countries = await collector.get_top_countries(site_id, days=days, limit=limit)
    return _json_response({"top_countries": countries, "period_days": days})


@routes.get("/api/sites/{id}/geomap/top-cities")
@require_auth
async def geomap_top_cities(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=CONST_20)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    collector = GeoMapCollector(db)
    cities = await collector.get_top_cities(site_id, days=days, limit=limit)
    return _json_response({"top_cities": cities, "period_days": days})


@routes.get("/api/sites/{id}/geomap/geojson")
@require_auth
async def geomap_geojson(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    collector = GeoMapCollector(db)
    geojson = await collector.generate_geojson(site_id, days=days)
    return _json_response(geojson)


@routes.get("/api/sites/{id}/geomap/country-geojson")
@require_auth
async def geomap_country_geojson(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    collector = GeoMapCollector(db)
    geojson = await collector.generate_country_geojson(site_id, days=days)
    return _json_response(geojson)


@routes.get("/api/sites/{id}/geomap/distribution")
@require_auth
async def geomap_distribution(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    collector = GeoMapCollector(db)
    distribution = await collector.get_visitor_country_distribution(site_id, days=days)
    return _json_response(distribution)


@routes.get("/api/sites/{id}/geomap/summary")
@require_auth
async def geomap_summary(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    collector = GeoMapCollector(db)
    summary = await collector.get_geo_summary(site_id, days=days)
    return _json_response(summary)


# ── Retention Analysis ──────────────────────────────────────────────────


@routes.get("/api/sites/{id}/retention/daily")
@require_auth
async def retention_daily(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    analyzer = RetentionAnalyzer(db)
    retention = await analyzer.get_daily_retention(site_id, days=days)
    return _json_response({"retention": retention, "period_days": days, "group_by": "day"})


@routes.get("/api/sites/{id}/retention/weekly")
@require_auth
async def retention_weekly(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    analyzer = RetentionAnalyzer(db)
    retention = await analyzer.get_weekly_retention(site_id)
    return _json_response({"retention": retention, "group_by": "week"})


@routes.get("/api/sites/{id}/retention/monthly")
@require_auth
async def retention_monthly(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    analyzer = RetentionAnalyzer(db)
    retention = await analyzer.get_monthly_retention(site_id)
    return _json_response({"retention": retention, "group_by": "month"})


@routes.get("/api/sites/{id}/retention/cohort")
@require_auth
async def retention_cohort(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request, default=90)
    group_by = request.query.get("group_by", "week")

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    analyzer = RetentionAnalyzer(db)
    cohort = await analyzer.get_cohort_analysis(site_id, days=days, group_by=group_by)
    return _json_response(cohort)


@routes.get("/api/sites/{id}/retention/churn")
@require_auth
async def retention_churn(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    inactive_days = CONST_30
    raw = request.query.get("inactive_days")
    if raw:
        try:
            inactive_days = max(1, min(int(raw), CONST_365))
        except ValueError:
            pass

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    analyzer = RetentionAnalyzer(db)
    churn = await analyzer.get_churn_rate(site_id, days=days, inactive_days=inactive_days)
    return _json_response(churn)


@routes.get("/api/sites/{id}/retention/return-visitors")
@require_auth
async def retention_return_visitors(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    analyzer = RetentionAnalyzer(db)
    stats = await analyzer.get_return_visitor_stats(site_id, days=days)
    return _json_response(stats)


@routes.get("/api/sites/{id}/retention/summary")
@require_auth
async def retention_summary(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    analyzer = RetentionAnalyzer(db)
    summary = await analyzer.get_retention_summary(site_id, days=days)
    return _json_response(summary)


# ── A/B Testing ────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/experiments")
@require_auth
async def list_experiments(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    mgr = ABTestManager(db)
    experiments = await mgr.get_experiments(site_id)
    return _json_response({"experiments": experiments})


@routes.post("/api/sites/{id}/experiments")
@require_role("editor")
async def create_experiment(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    variants = body.get("variants", [])
    traffic_pct = body.get("traffic_pct", 100.0)

    if not name:
        return _error("Missing 'name' field")
    if not variants or len(variants) < 2:
        return _error("At least 2 variants are required")

    mgr = ABTestManager(db)
    try:
        experiment = await mgr.create_experiment(
            site_id=site_id,
            name=name,
            variants=variants,
            description=description,
            traffic_pct=traffic_pct,
        )
    except ValueError as exc:
        return _error(str(exc))

    return _json_response(experiment, status=CONST_201)


@routes.get("/api/experiments/{id}")
@require_auth
async def get_experiment(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    mgr = ABTestManager(db)
    experiment = await mgr.get_experiment(experiment_id)
    if not experiment:
        return _error("Experiment not found", status=CONST_404)
    return _json_response(experiment)


@routes.post("/api/experiments/{id}/start")
@require_role("editor")
async def start_experiment(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    mgr = ABTestManager(db)
    started = await mgr.start_experiment(experiment_id)
    if not started:
        return _error("Experiment not found or already started", status=CONST_404)
    return _json_response({"ok": True, "status": "running"})


@routes.post("/api/experiments/{id}/stop")
@require_role("editor")
async def stop_experiment(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    mgr = ABTestManager(db)
    stopped = await mgr.stop_experiment(experiment_id)
    if not stopped:
        return _error("Experiment not found or not running", status=CONST_404)
    return _json_response({"ok": True, "status": "completed"})


@routes.delete("/api/experiments/{id}")
@require_role("editor")
async def delete_experiment(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    mgr = ABTestManager(db)
    deleted = await mgr.delete_experiment(experiment_id)
    if not deleted:
        return _error("Experiment not found", status=CONST_404)
    return _json_response({"ok": True})


@routes.post("/api/experiments/{id}/assign")
async def assign_visitor_to_variant(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    visitor_id = (body.get("visitor_id") or "").strip()
    if not visitor_id:
        return _error("Missing 'visitor_id' field")

    mgr = ABTestManager(db)
    assignment = await mgr.assign_visitor(experiment_id, visitor_id)
    if not assignment:
        return _error("Experiment not found or not running", status=CONST_404)
    return _json_response(assignment)


@routes.post("/api/experiments/{id}/convert")
async def track_ab_conversion(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    visitor_id = (body.get("visitor_id") or "").strip()
    if not visitor_id:
        return _error("Missing 'visitor_id' field")

    event_name = body.get("event_name", "conversion")
    value = body.get("value", 0.0)

    mgr = ABTestManager(db)
    conversion = await mgr.track_conversion(
        experiment_id=experiment_id,
        visitor_id=visitor_id,
        event_name=event_name,
        value=float(value),
    )
    if not conversion:
        return _error("Visitor not assigned to this experiment", status=CONST_404)
    return _json_response(conversion, status=CONST_201)


@routes.get("/api/experiments/{id}/stats")
@require_auth
async def experiment_stats(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    mgr = ABTestManager(db)
    stats = await mgr.get_experiment_stats(experiment_id, days=days)
    if not stats:
        return _error("Experiment not found", status=CONST_404)
    return _json_response(stats)


@routes.get("/api/experiments/{id}/significance")
@require_auth
async def experiment_significance(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    mgr = ABTestManager(db)
    significance = await mgr.get_statistical_significance(experiment_id, days=days)
    return _json_response(significance)


@routes.get("/api/sites/{id}/experiments/summary")
@require_auth
async def experiments_summary(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    mgr = ABTestManager(db)
    summary = await mgr.get_experiment_summary(site_id, days=days)
    return _json_response(summary)


# ── Multi-Tenant ──────────────────────────────────────────────────────


def _get_tenant(request: web.Request):
    from ghostly.core.multi_tenant import TenantManager
    db = _get_db(request)
    return TenantManager(db)


@routes.get("/api/organizations")
@require_auth
async def list_organizations(request: web.Request) -> web.Response:
    user = _get_user(request)
    tenant = _get_tenant(request)
    orgs = await tenant.get_user_organizations(user["user_id"])
    return _json_response({"organizations": orgs})


@routes.post("/api/organizations")
@require_auth
async def create_organization(request: web.Request) -> web.Response:
    user = _get_user(request)
    tenant = _get_tenant(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "").strip()
    plan = body.get("plan", "free")
    subdomain = body.get("subdomain")

    if not name:
        return _error("Missing 'name' field")

    try:
        org = await tenant.create_organization(
            name=name,
            owner_user_id=user["user_id"],
            plan=plan,
            subdomain=subdomain,
        )
    except Exception as exc:
        return _error(str(exc))

    return _json_response(org, status=CONST_201)


@routes.get("/api/organizations/{id}")
@require_auth
async def get_organization(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"])
    if not role:
        return _error("Access denied", CONST_403)

    org = await tenant.get_organization(org_id)
    if not org:
        return _error("Organization not found", CONST_404)
    return _json_response(org)


@routes.put("/api/organizations/{id}")
@require_auth
async def update_organization(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"], ["owner", "admin"])
    if not role:
        return _error("Insufficient permissions", CONST_403)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    updates = {}
    for key in ("name", "subdomain", "billing_email", "settings"):
        if key in body:
            updates[key] = body[key]

    try:
        await tenant.update_organization(org_id, **updates)
    except Exception as exc:
        return _error(str(exc))

    org = await tenant.get_organization(org_id)
    return _json_response(org)


@routes.delete("/api/organizations/{id}")
@require_auth
async def delete_organization(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"], ["owner"])
    if not role:
        return _error("Only the owner can delete the organization", CONST_403)

    await tenant.delete_organization(org_id)
    return _json_response({"ok": True})


@routes.get("/api/organizations/{id}/members")
@require_auth
async def list_org_members(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"])
    if not role:
        return _error("Access denied", CONST_403)

    members = await tenant.get_members(org_id)
    return _json_response({"members": members})


@routes.post("/api/organizations/{id}/members")
@require_auth
async def add_org_member(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"], ["owner", "admin"])
    if not role:
        return _error("Insufficient permissions", CONST_403)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    target_user_id = body.get("user_id")
    member_role = body.get("role", "viewer")

    if not target_user_id:
        return _error("Missing 'user_id'")

    try:
        member = await tenant.add_member(
            org_id=org_id,
            user_id=int(target_user_id),
            role=member_role,
            invited_by=user["user_id"],
        )
    except Exception as exc:
        return _error(str(exc))

    return _json_response(member, status=CONST_201)


@routes.put("/api/organizations/{org_id}/members/{user_id}/role")
@require_auth
async def update_org_member_role(request: web.Request) -> web.Response:
    org_id = int(request.match_info["org_id"])
    target_user_id = int(request.match_info["user_id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"], ["owner", "admin"])
    if not role:
        return _error("Insufficient permissions", CONST_403)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    new_role = body.get("role", "")
    if not new_role:
        return _error("Missing 'role'")

    try:
        await tenant.update_member_role(org_id, target_user_id, new_role)
    except Exception as exc:
        return _error(str(exc))

    return _json_response({"ok": True})


@routes.delete("/api/organizations/{org_id}/members/{user_id}")
@require_auth
async def remove_org_member(request: web.Request) -> web.Response:
    org_id = int(request.match_info["org_id"])
    target_user_id = int(request.match_info["user_id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"], ["owner", "admin"])
    if not role:
        return _error("Insufficient permissions", CONST_403)

    try:
        await tenant.remove_member(org_id, target_user_id)
    except Exception as exc:
        return _error(str(exc))

    return _json_response({"ok": True})


@routes.get("/api/organizations/{id}/usage")
@require_auth
async def org_usage(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"])
    if not role:
        return _error("Access denied", CONST_403)

    usage = await tenant.get_org_usage(org_id)
    return _json_response(usage)


@routes.get("/api/organizations/{id}/sites")
@require_auth
async def org_sites(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"])
    if not role:
        return _error("Access denied", CONST_403)

    sites = await tenant.get_org_sites(org_id)
    return _json_response({"sites": sites})


@routes.post("/api/organizations/{id}/sites/{site_id}")
@require_auth
async def add_site_to_org(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    site_id = int(request.match_info["site_id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"], ["owner", "admin"])
    if not role:
        return _error("Insufficient permissions", CONST_403)

    try:
        await tenant.add_site_to_org(org_id, site_id)
    except Exception as exc:
        return _error(str(exc))

    return _json_response({"ok": True})


@routes.delete("/api/organizations/{id}/sites/{site_id}")
@require_auth
async def remove_site_from_org(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    site_id = int(request.match_info["site_id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"], ["owner", "admin"])
    if not role:
        return _error("Insufficient permissions", CONST_403)

    await tenant.remove_site_from_org(org_id, site_id)
    return _json_response({"ok": True})


@routes.post("/api/organizations/{id}/upgrade")
@require_auth
async def upgrade_org_plan(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"], ["owner"])
    if not role:
        return _error("Only the owner can upgrade the plan", CONST_403)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    new_plan = body.get("plan", "")
    if not new_plan:
        return _error("Missing 'plan'")

    try:
        org = await tenant.upgrade_plan(org_id, new_plan)
    except Exception as exc:
        return _error(str(exc))

    return _json_response(org)


@routes.get("/api/plans")
@require_auth
async def list_plans(request: web.Request) -> web.Response:
    from ghostly.core.multi_tenant import TenantManager, PLAN_LIMITS, PLAN_PRICING
    tenant = _get_tenant(request)
    plans = {}
    for plan_name in PLAN_LIMITS:
        plans[plan_name] = {
            "limits": tenant.get_plan_limits(plan_name),
            "pricing": PLAN_PRICING[plan_name],
        }
    return _json_response({"plans": plans})


@routes.get("/api/organizations/{id}/invoices")
@require_auth
async def org_invoices(request: web.Request) -> web.Response:
    org_id = int(request.match_info["id"])
    tenant = _get_tenant(request)
    user = _get_user(request)

    role = await tenant.check_user_role(org_id, user["user_id"])
    if not role:
        return _error("Access denied", CONST_403)

    invoices = await tenant.get_invoices(org_id)
    return _json_response({"invoices": invoices})


# ── Search ────────────────────────────────────────────────────────────


def _get_search(request: web.Request):
    from ghostly.core.search import SearchEngine
    db = _get_db(request)
    return SearchEngine(db)


@routes.get("/api/sites/{id}/search")
@require_auth
async def search_analytics(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    search_engine = _get_search(request)
    db = _get_db(request)
    user = _get_user(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    query = request.query.get("q", "")
    limit = _parse_limit(request)
    offset_raw = request.query.get("offset", "0")
    try:
        offset = max(0, int(offset_raw))
    except ValueError:
        offset = 0

    filters = {}
    for key in ("country", "device_type", "browser", "path"):
        val = request.query.get(key)
        if val:
            filters[key] = val

    date_from = request.query.get("from")
    date_to = request.query.get("to")
    if date_from:
        filters["start_date"] = date_from
    if date_to:
        filters["end_date"] = date_to

    results = await search_engine.search(
        site_id=site_id,
        query=query,
        filters=filters,
        limit=limit,
        offset=offset,
        user_id=user["user_id"],
    )
    return _json_response(results)


@routes.get("/api/sites/{id}/search/advanced")
@require_auth
async def advanced_search(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    search_engine = _get_search(request)
    db = _get_db(request)
    user = _get_user(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    results = await search_engine.advanced_search(
        site_id=site_id,
        query=request.query.get("q", ""),
        date_from=request.query.get("from"),
        date_to=request.query.get("to"),
        country=request.query.get("country"),
        device_type=request.query.get("device_type"),
        browser=request.query.get("browser"),
        referrer=request.query.get("referrer"),
        page_pattern=request.query.get("page"),
        event_name=request.query.get("event"),
        sort_by=request.query.get("sort_by", "relevance"),
        sort_order=request.query.get("sort_order", "desc"),
        limit=_parse_limit(request),
        user_id=user["user_id"],
    )
    return _json_response(results)


@routes.get("/api/sites/{id}/search/autocomplete")
@require_auth
async def search_autocomplete(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    search_engine = _get_search(request)
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    prefix = request.query.get("q", "")
    limit = _parse_limit(request, default=10)

    suggestions = await search_engine.autocomplete(site_id, prefix, limit)
    return _json_response({"suggestions": suggestions})


@routes.get("/api/sites/{id}/search/popular")
@require_auth
async def popular_searches(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    search_engine = _get_search(request)
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    popular = await search_engine.get_popular_searches(site_id, days=days)
    return _json_response({"popular_searches": popular})


@routes.get("/api/auth/search-history")
@require_auth
async def search_history(request: web.Request) -> web.Response:
    search_engine = _get_search(request)
    user = _get_user(request)
    limit = _parse_limit(request, default=CONST_20)

    history = await search_engine.get_search_history(user["user_id"], limit)
    return _json_response({"history": history})


# ── Scheduler ─────────────────────────────────────────────────────────


def _get_scheduler(request: web.Request):
    from ghostly.core.scheduler import TaskScheduler
    db = _get_db(request)
    return TaskScheduler(db)


@routes.get("/api/scheduler/tasks")
@require_role("admin")
async def list_scheduler_tasks(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    tasks = scheduler.get_all_tasks()
    return _json_response({"tasks": tasks})


@routes.get("/api/scheduler/tasks/{name}")
@require_role("admin")
async def get_scheduler_task(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    name = request.match_info["name"]
    task = scheduler.get_task_status(name)
    if not task:
        return _error("Task not found", status=CONST_404)
    return _json_response(task)


@routes.post("/api/scheduler/tasks/{name}/enable")
@require_role("admin")
async def enable_scheduler_task(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    name = request.match_info["name"]
    enabled = await scheduler.enable_task(name)
    if not enabled:
        return _error("Task not found", status=CONST_404)
    return _json_response({"ok": True, "enabled": True})


@routes.post("/api/scheduler/tasks/{name}/disable")
@require_role("admin")
async def disable_scheduler_task(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    name = request.match_info["name"]
    disabled = await scheduler.disable_task(name)
    if not disabled:
        return _error("Task not found", status=CONST_404)
    return _json_response({"ok": True, "enabled": False})


@routes.post("/api/scheduler/tasks/{name}/run")
@require_role("admin")
async def run_scheduler_task(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    name = request.match_info["name"]
    result = await scheduler.run_task_now(name)
    if "error" in result:
        return _error(result["error"], status=CONST_404)
    return _json_response(result)


@routes.get("/api/scheduler/jobs")
@require_role("admin")
async def list_scheduled_jobs(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    org_id_raw = request.query.get("org_id")
    org_id = int(org_id_raw) if org_id_raw else None
    jobs = await scheduler.get_scheduled_jobs(org_id)
    return _json_response({"jobs": jobs})


@routes.post("/api/scheduler/jobs")
@require_role("admin")
async def create_scheduled_job(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "").strip()
    cron_expr = body.get("cron_expr", "* * * * *")
    job_type = (body.get("job_type") or "").strip()
    config = body.get("config", {})
    org_id = body.get("org_id")

    if not name or not job_type:
        return _error("Missing 'name' or 'job_type'")

    job_id = await scheduler.add_scheduled_job(
        name=name,
        cron_expr=cron_expr,
        job_type=job_type,
        config=config,
        org_id=int(org_id) if org_id else None,
    )
    return _json_response({"id": job_id, "ok": True}, status=CONST_201)


@routes.put("/api/scheduler/jobs/{id}")
@require_role("admin")
async def update_scheduled_job(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    job_id = int(request.match_info["id"])

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    updates = {}
    for key in ("name", "cron_expr", "config", "is_active"):
        if key in body:
            updates[key] = body[key]

    updated = await scheduler.update_scheduled_job(job_id, **updates)
    if not updated:
        return _error("Job not found", status=CONST_404)
    return _json_response({"ok": True})


@routes.delete("/api/scheduler/jobs/{id}")
@require_role("admin")
async def delete_scheduled_job(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    job_id = int(request.match_info["id"])

    deleted = await scheduler.delete_scheduled_job(job_id)
    if not deleted:
        return _error("Job not found", status=CONST_404)
    return _json_response({"ok": True})


@routes.get("/api/scheduler/jobs/{id}/logs")
@require_role("admin")
async def get_job_logs(request: web.Request) -> web.Response:
    scheduler = _get_scheduler(request)
    job_id = int(request.match_info["id"])
    limit = _parse_limit(request, default=CONST_50)

    logs = await scheduler.get_job_logs(job_id, limit)
    return _json_response({"logs": logs})


# ── Realtime ──────────────────────────────────────────────────────────


def _get_realtime(request: web.Request):
    from ghostly.core.realtime import RealtimeManager
    db = _get_db(request)
    return RealtimeManager(db)


@routes.get("/api/sites/{id}/realtime/live")
@require_auth
async def realtime_live(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    realtime = _get_realtime(request)
    snapshot = realtime.get_realtime_snapshot(site_id)
    return _json_response(snapshot)


@routes.get("/api/sites/{id}/realtime/active-by-page")
@require_auth
async def realtime_active_by_page(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    realtime = _get_realtime(request)
    by_page = realtime.get_active_by_page(site_id)
    return _json_response({"active_by_page": by_page})


@routes.get("/api/sites/{id}/realtime/geo")
@require_auth
async def realtime_geographic(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    realtime = _get_realtime(request)
    geo = realtime.get_geographic_distribution(site_id)
    return _json_response(geo)


@routes.get("/api/sites/{id}/realtime/sources")
@require_auth
async def realtime_traffic_sources(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    realtime = _get_realtime(request)
    sources = realtime.get_traffic_sources(site_id)
    return _json_response(sources)


@routes.get("/api/sites/{id}/realtime/visitors")
@require_auth
async def realtime_visitor_list(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    realtime = _get_realtime(request)
    visitors = realtime.get_visitor_list(site_id)
    return _json_response({"visitors": visitors, "total": len(visitors)})


@routes.get("/api/sites/{id}/realtime/history")
@require_auth
async def realtime_history(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    minutes_raw = request.query.get("minutes", "60")
    try:
        minutes = max(1, min(int(minutes_raw), 1440))
    except ValueError:
        minutes = 60

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=CONST_404)

    realtime = _get_realtime(request)
    history = await realtime.get_historical_snapshots(site_id, minutes=minutes)
    return _json_response({"history": history, "minutes": minutes})

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import aiosqlite
from aiohttp import web

from ghostly.core.alerts import AlertManager
from ghostly.core.auth import AuthManager
from ghostly.core.database import Database
from ghostly.core.export import ExportManager
from ghostly.core.funnels import FunnelManager
from ghostly.core.goals import GoalManager

logger = logging.getLogger("ghostly.api")

routes = web.RouteTableDef()


def _json_response(data: Any, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=json.dumps)


def _error(message: str, status: int = 400) -> web.Response:
    return _json_response({"error": message}, status=status)


def _get_db(request: web.Request) -> Database:
    db = request.app.get("db")
    if db is None:
        raise web.HTTPInternalServerError(reason="Database not initialised")
    return db


def _parse_days(request: web.Request, default: int = 30) -> int:
    raw = request.query.get("days")
    if raw is None:
        return default
    try:
        days = int(raw)
        return max(1, min(days, 365))
    except ValueError:
        return default


def _parse_limit(request: web.Request, default: int = 50) -> int:
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


# ── Health ──────────────────────────────────────────────────────────────


@routes.get("/api/health")
async def health(request: web.Request) -> web.Response:
    db = _get_db(request)
    try:
        await db.db.execute("SELECT 1")
        return _json_response({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        return _json_response({"status": "error", "message": str(exc)}, status=503)


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
        return _error("Unknown site", status=404)

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
        return _json_response({"ok": True, "id": event_id}, status=201)

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
            "SELECT id, page_count FROM sessions WHERE id=?",
            (session_id,),
        )
        if existing:
            await db.db.execute(
                "UPDATE sessions SET page_count = page_count + 1 WHERE id=?",
                (session_id,),
            )
        else:
            await db.db.execute(
                """INSERT INTO sessions (id, site_id, visitor_id, started_at, page_count, referrer, browser, os, device_type, country)
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

    return _json_response({"ok": True, "id": pv_id}, status=201)


# ── Sites CRUD ──────────────────────────────────────────────────────────


@routes.get("/api/sites")
async def list_sites(request: web.Request) -> web.Response:
    db = _get_db(request)
    sites = await db._fetch_all(
        "SELECT id, domain, name, created_at, is_active FROM sites ORDER BY created_at DESC"
    )
    return _json_response({"sites": sites})


@routes.post("/api/sites")
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

    return _json_response(
        {"id": site_id, "domain": clean_domain, "name": name or clean_domain},
        status=201,
    )


@routes.delete("/api/sites/{id}")
async def delete_site(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)
    await db.db.execute("DELETE FROM sites WHERE id=?", (site_id,))
    await db.db.commit()
    return _json_response({"ok": True})


# ── Site Stats ──────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/stats")
async def site_stats(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id, domain, name FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    stats = await db.get_site_stats(site_id, days=days)
    visitor_stats = await db.get_visitor_stats(site_id, days=days)

    return _json_response({
        "site": dict(site),
        "period_days": days,
        **stats,
        **visitor_stats,
    })


@routes.get("/api/sites/{id}/pages")
async def site_pages(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    pages = await db.get_page_stats(site_id, days=days, limit=limit)
    return _json_response({"pages": pages, "period_days": days})


@routes.get("/api/sites/{id}/referrers")
async def site_referrers(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=30)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    referrers = await db.get_referrer_stats(site_id, days=days, limit=limit)
    return _json_response({"referrers": referrers, "period_days": days})


@routes.get("/api/sites/{id}/devices")
async def site_devices(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    devices = await db.get_device_stats(site_id, days=days)
    return _json_response({"devices": devices, "period_days": days})


@routes.get("/api/sites/{id}/browsers")
async def site_browsers(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    browsers = await db.get_browser_stats(site_id, days=days)
    return _json_response({"browsers": browsers, "period_days": days})


@routes.get("/api/sites/{id}/countries")
async def site_countries(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=50)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    countries = await db.get_country_stats(site_id, days=days, limit=limit)
    return _json_response({"countries": countries, "period_days": days})


@routes.get("/api/sites/{id}/daily")
async def site_daily(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    daily = await db.get_daily_stats(site_id, days=days)
    return _json_response({"daily": daily, "period_days": days})


@routes.get("/api/sites/{id}/hourly")
async def site_hourly(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request, default=7)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    hourly = await db.get_hourly_stats(site_id, days=days)
    return _json_response({"hourly": hourly, "period_days": days})


@routes.get("/api/sites/{id}/realtime")
async def site_realtime(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    now = datetime.now(timezone.utc)
    since_iso = now.isoformat()
    five_min_ago = (now - __import__("datetime").timedelta(minutes=5)).isoformat()

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
async def site_retention(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    retention = await db.get_retention(site_id, days=days)
    return _json_response({"retention": retention, "period_days": days})


# ── API Keys ────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/api-keys")
async def list_api_keys(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    auth = AuthManager(db)
    keys = await auth.get_api_keys(site_id)
    return _json_response({"api_keys": keys})


@routes.post("/api/sites/{id}/api-keys")
async def create_api_key(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "unnamed").strip()
    permissions = body.get("permissions", ["read"])
    rate_limit = body.get("rate_limit", 1000)
    expires_in_days = body.get("expires_in_days")

    auth = AuthManager(db)
    key_data = await auth.create_api_key(
        site_id=site_id,
        name=name,
        permissions=permissions,
        rate_limit=rate_limit,
        expires_in_days=expires_in_days,
    )
    return _json_response(key_data, status=201)


@routes.delete("/api/api-keys/{id}")
async def delete_api_key(request: web.Request) -> web.Response:
    key_id = int(request.match_info["id"])
    db = _get_db(request)

    auth = AuthManager(db)
    deleted = await auth.revoke_api_key(key_id)
    if not deleted:
        return _error("API key not found", status=404)
    return _json_response({"ok": True})


@routes.get("/api/api-keys/{id}")
async def get_api_key(request: web.Request) -> web.Response:
    key_id = int(request.match_info["id"])
    db = _get_db(request)

    auth = AuthManager(db)
    key = await auth.get_api_key(key_id)
    if not key:
        return _error("API key not found", status=404)
    return _json_response(key)


# ── Alerts ──────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/alerts")
async def list_alerts(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    alert_mgr = AlertManager(db)
    alerts = await alert_mgr.get_alerts(site_id)
    return _json_response({"alerts": alerts})


@routes.post("/api/sites/{id}/alerts")
async def create_alert(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    name = (body.get("name") or "").strip()
    alert_type = (body.get("alert_type") or "").strip()
    threshold = body.get("threshold", 0)
    window_minutes = body.get("window_minutes", 5)
    cooldown_minutes = body.get("cooldown_minutes", 30)
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

    return _json_response(alert, status=201)


@routes.get("/api/alerts/{id}")
async def get_alert(request: web.Request) -> web.Response:
    alert_id = int(request.match_info["id"])
    db = _get_db(request)

    alert_mgr = AlertManager(db)
    alert = await alert_mgr.get_alert(alert_id)
    if not alert:
        return _error("Alert not found", status=404)
    return _json_response(alert)


@routes.patch("/api/alerts/{id}")
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
        return _error("Alert not found", status=404)

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
async def delete_alert(request: web.Request) -> web.Response:
    alert_id = int(request.match_info["id"])
    db = _get_db(request)

    alert_mgr = AlertManager(db)
    deleted = await alert_mgr.delete_alert(alert_id)
    if not deleted:
        return _error("Alert not found", status=404)
    return _json_response({"ok": True})


@routes.get("/api/sites/{id}/alerts/history")
async def alert_history(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    limit = _parse_limit(request, default=50)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    alert_mgr = AlertManager(db)
    history = await alert_mgr.get_alert_history(site_id, limit=limit)
    return _json_response({"history": history})


# ── Funnels ─────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/funnels")
async def list_funnels(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    funnel_mgr = FunnelManager(db)
    funnels = await funnel_mgr.get_funnels(site_id)
    return _json_response({"funnels": funnels})


@routes.post("/api/sites/{id}/funnels")
async def create_funnel(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

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
    return _json_response(funnel, status=201)


@routes.get("/api/funnels/{id}")
async def get_funnel(request: web.Request) -> web.Response:
    funnel_id = int(request.match_info["id"])
    db = _get_db(request)

    funnel_mgr = FunnelManager(db)
    funnel = await funnel_mgr.get_funnel(funnel_id)
    if not funnel:
        return _error("Funnel not found", status=404)
    return _json_response(funnel)


@routes.get("/api/funnels/{id}/stats")
async def funnel_stats(request: web.Request) -> web.Response:
    funnel_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    funnel_mgr = FunnelManager(db)
    try:
        stats = await funnel_mgr.get_funnel_stats(funnel_id, days=days)
    except ValueError as exc:
        return _error(str(exc), status=404)
    return _json_response(stats)


@routes.delete("/api/funnels/{id}")
async def delete_funnel(request: web.Request) -> web.Response:
    funnel_id = int(request.match_info["id"])
    db = _get_db(request)

    funnel_mgr = FunnelManager(db)
    deleted = await funnel_mgr.delete_funnel(funnel_id)
    if not deleted:
        return _error("Funnel not found", status=404)
    return _json_response({"ok": True})


# ── Goals ───────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/goals")
async def list_goals(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    goal_mgr = GoalManager(db)
    goals = await goal_mgr.get_goals(site_id)
    return _json_response({"goals": goals})


@routes.post("/api/sites/{id}/goals")
async def create_goal(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

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

    return _json_response(goal, status=201)


@routes.get("/api/goals/{id}")
async def get_goal(request: web.Request) -> web.Response:
    goal_id = int(request.match_info["id"])
    db = _get_db(request)

    goal_mgr = GoalManager(db)
    goal = await goal_mgr.get_goal(goal_id)
    if not goal:
        return _error("Goal not found", status=404)
    return _json_response(goal)


@routes.get("/api/goals/{id}/stats")
async def goal_stats(request: web.Request) -> web.Response:
    goal_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    goal_mgr = GoalManager(db)
    try:
        stats = await goal_mgr.get_goal_stats(goal_id, days=days)
    except ValueError as exc:
        return _error(str(exc), status=404)
    return _json_response(stats)


@routes.delete("/api/goals/{id}")
async def delete_goal(request: web.Request) -> web.Response:
    goal_id = int(request.match_info["id"])
    db = _get_db(request)

    goal_mgr = GoalManager(db)
    deleted = await goal_mgr.delete_goal(goal_id)
    if not deleted:
        return _error("Goal not found", status=404)
    return _json_response({"ok": True})


# ── Export ──────────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/export")
async def export_data(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    format = request.query.get("format", "json")
    start_date = request.query.get("start_date")
    end_date = request.query.get("end_date")
    data_types_raw = request.query.get("data_types", "pageviews,visitors,sessions,events")

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

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
        return _error(str(exc), status=404)

    await export_mgr.log_export(site_id, format, data_types)

    return web.Response(
        text=result["content"],
        content_type=result["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{result["filename"]}"',
        },
    )


@routes.get("/api/sites/{id}/export/history")
async def export_history(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    export_mgr = ExportManager(db)
    history = await export_mgr.get_export_history(site_id)
    return _json_response({"history": history})


# ── Dashboard ───────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/dashboard")
async def site_dashboard(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id, domain, name FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

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
async def list_webhooks(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    webhooks = await db.get_webhooks(site_id)
    return _json_response({"webhooks": webhooks})


@routes.post("/api/sites/{id}/webhooks")
async def create_webhook(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

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

    return _json_response({"id": webhook_id, "ok": True}, status=201)


@routes.delete("/api/webhooks/{id}")
async def delete_webhook(request: web.Request) -> web.Response:
    webhook_id = int(request.match_info["id"])
    db = _get_db(request)

    deleted = await db.delete_webhook(webhook_id)
    if not deleted:
        return _error("Webhook not found", status=404)
    return _json_response({"ok": True})

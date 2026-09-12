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

from ghostly.core.ab_test import ABTestManager
from ghostly.core.alerts import AlertManager
from ghostly.core.auth import AuthManager
from ghostly.core.database import Database
from ghostly.core.export import ExportManager
from ghostly.core.funnels import FunnelManager
from ghostly.core.geomap import GeoMapCollector
from ghostly.core.goals import GoalManager
from ghostly.core.retention import RetentionAnalyzer

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


# ── Email Reports ───────────────────────────────────────────────────────


@routes.get("/api/email/config")
async def get_email_config(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    db = _get_db(request)
    reporter = EmailReporter(db)
    await reporter.load_config()
    return _json_response({"config": reporter.get_config()})


@routes.post("/api/email/config")
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
    result = await reporter.send_report(int(site_id), recipients, days=7)
    return _json_response(result)


@routes.get("/api/sites/{id}/email/schedules")
async def list_email_schedules(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    reporter = EmailReporter(db)
    schedules = await reporter.get_schedules()
    site_schedules = [s for s in schedules if s.get("site_id") == site_id]
    return _json_response({"schedules": site_schedules})


@routes.post("/api/sites/{id}/email/schedules")
async def create_email_schedule(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    recipients = body.get("recipients", [])
    cron_expr = body.get("cron_expr", "0 8 * * 1")
    days = body.get("days", 7)

    if not recipients:
        return _error("Missing 'recipients' list")

    reporter = EmailReporter(db)
    try:
        schedule = await reporter.create_schedule(site_id, recipients, cron_expr, days)
    except ValueError as exc:
        return _error(str(exc))

    return _json_response(schedule, status=201)


@routes.delete("/api/email/schedules/{id}")
async def delete_email_schedule(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    schedule_id = int(request.match_info["id"])
    db = _get_db(request)
    reporter = EmailReporter(db)
    deleted = await reporter.delete_schedule(schedule_id)
    if not deleted:
        return _error("Schedule not found", status=404)
    return _json_response({"ok": True})


@routes.post("/api/sites/{id}/email/send")
async def send_report_now(request: web.Request) -> web.Response:
    from ghostly.core.email import EmailReporter
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _error("Invalid JSON body")

    recipients = body.get("recipients", [])
    days = body.get("days", 7)

    if not recipients:
        return _error("Missing 'recipients' list")

    reporter = EmailReporter(db)
    await reporter.load_config()
    result = await reporter.send_report(site_id, recipients, days=days)
    return _json_response(result)


# ── Webhook Management ──────────────────────────────────────────────────


@routes.get("/api/sites/{id}/webhooks/history")
async def webhook_history(request: web.Request) -> web.Response:
    from ghostly.core.webhooks import WebhookManager
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    mgr = WebhookManager(db)
    history = await mgr.get_delivery_history(site_id)
    return _json_response({"history": history})


@routes.post("/api/webhooks/{id}/test")
async def test_webhook(request: web.Request) -> web.Response:
    from ghostly.core.webhooks import WebhookManager
    webhook_id = int(request.match_info["id"])
    db = _get_db(request)
    mgr = WebhookManager(db)

    try:
        result = await mgr.test_webhook(webhook_id)
    except ValueError as exc:
        return _error(str(exc), status=404)

    return _json_response(result)


# ── Heatmap ─────────────────────────────────────────────────────────────


@routes.post("/api/sites/{id}/heatmap/click")
async def record_heatmap_click(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

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
    return _json_response({"ok": True, "id": click_id}, status=201)


@routes.get("/api/sites/{id}/heatmap/grid")
async def heatmap_grid(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    page_url = request.query.get("page_url")
    days = _parse_days(request)

    collector = HeatmapCollector(db)
    data = await collector.generate_grid_data(site_id, page_url=page_url, days=days)
    return _json_response(data)


@routes.get("/api/sites/{id}/heatmap/sections")
async def heatmap_sections(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    page_url = request.query.get("page_url")
    days = _parse_days(request)

    collector = HeatmapCollector(db)
    data = await collector.generate_section_data(site_id, page_url=page_url, days=days)
    return _json_response(data)


@routes.get("/api/sites/{id}/heatmap/elements")
async def heatmap_elements(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    page_url = request.query.get("page_url")
    days = _parse_days(request)

    collector = HeatmapCollector(db)
    elements = await collector.get_click_element_stats(site_id, page_url=page_url, days=days)
    return _json_response({"elements": elements})


@routes.get("/api/sites/{id}/heatmap/pages")
async def heatmap_pages(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    days = _parse_days(request)

    collector = HeatmapCollector(db)
    pages = await collector.get_page_click_counts(site_id, days=days)
    return _json_response({"pages": pages})


@routes.get("/api/sites/{id}/heatmap/clicks")
async def heatmap_clicks(request: web.Request) -> web.Response:
    from ghostly.core.heatmap import HeatmapCollector
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    page_url = request.query.get("page_url")
    days = _parse_days(request)

    collector = HeatmapCollector(db)
    clicks = await collector.get_clicks(site_id, page_url=page_url, days=days)
    return _json_response({"clicks": clicks, "total": len(clicks)})


# ── Themes ──────────────────────────────────────────────────────────────


@routes.get("/api/themes")
async def list_themes(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    db = _get_db(request)
    mgr = ThemeManager(db)
    themes = await mgr.get_themes()
    return _json_response({"themes": themes})


@routes.get("/api/themes/{id}")
async def get_theme(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    theme_id = request.match_info["id"]
    db = _get_db(request)
    mgr = ThemeManager(db)
    theme = await mgr.get_theme(theme_id)
    if not theme:
        return _error("Theme not found", status=404)
    return _json_response({"theme": theme})


@routes.post("/api/themes")
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

    return _json_response({"id": theme_id, "theme": theme}, status=201)


@routes.delete("/api/themes/{id}")
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
        return _error("Theme not found", status=404)
    return _json_response({"ok": True})


@routes.get("/api/themes/{id}/css")
async def get_theme_css(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    theme_id = request.match_info["id"]
    db = _get_db(request)
    mgr = ThemeManager(db)
    css = await mgr.get_theme_css(theme_id)
    return web.Response(text=css, content_type="text/css")


@routes.get("/api/users/{id}/theme")
async def get_user_theme(request: web.Request) -> web.Response:
    from ghostly.core.themes import ThemeManager
    user_id = request.match_info["id"]
    db = _get_db(request)
    mgr = ThemeManager(db)
    theme_id = await mgr.get_user_theme(user_id)
    return _json_response({"theme_id": theme_id or "dark"})


@routes.post("/api/users/{id}/theme")
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
async def list_plugins(request: web.Request) -> web.Response:
    from ghostly.core.plugins import PluginManager
    db = _get_db(request)
    mgr = PluginManager(db)
    plugins = mgr.list_plugins()
    hooks = mgr.get_hook_count()
    return _json_response({"plugins": plugins, "hooks": hooks})


@routes.post("/api/plugins/reload")
async def reload_plugins(request: web.Request) -> web.Response:
    from ghostly.core.plugins import PluginManager
    db = _get_db(request)
    mgr = PluginManager(db)
    await mgr.unload_all()
    count = await mgr.load_all_plugins()
    return _json_response({"ok": True, "loaded": count})


@routes.get("/api/plugins/{name}")
async def get_plugin(request: web.Request) -> web.Response:
    from ghostly.core.plugins import PluginManager
    name = request.match_info["name"]
    db = _get_db(request)
    mgr = PluginManager(db)
    plugin = mgr.get_plugin(name)
    if not plugin:
        return _error("Plugin not found", status=404)
    return _json_response({"plugin": plugin.to_dict()})


# ── Backup & Restore ────────────────────────────────────────────────────


@routes.get("/api/backups")
async def list_backups(request: web.Request) -> web.Response:
    from ghostly.core.backup import BackupManager
    db = _get_db(request)
    mgr = BackupManager(db)
    backups = await mgr.list_backups()
    return _json_response({"backups": backups})


@routes.post("/api/backups")
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
    return _json_response(result, status=201)


@routes.post("/api/backups/restore")
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
        return _error(str(exc), status=404)

    return _json_response(result)


@routes.delete("/api/backups/{filename}")
async def delete_backup(request: web.Request) -> web.Response:
    from ghostly.core.backup import BackupManager
    filename = request.match_info["filename"]
    db = _get_db(request)
    mgr = BackupManager(db)
    deleted = await mgr.delete_backup(filename)
    if not deleted:
        return _error("Backup not found", status=404)
    return _json_response({"ok": True})


@routes.post("/api/backups/prune")
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
        return _error("Site not found", status=404)

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
    return _json_response({"ok": True, "id": location_id}, status=201)


@routes.get("/api/sites/{id}/geomap/countries")
async def geomap_countries(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    collector = GeoMapCollector(db)
    countries = await collector.get_country_stats(site_id, days=days)
    return _json_response({"countries": countries, "period_days": days})


@routes.get("/api/sites/{id}/geomap/cities")
async def geomap_cities(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=100)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    collector = GeoMapCollector(db)
    cities = await collector.get_city_stats(site_id, days=days, limit=limit)
    return _json_response({"cities": cities, "period_days": days})


@routes.get("/api/sites/{id}/geomap/top-countries")
async def geomap_top_countries(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=10)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    collector = GeoMapCollector(db)
    countries = await collector.get_top_countries(site_id, days=days, limit=limit)
    return _json_response({"top_countries": countries, "period_days": days})


@routes.get("/api/sites/{id}/geomap/top-cities")
async def geomap_top_cities(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    limit = _parse_limit(request, default=20)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    collector = GeoMapCollector(db)
    cities = await collector.get_top_cities(site_id, days=days, limit=limit)
    return _json_response({"top_cities": cities, "period_days": days})


@routes.get("/api/sites/{id}/geomap/geojson")
async def geomap_geojson(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    collector = GeoMapCollector(db)
    geojson = await collector.generate_geojson(site_id, days=days)
    return _json_response(geojson)


@routes.get("/api/sites/{id}/geomap/country-geojson")
async def geomap_country_geojson(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    collector = GeoMapCollector(db)
    geojson = await collector.generate_country_geojson(site_id, days=days)
    return _json_response(geojson)


@routes.get("/api/sites/{id}/geomap/distribution")
async def geomap_distribution(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    collector = GeoMapCollector(db)
    distribution = await collector.get_visitor_country_distribution(site_id, days=days)
    return _json_response(distribution)


@routes.get("/api/sites/{id}/geomap/summary")
async def geomap_summary(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    collector = GeoMapCollector(db)
    summary = await collector.get_geo_summary(site_id, days=days)
    return _json_response(summary)


# ── Retention Analysis ──────────────────────────────────────────────────


@routes.get("/api/sites/{id}/retention/daily")
async def retention_daily(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    analyzer = RetentionAnalyzer(db)
    retention = await analyzer.get_daily_retention(site_id, days=days)
    return _json_response({"retention": retention, "period_days": days, "group_by": "day"})


@routes.get("/api/sites/{id}/retention/weekly")
async def retention_weekly(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    analyzer = RetentionAnalyzer(db)
    retention = await analyzer.get_weekly_retention(site_id)
    return _json_response({"retention": retention, "group_by": "week"})


@routes.get("/api/sites/{id}/retention/monthly")
async def retention_monthly(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    analyzer = RetentionAnalyzer(db)
    retention = await analyzer.get_monthly_retention(site_id)
    return _json_response({"retention": retention, "group_by": "month"})


@routes.get("/api/sites/{id}/retention/cohort")
async def retention_cohort(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request, default=90)
    group_by = request.query.get("group_by", "week")

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    analyzer = RetentionAnalyzer(db)
    cohort = await analyzer.get_cohort_analysis(site_id, days=days, group_by=group_by)
    return _json_response(cohort)


@routes.get("/api/sites/{id}/retention/churn")
async def retention_churn(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)
    inactive_days = 30
    raw = request.query.get("inactive_days")
    if raw:
        try:
            inactive_days = max(1, min(int(raw), 365))
        except ValueError:
            pass

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    analyzer = RetentionAnalyzer(db)
    churn = await analyzer.get_churn_rate(site_id, days=days, inactive_days=inactive_days)
    return _json_response(churn)


@routes.get("/api/sites/{id}/retention/return-visitors")
async def retention_return_visitors(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    analyzer = RetentionAnalyzer(db)
    stats = await analyzer.get_return_visitor_stats(site_id, days=days)
    return _json_response(stats)


@routes.get("/api/sites/{id}/retention/summary")
async def retention_summary(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    analyzer = RetentionAnalyzer(db)
    summary = await analyzer.get_retention_summary(site_id, days=days)
    return _json_response(summary)


# ── A/B Testing ────────────────────────────────────────────────────────


@routes.get("/api/sites/{id}/experiments")
async def list_experiments(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    mgr = ABTestManager(db)
    experiments = await mgr.get_experiments(site_id)
    return _json_response({"experiments": experiments})


@routes.post("/api/sites/{id}/experiments")
async def create_experiment(request: web.Request) -> web.Response:
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

    return _json_response(experiment, status=201)


@routes.get("/api/experiments/{id}")
async def get_experiment(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    mgr = ABTestManager(db)
    experiment = await mgr.get_experiment(experiment_id)
    if not experiment:
        return _error("Experiment not found", status=404)
    return _json_response(experiment)


@routes.post("/api/experiments/{id}/start")
async def start_experiment(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    mgr = ABTestManager(db)
    started = await mgr.start_experiment(experiment_id)
    if not started:
        return _error("Experiment not found or already started", status=404)
    return _json_response({"ok": True, "status": "running"})


@routes.post("/api/experiments/{id}/stop")
async def stop_experiment(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    mgr = ABTestManager(db)
    stopped = await mgr.stop_experiment(experiment_id)
    if not stopped:
        return _error("Experiment not found or not running", status=404)
    return _json_response({"ok": True, "status": "completed"})


@routes.delete("/api/experiments/{id}")
async def delete_experiment(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)

    mgr = ABTestManager(db)
    deleted = await mgr.delete_experiment(experiment_id)
    if not deleted:
        return _error("Experiment not found", status=404)
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
        return _error("Experiment not found or not running", status=404)
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
        return _error("Visitor not assigned to this experiment", status=404)
    return _json_response(conversion, status=201)


@routes.get("/api/experiments/{id}/stats")
async def experiment_stats(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    mgr = ABTestManager(db)
    stats = await mgr.get_experiment_stats(experiment_id, days=days)
    if not stats:
        return _error("Experiment not found", status=404)
    return _json_response(stats)


@routes.get("/api/experiments/{id}/significance")
async def experiment_significance(request: web.Request) -> web.Response:
    experiment_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    mgr = ABTestManager(db)
    significance = await mgr.get_statistical_significance(experiment_id, days=days)
    return _json_response(significance)


@routes.get("/api/sites/{id}/experiments/summary")
async def experiments_summary(request: web.Request) -> web.Response:
    site_id = int(request.match_info["id"])
    db = _get_db(request)
    days = _parse_days(request)

    site = await db._fetch_one("SELECT id FROM sites WHERE id=?", (site_id,))
    if not site:
        return _error("Site not found", status=404)

    mgr = ABTestManager(db)
    summary = await mgr.get_experiment_summary(site_id, days=days)
    return _json_response(summary)

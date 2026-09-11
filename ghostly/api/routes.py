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

from ghostly.core.database import Database

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

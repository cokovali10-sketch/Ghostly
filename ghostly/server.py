from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

from aiohttp import web

from ghostly.api.routes import routes as api_routes
from ghostly.core.auth import AuthManager
from ghostly.core.database import Database
from ghostly.core.plugins import PluginManager
from ghostly.core.themes import ThemeManager
from ghostly.core.websocket import WebSocketManager, WebSocketHandler

logger = logging.getLogger("ghostly")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

DEFAULT_PORT = 8080
DEFAULT_HOST = "0.0.0.0"


# ── CORS middleware ──────────────────────────────────────────────────────


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            response = exc

    origin = request.headers.get("Origin", "*")
    allowed_origins = request.app.get("cors_origins", ["*"])
    if allowed_origins != ["*"] and origin not in allowed_origins:
        origin = allowed_origins[0] if allowed_origins else ""

    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, X-API-Key"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response


# ── Security headers middleware ──────────────────────────────────────────


@web.middleware
async def security_middleware(request: web.Request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    response.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate")
    response.headers.setdefault("Pragma", "no-cache")
    return response


# ── Request logging middleware ───────────────────────────────────────────


@web.middleware
async def logging_middleware(request: web.Request, handler):
    method = request.method
    path = request.path
    start = time.monotonic()

    skip_logging = path.startswith("/api/track") or path == "/health" or path.startswith("/static/")
    if not skip_logging:
        logger.info("%s %s", method, path)

    try:
        response = await handler(request)
    except web.HTTPException:
        raise
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        logger.error("Unhandled error on %s %s (%.1fms): %s", method, path, elapsed, exc)
        raise

    elapsed = (time.monotonic() - start) * 1000
    if not skip_logging:
        logger.info("%s %s -> %d (%.1fms)", method, path, response.status, elapsed)

    return response


# ── Rate limiting middleware ─────────────────────────────────────────────


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    if request.path.startswith("/api/track") or request.path == "/health":
        return await handler(request)

    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote or "0.0.0.0"

    auth: AuthManager | None = request.app.get("auth")
    if auth:
        allowed = await auth.check_ip_rate_limit(ip, limit=200)
        if not allowed:
            logger.warning("Rate limit exceeded for IP %s", ip)
            return web.json_response(
                {"error": "Rate limit exceeded. Please try again later."},
                status=429,
                headers={"Retry-After": "60"},
            )

    return await handler(request)


# ── Error handling middleware ────────────────────────────────────────────


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPException as exc:
        return web.json_response(
            {"error": exc.reason or "Internal Server Error"},
            status=exc.status,
        )
    except Exception as exc:
        logger.error("Unhandled error on %s %s: %s", request.method, request.path, exc)
        return web.json_response(
            {"error": "Internal server error"},
            status=500,
        )


# ── Tenant middleware ─────────────────────────────────────────────────


@web.middleware
async def tenant_middleware(request: web.Request, handler):
    host = request.headers.get("Host", "")
    if host and "." in host:
        try:
            from ghostly.core.multi_tenant import TenantManager
            db: Database | None = request.app.get("db")
            if db:
                tenant_mgr = TenantManager(db)
                org = await tenant_mgr.resolve_subdomain(host)
                if org:
                    request["organization"] = org
                    request["org_id"] = org["id"]
        except Exception:
            pass
    return await handler(request)


# ── Theme middleware ─────────────────────────────────────────────────────


@web.middleware
async def theme_middleware(request: web.Request, handler):
    response = await handler(request)
    if request.path.startswith("/api/") and hasattr(response, "content_type"):
        ct = response.content_type or ""
        if "html" in ct:
            theme_id = request.query.get("theme", "")
            if not theme_id:
                theme_id = request.cookies.get("ghostly_theme", "")
            if theme_id and request.app.get("db"):
                try:
                    mgr = ThemeManager(request.app["db"])
                    css = await mgr.get_theme_css(theme_id)
                    if css and css != ":root {}":
                        theme_tag = f'<style id="ghostly-theme">{css}</style>'
                        if isinstance(response, web.Response) and response.body:
                            body = response.body.decode("utf-8") if isinstance(response.body, bytes) else str(response.body)
                            body = body.replace("</head>", f"{theme_tag}\n</head>")
                            response.body = body.encode("utf-8")
                            response.content_length = len(response.body)
                except Exception:
                    pass
    return response


# ── Template rendering ──────────────────────────────────────────────────


def render_template(template_name: str, context: dict | None = None) -> str:
    template_path = TEMPLATES_DIR / template_name
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    html = template_path.read_text(encoding="utf-8")
    if context:
        for key, value in context.items():
            html = html.replace("{{ " + key + " }}", str(value))
    return html


# ── Dashboard handlers ──────────────────────────────────────────────────


async def dashboard_index(request: web.Request) -> web.Response:
    try:
        html = render_template("index.html")
        return web.Response(text=html, content_type="text/html")
    except FileNotFoundError:
        return web.Response(text="<h1>Dashboard not configured</h1>", status=501, content_type="text/html")


async def dashboard_site(request: web.Request) -> web.Response:
    site_id = request.match_info.get("id", "")
    try:
        html = render_template("site.html", {"site_id": site_id})
        return web.Response(text=html, content_type="text/html")
    except FileNotFoundError:
        return web.Response(text="<h1>Site dashboard not configured</h1>", status=501, content_type="text/html")


# ── Health check handler ────────────────────────────────────────────────


async def health_check(request: web.Request) -> web.Response:
    db: Database = request.app["db"]
    try:
        await db.db.execute("SELECT 1")
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    auth: AuthManager | None = request.app.get("auth")
    auth_status = "ready" if auth else "not_configured"

    ws_manager: WebSocketManager = request.app.get("ws_manager")
    ws_status = "running" if ws_manager else "not_configured"

    scheduler = request.app.get("scheduler")
    scheduler_status = "running" if scheduler else "not_configured"

    all_ok = db_status == "connected" and auth_status == "ready"
    status_code = 200 if all_ok else 503

    return web.json_response(
        {
            "status": "ok" if all_ok else "degraded",
            "service": "ghostly",
            "version": "6.0.0",
            "components": {
                "database": db_status,
                "auth": auth_status,
                "websocket": ws_status,
                "scheduler": scheduler_status,
            },
            "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        },
        status=status_code,
    )


# ── Application factory ─────────────────────────────────────────────────


async def on_startup(app: web.Application) -> None:
    db: Database = app["db"]
    await db.connect()
    await db.init_db()
    logger.info("Database connected and initialised at %s", db.db_path)

    secret_key = app.get("secret_key")
    auth = AuthManager(db, secret_key=secret_key)
    app["auth"] = auth
    logger.info("Auth manager initialised")

    ws_manager: WebSocketManager = app["ws_manager"]
    await ws_manager.start()
    logger.info("WebSocket manager started")

    plugin_mgr: PluginManager = app["plugin_manager"]
    loaded = await plugin_mgr.load_all_plugins()
    logger.info("Plugin manager ready (%d plugins loaded)", loaded)

    from ghostly.core.scheduler import (
        TaskScheduler, ReportGenerator, DataAggregator, DataCleanup, EmailReportSender,
    )
    scheduler = TaskScheduler(db)
    report_gen = ReportGenerator(db)
    aggregator = DataAggregator(db)
    cleanup = DataCleanup(db)
    email_sender = EmailReportSender(db)

    scheduler.register_task("data_cleanup", lambda: cleanup.run_full_cleanup(), "0 2 * * *")
    scheduler.register_task("daily_aggregation", lambda: _run_daily_aggregation(db, aggregator), "0 3 * * *")
    scheduler.register_task("email_reports", lambda: email_sender.send_scheduled_reports(), "0 8 * * 1")
    scheduler.register_task("snapshot_realtime", lambda: _run_realtime_snapshot(db), "*/5 * * * *")

    await scheduler.start()
    app["scheduler"] = scheduler
    app["report_generator"] = report_gen
    app["data_aggregator"] = aggregator
    app["data_cleanup"] = cleanup
    app["email_report_sender"] = email_sender
    logger.info("Background scheduler started with registered tasks")


async def _run_daily_aggregation(db: Database, aggregator) -> None:
    sites = await db._fetch_all("SELECT id FROM sites WHERE is_active=1")
    for site in sites:
        try:
            await aggregator.run_aggregation(site["id"])
        except Exception as exc:
            logger.warning("Aggregation failed for site %s: %s", site["id"], exc)


async def _run_realtime_snapshot(db: Database) -> None:
    from ghostly.core.realtime import RealtimeManager
    realtime = RealtimeManager(db)
    sites = await db._fetch_all("SELECT id FROM sites WHERE is_active=1")
    for site in sites:
        try:
            await realtime.persist_snapshot(site["id"])
        except Exception as exc:
            logger.warning("Realtime snapshot failed for site %s: %s", site["id"], exc)


async def on_cleanup(app: web.Application) -> None:
    scheduler = app.get("scheduler")
    if scheduler:
        await scheduler.stop()
        logger.info("Scheduler stopped")

    plugin_mgr: PluginManager = app["plugin_manager"]
    await plugin_mgr.unload_all()
    logger.info("Plugins unloaded")

    ws_manager: WebSocketManager = app["ws_manager"]
    await ws_manager.stop()
    logger.info("WebSocket manager stopped")

    db: Database = app["db"]
    await db.close()
    logger.info("Database connection closed")


def create_app(
    db_path: str | Path | None = None,
    cors_origins: list[str] | None = None,
    secret_key: str | None = None,
) -> web.Application:
    middlewares = [
        error_middleware,
        rate_limit_middleware,
        tenant_middleware,
        cors_middleware,
        security_middleware,
        logging_middleware,
        theme_middleware,
    ]

    app = web.Application(middlewares=middlewares)

    if db_path:
        app["db"] = Database(db_path)
    else:
        app["db"] = Database()

    app["cors_origins"] = cors_origins or ["*"]
    app["secret_key"] = secret_key

    ws_manager = WebSocketManager()
    app["ws_manager"] = ws_manager
    ws_handler = WebSocketHandler(ws_manager)

    plugin_manager = PluginManager(app["db"])
    app["plugin_manager"] = plugin_manager

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app.router.add_routes(api_routes)

    app.router.add_get("/", dashboard_index)
    app.router.add_get("/dashboard", dashboard_index)
    app.router.add_get("/dashboard/", dashboard_index)
    app.router.add_get("/dashboard/site/{id}", dashboard_site)
    app.router.add_get("/dashboard/site/{id}/", dashboard_site)

    app.router.add_get("/health", health_check)

    app.router.add_get("/ws/{site_id}", ws_handler.handle_connection)

    if STATIC_DIR.exists():
        app.router.add_static("/static/", STATIC_DIR, name="static", show_index=False)

    return app


# ── CLI entry point ─────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ghostly-server",
        description="Ghostly v6.0 – privacy-focused analytics server with multi-tenant support",
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--db", default=None,
        help="Path to SQLite database file (default: ghostly_data.db)",
    )
    parser.add_argument(
        "--secret-key", default=None,
        help="Secret key for JWT tokens (default: auto-generated)",
    )
    parser.add_argument(
        "--cors-origins", default="*",
        help="Comma-separated CORS origins (default: *)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    db_path = Path(args.db) if args.db else None
    cors_origins = [o.strip() for o in args.cors_origins.split(",")] if args.cors_origins else ["*"]

    app = create_app(
        db_path=db_path,
        cors_origins=cors_origins,
        secret_key=args.secret_key,
    )

    logger.info("Starting Ghostly server on %s:%s", args.host, args.port)

    try:
        web.run_app(
            app,
            host=args.host,
            port=args.port,
            print=lambda _: logger.info(
                "Server running at http://%s:%s", args.host, args.port
            ),
            shutdown_timeout=5.0,
        )
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully")
    finally:
        logger.info("Ghostly server stopped")


if __name__ == "__main__":
    main()

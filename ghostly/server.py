from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from aiohttp import web

from ghostly.api.routes import routes as api_routes
from ghostly.core.database import Database

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
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
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
    return response


# ── Request logging middleware ───────────────────────────────────────────


@web.middleware
async def logging_middleware(request: web.Request, handler):
    method = request.method
    path = request.path
    if path.startswith("/api/") and path != "/api/track":
        logger.info("%s %s", method, path)
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as exc:
        logger.error("Unhandled error on %s %s: %s", method, path, exc)
        raise


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


# ── Application factory ─────────────────────────────────────────────────


async def on_startup(app: web.Application) -> None:
    db: Database = app["db"]
    await db.connect()
    await db.init_db()
    logger.info("Database connected and initialised at %s", db.db_path)


async def on_cleanup(app: web.Application) -> None:
    db: Database = app["db"]
    await db.close()
    logger.info("Database connection closed")


def create_app(db_path: str | Path | None = None) -> web.Application:
    middlewares = [cors_middleware, security_middleware, logging_middleware]

    app = web.Application(middlewares=middlewares)

    if db_path:
        app["db"] = Database(db_path)
    else:
        app["db"] = Database()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app.router.add_routes(api_routes)

    app.router.add_get("/", dashboard_index)
    app.router.add_get("/dashboard", dashboard_index)
    app.router.add_get("/dashboard/", dashboard_index)
    app.router.add_get("/dashboard/site/{id}", dashboard_site)
    app.router.add_get("/dashboard/site/{id}/", dashboard_site)

    if STATIC_DIR.exists():
        app.router.add_static("/static/", STATIC_DIR, name="static", show_index=False)

    return app


# ── CLI entry point ─────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ghostly-server",
        description="Ghostly – privacy-focused analytics server",
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
    app = create_app(db_path=db_path)

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

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from .database import Database

logger = logging.getLogger("ghostly.plugins")

PLUGINS_DIR = Path(__file__).parent.parent.parent / "plugins"


class PluginAPI:
    """API exposed to plugins for interacting with Ghostly."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_site_stats(self, site_id: int, days: int = 30) -> dict[str, Any]:
        return await self.db.get_site_stats(site_id, days=days)

    async def get_page_stats(self, site_id: int, days: int = 30) -> list[dict[str, Any]]:
        return await self.db.get_page_stats(site_id, days=days)

    async def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return await self.db._fetch_all(sql, params)

    async def query_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        return await self.db._fetch_one(sql, params)

    async def log_event(
        self,
        site_id: int,
        name: str,
        meta: dict[str, Any] | None = None,
        visitor_id: str = "plugin",
        session_id: str = "plugin",
    ) -> int:
        return await self.db.insert_event(
            site_id=site_id,
            visitor_id=visitor_id,
            session_id=session_id,
            name=name,
            meta=meta,
        )


class PluginMeta:
    """Metadata about a loaded plugin."""

    def __init__(
        self,
        name: str,
        version: str,
        author: str,
        description: str,
        module: Any,
    ) -> None:
        self.name = name
        self.version = version
        self.author = author
        self.description = description
        self.module = module

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
        }


class PluginManager:
    """Loads, manages, and invokes hooks for Ghostly plugins."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.api = PluginAPI(db)
        self._plugins: dict[str, PluginMeta] = {}
        self._hooks: dict[str, list[Callable]] = {
            "on_pageview": [],
            "on_event": [],
            "on_report": [],
            "on_startup": [],
            "on_shutdown": [],
        }

    def get_plugins_dir(self) -> Path:
        return PLUGINS_DIR

    async def load_all_plugins(self) -> int:
        plugins_dir = self.get_plugins_dir()
        if not plugins_dir.exists():
            plugins_dir.mkdir(parents=True, exist_ok=True)
            logger.info("Created plugins directory: %s", plugins_dir)
            return 0

        count = 0
        for path in sorted(plugins_dir.iterdir()):
            if path.is_dir() and (path / "__init__.py").exists():
                if await self.load_plugin(path.name):
                    count += 1
            elif path.suffix == ".py" and path.stem != "__init__":
                if await self.load_plugin_file(path):
                    count += 1

        logger.info("Loaded %d plugin(s)", count)
        return count

    async def load_plugin(self, plugin_name: str) -> bool:
        plugins_dir = self.get_plugins_dir()
        plugin_path = plugins_dir / plugin_name
        if not plugin_path.is_dir():
            logger.warning("Plugin directory not found: %s", plugin_path)
            return False

        init_file = plugin_path / "__init__.py"
        if not init_file.exists():
            logger.warning("Plugin missing __init__.py: %s", plugin_path)
            return False

        return await self._load_module(plugin_name, init_file)

    async def load_plugin_file(self, file_path: Path) -> bool:
        stem = file_path.stem
        module_name = f"ghostly_plugin_{stem}"
        return await self._load_module(module_name, file_path)

    async def _load_module(self, module_name: str, file_path: Path) -> bool:
        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                logger.error("Cannot create module spec for %s", file_path)
                return False

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            meta = self._extract_meta(module, module_name)
            self._plugins[meta.name] = meta

            self._register_hooks(meta)
            self._call_hook("on_startup", meta)

            if hasattr(module, "setup"):
                try:
                    result = module.setup(self.api)
                    if hasattr(result, "__await__"):
                        await result
                except Exception as exc:
                    logger.error("Plugin '%s' setup failed: %s", meta.name, exc)
                    return False

            logger.info("Loaded plugin: %s v%s by %s", meta.name, meta.version, meta.author)
            return True

        except Exception as exc:
            logger.error("Failed to load plugin from %s: %s", file_path, exc)
            return False

    def _extract_meta(self, module: Any, fallback_name: str) -> PluginMeta:
        return PluginMeta(
            name=getattr(module, "PLUGIN_NAME", fallback_name),
            version=getattr(module, "PLUGIN_VERSION", "0.0.0"),
            author=getattr(module, "PLUGIN_AUTHOR", "Unknown"),
            description=getattr(module, "PLUGIN_DESCRIPTION", ""),
            module=module,
        )

    def _register_hooks(self, meta: PluginMeta) -> None:
        module = meta.module
        for hook_name in self._hooks:
            handler = getattr(module, hook_name, None)
            if callable(handler):
                self._hooks[hook_name].append(handler)

    def _call_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> list[Any]:
        results = []
        for handler in self._hooks.get(hook_name, []):
            try:
                result = handler(*args, **kwargs)
                if hasattr(result, "__await__"):
                    logger.warning("Async hook %s from %s not awaited", hook_name, handler)
                results.append(result)
            except Exception as exc:
                logger.error("Hook %s error in %s: %s", hook_name, handler, exc)
        return results

    async def fire_pageview(self, site_id: int, data: dict[str, Any]) -> None:
        for handler in self._hooks.get("on_pageview", []):
            try:
                result = handler(self.api, site_id, data)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.error("on_pageview hook error: %s", exc)

    async def fire_event(self, site_id: int, data: dict[str, Any]) -> None:
        for handler in self._hooks.get("on_event", []):
            try:
                result = handler(self.api, site_id, data)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.error("on_event hook error: %s", exc)

    async def fire_report(self, site_id: int, report_data: dict[str, Any]) -> None:
        for handler in self._hooks.get("on_report", []):
            try:
                result = handler(self.api, site_id, report_data)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.error("on_report hook error: %s", exc)

    async def unload_all(self) -> None:
        for name, meta in self._plugins.items():
            try:
                if hasattr(meta.module, "teardown"):
                    result = meta.module.teardown(self.api)
                    if hasattr(result, "__await__"):
                        await result
                self._call_hook("on_shutdown", meta)
                logger.info("Unloaded plugin: %s", name)
            except Exception as exc:
                logger.error("Error unloading plugin %s: %s", name, exc)

        self._plugins.clear()
        for hook_name in self._hooks:
            self._hooks[hook_name].clear()

    def list_plugins(self) -> list[dict[str, str]]:
        return [meta.to_dict() for meta in self._plugins.values()]

    def get_plugin(self, name: str) -> PluginMeta | None:
        return self._plugins.get(name)

    def get_hook_count(self) -> dict[str, int]:
        return {hook: len(handlers) for hook, handlers in self._hooks.items()}

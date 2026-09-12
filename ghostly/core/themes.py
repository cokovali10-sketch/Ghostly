from __future__ import annotations

import json
import logging
from typing import Any

from .database import Database

logger = logging.getLogger("ghostly.themes")

BUILTIN_THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "name": "Dark",
        "--bg-primary": "#0f0f23",
        "--bg-secondary": "#1a1a2e",
        "--bg-tertiary": "#16213e",
        "--bg-card": "#1e1e3f",
        "--text-primary": "#e2e8f0",
        "--text-secondary": "#94a3b8",
        "--text-muted": "#64748b",
        "--accent": "#6366f1",
        "--accent-hover": "#818cf8",
        "--border": "#334155",
        "--success": "#10b981",
        "--warning": "#f59e0b",
        "--danger": "#ef4444",
        "--info": "#3b82f6",
        "--chart-line": "#818cf8",
        "--chart-fill": "rgba(99,102,241,0.15)",
        "--sidebar-bg": "#0f0f23",
        "--sidebar-text": "#94a3b8",
        "--sidebar-active": "#6366f1",
    },
    "light": {
        "name": "Light",
        "--bg-primary": "#f8fafc",
        "--bg-secondary": "#ffffff",
        "--bg-tertiary": "#f1f5f9",
        "--bg-card": "#ffffff",
        "--text-primary": "#1e293b",
        "--text-secondary": "#475569",
        "--text-muted": "#94a3b8",
        "--accent": "#6366f1",
        "--accent-hover": "#4f46e5",
        "--border": "#e2e8f0",
        "--success": "#059669",
        "--warning": "#d97706",
        "--danger": "#dc2626",
        "--info": "#2563eb",
        "--chart-line": "#6366f1",
        "--chart-fill": "rgba(99,102,241,0.1)",
        "--sidebar-bg": "#1e1b4b",
        "--sidebar-text": "#c7d2fe",
        "--sidebar-active": "#818cf8",
    },
    "midnight": {
        "name": "Midnight",
        "--bg-primary": "#0a0a1a",
        "--bg-secondary": "#111127",
        "--bg-tertiary": "#1a1a3e",
        "--bg-card": "#15152b",
        "--text-primary": "#e0e7ff",
        "--text-secondary": "#a5b4fc",
        "--text-muted": "#6366f1",
        "--accent": "#a78bfa",
        "--accent-hover": "#c4b5fd",
        "--border": "#2e2e5e",
        "--success": "#34d399",
        "--warning": "#fbbf24",
        "--danger": "#f87171",
        "--info": "#60a5fa",
        "--chart-line": "#a78bfa",
        "--chart-fill": "rgba(167,139,250,0.12)",
        "--sidebar-bg": "#0a0a1a",
        "--sidebar-text": "#a5b4fc",
        "--sidebar-active": "#a78bfa",
    },
    "ocean": {
        "name": "Ocean",
        "--bg-primary": "#0c1929",
        "--bg-secondary": "#132e4a",
        "--bg-tertiary": "#1a3a5c",
        "--bg-card": "#15304d",
        "--text-primary": "#e0f2fe",
        "--text-secondary": "#7dd3fc",
        "--text-muted": "#38bdf8",
        "--accent": "#0ea5e9",
        "--accent-hover": "#38bdf8",
        "--border": "#1e4d7b",
        "--success": "#2dd4bf",
        "--warning": "#fcd34d",
        "--danger": "#fb7185",
        "--info": "#38bdf8",
        "--chart-line": "#38bdf8",
        "--chart-fill": "rgba(56,189,248,0.12)",
        "--sidebar-bg": "#0c1929",
        "--sidebar-text": "#7dd3fc",
        "--sidebar-active": "#0ea5e9",
    },
    "forest": {
        "name": "Forest",
        "--bg-primary": "#0f1a0f",
        "--bg-secondary": "#162616",
        "--bg-tertiary": "#1e3a1e",
        "--bg-card": "#1a2f1a",
        "--text-primary": "#dcfce7",
        "--text-secondary": "#86efac",
        "--text-muted": "#4ade80",
        "--accent": "#22c55e",
        "--accent-hover": "#4ade80",
        "--border": "#1a5c1a",
        "--success": "#4ade80",
        "--warning": "#fde047",
        "--danger": "#fb7185",
        "--info": "#6ee7b7",
        "--chart-line": "#4ade80",
        "--chart-fill": "rgba(74,222,128,0.12)",
        "--sidebar-bg": "#0f1a0f",
        "--sidebar-text": "#86efac",
        "--sidebar-active": "#22c55e",
    },
}


class ThemeManager:
    """Manages dashboard themes including built-in and custom themes."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def get_themes(self) -> dict[str, Any]:
        custom = await self._load_custom_themes()
        all_themes: dict[str, dict[str, str]] = {}
        for key, vars_ in BUILTIN_THEMES.items():
            all_themes[key] = vars_
        for key, vars_ in custom.items():
            all_themes[key] = vars_
        return all_themes

    async def get_theme(self, theme_id: str) -> dict[str, str] | None:
        if theme_id in BUILTIN_THEMES:
            return BUILTIN_THEMES[theme_id]
        custom = await self._load_custom_themes()
        return custom.get(theme_id)

    async def save_theme(self, theme_id: str, variables: dict[str, str]) -> dict[str, str]:
        if theme_id in BUILTIN_THEMES:
            raise ValueError(f"Cannot overwrite built-in theme '{theme_id}'")

        required = [
            "--bg-primary", "--bg-secondary", "--text-primary",
            "--text-secondary", "--accent", "--border",
        ]
        missing = [k for k in required if k not in variables]
        if missing:
            raise ValueError(f"Missing required CSS variables: {', '.join(missing)}")

        variables["name"] = variables.get("name", theme_id)

        custom = await self._load_custom_themes()
        custom[theme_id] = variables

        await self.db.db.execute(
            """INSERT INTO themes (id, variables) VALUES (?, ?)
               ON CONFLICT(id) DO UPDATE SET variables=excluded.variables""",
            (theme_id, json.dumps(variables)),
        )
        await self.db.db.commit()

        logger.info("Saved custom theme '%s'", theme_id)
        return variables

    async def delete_theme(self, theme_id: str) -> bool:
        if theme_id in BUILTIN_THEMES:
            raise ValueError(f"Cannot delete built-in theme '{theme_id}'")

        result = await self.db.db.execute("DELETE FROM themes WHERE id=?", (theme_id,))
        await self.db.db.commit()
        return result.rowcount > 0

    async def set_user_theme(self, user_id: str, theme_id: str) -> None:
        theme = await self.get_theme(theme_id)
        if not theme:
            raise ValueError(f"Theme '{theme_id}' not found")

        await self.db.db.execute(
            """INSERT INTO user_themes (user_id, theme_id) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET theme_id=excluded.theme_id""",
            (user_id, theme_id),
        )
        await self.db.db.commit()

    async def get_user_theme(self, user_id: str) -> str | None:
        row = await self.db._fetch_one(
            "SELECT theme_id FROM user_themes WHERE user_id=?",
            (user_id,),
        )
        return row["theme_id"] if row else None

    async def _load_custom_themes(self) -> dict[str, dict[str, str]]:
        rows = await self.db._fetch_all("SELECT id, variables FROM themes")
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            try:
                result[row["id"]] = json.loads(row["variables"])
            except (json.JSONDecodeError, TypeError):
                continue
        return result

    def generate_css(self, variables: dict[str, str]) -> str:
        lines = [":root {"]
        for key, value in variables.items():
            if key.startswith("--"):
                lines.append(f"  {key}: {value};")
        lines.append("}")
        return "\n".join(lines)

    async def get_theme_css(self, theme_id: str) -> str:
        theme = await self.get_theme(theme_id)
        if not theme:
            return ":root {}"
        return self.generate_css(theme)

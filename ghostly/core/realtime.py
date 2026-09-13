from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from ghostly.core.database import Database

logger = logging.getLogger("ghostly.realtime")


class RealtimeManager:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._visitors: dict[int, dict[str, Any]] = {}
        self._page_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._events: dict[int, list[dict[str, Any]]] = defaultdict(list)
        self._subscribers: dict[int, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._geo_data: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._source_data: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._lock = asyncio.Lock()
        self._max_events = 500
        self._cleanup_interval = 60
        self._last_cleanup = time.monotonic()

    async def track_visitor(self, site_id: int, visitor_id: str, page: str = "/", country: str = "", referrer: str = "") -> None:
        async with self._lock:
            now = time.time()
            if site_id not in self._visitors:
                self._visitors[site_id] = {}

            self._visitors[site_id][visitor_id] = {
                "visitor_id": visitor_id,
                "page": page,
                "country": country,
                "referrer": referrer,
                "last_seen": now,
                "entered_at": self._visitors[site_id].get(visitor_id, {}).get("entered_at", now),
            }

            self._page_counts[site_id][page] += 1

            if country:
                self._geo_data[site_id][country] += 1

            if referrer:
                source = self._extract_source(referrer)
                if source:
                    self._source_data[site_id][source] += 1

            event = {
                "type": "pageview",
                "visitor_id": visitor_id,
                "page": page,
                "country": country,
                "referrer": referrer,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._events[site_id].append(event)
            if len(self._events[site_id]) > self._max_events:
                self._events[site_id] = self._events[site_id][-self._max_events:]

            await self._broadcast(site_id, event)

        if time.monotonic() - self._last_cleanup > self._cleanup_interval:
            await self._cleanup_stale()

    async def track_event(self, site_id: int, event_name: str, visitor_id: str = "", meta: dict[str, Any] | None = None) -> None:
        event = {
            "type": "custom_event",
            "name": event_name,
            "visitor_id": visitor_id,
            "meta": meta or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        async with self._lock:
            self._events[site_id].append(event)
            if len(self._events[site_id]) > self._max_events:
                self._events[site_id] = self._events[site_id][-self._max_events:]
        await self._broadcast(site_id, event)

    def get_active_visitors(self, site_id: int, window_seconds: int = 300) -> dict[str, Any]:
        now = time.time()
        cutoff = now - window_seconds
        visitors = {}
        for vid, data in self._visitors.get(site_id, {}).items():
            if data["last_seen"] >= cutoff:
                visitors[vid] = data

        pages = defaultdict(int)
        for v in visitors.values():
            pages[v["page"]] += 1

        return {
            "active_visitors": len(visitors),
            "active_by_page": dict(pages),
            "window_seconds": window_seconds,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_active_by_page(self, site_id: int, window_seconds: int = 300) -> dict[str, int]:
        now = time.time()
        cutoff = now - window_seconds
        pages: dict[str, int] = defaultdict(int)
        for vid, data in self._visitors.get(site_id, {}).items():
            if data["last_seen"] >= cutoff:
                pages[data["page"]] += 1
        return dict(pages)

    def get_visitor_list(self, site_id: int, window_seconds: int = 300) -> list[dict[str, Any]]:
        now = time.time()
        cutoff = now - window_seconds
        result = []
        for vid, data in self._visitors.get(site_id, {}).items():
            if data["last_seen"] >= cutoff:
                result.append({
                    "visitor_id": vid,
                    "page": data["page"],
                    "country": data["country"],
                    "duration_seconds": round(now - data["entered_at"]),
                })
        return result

    def get_geographic_distribution(self, site_id: int) -> dict[str, Any]:
        geo = dict(self._geo_data.get(site_id, {}))
        total = sum(geo.values()) or 1
        distribution = {k: {"count": v, "percentage": round(v / total * 100, 1)} for k, v in geo.items()}
        sorted_dist = dict(sorted(distribution.items(), key=lambda x: x[1]["count"], reverse=True))
        return {
            "countries": sorted_dist,
            "total_visitors": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_traffic_sources(self, site_id: int) -> dict[str, Any]:
        sources = dict(self._source_data.get(site_id, {}))
        total = sum(sources.values()) or 1
        distribution = {k: {"count": v, "percentage": round(v / total * 100, 1)} for k, v in sources.items()}
        sorted_dist = dict(sorted(distribution.items(), key=lambda x: x[1]["count"], reverse=True))
        return {
            "sources": sorted_dist,
            "total_tracked": total,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_realtime_snapshot(self, site_id: int) -> dict[str, Any]:
        active = self.get_active_visitors(site_id, window_seconds=300)
        active_1m = self.get_active_visitors(site_id, window_seconds=60)
        geo = self.get_geographic_distribution(site_id)
        sources = self.get_traffic_sources(site_id)
        recent_events = self._events.get(site_id, [])[-20:]

        return {
            "active_visitors": active["active_visitors"],
            "active_1m": active_1m["active_visitors"],
            "active_by_page": active["active_by_page"],
            "geographic": geo,
            "traffic_sources": sources,
            "recent_events": recent_events,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def subscribe(self, site_id: int) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        async with self._lock:
            self._subscribers[site_id].append(queue)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            async with self._lock:
                if queue in self._subscribers[site_id]:
                    self._subscribers[site_id].remove(queue)

    async def _broadcast(self, site_id: int, event: dict[str, Any]) -> None:
        dead_queues = []
        for queue in self._subscribers.get(site_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                dead_queues.append(queue)
        for q in dead_queues:
            self._subscribers[site_id].remove(q)

    async def close_all_subscriptions(self, site_id: int) -> None:
        async with self._lock:
            for queue in self._subscribers.get(site_id, []):
                try:
                    queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass
            self._subscribers[site_id].clear()

    async def _cleanup_stale(self) -> None:
        async with self._lock:
            now = time.time()
            stale_threshold = now - 600
            for site_id in list(self._visitors.keys()):
                stale = [
                    vid for vid, data in self._visitors[site_id].items()
                    if data["last_seen"] < stale_threshold
                ]
                for vid in stale:
                    del self._visitors[site_id][vid]
            self._last_cleanup = now

    def _extract_source(self, referrer: str) -> str:
        from urllib.parse import urlparse
        try:
            parsed = urlparse(referrer)
            host = parsed.hostname or ""
            host = host.lower().replace("www.", "")
            known_sources = {
                "google": "Google Search",
                "bing": "Bing Search",
                "yahoo": "Yahoo Search",
                "duckduckgo": "DuckDuckGo",
                "baidu": "Baidu Search",
                "facebook": "Facebook",
                "twitter": "Twitter / X",
                "x.com": "Twitter / X",
                "instagram": "Instagram",
                "linkedin": "LinkedIn",
                "reddit": "Reddit",
                "youtube": "YouTube",
                "t.co": "Twitter / X",
                "bit.ly": "Bitly",
                "github": "GitHub",
                "stackoverflow": "Stack Overflow",
                "medium": "Medium",
                "pinterest": "Pinterest",
                "tiktok": "TikTok",
            }
            for key, label in known_sources.items():
                if key in host:
                    return label
            return host or "Direct"
        except Exception:
            return "Unknown"

    async def persist_snapshot(self, site_id: int) -> None:
        snapshot = self.get_realtime_snapshot(site_id)
        try:
            await self.db.db.execute(
                """INSERT INTO realtime_snapshots (site_id, active_visitors, data, created_at)
                   VALUES (?, ?, ?, datetime('now'))""",
                (site_id, snapshot["active_visitors"], json.dumps(snapshot)),
            )
            await self.db.db.commit()
        except Exception as exc:
            logger.warning("Failed to persist realtime snapshot: %s", exc)

    async def get_historical_snapshots(self, site_id: int, minutes: int = 60) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        rows = await self.db._fetch_all(
            """SELECT active_visitors, data, created_at
               FROM realtime_snapshots WHERE site_id=? AND created_at>=?
               ORDER BY created_at""",
            (site_id, since),
        )
        return [
            {
                "active_visitors": r["active_visitors"],
                "data": json.loads(r["data"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

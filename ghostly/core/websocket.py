from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from aiohttp import web

logger = logging.getLogger("ghostly.websocket")


class ClientConnection:
    """Represents a single WebSocket client connection."""

    def __init__(self, ws: web.WebSocketResponse, site_id: int, client_id: str) -> None:
        self.ws = ws
        self.site_id = site_id
        self.client_id = client_id
        self.connected_at = time.time()
        self.last_ping = time.time()
        self.last_pong = time.time()
        self.is_alive = True
        self.subscriptions: list[str] = []
        self.messages_sent: int = 0
        self.messages_received: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "site_id": self.site_id,
            "connected_at": self.connected_at,
            "last_ping": self.last_ping,
            "is_alive": self.is_alive,
            "subscriptions": self.subscriptions,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "uptime_seconds": round(time.time() - self.connected_at, 1),
        }


class WebSocketManager:
    """Manages WebSocket connections for real-time dashboard updates."""

    def __init__(self) -> None:
        self._clients: dict[str, ClientConnection] = {}
        self._site_clients: dict[int, set[str]] = {}
        self._client_counter: int = 0
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._ping_interval: float = 30.0
        self._pong_timeout: float = 10.0
        self._lock = asyncio.Lock()
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._batch_task: asyncio.Task[None] | None = None
        self._batch_size: int = 50
        self._batch_interval: float = 1.0

    @property
    def total_connections(self) -> int:
        return len(self._clients)

    def get_site_connection_count(self, site_id: int) -> int:
        return len(self._site_clients.get(site_id, set()))

    def get_site_clients(self, site_id: int) -> list[dict[str, Any]]:
        client_ids = self._site_clients.get(site_id, set())
        return [
            self._clients[cid].to_dict()
            for cid in client_ids
            if cid in self._clients
        ]

    async def start(self) -> None:
        """Start the heartbeat background task."""
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            logger.info("WebSocket heartbeat started")
        if self._batch_task is None or self._batch_task.done():
            self._batch_task = asyncio.create_task(self._batch_broadcast_loop())
            logger.info("WebSocket batch broadcast started")

    async def stop(self) -> None:
        """Stop the heartbeat and close all connections."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._batch_task and not self._batch_task.done():
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass

        async with self._lock:
            for client in list(self._clients.values()):
                try:
                    await client.ws.close(code=1001, message=b"Server shutting down")
                except Exception:
                    pass
                client.is_alive = False
            self._clients.clear()
            self._site_clients.clear()
        logger.info("WebSocket manager stopped, all connections closed")

    async def register(self, ws: web.WebSocketResponse, site_id: int) -> ClientConnection:
        """Register a new WebSocket client connection."""
        async with self._lock:
            self._client_counter += 1
            client_id = f"ws-{site_id}-{self._client_counter}-{int(time.time())}"
            client = ClientConnection(ws, site_id, client_id)
            self._clients[client_id] = client

            if site_id not in self._site_clients:
                self._site_clients[site_id] = set()
            self._site_clients[site_id].add(client_id)

        logger.info(
            "Client %s connected to site %d (total: %d, site: %d)",
            client_id, site_id,
            self.total_connections,
            self.get_site_connection_count(site_id),
        )
        return client

    async def unregister(self, client_id: str) -> None:
        """Unregister a WebSocket client connection."""
        async with self._lock:
            client = self._clients.pop(client_id, None)
            if client:
                client.is_alive = False
                site_id = client.site_id
                if site_id in self._site_clients:
                    self._site_clients[site_id].discard(client_id)
                    if not self._site_clients[site_id]:
                        del self._site_clients[site_id]
                logger.info(
                    "Client %s disconnected from site %d (total: %d, site: %d)",
                    client_id, site_id,
                    self.total_connections,
                    self.get_site_connection_count(site_id),
                )

    async def broadcast_to_site(self, site_id: int, event_type: str, data: dict[str, Any]) -> int:
        """Broadcast a message to all clients connected to a specific site."""
        message = json.dumps({
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
        })
        sent = 0
        dead_clients: list[str] = []

        client_ids = list(self._site_clients.get(site_id, set()))
        for client_id in client_ids:
            client = self._clients.get(client_id)
            if not client or not client.is_alive:
                dead_clients.append(client_id)
                continue
            try:
                await client.ws.send_str(message)
                client.messages_sent += 1
                sent += 1
            except (ConnectionResetError, RuntimeError, AttributeError):
                dead_clients.append(client_id)
                client.is_alive = False

        for cid in dead_clients:
            await self.unregister(cid)

        return sent

    async def broadcast_pageview(self, site_id: int, pageview_data: dict[str, Any]) -> int:
        """Broadcast a pageview event to all connected dashboards for a site."""
        return await self.broadcast_to_site(site_id, "pageview", pageview_data)

    async def broadcast_event(self, site_id: int, event_data: dict[str, Any]) -> int:
        """Broadcast a custom event to all connected dashboards for a site."""
        return await self.broadcast_to_site(site_id, "event", event_data)

    async def broadcast_realtime_update(self, site_id: int, stats: dict[str, Any]) -> int:
        """Broadcast a realtime stats update to all connected dashboards for a site."""
        return await self.broadcast_to_site(site_id, "realtime_update", stats)

    async def broadcast_alert(self, site_id: int, alert_data: dict[str, Any]) -> int:
        """Broadcast an alert notification to all connected dashboards for a site."""
        return await self.broadcast_to_site(site_id, "alert", alert_data)

    async def send_to_client(self, client_id: str, event_type: str, data: dict[str, Any]) -> bool:
        """Send a message to a specific client."""
        client = self._clients.get(client_id)
        if not client or not client.is_alive:
            return False
        try:
            message = json.dumps({
                "type": event_type,
                "data": data,
                "timestamp": time.time(),
            })
            await client.ws.send_str(message)
            client.messages_sent += 1
            return True
        except (ConnectionResetError, RuntimeError, AttributeError):
            await self.unregister(client_id)
            return False

    async def queue_broadcast(self, site_id: int, event_type: str, data: dict[str, Any]) -> None:
        """Queue a broadcast message for batch processing."""
        await self._message_queue.put({
            "site_id": site_id,
            "event_type": event_type,
            "data": data,
            "timestamp": time.time(),
        })

    async def _batch_broadcast_loop(self) -> None:
        """Background task to process queued broadcasts in batches."""
        while True:
            try:
                await asyncio.sleep(self._batch_interval)
                await self._process_batch()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Batch broadcast error: %s", exc)
                await asyncio.sleep(5.0)

    async def _process_batch(self) -> None:
        """Process a batch of queued messages."""
        batch: list[dict[str, Any]] = []

        while not self._message_queue.empty() and len(batch) < self._batch_size:
            try:
                msg = self._message_queue.get_nowait()
                batch.append(msg)
            except asyncio.QueueEmpty:
                break

        if not batch:
            return

        messages_by_site: dict[int, list[dict[str, Any]]] = {}
        for msg in batch:
            site_id = msg["site_id"]
            if site_id not in messages_by_site:
                messages_by_site[site_id] = []
            messages_by_site[site_id].append(msg)

        for site_id, messages in messages_by_site.items():
            if len(messages) == 1:
                msg = messages[0]
                await self.broadcast_to_site(site_id, msg["event_type"], msg["data"])
            else:
                combined = {
                    "events": [{"type": m["event_type"], "data": m["data"]} for m in messages],
                    "count": len(messages),
                }
                await self.broadcast_to_site(site_id, "batch_update", combined)

    async def _heartbeat_loop(self) -> None:
        """Background task to ping clients and detect dead connections."""
        while True:
            try:
                await asyncio.sleep(self._ping_interval)
                await self._ping_all_clients()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Heartbeat error: %s", exc)
                await asyncio.sleep(5.0)

    async def _ping_all_clients(self) -> None:
        """Send ping to all connected clients and close unresponsive ones."""
        now = time.time()
        dead_clients: list[str] = []

        for client_id, client in list(self._clients.items()):
            if not client.is_alive:
                dead_clients.append(client_id)
                continue

            if now - client.last_pong > (self._ping_interval + self._pong_timeout):
                logger.warning("Client %s timed out (no pong received)", client_id)
                dead_clients.append(client_id)
                continue

            try:
                ping_time = now
                await client.ws.ping()
                client.last_ping = ping_time
            except (ConnectionResetError, RuntimeError, AttributeError):
                dead_clients.append(client_id)
                client.is_alive = False

        for cid in dead_clients:
            await self.unregister(cid)

    def get_stats(self) -> dict[str, Any]:
        """Get overall WebSocket manager statistics."""
        site_stats = {}
        for site_id, client_ids in self._site_clients.items():
            site_stats[site_id] = {
                "connected_clients": len(client_ids),
                "clients": [
                    self._clients[cid].to_dict()
                    for cid in client_ids
                    if cid in self._clients
                ],
            }
        return {
            "total_connections": self.total_connections,
            "total_sites": len(self._site_clients),
            "sites": site_stats,
            "heartbeat_interval": self._ping_interval,
            "pong_timeout": self._pong_timeout,
            "queue_size": self._message_queue.qsize(),
            "batch_size": self._batch_size,
            "batch_interval": self._batch_interval,
        }


class WebSocketHandler:
    """Handles WebSocket upgrade requests and message routing."""

    def __init__(self, manager: WebSocketManager) -> None:
        self.manager = manager

    async def handle_connection(self, request: web.Request) -> web.WebSocketResponse:
        """Handle a WebSocket upgrade request for a specific site."""
        site_id_str = request.match_info.get("site_id", "0")
        try:
            site_id = int(site_id_str)
        except ValueError:
            return web.Response(text="Invalid site_id", status=400)

        ws = web.WebSocketResponse(
            heartbeat=self.manager._ping_interval,
            max_msg_size=1024 * 1024,
            autoclose=True,
            autoping=True,
        )
        await ws.prepare(request)

        client = await self.manager.register(ws, site_id)

        try:
            welcome = json.dumps({
                "type": "connected",
                "data": {
                    "client_id": client.client_id,
                    "site_id": site_id,
                    "message": "Connected to Ghostly real-time dashboard",
                    "heartbeat_interval": self.manager._ping_interval,
                },
                "timestamp": time.time(),
            })
            await ws.send_str(welcome)
            client.messages_sent += 1

            async for msg in ws:
                if msg.type == web.WSMsgType.TEXT:
                    client.messages_received += 1
                    await self._handle_message(client, msg.data)
                elif msg.type == web.WSMsgType.ERROR:
                    logger.error("WebSocket error: %s", ws.exception())
                    break
                elif msg.type in (web.WSMsgType.CLOSE, web.WSMsgType.CLOSING, web.WSMsgType.CLOSED):
                    break
        except Exception as exc:
            logger.error("WebSocket handler error for %s: %s", client.client_id, exc)
        finally:
            await self.manager.unregister(client.client_id)

        return ws

    async def _handle_message(self, client: ClientConnection, raw: str) -> None:
        """Handle incoming WebSocket messages from clients."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type", "")

        if msg_type == "ping":
            client.last_pong = time.time()
            pong = json.dumps({
                "type": "pong",
                "timestamp": time.time(),
            })
            try:
                await client.ws.send_str(pong)
                client.messages_sent += 1
            except Exception:
                pass

        elif msg_type == "pong":
            client.last_pong = time.time()

        elif msg_type == "subscribe":
            channel = msg.get("channel", "default")
            if channel not in client.subscriptions:
                client.subscriptions.append(channel)
            ack = json.dumps({
                "type": "subscribed",
                "channel": channel,
                "timestamp": time.time(),
            })
            try:
                await client.ws.send_str(ack)
                client.messages_sent += 1
            except Exception:
                pass

        elif msg_type == "unsubscribe":
            channel = msg.get("channel", "default")
            if channel in client.subscriptions:
                client.subscriptions.remove(channel)
            ack = json.dumps({
                "type": "unsubscribed",
                "channel": channel,
                "timestamp": time.time(),
            })
            try:
                await client.ws.send_str(ack)
                client.messages_sent += 1
            except Exception:
                pass

        elif msg_type == "request_stats":
            from ghostly.core.aggregator import Aggregator
            from ghostly.core.database import Database

            db = client.ws._request.app.get("db") if hasattr(client.ws, "_request") else None
            if db:
                aggregator = Aggregator(db)
                stats = await aggregator.get_realtime_stats(client.site_id)
                response = json.dumps({
                    "type": "stats_response",
                    "data": stats,
                    "timestamp": time.time(),
                })
                try:
                    await client.ws.send_str(response)
                    client.messages_sent += 1
                except Exception:
                    pass

        elif msg_type == "get_connections":
            site_count = self.manager.get_site_connection_count(client.site_id)
            response = json.dumps({
                "type": "connections_info",
                "data": {
                    "site_connections": site_count,
                    "total_connections": self.manager.total_connections,
                },
                "timestamp": time.time(),
            })
            try:
                await client.ws.send_str(response)
                client.messages_sent += 1
            except Exception:
                pass

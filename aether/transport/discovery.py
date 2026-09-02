"""
Aether Transport — Device discovery via UDP broadcast.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Callable

logger = logging.getLogger(__name__)

DISCOVERY_MAGIC = b"AETHER_DISCOVERY"
DISCOVERY_PORT = 8766
DISCOVERY_INTERVAL_S = 3


class DiscoveryServer:
    """Controller-side: listens for worker UDP advertisements."""

    def __init__(self, port: int = DISCOVERY_PORT, on_discover: Callable | None = None):
        self.port = port
        self.on_discover = on_discover
        self._sock: socket.socket | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        self._known: dict[str, float] = {}

    async def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind(("", self.port))
        except OSError:
            self._sock.bind(("127.0.0.1", self.port))
        self._sock.setblocking(False)
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("Discovery server on UDP %d", self.port)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        if self._sock:
            self._sock.close()

    async def _listen_loop(self):
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                data, addr = await loop.sock_recvfrom(self._sock, 4096)
                if data.startswith(DISCOVERY_MAGIC):
                    try:
                        payload = json.loads(data[len(DISCOVERY_MAGIC):])
                        device_id = payload.get("device_id", "unknown")
                        self._known[device_id] = time.time()
                        if self.on_discover:
                            self.on_discover(payload, addr)
                    except (json.JSONDecodeError, KeyError):
                        pass
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def get_known_devices(self) -> dict[str, float]:
        return dict(self._known)


class DiscoveryClient:
    """Worker-side: broadcasts presence on the LAN."""

    def __init__(self, device_id: str, display_name: str, port: int = DISCOVERY_PORT):
        self.device_id = device_id
        self.display_name = display_name
        self.port = port
        self._sock: socket.socket | None = None
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._running = True
        self._task = asyncio.create_task(self._advertise_loop())
        logger.info("Discovery client broadcasting as %s", self.device_id)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        if self._sock:
            self._sock.close()

    async def _advertise_loop(self):
        while self._running:
            try:
                payload = json.dumps({
                    "device_id": self.device_id,
                    "display_name": self.display_name,
                    "timestamp": time.time(),
                    "port": self.port,
                }).encode("utf-8")
                self._sock.sendto(DISCOVERY_MAGIC + payload, ("<broadcast>", self.port))
            except Exception:
                pass
            await asyncio.sleep(DISCOVERY_INTERVAL_S)

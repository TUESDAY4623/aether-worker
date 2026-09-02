"""
Aether Workers — Registry for connected Android Worker devices.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkerCapabilities:
    device_model: str = ""
    cpu_cores: int = 0
    cpu_arch: str = ""
    total_ram_mb: int = 0
    available_ram_mb: int = 0
    has_npu: bool = False
    supported_ops: list[str] = field(default_factory=list)
    supported_dtypes: list[str] = field(default_factory=list)
    max_tensor_dim: int = 0
    estimated_compute_mbps: float = 0.0
    transport_types: list[str] = field(default_factory=list)


@dataclass
class WorkerDevice:
    device_id: str
    display_name: str = ""
    capabilities: WorkerCapabilities = field(default_factory=WorkerCapabilities)
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    paired: bool = False
    session_id: str = ""
    thermal_state: str = "normal"
    available: bool = True
    transport: str = "wifi"
    peer_addr: str = ""


class WorkerRegistry:
    """Registry of all known/connected worker devices."""

    def __init__(self, discovery_timeout_s: float = 30.0):
        self._workers: dict[str, WorkerDevice] = {}
        self._discovery_timeout_s = discovery_timeout_s

    def register(self, worker: WorkerDevice) -> bool:
        existing = self._workers.get(worker.device_id)
        if existing:
            existing.last_seen = time.time()
            existing.available = True
            if worker.capabilities.device_model:
                existing.capabilities = worker.capabilities
            logger.debug("Updated worker %s", worker.device_id)
        else:
            self._workers[worker.device_id] = worker
            logger.info("Registered worker %s (%s)", worker.device_id, worker.display_name)
        return True

    def unregister(self, device_id: str):
        self._workers.pop(device_id, None)
        logger.info("Unregistered worker %s", device_id)

    def get(self, device_id: str) -> Optional[WorkerDevice]:
        return self._workers.get(device_id)

    def get_paired(self) -> list[WorkerDevice]:
        return [w for w in self._workers.values() if w.paired and w.available]

    def get_available(self) -> list[WorkerDevice]:
        return [w for w in self._workers.values() if w.available]

    def mark_unavailable(self, device_id: str):
        w = self._workers.get(device_id)
        if w:
            w.available = False
            logger.warning("Worker %s marked unavailable", device_id)

    def mark_available(self, device_id: str):
        w = self._workers.get(device_id)
        if w:
            w.available = True
            w.last_seen = time.time()

    def check_stale(self) -> list[str]:
        now = time.time()
        stale = []
        for device_id, w in self._workers.items():
            if now - w.last_seen > self._discovery_timeout_s:
                w.available = False
                stale.append(device_id)
        return stale

    def update_thermal(self, device_id: str, thermal_state: str):
        w = self._workers.get(device_id)
        if w:
            w.thermal_state = thermal_state

    @property
    def count(self) -> int:
        return len(self._workers)

    @property
    def all_workers(self) -> list[WorkerDevice]:
        return list(self._workers.values())

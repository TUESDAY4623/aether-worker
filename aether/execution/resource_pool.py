"""Resource Pool Manager — unified view of CPU, memory, and bandwidth across devices."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ResourceType(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"
    BANDWIDTH = "bandwidth"
    NPU = "npu"
    GPU = "gpu"


class AllocationStrategy(str, Enum):
    FIRST_FIT = "first_fit"
    BEST_FIT = "best_fit"
    WORST_FIT = "worst_fit"
    BALANCED = "balanced"


@dataclass
class ResourceReservation:
    reservation_id: str
    device_id: str
    resource_type: ResourceType
    amount: float
    allocated_at: float
    expires_at: float
    owner: str = ""


@dataclass
class DeviceResources:
    device_id: str
    cpu_cores: int = 0
    cpu_utilization_pct: float = 0.0
    memory_total_mb: int = 0
    memory_available_mb: int = 0
    bandwidth_mbps: float = 0.0
    npu_available: bool = False
    gpu_available: bool = False
    thermal_state: str = "idle"


class ResourcePoolManager:
    def __init__(self, strategy: AllocationStrategy = AllocationStrategy.BEST_FIT) -> None:
        self._lock = threading.RLock()
        self._strategy = strategy
        self._devices: dict[str, DeviceResources] = {}
        self._reservations: dict[str, ResourceReservation] = {}

    def register_device(self, resources: DeviceResources) -> None:
        with self._lock:
            self._devices[resources.device_id] = resources
            logger.info("Registered device resources: %s", resources.device_id)

    def update_device(self, resources: DeviceResources) -> None:
        with self._lock:
            self._devices[resources.device_id] = resources

    def get_device(self, device_id: str) -> DeviceResources | None:
        with self._lock:
            return self._devices.get(device_id)

    def reserve(self, device_id: str, resource_type: ResourceType, amount: float,
                duration_s: float, owner: str = "") -> ResourceReservation | None:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return None
            available = self._get_available(device, resource_type)
            if available < amount:
                return None
            import time
            reservation = ResourceReservation(
                reservation_id="res_" + str(int(time.time() * 1000)),
                device_id=device_id,
                resource_type=resource_type,
                amount=amount,
                allocated_at=time.time(),
                expires_at=time.time() + duration_s,
                owner=owner,
            )
            self._reservations[reservation.reservation_id] = reservation
            return reservation

    def release(self, reservation_id: str) -> bool:
        with self._lock:
            if reservation_id in self._reservations:
                del self._reservations[reservation_id]
                return True
            return False

    def find_best_device(self, resource_type: ResourceType, amount: float) -> str | None:
        with self._lock:
            candidates = []
            for device_id, device in self._devices.items():
                available = self._get_available(device, resource_type)
                if available >= amount:
                    candidates.append((available, device_id))
            if not candidates:
                return None
            if self._strategy == AllocationStrategy.BEST_FIT:
                candidates.sort(key=lambda x: x[0])
            elif self._strategy == AllocationStrategy.WORST_FIT:
                candidates.sort(key=lambda x: x[0], reverse=True)
            else:
                candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

    def get_total(self, resource_type: ResourceType) -> float:
        with self._lock:
            total = 0.0
            for device in self._devices.values():
                total += self._get_available(device, resource_type)
            return total

    def get_utilization(self, device_id: str) -> dict[str, float]:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return {}
            return {
                "cpu": device.cpu_utilization_pct / 100.0,
                "memory": 1.0 - (device.memory_available_mb / max(device.memory_total_mb, 1)),
                "bandwidth": 0.0,
            }

    def _get_available(self, device: DeviceResources, resource_type: ResourceType) -> float:
        if resource_type == ResourceType.CPU:
            return max(0, device.cpu_cores * (1.0 - device.cpu_utilization_pct / 100.0))
        elif resource_type == ResourceType.MEMORY:
            return max(0, device.memory_available_mb)
        elif resource_type == ResourceType.BANDWIDTH:
            return max(0, device.bandwidth_mbps)
        elif resource_type == ResourceType.NPU:
            return 1.0 if device.npu_available else 0.0
        elif resource_type == ResourceType.GPU:
            return 1.0 if device.gpu_available else 0.0
        return 0.0

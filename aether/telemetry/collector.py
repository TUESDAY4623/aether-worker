"""
Aether Telemetry — Structured metrics collection for all devices.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DeviceTelemetry:
    """Snapshot of a device's current state."""
    device_id: str
    timestamp: float = field(default_factory=time.time)
    temperature_c: float = 0.0
    memory_total_mb: int = 0
    memory_available_mb: int = 0
    memory_aether_reserved_mb: int = 0
    cpu_utilization_pct: float = 0.0
    npu_utilization_pct: float = 0.0
    battery_pct: float = 0.0
    is_charging: bool = False
    power_state: str = "unknown"
    network_latency_ms: float = 0.0
    tensor_bandwidth_mbps: float = 0.0
    available: bool = True

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "temperature_c": self.temperature_c,
            "memory_total_mb": self.memory_total_mb,
            "memory_available_mb": self.memory_available_mb,
            "memory_aether_reserved_mb": self.memory_aether_reserved_mb,
            "cpu_utilization_pct": self.cpu_utilization_pct,
            "npu_utilization_pct": self.npu_utilization_pct,
            "battery_pct": self.battery_pct,
            "is_charging": self.is_charging,
            "power_state": self.power_state,
            "network_latency_ms": self.network_latency_ms,
            "tensor_bandwidth_mbps": self.tensor_bandwidth_mbps,
            "available": self.available,
        }


class TelemetryCollector:
    """Collects and stores telemetry snapshots with rolling history."""

    def __init__(self, max_history: int = 1000):
        self._history: dict[str, list[DeviceTelemetry]] = {}
        self._latest: dict[str, DeviceTelemetry] = {}
        self._max_history = max_history

    def report(self, telemetry: DeviceTelemetry):
        device_id = telemetry.device_id
        if device_id not in self._history:
            self._history[device_id] = []
        self._history[device_id].append(telemetry)
        self._latest[device_id] = telemetry
        if len(self._history[device_id]) > self._max_history:
            self._history[device_id] = self._history[device_id][-self._max_history:]
        logger.debug("Telemetry %s: temp=%.1fC mem=%d/%dMB bat=%.0f%%",
                      device_id, telemetry.temperature_c,
                      telemetry.memory_available_mb, telemetry.memory_total_mb,
                      telemetry.battery_pct)

    def get_latest(self, device_id: str) -> Optional[DeviceTelemetry]:
        return self._latest.get(device_id)

    def get_history(self, device_id: str, count: int = 100) -> list[DeviceTelemetry]:
        hist = self._history.get(device_id, [])
        return hist[-count:] if count > 0 else hist

    def temperature_trend(self, device_id: str, window_s: float = 60.0) -> float:
        """Temperature trend (degrees/sec). Positive = heating up."""
        hist = self._history.get(device_id, [])
        now = time.time()
        recent = [t for t in hist if now - t.timestamp <= window_s]
        if len(recent) < 2:
            return 0.0
        temps = [t.temperature_c for t in recent]
        times = [t.timestamp for t in recent]
        t0 = times[0]
        norm_times = [(t - t0) for t in times]
        n = len(temps)
        sum_x = sum(norm_times); sum_y = sum(temps)
        sum_xy = sum(nt * temp for nt, temp in zip(norm_times, temps))
        sum_x2 = sum(nt * nt for nt in norm_times)
        denom = n * sum_x2 - sum_x * sum_x
        if abs(denom) < 1e-6:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denom

    def all_latest(self) -> dict[str, DeviceTelemetry]:
        return dict(self._latest)

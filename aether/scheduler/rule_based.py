"""
Aether Scheduler — Phase 1 deterministic rule-based scheduler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from aether.telemetry.collector import TelemetryCollector
    from aether.thermal.manager import ThermalManager, ThermalState

logger = logging.getLogger(__name__)


@dataclass
class DeviceScore:
    device_id: str
    score: float = 0.0
    compute_score: float = 0.0
    memory_score: float = 0.0
    thermal_score: float = 0.0
    latency_score: float = 0.0
    power_score: float = 0.0
    utilization_score: float = 0.0
    details: dict = field(default_factory=dict)


class RuleBasedScheduler:
    """
    Phase 1 deterministic scheduler.
    Scores candidate devices using weighted factors.
    """

    def __init__(self, thermal_manager: "ThermalManager", telemetry: "TelemetryCollector"):
        self.thermal = thermal_manager
        self.telemetry = telemetry
        self.w_compute = 0.25
        self.w_memory = 0.25
        self.w_thermal = 0.20
        self.w_latency = 0.15
        self.w_power = 0.10
        self.w_util = 0.05

    def select_device_for_segment(
        self, device_ids: list[str], segment_size_mb: int = 0,
    ) -> Optional[DeviceScore]:
        """Select best device for a memory segment from available candidates."""
        candidates = [
            did for did in device_ids
            if self.telemetry.get_latest(did) is not None
        ]
        if not candidates:
            return None
        scores = [self._score_for_segment(did, segment_size_mb) for did in candidates]
        scores.sort(key=lambda s: s.score, reverse=True)
        logger.debug("Segment scores: %s", [(s.device_id, f"{s.score:.1f}") for s in scores])
        return scores[0]

    def select_device_for_compute(
        self, device_ids: list[str], min_memory_mb: int = 0,
        required_ops: Optional[list[str]] = None,
    ) -> Optional[DeviceScore]:
        """Select best device for a compute task."""
        candidates = [
            did for did in device_ids
            if self.thermal.can_compute(did)
            and self.telemetry.get_latest(did) is not None
        ]
        if not candidates:
            return None
        scores = [self._score_for_compute(did, min_memory_mb, required_ops) for did in candidates]
        scores.sort(key=lambda s: s.score, reverse=True)
        return scores[0]

    def score_all(self, device_ids: list[str]) -> dict[str, DeviceScore]:
        return {did: self._score_for_segment(did, 0) for did in device_ids}

    def _score_for_segment(self, device_id: str, segment_size_mb: int) -> DeviceScore:
        tel = self.telemetry.get_latest(device_id)
        if not tel:
            return DeviceScore(device_id=device_id, score=0.0)

        free_ratio = tel.memory_available_mb / max(tel.memory_total_mb, 1)
        mem_score = min(free_ratio * 100, 100.0)

        therm_map = {
            "normal": 100.0, "warm": 70.0, "hot": 30.0,
            "critical": 0.0, "recovery": 50.0,
        }
        thermal_score = therm_map.get(self.thermal.get_state(device_id).value, 50.0)
        if segment_size_mb > 0 and tel.memory_available_mb < segment_size_mb:
            mem_score *= 0.1

        compute_score = 50.0
        latency_score = 50.0
        power_score = 50.0 if (tel.is_charging or tel.battery_pct > 50) else 20.0
        util_score = max(0.0, 100.0 - tel.cpu_utilization_pct)

        total = (
            self.w_compute * compute_score + self.w_memory * mem_score +
            self.w_thermal * thermal_score + self.w_latency * latency_score +
            self.w_power * power_score + self.w_util * util_score
        )
        return DeviceScore(
            device_id=device_id, score=total,
            compute_score=compute_score, memory_score=mem_score,
            thermal_score=thermal_score, latency_score=latency_score,
            power_score=power_score, utilization_score=util_score,
            details={"free_ratio": round(free_ratio, 3),
                     "thermal": self.thermal.get_state(device_id).value,
                     "battery_pct": tel.battery_pct},
        )

    def _score_for_compute(
        self, device_id: str, min_memory_mb: int, required_ops: Optional[list[str]],
    ) -> DeviceScore:
        base = self._score_for_segment(device_id, 0)
        tel = self.telemetry.get_latest(device_id)
        if tel and min_memory_mb > 0 and tel.memory_available_mb < min_memory_mb:
            base.score *= 0.1
        base.details["estimated_compute"] = True
        return base

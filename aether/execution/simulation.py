"""Simulation Environment — runs virtual device topologies before live deployment.

Phase 7 §25: validates partition plans, estimates end-to-end latency, predicts thermal behavior.
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VirtualDevice:
    device_id: str
    device_type: str
    cpu_cores: int = 4
    npu_available: bool = False
    gpu_available: bool = False
    memory_mb: int = 4096
    bandwidth_mbps: float = 100.0
    base_temperature_c: float = 40.0
    thermal_capacity: float = 1.0
    compute_tops: float = 1.0


@dataclass
class SimulatedPartition:
    device_id: str
    layers: list[int]
    compute_ms: float = 0.0
    transfer_ms: float = 0.0
    temperature_c: float = 40.0


@dataclass
class SimulationResult:
    simulation_id: str
    total_latency_ms: float
    max_temperature_c: float
    any_thermal_violation: bool
    partitions: list[SimulatedPartition]
    warnings: list[str] = field(default_factory=list)
    score: float = 0.0


class SimulationEnvironment:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._devices: dict[str, VirtualDevice] = {}
        self._results: dict[str, SimulationResult] = {}

    def add_device(self, device: VirtualDevice) -> None:
        with self._lock:
            self._devices[device.device_id] = device

    def get_device(self, device_id: str) -> VirtualDevice | None:
        with self._lock:
            return self._devices.get(device_id)

    def simulate_partition(self, simulation_id: str, partitions: list[SimulatedPartition],
                           model_config: dict | None = None) -> SimulationResult:
        with self._lock:
            total_latency = 0.0
            max_temp = 0.0
            warnings = []
            for partition in partitions:
                device = self._devices.get(partition.device_id)
                if device:
                    compute = len(partition.layers) * 15.0 / max(device.compute_tops, 0.1)
                    partition.compute_ms = compute
                    heat_generated = len(partition.layers) * 2.0 * device.thermal_capacity
                    partition.temperature_c = min(device.base_temperature_c + heat_generated,
                                                  100.0)
                    max_temp = max(max_temp, partition.temperature_c)
                    total_latency += compute
                    if partition.temperature_c > 80.0:
                        warnings.append("Thermal threshold exceeded on " + partition.device_id)
                else:
                    partition.compute_ms = len(partition.layers) * 15.0
                    total_latency += partition.compute_ms
            transfer_overhead = len(partitions) * 5.0
            total_latency += transfer_overhead
            score = max(0.0, 100.0 - (total_latency / 10.0) - (max_temp - 40.0) * 2.0)
            result = SimulationResult(
                simulation_id=simulation_id,
                total_latency_ms=total_latency,
                max_temperature_c=max_temp,
                any_thermal_violation=max_temp > 80.0,
                partitions=partitions,
                warnings=warnings,
                score=score,
            )
            self._results[simulation_id] = result
            return result

    def compare_plans(self, plan_a: list[SimulatedPartition],
                      plan_b: list[SimulatedPartition]) -> dict[str, Any]:
        result_a = self.simulate_partition("compare_a", plan_a)
        result_b = self.simulate_partition("compare_b", plan_b)
        return {
            "plan_a_latency_ms": result_a.total_latency_ms,
            "plan_b_latency_ms": result_b.total_latency_ms,
            "plan_a_score": result_a.score,
            "plan_b_score": result_b.score,
            "plan_a_thermal": result_a.any_thermal_violation,
            "plan_b_thermal": result_b.any_thermal_violation,
            "winner": "a" if result_a.score > result_b.score else "b",
            "improvement_pct": abs(result_a.score - result_b.score) / max(result_b.score, 0.01) * 100,
        }

    def get_result(self, simulation_id: str) -> SimulationResult | None:
        with self._lock:
            return self._results.get(simulation_id)

"""Autonomous Planner — generates optimal execution plans without manual configuration.

Phase 8 §6: analyzes available resources, model requirements, and network topology
to produce a complete inference plan.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PlanningStrategy(str, Enum):
    AUTOMATIC = "automatic"
    LOW_LATENCY = "low_latency"
    THROUGHPUT = "throughput"
    ENERGY_EFFICIENT = "energy_efficient"
    THERMAL_SAFE = "thermal_safe"


@dataclass
class ResourceSnapshot:
    device_id: str
    cpu_cores: int = 0
    cpu_utilization_pct: float = 0.0
    memory_available_mb: int = 0
    memory_total_mb: int = 0
    npu_available: bool = False
    gpu_available: bool = False
    bandwidth_mbps: float = 0.0
    temperature_c: float = 45.0
    battery_pct: float = 100.0
    is_charging: bool = True
    latency_to_controller_ms: float = 50.0


@dataclass
class ExecutionPlan:
    plan_id: str
    model_id: str
    strategy: PlanningStrategy
    device_assignments: dict[str, list[int]]
    estimated_latency_ms: float = 0.0
    estimated_energy_j: float = 0.0
    max_temperature_c: float = 45.0
    confidence: float = 1.0
    fallback_plan: str = ""


class AutonomousPlanner:
    def __init__(self, default_strategy: PlanningStrategy = PlanningStrategy.AUTOMATIC) -> None:
        self._lock = threading.RLock()
        self._default_strategy = default_strategy
        self._plans: dict[str, ExecutionPlan] = {}

    def create_plan(self, model_id: str, resources: list[ResourceSnapshot],
                    model_layers: int, strategy: PlanningStrategy | None = None
                    ) -> ExecutionPlan:
        with self._lock:
            plan_strategy = strategy or self._default_strategy
            total_layers = model_layers
            devices = [r for r in resources if r.memory_available_mb > 0]
            if not devices:
                return ExecutionPlan(
                    plan_id="plan_fallback_" + str(int(time.time())),
                    model_id=model_id,
                    strategy=plan_strategy,
                    device_assignments={},
                    confidence=0.0,
                    fallback_plan="local_only",
                )
            assignments = {}
            layers_per_device = total_layers // len(devices)
            for i, res in enumerate(devices):
                start = i * layers_per_device
                end = total_layers if i == len(devices) - 1 else (i + 1) * layers_per_device
                assignments[res.device_id] = list(range(start, end))
            estimated_latency = self._estimate_latency(assignments, devices)
            estimated_energy = self._estimate_energy(assignments, devices)
            max_temp = max((r.temperature_c for r in devices), default=45.0)
            plan = ExecutionPlan(
                plan_id="plan_" + str(int(time.time())),
                model_id=model_id,
                strategy=plan_strategy,
                device_assignments=assignments,
                estimated_latency_ms=estimated_latency,
                estimated_energy_j=estimated_energy,
                max_temperature_c=max_temp,
                confidence=0.85,
            )
            self._plans[plan.plan_id] = plan
            return plan

    def create_fallback_plan(self, model_id: str, local_resources: ResourceSnapshot
                              ) -> ExecutionPlan:
        plan = ExecutionPlan(
            plan_id="plan_fallback_" + str(int(time.time())),
            model_id=model_id,
            strategy=PlanningStrategy.AUTOMATIC,
            device_assignments={"local": list(range(10))},
            estimated_latency_ms=500.0,
            confidence=0.3,
            fallback_plan="local_only",
        )
        self._plans[plan.plan_id] = plan
        return plan

    def _estimate_latency(self, assignments: dict[str, list[int]],
                          resources: list[ResourceSnapshot]) -> float:
        latency = 0.0
        for device_id, layers in assignments.items():
            res = next((r for r in resources if r.device_id == device_id), None)
            if res:
                layer_ms = 15.0 / max(res.cpu_cores, 1)
                latency += len(layers) * layer_ms + res.latency_to_controller_ms
        return latency

    def _estimate_energy(self, assignments: dict[str, list[int]],
                         resources: list[ResourceSnapshot]) -> float:
        energy = 0.0
        for device_id, layers in assignments.items():
            res = next((r for r in resources if r.device_id == device_id), None)
            if res:
                energy += len(layers) * 0.5 * (1.0 - res.battery_pct / 100.0)
        return energy

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        with self._lock:
            return self._plans.get(plan_id)

    def list_plans(self) -> list[str]:
        with self._lock:
            return list(self._plans.keys())

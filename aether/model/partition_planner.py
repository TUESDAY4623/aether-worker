"""
Partition Planner — evaluates partitioning strategies and selects the best plan.

Phase 2 §2 + Phase 3 §2: evaluates 3 strategies (distributed memory residency,
layer offload, tensor-level distribution), runs cost simulation, and returns
the lowest-cost valid plan.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from aether.execution.resource_pool import ResourcePoolManager
from aether.model.analyzer import AnalyzeResult
from aether.model.manifest import (
    ModelManifest, ModelPartitioner, PartitionPlan,
)
from aether.scheduler.cost_based import CostBasedScheduler

logger = logging.getLogger(__name__)


@dataclass
class StrategyEvaluation:
    """Result of evaluating one partitioning strategy."""
    strategy: str
    valid: bool
    placements: list[dict] = field(default_factory=list)
    estimated_compute_ms: float = 0.0
    estimated_transfer_mb: float = 0.0
    estimated_cost: float = 0.0
    devices_used: int = 0
    failure_reason: str = ""
    evaluated_at: float = field(default_factory=time.time)


@dataclass
class PartitionPlanV2:
    """Enhanced partition plan with strategy evaluation results."""
    model_id: str
    selected_strategy: str
    placements: list[dict] = field(default_factory=list)
    estimated_compute_ms: float = 0.0
    estimated_transfer_mb: float = 0.0
    estimated_cost: float = 0.0
    confidence: float = 0.0
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    all_evaluations: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "selected_strategy": self.selected_strategy,
            "placements": self.placements,
            "estimated_compute_ms": round(self.estimated_compute_ms, 2),
            "estimated_transfer_mb": round(self.estimated_transfer_mb, 2),
            "estimated_cost": round(self.estimated_cost, 2),
            "confidence": round(self.confidence, 2),
            "alternatives": self.alternatives,
            "all_evaluations": self.all_evaluations,
            "created_at": self.created_at,
        }


class PartitionPlanner:
    """Evaluates multiple partitioning strategies and selects the best plan.

    Strategies:
    A. Distributed Memory Residency — weights on workers, compute on laptop.
    B. Layer Offload — layer groups on workers with activation transfers.
    C. Tensor-Level Distribution — fine-grained tensor sharding (if applicable).
    """

    STRATEGIES = ["memory_only", "layer_offload", "tensor_level"]

    def __init__(
        self,
        partitioner: ModelPartitioner | None = None,
        cost_scheduler: CostBasedScheduler | None = None,
        resource_pool: ResourcePoolManager | None = None,
    ):
        self._lock = threading.RLock()
        self._partitioner = partitioner or ModelPartitioner(scheduler=None)
        self._cost_scheduler = cost_scheduler or CostBasedScheduler()
        self._resource_pool = resource_pool
        self._plans: dict[str, PartitionPlanV2] = {}

    def plan_partition(
        self,
        model_id: str,
        manifest: ModelManifest,
        device_ids: list[str],
        local_device: str = "laptop",
        analysis: AnalyzeResult | None = None,
        context: dict[str, Any] | None = None,
    ) -> PartitionPlanV2:
        """Evaluate all strategies and select the lowest-cost valid plan.

        Args:
            model_id: Model identifier.
            manifest: Model placement manifest.
            device_ids: Available device IDs (including local).
            local_device: The local (controller) device ID.
            analysis: Optional ModelAnalyzer result for better estimates.
            context: Optional context (bandwidth, thermal states, etc.).

        Returns:
            PartitionPlanV2 with selected strategy and alternatives.
        """
        with self._lock:
            context = context or {}
            workers = [d for d in device_ids if d != local_device]
            bandwidth_mbps = context.get("bandwidth_mbps", 100.0)
            thermal_states = context.get("thermal_states", {})
            failure_counts = context.get("failure_counts", {})

            # Build resource memory map if pool is available
            device_memory: dict[str, tuple[int, int]] = {}
            if self._resource_pool:
                for did in device_ids:
                    res = self._resource_pool.get_device(did)
                    if res:
                        device_memory[did] = (res.memory_total_mb, res.memory_available_mb)

            # Evaluate each strategy
            evaluations: list[StrategyEvaluation] = []
            for strategy in self.STRATEGIES:
                if not workers and strategy != "memory_only":
                    ev = StrategyEvaluation(
                        strategy=strategy, valid=False,
                        failure_reason="no remote devices available",
                    )
                else:
                    ev = self._evaluate_strategy(
                        strategy=strategy,
                        manifest=manifest,
                        device_ids=device_ids,
                        local_device=local_device,
                        bandwidth_mbps=bandwidth_mbps,
                        thermal_states=thermal_states,
                        failure_counts=failure_counts,
                        device_memory=device_memory,
                    )
                evaluations.append(ev)

            # Pick best valid strategy
            valid_evals = [e for e in evaluations if e.valid]
            if not valid_evals:
                fallback = self._local_fallback(model_id, manifest, local_device)
                plan = PartitionPlanV2(
                    model_id=model_id,
                    selected_strategy="local_only",
                    placements=fallback,
                    confidence=0.3,
                    all_evaluations=[self._eval_to_dict(e) for e in evaluations],
                )
                self._plans[model_id] = plan
                return plan

            valid_evals.sort(key=lambda e: e.estimated_cost)
            best = valid_evals[0]

            # Alternatives
            alternatives = []
            for ev in valid_evals[1:]:
                alternatives.append({
                    "strategy": ev.strategy,
                    "cost": round(ev.estimated_cost, 2),
                    "devices_used": ev.devices_used,
                    "transfer_mb": round(ev.estimated_transfer_mb, 2),
                })

            # Confidence based on margin
            confidence = 0.7
            if len(valid_evals) >= 2:
                next_cost = valid_evals[1].estimated_cost
                if next_cost > 0:
                    margin = (next_cost - best.estimated_cost) / next_cost
                    confidence = min(0.95, 0.7 + margin * 0.3)

            plan = PartitionPlanV2(
                model_id=model_id,
                selected_strategy=best.strategy,
                placements=best.placements,
                estimated_compute_ms=best.estimated_compute_ms,
                estimated_transfer_mb=best.estimated_transfer_mb,
                estimated_cost=best.estimated_cost,
                confidence=round(confidence, 2),
                alternatives=alternatives,
                all_evaluations=[self._eval_to_dict(e) for e in evaluations],
            )
            self._plans[model_id] = plan
            logger.info(
                "Selected strategy '%s' for %s (cost=%.1f, devices=%d)",
                best.strategy, model_id, best.estimated_cost, best.devices_used,
            )
            return plan

    def _evaluate_strategy(
        self, strategy: str, manifest: ModelManifest,
        device_ids: list[str], local_device: str,
        bandwidth_mbps: float, thermal_states: dict[str, str],
        failure_counts: dict[str, int],
        device_memory: dict[str, tuple[int, int]],
    ) -> StrategyEvaluation:
        """Evaluate a single partitioning strategy."""
        try:
            partition_plan = self._partitioner.partition(
                manifest=manifest,
                device_ids=device_ids,
                strategy=strategy,
                local_device=local_device,
            )
        except (ValueError, Exception) as exc:
            return StrategyEvaluation(
                strategy=strategy, valid=False,
                failure_reason=f"partitioning error: {exc}",
            )

        placements = partition_plan.placements
        if not placements:
            return StrategyEvaluation(
                strategy=strategy, valid=False,
                failure_reason="no placements produced",
            )

        # Compute load per device
        layers_per_device: dict[str, int] = {}
        for p in placements:
            did = p.get("device", local_device)
            layers_per_device[did] = layers_per_device.get(did, 0) + 1

        # Transfer estimate
        transfer_mb = partition_plan.estimated_transfer_mb or manifest.total_size_mb() * 0.5
        if strategy == "memory_only":
            transfer_mb = manifest.total_size_mb()

        # Cost per device
        total_cost = 0.0
        for did, layer_count in layers_per_device.items():
            res = self._resource_pool.get_device(did) if self._resource_pool else None
            total_mb = res.memory_total_mb if res else 4096
            used_mb = res.memory_total_mb - res.memory_available_mb if res else 0
            breakdown = self._cost_scheduler.estimate_cost(
                device_id=did,
                compute_load_ms=layer_count * 15.0,
                transfer_mb=transfer_mb if did != local_device else 0.0,
                bandwidth_mbps=bandwidth_mbps,
                layer_count=layer_count,
                device_total_memory_mb=total_mb,
                device_used_memory_mb=used_mb,
                thermal_state=thermal_states.get(did, "normal"),
                failure_count=failure_counts.get(did, 0),
            )
            total_cost += breakdown.total_cost

        return StrategyEvaluation(
            strategy=strategy,
            valid=True,
            placements=placements,
            estimated_compute_ms=partition_plan.estimated_compute_ms,
            estimated_transfer_mb=round(transfer_mb, 2),
            estimated_cost=round(total_cost, 2),
            devices_used=len(set(p.get("device", local_device) for p in placements)),
        )

    def _local_fallback(self, model_id: str, manifest: ModelManifest,
                        local_device: str) -> list[dict]:
        placements = []
        for entry in manifest.entries:
            placements.append({
                "tensor_id": entry.tensor_id,
                "device": local_device,
                "mode": "local",
            })
        return placements

    def _eval_to_dict(self, ev: StrategyEvaluation) -> dict[str, Any]:
        return {
            "strategy": ev.strategy,
            "valid": ev.valid,
            "estimated_cost": round(ev.estimated_cost, 2),
            "estimated_transfer_mb": round(ev.estimated_transfer_mb, 2),
            "devices_used": ev.devices_used,
            "failure_reason": ev.failure_reason,
        }

    def get_plan(self, model_id: str) -> PartitionPlanV2 | None:
        with self._lock:
            return self._plans.get(model_id)

    def list_plans(self) -> list[str]:
        with self._lock:
            return list(self._plans.keys())

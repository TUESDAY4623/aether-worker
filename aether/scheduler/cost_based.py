"""
Cost-Based Scheduler — multi-factor cost model for device selection.

Phase 2 §5: Total Cost = Compute + Transfer + Synchronization +
Memory Pressure + Thermal + Recovery Risk.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from aether.scheduler.rule_based import RuleBasedScheduler

logger = logging.getLogger(__name__)


@dataclass
class CostBreakdown:
    """Per-device cost breakdown."""
    device_id: str
    compute_cost: float = 0.0
    transfer_cost: float = 0.0
    sync_cost: float = 0.0
    memory_pressure_cost: float = 0.0
    thermal_cost: float = 0.0
    recovery_risk_cost: float = 0.0
    total_cost: float = 0.0
    raw_score: float = 0.0
    details: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "compute_cost": round(self.compute_cost, 2),
            "transfer_cost": round(self.transfer_cost, 2),
            "sync_cost": round(self.sync_cost, 2),
            "memory_pressure_cost": round(self.memory_pressure_cost, 2),
            "thermal_cost": round(self.thermal_cost, 2),
            "recovery_risk_cost": round(self.recovery_risk_cost, 2),
            "total_cost": round(self.total_cost, 2),
            "raw_score": round(self.raw_score, 2),
            "details": {k: round(v, 2) for k, v in self.details.items()},
        }


class CostBasedScheduler:
    """Cost-based device scheduler using a 6-factor cost model.

    Cost = w_compute * compute + w_transfer * transfer + w_sync * sync
         + w_mem * memory_pressure + w_thermal * thermal + w_recovery * recovery_risk

    Lower total cost = better choice.
    Falls back to a RuleBasedScheduler for base scores when available.
    """

    # Default weights (sum to 1.0)
    DEFAULT_WEIGHTS = {
        "compute": 0.20,
        "transfer": 0.20,
        "sync": 0.10,
        "memory": 0.20,
        "thermal": 0.20,
        "recovery": 0.10,
    }

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        rule_scheduler: Optional["RuleBasedScheduler"] = None,
    ):
        self._lock = threading.RLock()
        self.weights = dict(self.DEFAULT_WEIGHTS)
        if weights:
            self.weights.update(weights)
        self._normalize_weights()
        self._rule_scheduler = rule_scheduler

    def _normalize_weights(self) -> None:
        total = sum(self.weights.values())
        if total > 0 and abs(total - 1.0) > 0.001:
            for key in self.weights:
                self.weights[key] /= total

    def estimate_cost(
        self,
        device_id: str,
        compute_load_ms: float = 0.0,
        transfer_mb: float = 0.0,
        bandwidth_mbps: float = 100.0,
        layer_count: int = 0,
        device_total_memory_mb: int = 0,
        device_used_memory_mb: int = 0,
        thermal_state: str = "normal",
        failure_count: int = 0,
        raw_score: float = 50.0,
    ) -> CostBreakdown:
        """Estimate the total cost of executing on a device.

        All costs are normalized to [0, 100] where 0 = cheapest.
        """
        with self._lock:
            w = self.weights

            # Compute cost: higher load = higher cost
            compute_cost = min(compute_load_ms / 10.0, 100.0)

            # Transfer cost: based on data size and available bandwidth
            transfer_rate = transfer_mb / max(bandwidth_mbps, 1.0)
            transfer_cost = min(transfer_rate * 10.0, 100.0)

            # Sync cost: more layers = more synchronization points
            sync_cost = min(layer_count * 2.0, 100.0)

            # Memory pressure cost
            if device_total_memory_mb > 0:
                pressure = device_used_memory_mb / device_total_memory_mb
                memory_pressure_cost = pressure * 100.0
            else:
                memory_pressure_cost = 50.0

            # Thermal cost
            thermal_map = {
                "normal": 0.0, "warm": 25.0,
                "hot": 60.0, "critical": 100.0, "recovery": 40.0,
            }
            thermal_cost = thermal_map.get(thermal_state, 50.0)

            # Recovery risk: based on recent failure count
            recovery_risk_cost = min(failure_count * 25.0, 100.0)

            # Weighted total (lower is better)
            total_cost = (
                w["compute"] * compute_cost
                + w["transfer"] * transfer_cost
                + w["sync"] * sync_cost
                + w["memory"] * memory_pressure_cost
                + w["thermal"] * thermal_cost
                + w["recovery"] * recovery_risk_cost
            )

            breakdown = CostBreakdown(
                device_id=device_id,
                compute_cost=compute_cost,
                transfer_cost=transfer_cost,
                sync_cost=sync_cost,
                memory_pressure_cost=memory_pressure_cost,
                thermal_cost=thermal_cost,
                recovery_risk_cost=recovery_risk_cost,
                total_cost=round(total_cost, 2),
                raw_score=raw_score,
                details={
                    "compute_load_ms": compute_load_ms,
                    "transfer_mb": transfer_mb,
                    "bandwidth_mbps": bandwidth_mbps,
                    "layer_count": layer_count,
                    "memory_pressure_pct": round(
                        device_used_memory_mb / max(device_total_memory_mb, 1) * 100, 1
                    ),
                    "thermal_state": thermal_state,
                    "failure_count": failure_count,
                },
            )
            return breakdown

    def select_with_cost_model(
        self,
        device_ids: list[str],
        compute_load_ms: float = 0.0,
        transfer_mb: float = 0.0,
        bandwidth_mbps: float = 100.0,
        layer_count: int = 0,
        device_memory: dict[str, tuple[int, int]] | None = None,
        thermal_states: dict[str, str] | None = None,
        failure_counts: dict[str, int] | None = None,
        raw_scores: dict[str, float] | None = None,
    ) -> list[CostBreakdown]:
        """Select the best device(s) using the cost model.

        Args:
            device_ids: Candidate device IDs.
            compute_load_ms: Estimated compute time on the device.
            transfer_mb: Data to transfer (MB).
            bandwidth_mbps: Available bandwidth.
            layer_count: Number of layers to place.
            device_memory: Dict of device_id -> (total_mb, used_mb).
            thermal_states: Dict of device_id -> thermal state string.
            failure_counts: Dict of device_id -> recent failure count.
            raw_scores: Dict of device_id -> base score from rule scheduler.

        Returns:
            Sorted list of CostBreakdown (lowest cost first).
        """
        with self._lock:
            device_memory = device_memory or {}
            thermal_states = thermal_states or {}
            failure_counts = failure_counts or {}
            raw_scores = raw_scores or {}

            results: list[CostBreakdown] = []
            for did in device_ids:
                total_mb, used_mb = device_memory.get(did, (0, 0))
                breakdown = self.estimate_cost(
                    device_id=did,
                    compute_load_ms=compute_load_ms,
                    transfer_mb=transfer_mb,
                    bandwidth_mbps=bandwidth_mbps,
                    layer_count=layer_count,
                    device_total_memory_mb=total_mb,
                    device_used_memory_mb=used_mb,
                    thermal_state=thermal_states.get(did, "normal"),
                    failure_count=failure_counts.get(did, 0),
                    raw_score=raw_scores.get(did, 50.0),
                )
                results.append(breakdown)

            results.sort(key=lambda b: b.total_cost)
            logger.debug("Cost model rankings: %s",
                         [(b.device_id, f"{b.total_cost:.1f}") for b in results])
            return results

    def get_weights(self) -> dict[str, float]:
        """Return current weight configuration."""
        with self._lock:
            return dict(self.weights)

    def set_weights(self, weights: dict[str, float]) -> None:
        """Update cost model weights."""
        with self._lock:
            self.weights.update(weights)
            self._normalize_weights()
            logger.info("Updated cost weights: %s", self.weights)

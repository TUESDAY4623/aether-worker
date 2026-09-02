"""
Tests for aether.scheduler.cost_based — CostBasedScheduler uncovered lines.
Targets: line 35 (_normalize_weights edge), 77 (zero memory fallback),
122 (thermal unknown state), 196-222 (select_with_cost_model full),
226-227 (set_weights).
"""
from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from aether.scheduler.cost_based import CostBasedScheduler, CostBreakdown


class TestCostBreakdown(unittest.TestCase):
    def test_defaults(self):
        cb = CostBreakdown(device_id="d1")
        assert cb.device_id == "d1"
        assert cb.total_cost == 0.0
        assert cb.details == {}

    def test_to_dict_rounds(self):
        cb = CostBreakdown(device_id="d1", compute_cost=1.234, total_cost=50.678)
        d = cb.to_dict()
        assert d["compute_cost"] == 1.23
        assert d["total_cost"] == 50.68
        assert d["device_id"] == "d1"


class TestNormalizeWeights(unittest.TestCase):
    def test_default_weights_sum_to_one(self):
        sched = CostBasedScheduler()
        total = sum(sched.weights.values())
        assert abs(total - 1.0) < 0.001

    def test_custom_weights_normalized(self):
        sched = CostBasedScheduler(weights={"compute": 0.5, "transfer": 0.5, "sync": 0.5,
                                             "memory": 0.5, "thermal": 0.5, "recovery": 0.5})
        total = sum(sched.weights.values())
        assert abs(total - 1.0) < 0.001
        for v in sched.weights.values():
            assert abs(v - 0.16667) < 0.01

    def test_partial_weights_kept(self):
        sched = CostBasedScheduler(weights={"thermal": 0.9})
        total = sum(sched.weights.values())
        assert abs(total - 1.0) < 0.001


class TestEstimateCost(unittest.TestCase):
    def _sched(self):
        return CostBasedScheduler()

    def test_basic_cost(self):
        sched = self._sched()
        cb = sched.estimate_cost("dev1", compute_load_ms=50, transfer_mb=10,
                                 bandwidth_mbps=100, layer_count=3)
        assert cb.device_id == "dev1"
        assert cb.total_cost > 0

    def test_zero_memory_device_uses_default(self):
        """Line 77: when device_total_memory_mb == 0, memory_pressure_cost = 50."""
        sched = self._sched()
        cb = sched.estimate_cost("dev1", compute_load_ms=0, transfer_mb=0,
                                 device_total_memory_mb=0, device_used_memory_mb=0)
        assert cb.memory_pressure_cost == 50.0

    def test_memory_pressure_scales(self):
        sched = self._sched()
        cb = sched.estimate_cost("dev1", compute_load_ms=0, transfer_mb=0,
                                 device_total_memory_mb=1000, device_used_memory_mb=750)
        assert cb.memory_pressure_cost == 75.0

    def test_thermal_states(self):
        sched = self._sched()
        states = {"normal": 0.0, "warm": 25.0, "hot": 60.0, "critical": 100.0, "recovery": 40.0}
        for state, expected in states.items():
            cb = sched.estimate_cost("dev1", thermal_state=state)
            assert cb.thermal_cost == expected, f"thermal state {state}"

    def test_thermal_unknown_state_defaults(self):
        """Line 122: unknown thermal state defaults to 50."""
        sched = self._sched()
        cb = sched.estimate_cost("dev1", thermal_state="unknown_state")
        assert cb.thermal_cost == 50.0

    def test_recovery_risk_scales(self):
        sched = self._sched()
        cb = sched.estimate_cost("dev1", failure_count=2)
        assert cb.recovery_risk_cost == 50.0  # min(2*25, 100)
        cb2 = sched.estimate_cost("dev1", failure_count=5)
        assert cb2.recovery_risk_cost == 100.0  # capped

    def test_details_dict_populated(self):
        sched = self._sched()
        cb = sched.estimate_cost("dev1", compute_load_ms=100, transfer_mb=50,
                                 bandwidth_mbps=200, layer_count=5,
                                 device_total_memory_mb=4000, device_used_memory_mb=2000,
                                 thermal_state="warm", failure_count=1)
        assert "compute_load_ms" in cb.details
        assert cb.details["memory_pressure_pct"] == 50.0
        assert cb.details["thermal_state"] == "warm"


class TestSelectWithCostModel(unittest.TestCase):
    def _defaults(self):
        return {
            "compute_load_ms": 100.0,
            "transfer_mb": 50.0,
            "bandwidth_mbps": 100.0,
            "layer_count": 5,
            "device_memory": {"d1": (4000, 2000), "d2": (8000, 1000)},
            "thermal_states": {"d1": "normal", "d2": "hot"},
            "failure_counts": {"d1": 0, "d2": 3},
            "raw_scores": {"d1": 80.0, "d2": 40.0},
        }

    def test_returns_sorted_list(self):
        sched = CostBasedScheduler()
        kwargs = self._defaults()
        results = sched.select_with_cost_model(["d1", "d2"], **kwargs)
        assert len(results) == 2
        # Lower cost should be first
        assert results[0].total_cost <= results[1].total_cost

    def test_empty_device_list(self):
        sched = CostBasedScheduler()
        results = sched.select_with_cost_model([])
        assert results == []

    def test_single_device(self):
        sched = CostBasedScheduler()
        results = sched.select_with_cost_model(["d1"], compute_load_ms=10)
        assert len(results) == 1
        assert results[0].device_id == "d1"

    def test_no_optional_dicts(self):
        """Lines 196-222: None dicts should not raise."""
        sched = CostBasedScheduler()
        results = sched.select_with_cost_model(["d1", "d2"],
                                               device_memory=None,
                                               thermal_states=None,
                                               failure_counts=None,
                                               raw_scores=None)
        assert len(results) == 2

    def test_thread_safety(self):
        """Concurrent calls should be safe."""
        sched = CostBasedScheduler()
        errors = []

        def worker():
            try:
                sched.select_with_cost_model(["d1", "d2"], **self._defaults())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestGetSetWeights(unittest.TestCase):
    def test_get_weights_returns_copy(self):
        sched = CostBasedScheduler()
        w = sched.get_weights()
        w["compute"] = 0.99
        assert sched.weights["compute"] != 0.99

    def test_set_weights_updates(self):
        sched = CostBasedScheduler()
        sched.set_weights({"compute": 0.5, "transfer": 0.5})
        assert abs(sched.weights["compute"] - 0.5) < 0.01
        total = sum(sched.weights.values())
        assert abs(total - 1.0) < 0.001

    def test_set_weights_partial_update(self):
        sched = CostBasedScheduler()
        original = sched.get_weights()
        sched.set_weights({"thermal": 0.9})
        # set_weights uses update() so original keys remain and all get normalized
        total = sum(sched.weights.values())
        assert abs(total - 1.0) < 0.001
        # After normalization, thermal weight = 0.9 / 1.6 ≈ 0.5625
        assert abs(sched.weights["thermal"] - 0.5625) < 0.01
        assert "compute" in sched.weights


class TestConcurrentAccess(unittest.TestCase):
    def test_concurrent_select(self):
        import threading
        sched = CostBasedScheduler()
        errors = []
        kwargs = {
            "compute_load_ms": 100.0,
            "transfer_mb": 50.0,
            "bandwidth_mbps": 100.0,
            "layer_count": 5,
            "device_memory": {"d1": (4000, 2000), "d2": (8000, 1000)},
            "thermal_states": {"d1": "normal", "d2": "hot"},
            "failure_counts": {"d1": 0, "d2": 3},
            "raw_scores": {"d1": 80.0, "d2": 40.0},
        }

        def worker():
            try:
                sched.select_with_cost_model(["d1", "d2"], **kwargs)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


if __name__ == "__main__":
    unittest.main()

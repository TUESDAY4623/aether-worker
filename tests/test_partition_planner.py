"""
Tests for aether.model.partition_planner — Partition Planner.
"""
from __future__ import annotations

import unittest

from aether.execution.resource_pool import (
    AllocationStrategy, DeviceResources, ResourcePoolManager,
)
from aether.model.analyzer import AnalyzeResult
from aether.model.manifest import ModelManifest, ManifestEntry, ModelPartitioner
from aether.model.partition_planner import PartitionPlanner, PartitionPlanV2, StrategyEvaluation
from aether.scheduler.cost_based import CostBasedScheduler


def _make_manifest(model_id="m1", num_layers=6):
    partitioner = ModelPartitioner(scheduler=None)
    layers = [
        {"name": f"layer_{i}", "shape": [128, 128], "byte_size": 65536,
         "params": 16384, "ops": ["matmul"]}
        for i in range(num_layers)
    ]
    return partitioner.create_manifest(model_id, "TestModel", layers)


class TestStrategyEvaluation(unittest.TestCase):
    def test_create_evaluation(self):
        ev = StrategyEvaluation(strategy="memory_only", valid=True, estimated_cost=50.0)
        assert ev.strategy == "memory_only"
        assert ev.valid is True
        assert ev.estimated_cost == 50.0

    def test_defaults(self):
        ev = StrategyEvaluation(strategy="test", valid=True)
        assert ev.placements == []
        assert ev.devices_used == 0
        assert ev.failure_reason == ""


class TestPartitionPlanV2(unittest.TestCase):
    def test_create_plan(self):
        plan = PartitionPlanV2(model_id="m1", selected_strategy="layer_offload")
        assert plan.model_id == "m1"
        assert plan.confidence == 0.0
        assert plan.alternatives == []

    def test_to_dict(self):
        plan = PartitionPlanV2(
            model_id="m1", selected_strategy="memory_only",
            placements=[{"tensor_id": "t1", "device": "laptop"}],
            estimated_cost=25.0, confidence=0.8,
        )
        d = plan.to_dict()
        assert d["model_id"] == "m1"
        assert d["selected_strategy"] == "memory_only"
        assert d["estimated_cost"] == 25.0
        assert d["confidence"] == 0.8
        assert len(d["placements"]) == 1


class TestPartitionPlanner(unittest.TestCase):
    def test_plan_with_workers(self):
        planner = PartitionPlanner()
        manifest = _make_manifest("m1", 6)
        plan = planner.plan_partition("m1", manifest, ["laptop", "phone_1", "phone_2"])
        assert plan.selected_strategy in planner.STRATEGIES
        assert len(plan.placements) > 0
        assert plan.estimated_cost >= 0

    def test_plan_no_workers(self):
        planner = PartitionPlanner()
        manifest = _make_manifest("m1", 4)
        plan = planner.plan_partition("m1", manifest, ["laptop"])
        # memory_only works without workers (places locally)
        assert plan.selected_strategy == "memory_only"
        assert all(p["device"] == "laptop" for p in plan.placements)

    def test_plan_no_remote_devices(self):
        planner = PartitionPlanner()
        manifest = _make_manifest("m1", 4)
        plan = planner.plan_partition("m1", manifest, ["laptop", "phone_1"])
        # With workers, should get a distributed strategy
        assert plan.selected_strategy in planner.STRATEGIES

    def test_plan_with_resource_pool(self):
        pool = ResourcePoolManager()
        pool.register_device(DeviceResources(
            device_id="laptop", cpu_cores=4, memory_total_mb=16384, memory_available_mb=8192,
        ))
        pool.register_device(DeviceResources(
            device_id="phone_1", cpu_cores=8, memory_total_mb=8192, memory_available_mb=4096,
        ))
        planner = PartitionPlanner(resource_pool=pool)
        manifest = _make_manifest("m1", 6)
        plan = planner.plan_partition("m1", manifest, ["laptop", "phone_1"])
        assert plan.selected_strategy in planner.STRATEGIES

    def test_plan_with_context(self):
        planner = PartitionPlanner()
        manifest = _make_manifest("m1", 6)
        plan = planner.plan_partition("m1", manifest, ["laptop", "phone_1"],
                                       context={"bandwidth_mbps": 500.0})
        assert plan.estimated_cost >= 0

    def test_plan_has_alternatives(self):
        planner = PartitionPlanner()
        manifest = _make_manifest("m1", 6)
        plan = planner.plan_partition("m1", manifest, ["laptop", "phone_1", "phone_2"])
        # With 3+ devices, should have alternatives
        assert len(plan.all_evaluations) == len(planner.STRATEGIES)

    def test_plan_caching(self):
        planner = PartitionPlanner()
        manifest = _make_manifest("m1", 4)
        plan1 = planner.plan_partition("m1", manifest, ["laptop", "phone_1"])
        plan2 = planner.get_plan("m1")
        assert plan2 is not None
        assert plan2.model_id == "m1"

    def test_list_plans(self):
        planner = PartitionPlanner()
        manifest = _make_manifest("m1", 4)
        planner.plan_partition("m1", manifest, ["laptop"])
        planner.plan_partition("m2", manifest, ["laptop"])
        plans = planner.list_plans()
        assert len(plans) == 2

    def test_all_evaluations_recorded(self):
        planner = PartitionPlanner()
        manifest = _make_manifest("m1", 6)
        plan = planner.plan_partition("m1", manifest, ["laptop", "phone_1"])
        assert len(plan.all_evaluations) == 3  # 3 strategies evaluated
        strategies_evaluated = [e["strategy"] for e in plan.all_evaluations]
        assert "memory_only" in strategies_evaluated
        assert "layer_offload" in strategies_evaluated


class TestPartitionPlannerWithCostScheduler(unittest.TestCase):
    def test_custom_cost_weights(self):
        cost_scheduler = CostBasedScheduler()
        cost_scheduler.set_weights({"thermal": 0.5, "compute": 0.3})
        planner = PartitionPlanner(cost_scheduler=cost_scheduler)
        manifest = _make_manifest("m1", 4)
        plan = planner.plan_partition("m1", manifest, ["laptop"])
        # memory_only works without workers
        assert plan.selected_strategy == "memory_only"


if __name__ == "__main__":
    unittest.main()

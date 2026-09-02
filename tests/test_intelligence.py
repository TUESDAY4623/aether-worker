"""Tests for Phase 8 Intelligence modules."""
from __future__ import annotations

import unittest

from aether.intelligence.planner import (
    AutonomousPlanner,
    ExecutionPlan,
    PlanningStrategy,
    ResourceSnapshot,
)
from aether.intelligence.self_healing import (
    FailoverAction,
    FailureType,
    HealthRecord,
    HealthStatus,
    SelfHealingEngine,
)
from aether.intelligence.kv_fabric import (
    CacheFragmentationReport,
    CacheTransferResult,
    KVCacheBlock,
    KVCacheFabric,
)
from aether.intelligence.hierarchy import (
    Hierarchy,
    HierarchyEvent,
    HierarchyNode,
    HierarchyRole,
)


class TestAutonomousPlanner(unittest.TestCase):
    def test_create_plan(self):
        planner = AutonomousPlanner()
        resources = [
            ResourceSnapshot(device_id="dev0", cpu_cores=4, memory_available_mb=2048,
                             temperature_c=45.0),
            ResourceSnapshot(device_id="dev1", cpu_cores=8, memory_available_mb=4096,
                             temperature_c=40.0),
        ]
        plan = planner.create_plan("model0", resources, 32)
        self.assertIsInstance(plan, ExecutionPlan)
        self.assertEqual(plan.model_id, "model0")
        self.assertGreater(len(plan.device_assignments), 0)
        self.assertGreater(plan.estimated_latency_ms, 0)

    def test_fallback_plan(self):
        planner = AutonomousPlanner()
        local = ResourceSnapshot(device_id="local", cpu_cores=2, memory_available_mb=1024)
        plan = planner.create_fallback_plan("model0", local)
        self.assertEqual(plan.fallback_plan, "local_only")
        self.assertLess(plan.confidence, 0.5)


class TestSelfHealingEngine(unittest.TestCase):
    def test_register_and_health(self):
        engine = SelfHealingEngine()
        engine.register_device("dev0")
        engine.register_device("dev1")
        record = engine.get_health("dev0")
        self.assertIsNotNone(record)
        self.assertEqual(record.status, HealthStatus.HEALTHY)

    def test_detect_failure(self):
        engine = SelfHealingEngine(max_retries=2)
        engine.register_device("dev0")
        engine.update_health("dev0", HealthStatus.FAILING, FailureType.THERMAL_THROTTLE)
        self.assertEqual(engine.get_health("dev0").failure_count, 1)
        engine.update_health("dev0", HealthStatus.FAILING, FailureType.THERMAL_THROTTLE)
        self.assertEqual(engine.get_health("dev0").failure_count, 2)
        self.assertTrue(engine.detect_failure("dev0", FailureType.THERMAL_THROTTLE))

    def test_attempt_recovery(self):
        engine = SelfHealingEngine()
        engine.register_device("dev0")
        action = engine.attempt_recovery("dev0", "dev1", [0, 1, 2])
        self.assertIsInstance(action, FailoverAction)
        self.assertTrue(action.success)
        self.assertEqual(action.failed_device_id, "dev0")
        self.assertEqual(action.target_device_id, "dev1")

    def test_degraded_devices(self):
        engine = SelfHealingEngine()
        engine.register_device("dev0")
        engine.register_device("dev1")
        engine.update_health("dev0", HealthStatus.DEGRADED)
        degraded = engine.get_degraded_devices()
        self.assertIn("dev0", degraded)
        self.assertNotIn("dev1", degraded)


class TestKVCacheFabric(unittest.TestCase):
    def test_allocate_and_get(self):
        fabric = KVCacheFabric(max_total_blocks=10)
        block = fabric.allocate_block("dev0", 0)
        self.assertIsNotNone(block)
        self.assertEqual(block.device_id, "dev0")
        self.assertEqual(block.layer_index, 0)
        retrieved = fabric.get_block(block.block_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.block_id, block.block_id)

    def test_pin_unpin(self):
        fabric = KVCacheFabric()
        block = fabric.allocate_block("dev0", 0)
        self.assertTrue(fabric.pin_block(block.block_id))
        self.assertTrue(block.pinned)
        self.assertTrue(fabric.unpin_block(block.block_id))
        self.assertFalse(block.pinned)

    def test_transfer_block(self):
        fabric = KVCacheFabric()
        block = fabric.allocate_block("dev0", 0)
        result = fabric.transfer_block(block.block_id, "dev1")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.to_device, "dev1")
        self.assertEqual(block.device_id, "dev1")

    def test_fragmentation_report(self):
        fabric = KVCacheFabric()
        b1 = fabric.allocate_block("dev0", 0)
        b2 = fabric.allocate_block("dev0", 1)
        fabric.pin_block(b1.block_id)
        report = fabric.get_fragmentation_report()
        self.assertEqual(report.total_blocks, 2)
        self.assertEqual(report.pinned_blocks, 1)
        self.assertEqual(report.evictable_blocks, 1)


class TestHierarchy(unittest.TestCase):
    def test_register_and_get(self):
        hier = Hierarchy(super_node_id="ctrl")
        node = hier.register_node("dev0", HierarchyRole.WORKER)
        self.assertEqual(node.node_id, "dev0")
        self.assertEqual(node.role, HierarchyRole.WORKER)
        retrieved = hier.get_node("dev0")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.node_id, "dev0")

    def test_promote_node(self):
        hier = Hierarchy()
        hier.register_node("dev0", HierarchyRole.WORKER)
        promoted = hier.promote_node("dev0", HierarchyRole.PRIMARY, "supervisor_up")
        self.assertIsNotNone(promoted)
        self.assertEqual(promoted.role, HierarchyRole.PRIMARY)
        events = hier._events
        self.assertGreater(len(events), 0)
        self.assertEqual(events[0].new_role, HierarchyRole.PRIMARY)

    def test_get_children(self):
        hier = Hierarchy()
        hier.register_node("dev0", HierarchyRole.PRIMARY)
        hier.register_node("dev1", HierarchyRole.WORKER, parent_id="dev0")
        children = hier.get_children("dev0")
        self.assertIn("dev1", children)

    def test_get_descendants(self):
        hier = Hierarchy()
        hier.register_node("dev0", HierarchyRole.PRIMARY)
        hier.register_node("dev1", HierarchyRole.WORKER, parent_id="dev0")
        hier.register_node("dev2", HierarchyRole.WORKER, parent_id="dev1")
        descendants = hier.get_descendants("dev0")
        self.assertIn("dev1", descendants)
        self.assertIn("dev2", descendants)

    def test_role_summary(self):
        hier = Hierarchy()
        hier.register_node("dev0", HierarchyRole.SUPER)
        hier.register_node("dev1", HierarchyRole.PRIMARY)
        hier.register_node("dev2", HierarchyRole.WORKER)
        summary = hier.get_role_summary()
        self.assertEqual(summary.get("super", 0), 1)
        self.assertEqual(summary.get("primary", 0), 1)
        self.assertEqual(summary.get("worker", 0), 1)


if __name__ == "__main__":
    unittest.main()

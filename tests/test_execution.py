"""Tests for Phase 7 Execution modules."""
from __future__ import annotations

import threading
import time
import unittest

from aether.execution.accelerator import (
    AcceleratorCapabilities,
    AcceleratorManager,
    AcceleratorRuntime,
    AcceleratorType,
    CPUAcceleratorRuntime,
    NPUAcceleratorRuntime,
)
from aether.execution.pipeline import (
    ExecutionState,
    PipelineEngine,
    PipelineGraph,
    Stage,
)
from aether.execution.resource_pool import (
    AllocationStrategy,
    DeviceResources,
    ResourcePoolManager,
    ResourceReservation,
    ResourceType,
)
from aether.execution.simulation import (
    SimulationEnvironment,
    SimulatedPartition,
    SimulationResult,
    VirtualDevice,
)
from aether.execution.topology import (
    DeviceNode,
    OptimizationResult,
    PlacementStrategy,
    TopologyGraph,
    TopologyOptimizer,
)


class TestAcceleratorManager(unittest.TestCase):
    def test_register_cpu(self):
        mgr = AcceleratorManager()
        caps = AcceleratorCapabilities(
            accelerator_type=AcceleratorType.CPU,
            device_id="cpu0",
            model_name="Test CPU",
            peak_tops=10.0,
            memory_mb=4096,
        )
        runtime = mgr.register_capabilities(caps)
        self.assertIsInstance(runtime, CPUAcceleratorRuntime)
        self.assertTrue(runtime.is_available())

    def test_list_available(self):
        mgr = AcceleratorManager()
        caps = AcceleratorCapabilities(
            accelerator_type=AcceleratorType.CPU, device_id="cpu0", model_name="CPU"
        )
        mgr.register_capabilities(caps)
        available = mgr.list_available()
        self.assertIn("cpu0", available)

    def test_select_for_operation(self):
        mgr = AcceleratorManager()
        caps = AcceleratorCapabilities(
            accelerator_type=AcceleratorType.CPU, device_id="cpu0", model_name="CPU"
        )
        mgr.register_capabilities(caps)
        result = mgr.select_for_operation("matmul")
        self.assertIsNotNone(result)
        device_id, runtime = result
        self.assertEqual(device_id, "cpu0")


class TestPipelineEngine(unittest.TestCase):
    def test_create_graph(self):
        engine = PipelineEngine()
        stages = [
            Stage(stage_id="s0", device_id="dev0", layer_indices=[0, 1],
                  input_dtype="float32", output_dtype="float32"),
            Stage(stage_id="s1", device_id="dev1", layer_indices=[2, 3],
                  input_dtype="float32", output_dtype="float32"),
        ]
        graph = engine.create_graph("g0", "model0", stages, [("s0", "s1")])
        self.assertEqual(len(graph.stages), 2)
        self.assertEqual(len(graph.edges), 1)

    def test_get_ready_stages(self):
        engine = PipelineEngine()
        stages = [
            Stage(stage_id="s0", device_id="dev0", layer_indices=[0],
                  input_dtype="float32", output_dtype="float32"),
            Stage(stage_id="s1", device_id="dev1", layer_indices=[1],
                  input_dtype="float32", output_dtype="float32"),
        ]
        engine.create_graph("g0", "m0", stages, [("s0", "s1")])
        ready = engine.get_ready_stages("g0")
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].stage_id, "s0")

    def test_submit_stage(self):
        engine = PipelineEngine()
        stages = [Stage(stage_id="s0", device_id="dev0", layer_indices=[0],
                        input_dtype="float32", output_dtype="float32")]
        engine.create_graph("g0", "m0", stages, [])
        result = engine.submit_stage("g0", "s0")
        self.assertEqual(result.state, ExecutionState.COMPLETED)


class TestResourcePoolManager(unittest.TestCase):
    def test_register_device(self):
        mgr = ResourcePoolManager()
        dev = DeviceResources(
            device_id="dev0", cpu_cores=4, memory_total_mb=4096, memory_available_mb=2048
        )
        mgr.register_device(dev)
        retrieved = mgr.get_device("dev0")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.device_id, "dev0")

    def test_find_best_device(self):
        mgr = ResourcePoolManager()
        mgr.register_device(DeviceResources(
            device_id="dev0", cpu_cores=4, memory_total_mb=4096, memory_available_mb=1024
        ))
        mgr.register_device(DeviceResources(
            device_id="dev1", cpu_cores=8, memory_total_mb=8192, memory_available_mb=4096
        ))
        mgr._strategy = AllocationStrategy.BEST_FIT
        best = mgr.find_best_device(ResourceType.MEMORY, 500.0)
        self.assertEqual(best, "dev0")


class TestTopologyOptimizer(unittest.TestCase):
    def test_build_topology(self):
        optimizer = TopologyOptimizer()
        devices = [
            {"device_id": "dev0", "device_type": "phone", "memory_mb": 4096, "compute_tops": 5.0},
            {"device_id": "dev1", "device_type": "laptop", "memory_mb": 16384, "compute_tops": 20.0},
        ]
        graph = optimizer.build_topology(devices)
        self.assertEqual(len(graph.nodes), 2)

    def test_optimize(self):
        optimizer = TopologyOptimizer()
        devices = [
            {"device_id": "dev0", "device_type": "phone", "memory_mb": 4096, "compute_tops": 5.0},
            {"device_id": "dev1", "device_type": "laptop", "memory_mb": 16384, "compute_tops": 20.0},
        ]
        graph = optimizer.build_topology(devices)
        result = optimizer.optimize(graph, 32)
        self.assertIsInstance(result, OptimizationResult)
        self.assertTrue(result.feasible)
        self.assertGreater(len(result.placements), 0)


class TestSimulationEnvironment(unittest.TestCase):
    def test_simulate_partition(self):
        sim = SimulationEnvironment()
        sim.add_device(VirtualDevice(device_id="dev0", device_type="laptop",
                                     compute_tops=10.0, memory_mb=4096))
        partitions = [SimulatedPartition(device_id="dev0", layers=[0, 1, 2])]
        result = sim.simulate_partition("sim1", partitions)
        self.assertIsInstance(result, SimulationResult)
        self.assertGreater(result.total_latency_ms, 0)

    def test_compare_plans(self):
        sim = SimulationEnvironment()
        sim.add_device(VirtualDevice(device_id="dev0", device_type="laptop", compute_tops=10.0))
        plan_a = [SimulatedPartition(device_id="dev0", layers=[0, 1])]
        plan_b = [SimulatedPartition(device_id="dev0", layers=[0])]
        comparison = sim.compare_plans(plan_a, plan_b)
        self.assertIn("winner", comparison)
        self.assertIn("plan_a_score", comparison)


if __name__ == "__main__":
    unittest.main()

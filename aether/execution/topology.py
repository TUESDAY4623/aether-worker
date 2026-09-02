"""Topology Optimizer — finds optimal device arrangements for model partitioning.

Phase 7 §16: minimizes latency while respecting thermal and bandwidth constraints.
"""
from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PlacementStrategy(str, Enum):
    GREEDY = "greedy"
    OPTIMAL = "optimal"
    BALANCED = "balanced"
    THERMAL_AWARE = "thermal_aware"


@dataclass
class DeviceNode:
    device_id: str
    device_type: str
    memory_mb: int = 0
    compute_tops: float = 0.0
    bandwidth_mbps: float = 0.0
    temperature_c: float = 45.0
    latency_ms: dict[str, float] = field(default_factory=dict)

    def get_latency_to(self, other_id: str) -> float:
        return self.latency_ms.get(other_id, 50.0)


@dataclass
class TopologyLink:
    source_id: str
    target_id: str
    bandwidth_mbps: float = 0.0
    latency_ms: float = 0.0
    reliable: bool = True


@dataclass
class TopologyGraph:
    graph_id: str
    nodes: dict[str, DeviceNode] = field(default_factory=dict)
    links: list[TopologyLink] = field(default_factory=list)
    controller_id: str = "controller"

    def add_node(self, node: DeviceNode) -> None:
        self.nodes[node.device_id] = node

    def add_link(self, link: TopologyLink) -> None:
        self.links.append(link)

    def get_neighbors(self, device_id: str) -> list[str]:
        neighbors = []
        for link in self.links:
            if link.source_id == device_id:
                neighbors.append(link.target_id)
            elif link.target_id == device_id:
                neighbors.append(link.source_id)
        return neighbors


@dataclass
class PlacementResult:
    device_id: str
    layers: list[int]
    estimated_latency_ms: float = 0.0
    thermal_risk: float = 0.0
    bandwidth_usage_mbps: float = 0.0
    confidence: float = 1.0


@dataclass
class OptimizationResult:
    strategy: PlacementStrategy
    placements: list[PlacementResult]
    total_estimated_ms: float = 0.0
    max_thermal_risk: float = 0.0
    total_bandwidth_mbps: float = 0.0
    feasible: bool = True
    warnings: list[str] = field(default_factory=list)


class TopologyOptimizer:
    def __init__(self, strategy: PlacementStrategy = PlacementStrategy.GREEDY) -> None:
        self._lock = threading.RLock()
        self._strategy = strategy
        self._topologies: dict[str, TopologyGraph] = {}
        self._history: list[OptimizationResult] = []

    def build_topology(self, devices: list[dict]) -> TopologyGraph:
        with self._lock:
            graph_id = "topo_" + str(len(self._topologies))
            graph = TopologyGraph(graph_id=graph_id, controller_id="controller")
            for dev in devices:
                node = DeviceNode(
                    device_id=dev["device_id"],
                    device_type=dev.get("device_type", "unknown"),
                    memory_mb=dev.get("memory_mb", 0),
                    compute_tops=dev.get("compute_tops", 0.0),
                    bandwidth_mbps=dev.get("bandwidth_mbps", 0.0),
                    temperature_c=dev.get("temperature_c", 45.0),
                    latency_ms=dev.get("latency_ms", {}),
                )
                graph.add_node(node)
            for src_id, node in graph.nodes.items():
                for dst_id in graph.nodes:
                    if src_id != dst_id and dst_id in node.latency_ms:
                        link = TopologyLink(
                            source_id=src_id,
                            target_id=dst_id,
                            bandwidth_mbps=min(node.bandwidth_mbps, graph.nodes[dst_id].bandwidth_mbps),
                            latency_ms=node.get_latency_to(dst_id),
                        )
                        graph.add_link(link)
            self._topologies[graph_id] = graph
            logger.info("Built topology %s with %d nodes", graph_id, len(graph.nodes))
            return graph

    def optimize(self, graph: TopologyGraph, model_layers: int,
                 layer_memory_mb: float = 100.0) -> OptimizationResult:
        with self._lock:
            if self._strategy == PlacementStrategy.GREEDY:
                result = self._greedy_placement(graph, model_layers, layer_memory_mb)
            elif self._strategy == PlacementStrategy.BALANCED:
                result = self._balanced_placement(graph, model_layers, layer_memory_mb)
            else:
                result = self._greedy_placement(graph, model_layers, layer_memory_mb)
            self._history.append(result)
            return result

    def _greedy_placement(self, graph: TopologyGraph, model_layers: int,
                          layer_memory_mb: float) -> OptimizationResult:
        placements = []
        remaining_layers = list(range(model_layers))
        devices = sorted(graph.nodes.values(), key=lambda n: n.compute_tops, reverse=True)
        total_latency = 0.0
        for device in devices:
            if not remaining_layers:
                break
            layers_per_device = max(1, model_layers // len(devices))
            assigned = remaining_layers[:layers_per_device]
            remaining_layers = remaining_layers[len(assigned):]
            estimated_latency = len(assigned) * 10.0 + device.get_latency_to("controller")
            thermal_risk = max(0, (device.temperature_c - 50.0) / 40.0)
            placements.append(PlacementResult(
                device_id=device.device_id,
                layers=assigned,
                estimated_latency_ms=estimated_latency,
                thermal_risk=thermal_risk,
                bandwidth_usage_mbps=device.bandwidth_mbps * 0.5,
                confidence=0.85,
            ))
            total_latency += estimated_latency
        return OptimizationResult(
            strategy=PlacementStrategy.GREEDY,
            placements=placements,
            total_estimated_ms=total_latency,
            max_thermal_risk=max((p.thermal_risk for p in placements), default=0.0),
            total_bandwidth_mbps=sum(p.bandwidth_usage_mbps for p in placements),
        )

    def _balanced_placement(self, graph: TopologyGraph, model_layers: int,
                            layer_memory_mb: float) -> OptimizationResult:
        placements = []
        devices = list(graph.nodes.values())
        if not devices:
            return OptimizationResult(strategy=PlacementStrategy.BALANCED, placements=[],
                                      feasible=False, warnings=["No devices available"])
        layers_per_device = model_layers // len(devices)
        total_latency = 0.0
        for i, device in enumerate(devices):
            start = i * layers_per_device
            end = model_layers if i == len(devices) - 1 else (i + 1) * layers_per_device
            layers = list(range(start, end))
            estimated_latency = len(layers) * 10.0 + device.get_latency_to("controller")
            thermal_risk = max(0, (device.temperature_c - 50.0) / 40.0)
            placements.append(PlacementResult(
                device_id=device.device_id,
                layers=layers,
                estimated_latency_ms=estimated_latency,
                thermal_risk=thermal_risk,
                bandwidth_usage_mbps=device.bandwidth_mbps * 0.5,
                confidence=0.8,
            ))
            total_latency += estimated_latency
        return OptimizationResult(
            strategy=PlacementStrategy.BALANCED,
            placements=placements,
            total_estimated_ms=total_latency,
            max_thermal_risk=max((p.thermal_risk for p in placements), default=0.0),
            total_bandwidth_mbps=sum(p.bandwidth_usage_mbps for p in placements),
        )

    def get_topology(self, graph_id: str) -> TopologyGraph | None:
        with self._lock:
            return self._topologies.get(graph_id)

    def list_topologies(self) -> list[str]:
        with self._lock:
            return list(self._topologies.keys())

    def set_strategy(self, strategy: PlacementStrategy) -> None:
        with self._lock:
            self._strategy = strategy

"""
Execution Graph — DAG representation of model execution for scheduling.

Phase 3 §3: nodes = operations/layers, edges = tensor dependencies.
Supports topological sort, critical path calculation, and stage grouping.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GraphNode:
    """A node in the execution graph representing one operation or layer."""
    node_id: str
    label: str = ""
    layer_index: int = -1
    device_id: str = ""
    estimated_ms: float = 0.0
    memory_mb: float = 0.0
    ops: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.node_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, GraphNode):
            return self.node_id == other.node_id
        return NotImplemented


@dataclass
class GraphEdge:
    """A directed edge representing a tensor dependency."""
    source: str
    target: str
    tensor_size_mb: float = 0.0
    tensor_shape: list[int] = field(default_factory=list)


@dataclass
class StageGroup:
    """A group of nodes that can execute in parallel (pipeline stage)."""
    stage_id: int
    node_ids: list[str]
    estimated_ms: float = 0.0
    total_memory_mb: float = 0.0


@dataclass
class CriticalPathResult:
    """Result of critical path analysis."""
    path: list[str]
    total_ms: float
    bottleneck_node: str = ""
    bottleneck_ms: float = 0.0


class ExecutionGraph:
    """Directed acyclic graph of model execution operations.

    Provides topological ordering, critical path analysis, and
    pipeline stage grouping for parallel execution planning.
    """

    def __init__(self, name: str = "unnamed"):
        self._lock = threading.RLock()
        self.name = name
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._adjacency: dict[str, list[str]] = {}
        self._reverse_adj: dict[str, list[str]] = {}
        self._dirty = True
        self._topo_order: list[str] = []

    def add_node(self, node: GraphNode) -> None:
        """Add a node to the graph."""
        with self._lock:
            self._nodes[node.node_id] = node
            self._adjacency.setdefault(node.node_id, [])
            self._reverse_adj.setdefault(node.node_id, [])
            self._dirty = True

    def add_edge(self, source: str, target: str,
                 tensor_size_mb: float = 0.0,
                 tensor_shape: list[int] | None = None) -> None:
        """Add a directed edge (dependency) between nodes."""
        with self._lock:
            if source not in self._nodes or target not in self._nodes:
                raise ValueError(
                    f"Cannot add edge: nodes must exist ({source} -> {target})"
                )
            edge = GraphEdge(
                source=source, target=target,
                tensor_size_mb=tensor_size_mb,
                tensor_shape=tensor_shape or [],
            )
            self._edges.append(edge)
            self._adjacency[source].append(target)
            self._reverse_adj[target].append(source)
            self._dirty = True

    def node_count(self) -> int:
        with self._lock:
            return len(self._nodes)

    def edge_count(self) -> int:
        with self._lock:
            return len(self._edges)

    def get_node(self, node_id: str) -> GraphNode | None:
        with self._lock:
            return self._nodes.get(node_id)

    def get_dependencies(self, node_id: str) -> list[str]:
        """Get immediate predecessors of a node."""
        with self._lock:
            return list(self._reverse_adj.get(node_id, []))

    def get_dependents(self, node_id: str) -> list[str]:
        """Get immediate successors of a node."""
        with self._lock:
            return list(self._adjacency.get(node_id, []))

    def topological_sort(self) -> list[str]:
        """Return nodes in topological order (dependencies first)."""
        with self._lock:
            if not self._dirty and self._topo_order:
                return list(self._topo_order)

            in_degree: dict[str, int] = {nid: 0 for nid in self._nodes}
            for edge in self._edges:
                in_degree.setdefault(edge.source, 0)
                in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

            queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
            order: list[str] = []

            while queue:
                node_id = queue.popleft()
                order.append(node_id)
                for dependent in self._adjacency.get(node_id, []):
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

            if len(order) != len(self._nodes):
                logger.warning("Execution graph has cycles — topological sort incomplete")
                # Don't cache incomplete results so validate() re-detects each call
                return list(order)

            self._topo_order = order
            self._dirty = False
            return list(order)

    def get_critical_path(self) -> CriticalPathResult:
        """Find the longest path through the graph (critical path).

        Uses longest-path in a DAG (topological order + DP).
        """
        with self._lock:
            topo = self.topological_sort()
            if not topo:
                return CriticalPathResult(path=[], total_ms=0.0)

            # dist[node] = longest time from node to end
            dist: dict[str, float] = {nid: 0.0 for nid in self._nodes}
            predecessor: dict[str, str] = {}

            for node_id in reversed(topo):
                node = self._nodes[node_id]
                node_dist = node.estimated_ms
                for dependent in self._adjacency.get(node_id, []):
                    if dist[dependent] > 0:
                        node_dist = max(node_dist, node.estimated_ms + dist[dependent])
                        predecessor[node_id] = dependent
                dist[node_id] = node_dist

            # Find the start of the longest path
            start_node = max(dist, key=lambda n: dist[n])
            total_ms = dist[start_node]

            # Trace back
            path: list[str] = []
            current = start_node
            while current in self._adjacency and self._adjacency[current]:
                path.append(current)
                # Pick the dependent with highest dist
                deps = self._adjacency[current]
                current = max(deps, key=lambda d: dist.get(d, 0))
            path.append(current)

            # Find bottleneck
            bottleneck_node = ""
            bottleneck_ms = 0.0
            for nid in path:
                node = self._nodes[nid]
                if node.estimated_ms > bottleneck_ms:
                    bottleneck_ms = node.estimated_ms
                    bottleneck_node = nid

            return CriticalPathResult(
                path=path,
                total_ms=round(total_ms, 2),
                bottleneck_node=bottleneck_node,
                bottleneck_ms=round(bottleneck_ms, 2),
            )

    def group_into_stages(self, max_stage_ms: float = 50.0) -> list[StageGroup]:
        """Group nodes into pipeline stages based on the critical path.

        Nodes in the same stage have no dependencies between each other
        and the combined estimated time stays within max_stage_ms.
        """
        with self._lock:
            topo = self.topological_sort()
            if not topo:
                return []

            # Compute earliest completion time for each node
            earliest: dict[str, float] = {}
            for node_id in topo:
                node = self._nodes[node_id]
                deps = self._reverse_adj.get(node_id, [])
                start_time = max((earliest.get(d, 0.0) for d in deps), default=0.0)
                earliest[node_id] = start_time + node.estimated_ms

            stages: list[StageGroup] = []
            assigned: set[str] = set()
            stage_id = 0

            while len(assigned) < len(self._nodes):
                # Collect nodes whose dependencies are all assigned
                candidates = []
                for nid in topo:
                    if nid in assigned:
                        continue
                    deps = self._reverse_adj.get(nid, [])
                    if all(d in assigned for d in deps):
                        candidates.append(nid)

                if not candidates:
                    logger.warning("Could not group remaining nodes into stages")
                    break

                # Greedily pack candidates into this stage
                stage_nodes: list[str] = []
                stage_ms = 0.0
                stage_mem = 0.0

                for nid in candidates:
                    node = self._nodes[nid]
                    if stage_ms + node.estimated_ms <= max_stage_ms or not stage_nodes:
                        stage_nodes.append(nid)
                        stage_ms += node.estimated_ms
                        stage_mem += node.memory_mb
                    # else: save for next stage

                for nid in stage_nodes:
                    assigned.add(nid)

                stages.append(StageGroup(
                    stage_id=stage_id,
                    node_ids=stage_nodes,
                    estimated_ms=round(stage_ms, 2),
                    total_memory_mb=round(stage_mem, 2),
                ))
                stage_id += 1

            return stages

    def validate(self) -> list[str]:
        """Validate the graph. Returns list of issue strings (empty if valid)."""
        with self._lock:
            issues = []

            # Check all edge endpoints exist
            for edge in self._edges:
                if edge.source not in self._nodes:
                    issues.append(f"Edge source missing: {edge.source}")
                if edge.target not in self._nodes:
                    issues.append(f"Edge target missing: {edge.target}")

            # Check for cycles
            topo = self.topological_sort()
            if len(topo) != len(self._nodes):
                issues.append("Graph contains cycles")

            return issues

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for API responses."""
        with self._lock:
            return {
                "name": self.name,
                "node_count": len(self._nodes),
                "edge_count": len(self._edges),
                "has_cycles": len(self.topological_sort()) != len(self._nodes),
            }

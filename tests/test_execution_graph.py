"""
Tests for aether.model.execution_graph — Execution Graph DAG.
"""
from __future__ import annotations

import unittest

from aether.model.execution_graph import (
    ExecutionGraph, GraphNode, GraphEdge, StageGroup, CriticalPathResult,
)


class TestGraphNode(unittest.TestCase):
    def test_create_node(self):
        n = GraphNode(node_id="n0", label="input", estimated_ms=10.0)
        assert n.node_id == "n0"
        assert n.estimated_ms == 10.0

    def test_node_hash(self):
        n1 = GraphNode(node_id="n0")
        n2 = GraphNode(node_id="n0")
        assert hash(n1) == hash(n2)
        assert n1 == n2

    def test_node_defaults(self):
        n = GraphNode(node_id="n0")
        assert n.label == ""
        assert n.layer_index == -1
        assert n.device_id == ""
        assert n.ops == []


class TestGraphEdge(unittest.TestCase):
    def test_create_edge(self):
        e = GraphEdge(source="n0", target="n1", tensor_size_mb=4.0)
        assert e.source == "n0"
        assert e.tensor_size_mb == 4.0

    def test_edge_defaults(self):
        e = GraphEdge(source="n0", target="n1")
        assert e.tensor_size_mb == 0.0
        assert e.tensor_shape == []


class TestStageGroup(unittest.TestCase):
    def test_create_stage(self):
        sg = StageGroup(stage_id=0, node_ids=["n0", "n1"], estimated_ms=20.0)
        assert sg.stage_id == 0
        assert len(sg.node_ids) == 2

    def test_stage_defaults(self):
        sg = StageGroup(stage_id=1, node_ids=["n2"])
        assert sg.estimated_ms == 0.0
        assert sg.total_memory_mb == 0.0


class TestCriticalPathResult(unittest.TestCase):
    def test_create(self):
        cpr = CriticalPathResult(path=["a", "b", "c"], total_ms=50.0, bottleneck_node="b")
        assert cpr.total_ms == 50.0
        assert cpr.bottleneck_node == "b"


class TestExecutionGraph(unittest.TestCase):
    def test_add_nodes(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n0", estimated_ms=10.0))
        g.add_node(GraphNode(node_id="n1", estimated_ms=20.0))
        assert g.node_count() == 2

    def test_add_edge(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n0"))
        g.add_node(GraphNode(node_id="n1"))
        g.add_edge("n0", "n1")
        assert g.edge_count() == 1

    def test_add_edge_missing_node_raises(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n0"))
        with self.assertRaises(ValueError):
            g.add_edge("n0", "nonexistent")

    def test_topological_sort_linear(self):
        g = ExecutionGraph("linear")
        for i in range(5):
            g.add_node(GraphNode(node_id=f"n{i}", estimated_ms=float(i)))
        for i in range(4):
            g.add_edge(f"n{i}", f"n{i+1}")
        order = g.topological_sort()
        assert order == ["n0", "n1", "n2", "n3", "n4"]

    def test_topological_sort_branching(self):
        g = ExecutionGraph("branch")
        g.add_node(GraphNode(node_id="n0"))
        g.add_node(GraphNode(node_id="n1"))
        g.add_node(GraphNode(node_id="n2"))
        g.add_node(GraphNode(node_id="n3"))
        g.add_edge("n0", "n1")
        g.add_edge("n0", "n2")
        g.add_edge("n1", "n3")
        g.add_edge("n2", "n3")
        order = g.topological_sort()
        assert order[0] == "n0"
        assert order[-1] == "n3"
        assert order.index("n1") < order.index("n3")
        assert order.index("n2") < order.index("n3")

    def test_topological_sort_cached(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n0"))
        g.add_node(GraphNode(node_id="n1"))
        g.add_edge("n0", "n1")
        first = g.topological_sort()
        second = g.topological_sort()
        assert first == second

    def test_get_dependencies(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n1"))
        g.add_node(GraphNode(node_id="n2"))
        g.add_node(GraphNode(node_id="n3"))
        g.add_edge("n1", "n2")
        g.add_edge("n1", "n3")
        deps = g.get_dependencies("n2")
        assert "n1" in deps

    def test_get_dependents(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n1"))
        g.add_node(GraphNode(node_id="n2"))
        g.add_edge("n1", "n2")
        deps = g.get_dependents("n1")
        assert "n2" in deps

    def test_get_dependencies_nonexistent(self):
        g = ExecutionGraph("test")
        deps = g.get_dependencies("missing")
        assert deps == []

    def test_critical_path(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="a", estimated_ms=10.0))
        g.add_node(GraphNode(node_id="b", estimated_ms=20.0))
        g.add_node(GraphNode(node_id="c", estimated_ms=5.0))
        g.add_node(GraphNode(node_id="d", estimated_ms=15.0))
        g.add_edge("a", "b")
        g.add_edge("b", "d")
        g.add_edge("a", "c")
        g.add_edge("c", "d")
        result = g.get_critical_path()
        assert result.total_ms > 0
        assert len(result.path) > 0
        assert result.bottleneck_node != ""

    def test_critical_path_empty(self):
        g = ExecutionGraph("empty")
        result = g.get_critical_path()
        assert result.total_ms == 0.0
        assert result.path == []

    def test_critical_path_bottleneck(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="a", estimated_ms=5.0))
        g.add_node(GraphNode(node_id="b", estimated_ms=50.0))
        g.add_node(GraphNode(node_id="c", estimated_ms=5.0))
        g.add_edge("a", "b")
        g.add_edge("b", "c")
        result = g.get_critical_path()
        assert result.bottleneck_node == "b"
        assert result.bottleneck_ms == 50.0

    def test_group_into_stages(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="a", estimated_ms=10.0))
        g.add_node(GraphNode(node_id="b", estimated_ms=10.0))
        g.add_node(GraphNode(node_id="c", estimated_ms=10.0))
        g.add_edge("a", "c")
        g.add_edge("b", "c")
        stages = g.group_into_stages(max_stage_ms=25.0)
        assert len(stages) >= 2
        assert stages[0].stage_id == 0

    def test_group_into_stages_empty(self):
        g = ExecutionGraph("empty")
        stages = g.group_into_stages()
        assert stages == []

    def test_group_into_stages_single_node(self):
        g = ExecutionGraph("single")
        g.add_node(GraphNode(node_id="a", estimated_ms=5.0))
        stages = g.group_into_stages()
        assert len(stages) == 1
        assert stages[0].node_ids == ["a"]

    def test_validate_no_issues(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n0"))
        g.add_node(GraphNode(node_id="n1"))
        g.add_edge("n0", "n1")
        issues = g.validate()
        assert issues == []

    def test_validate_missing_edge_node(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n0"))
        g._edges.append(GraphEdge(source="n0", target="missing"))
        issues = g.validate()
        assert len(issues) > 0

    def test_validate_detects_cycles(self):
        g = ExecutionGraph("cyclic")
        g.add_node(GraphNode(node_id="a"))
        g.add_node(GraphNode(node_id="b"))
        g.add_edge("a", "b")
        g.add_edge("b", "a")
        issues = g.validate()
        assert any("cycle" in i.lower() for i in issues)

    def test_summary(self):
        g = ExecutionGraph("test_graph")
        g.add_node(GraphNode(node_id="n0"))
        g.add_node(GraphNode(node_id="n1"))
        g.add_edge("n0", "n1")
        s = g.summary()
        assert s["name"] == "test_graph"
        assert s["node_count"] == 2
        assert s["edge_count"] == 1
        assert s["has_cycles"] is False

    def test_get_node(self):
        g = ExecutionGraph("test")
        g.add_node(GraphNode(node_id="n0", label="first", estimated_ms=5.0))
        node = g.get_node("n0")
        assert node is not None
        assert node.label == "first"
        assert g.get_node("missing") is None


if __name__ == "__main__":
    unittest.main()

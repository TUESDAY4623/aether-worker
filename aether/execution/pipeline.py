"""Pipeline Parallel Execution Engine — splits model layers across devices.

Phase 7 §11: core scheduling primitive for distributed inference.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ExecutionState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Stage:
    stage_id: str
    device_id: str
    layer_indices: list[int]
    input_dtype: str
    output_dtype: str
    estimated_ms: float = 0.0
    state: ExecutionState = ExecutionState.PENDING
    result: Any = None
    error: str | None = None


@dataclass
class StageResult:
    stage_id: str
    state: ExecutionState
    output: Any = None
    error: str | None = None
    latency_ms: float = 0.0


@dataclass
class PipelineGraph:
    graph_id: str
    model_id: str
    stages: list[Stage]
    edges: list[tuple[str, str]]
    estimated_total_ms: float = 0.0

    def get_stage(self, stage_id: str) -> Stage | None:
        for s in self.stages:
            if s.stage_id == stage_id:
                return s
        return None

    def get_upstream(self, stage_id: str) -> list[Stage]:
        upstream_ids = {src for src, dst in self.edges if dst == stage_id}
        return [s for s in self.stages if s.stage_id in upstream_ids]


class PipelineEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._graphs: dict[str, PipelineGraph] = {}

    def create_graph(self, graph_id: str, model_id: str, stages: list[Stage],
                     edges: list[tuple[str, str]]) -> PipelineGraph:
        with self._lock:
            graph = PipelineGraph(
                graph_id=graph_id,
                model_id=model_id,
                stages=stages,
                edges=edges,
            )
            self._graphs[graph_id] = graph
            logger.info("Created pipeline graph %s with %d stages", graph_id, len(stages))
            return graph

    def get_graph(self, graph_id: str) -> PipelineGraph | None:
        with self._lock:
            return self._graphs.get(graph_id)

    def submit_stage(self, graph_id: str, stage_id: str) -> StageResult:
        with self._lock:
            graph = self._graphs.get(graph_id)
            if not graph:
                return StageResult(stage_id=stage_id, state=ExecutionState.FAILED,
                                   error="Graph not found")
            stage = graph.get_stage(stage_id)
            if not stage:
                return StageResult(stage_id=stage_id, state=ExecutionState.FAILED,
                                   error="Stage not found")
            stage.state = ExecutionState.RUNNING
            stage.result = stage.layer_indices
            stage.state = ExecutionState.COMPLETED
            logger.info("Stage %s completed on device %s", stage_id, stage.device_id)
            return StageResult(stage_id=stage_id, state=ExecutionState.COMPLETED,
                               output=stage.layer_indices)

    def get_ready_stages(self, graph_id: str) -> list[Stage]:
        with self._lock:
            graph = self._graphs.get(graph_id)
            if not graph:
                return []
            ready = []
            for stage in graph.stages:
                if stage.state != ExecutionState.PENDING:
                    continue
                upstream = graph.get_upstream(stage.stage_id)
                if all(s.state == ExecutionState.COMPLETED for s in upstream):
                    ready.append(stage)
            return ready

    def get_graph_status(self, graph_id: str) -> dict[str, Any]:
        with self._lock:
            graph = self._graphs.get(graph_id)
            if not graph:
                return {}
            counts = {}
            for state in ExecutionState:
                counts[state.value] = sum(1 for s in graph.stages if s.state == state)
            return {
                "graph_id": graph_id,
                "model_id": graph.model_id,
                "total_stages": len(graph.stages),
                "state_counts": counts,
                "estimated_total_ms": graph.estimated_total_ms,
            }

    def cancel_graph(self, graph_id: str) -> bool:
        with self._lock:
            graph = self._graphs.get(graph_id)
            if not graph:
                return False
            for stage in graph.stages:
                if stage.state in (ExecutionState.PENDING, ExecutionState.READY):
                    stage.state = ExecutionState.CANCELLED
            logger.info("Cancelled pipeline graph %s", graph_id)
            return True

    def list_graphs(self) -> list[str]:
        with self._lock:
            return list(self._graphs.keys())

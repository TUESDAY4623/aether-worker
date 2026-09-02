"""
Workload Analyzer — characterizes AI workloads for the planner.

Phase 5 §7 + §8: analyzes model architecture, context length, expected
output length, token generation patterns. Detects workload phase changes.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class WorkloadPhase(str, Enum):
    """Phases of an inference workload."""
    IDLE = "idle"
    PREFILL = "prefill"
    DECODE = "decode"
    MIXED = "mixed"
    COMPLETED = "completed"


class WorkloadType(str, Enum):
    """Types of AI workloads."""
    CHAT = "chat"
    COMPLETION = "completion"
    CODE_GENERATION = "code_generation"
    EMBEDDING = "embedding"
    CLASSIFICATION = "classification"
    SUMMARIZATION = "summarization"


@dataclass
class WorkloadProfile:
    """Complete characterization of an AI workload."""
    workload_id: str
    workload_type: WorkloadType = WorkloadType.CHAT
    model_id: str = ""
    model_architecture: str = "transformer"
    context_length: int = 4096
    expected_output_length: int = 512
    batch_size: int = 1
    concurrent_sessions: int = 1
    estimated_prefill_ms: float = 0.0
    estimated_decode_ms_per_token: float = 0.0
    estimated_total_ms: float = 0.0
    memory_requirements_mb: int = 0
    kv_cache_requirements_mb: int = 0
    requires_quantization: bool = False
    preferred_accelerator: str = "cpu"
    is_memory_bound: bool = False
    is_compute_bound: bool = False
    is_io_bound: bool = False
    current_phase: WorkloadPhase = WorkloadPhase.IDLE
    tokens_generated: int = 0
    total_tokens_expected: int = 0

    def __post_init__(self):
        if self.total_tokens_expected == 0:
            self.total_tokens_expected = self.expected_output_length
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "workload_type": self.workload_type.value,
            "model_id": self.model_id,
            "model_architecture": self.model_architecture,
            "context_length": self.context_length,
            "expected_output_length": self.expected_output_length,
            "batch_size": self.batch_size,
            "concurrent_sessions": self.concurrent_sessions,
            "estimated_prefill_ms": round(self.estimated_prefill_ms, 2),
            "estimated_decode_ms_per_token": round(self.estimated_decode_ms_per_token, 2),
            "estimated_total_ms": round(self.estimated_total_ms, 2),
            "memory_requirements_mb": self.memory_requirements_mb,
            "kv_cache_requirements_mb": self.kv_cache_requirements_mb,
            "requires_quantization": self.requires_quantization,
            "preferred_accelerator": self.preferred_accelerator,
            "is_memory_bound": self.is_memory_bound,
            "is_compute_bound": self.is_compute_bound,
            "is_io_bound": self.is_io_bound,
            "current_phase": self.current_phase.value,
            "tokens_generated": self.tokens_generated,
            "total_tokens_expected": self.total_tokens_expected,
            "progress_pct": round(
                self.tokens_generated / max(self.total_tokens_expected, 1) * 100, 1
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class WorkloadAnalyzer:
    """Analyzes AI workloads to produce structured workload profiles.

    Provides workload characterization and runtime phase detection
    for adaptive scheduling and resource allocation.
    """

    # Heuristic estimates (ms) for different model sizes
    PREFILL_ESTIMATES = {
        "2b": 50.0,
        "7b": 200.0,
        "8b": 220.0,
        "13b": 400.0,
        "70b": 2000.0,
    }
    DECODE_ESTIMATES = {
        "2b": 8.0,
        "7b": 20.0,
        "8b": 22.0,
        "13b": 40.0,
        "70b": 150.0,
    }

    def __init__(self):
        self._lock = threading.RLock()
        self._profiles: dict[str, WorkloadProfile] = {}
        self._phase_history: dict[str, list[tuple[float, WorkloadPhase]]] = {}

    def analyze(
        self,
        workload_id: str,
        model_id: str = "",
        context_length: int = 4096,
        expected_output_length: int = 512,
        workload_type: str = "chat",
        model_size_b: float = 7.0,
        batch_size: int = 1,
        concurrent_sessions: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> WorkloadProfile:
        """Analyze a workload and produce a structured profile."""
        with self._lock:
            metadata = metadata or {}
            wt = WorkloadType(workload_type) if workload_type in [e.value for e in WorkloadType] else WorkloadType.CHAT

            size_key = self._closest_size_key(model_size_b)
            prefill_ms = self.PREFILL_ESTIMATES.get(size_key, 200.0)
            decode_ms = self.DECODE_ESTIMATES.get(size_key, 20.0)

            # Adjust for batch size and concurrency
            prefill_ms *= (1.0 + (batch_size - 1) * 0.5)
            decode_ms *= (1.0 + (batch_size - 1) * 0.3)
            prefill_ms *= (1.0 + (concurrent_sessions - 1) * 0.2)

            # KV cache estimate: 2 bytes per token per layer, ~32 layers
            kv_cache_mb = (
                context_length * 2 * 32 * 2 * 2 / (1024 * 1024)
            ) * batch_size * concurrent_sessions

            memory_mb = int(
                model_size_b * 1000 * 0.25  # int4 estimate
                + kv_cache_mb * 0.5
            )

            is_memory = memory_mb > 6000
            is_compute = decode_ms > 50.0
            is_io = context_length > 8192

            preferred = "cpu"
            if model_size_b <= 7.0:
                preferred = "npu"
            elif model_size_b <= 13.0:
                preferred = "gpu" if metadata.get("gpu_available") else "npu"

            profile = WorkloadProfile(
                workload_id=workload_id,
                workload_type=wt,
                model_id=model_id,
                model_architecture=metadata.get("architecture", "transformer"),
                context_length=context_length,
                expected_output_length=expected_output_length,
                batch_size=batch_size,
                concurrent_sessions=concurrent_sessions,
                estimated_prefill_ms=round(prefill_ms, 1),
                estimated_decode_ms_per_token=round(decode_ms, 2),
                estimated_total_ms=round(prefill_ms + decode_ms * expected_output_length, 1),
                memory_requirements_mb=memory_mb,
                kv_cache_requirements_mb=int(kv_cache_mb),
                requires_quantization=model_size_b > 7.0,
                preferred_accelerator=preferred,
                is_memory_bound=is_memory,
                is_compute_bound=is_compute,
                is_io_bound=is_io,
                total_tokens_expected=expected_output_length,
            )
            self._profiles[workload_id] = profile
            logger.info(
                "Analyzed workload %s: %s, %d MB, %.0f ms",
                workload_id, wt.value, memory_mb, profile.estimated_total_ms,
            )
            return profile

    def detect_phase_change(
        self, workload_id: str, tokens_generated: int,
        is_prefill_active: bool = False,
    ) -> WorkloadPhase:
        """Detect the current workload phase based on generation progress."""
        with self._lock:
            profile = self._profiles.get(workload_id)
            if not profile:
                return WorkloadPhase.IDLE

            if is_prefill_active and tokens_generated == 0:
                new_phase = WorkloadPhase.PREFILL
            elif tokens_generated == 0:
                new_phase = WorkloadPhase.PREFILL
            elif tokens_generated >= profile.total_tokens_expected:
                new_phase = WorkloadPhase.COMPLETED
            elif tokens_generated > 0 and profile.current_phase == WorkloadPhase.PREFILL:
                new_phase = WorkloadPhase.MIXED
            else:
                new_phase = WorkloadPhase.DECODE

            old_phase = profile.current_phase
            profile.current_phase = new_phase
            profile.tokens_generated = tokens_generated
            profile.updated_at = time.time()

            if new_phase != old_phase:
                history = self._phase_history.setdefault(workload_id, [])
                history.append((time.time(), new_phase))
                logger.debug("Workload %s: %s -> %s", workload_id, old_phase.value, new_phase.value)

            return new_phase

    def get_profile(self, workload_id: str) -> WorkloadProfile | None:
        with self._lock:
            return self._profiles.get(workload_id)

    def list_profiles(self) -> list[str]:
        with self._lock:
            return list(self._profiles.keys())

    def get_phase_history(self, workload_id: str) -> list[tuple[float, str]]:
        with self._lock:
            history = self._phase_history.get(workload_id, [])
            return [(ts, phase.value) for ts, phase in history]

    def _closest_size_key(self, size_b: float) -> str:
        sizes = [2, 7, 8, 13, 70]
        closest = min(sizes, key=lambda s: abs(s - size_b))
        return str(closest)

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(
                1 for p in self._profiles.values()
                if p.current_phase not in (WorkloadPhase.IDLE, WorkloadPhase.COMPLETED)
            )

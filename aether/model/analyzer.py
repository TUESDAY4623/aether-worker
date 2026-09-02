"""
Model Analyzer — inspects model descriptions to produce structured analysis.

Phase 2 §2 + Phase 3 §1: analyzes parameter count, layers, tensor dims,
quantization compatibility, operator dependencies, and backend compatibility.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aether.model.capability_registry import (
    ModelCapabilities, ModelCapabilityRegistry,
    ArchitectureFamily, QuantizationFormat, DataType,
    DistributedCompatibility,
)

logger = logging.getLogger(__name__)


class BackendSupport(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


@dataclass
class LayerInfo:
    """Describes a single model layer."""
    index: int
    name: str = ""
    layer_type: str = ""
    param_count: int = 0
    output_shape: list[int] = field(default_factory=list)
    required_ops: list[str] = field(default_factory=list)
    byte_size: int = 0
    quantizable: bool = True
    notes: str = ""


@dataclass
class AnalyzeResult:
    """Full analysis result for a model."""
    model_id: str
    model_name: str = ""
    total_params: int = 0
    layer_count: int = 0
    layers: list[LayerInfo] = field(default_factory=list)
    quantization_format: str = "int4"
    estimated_fp16_mb: float = 0.0
    estimated_int4_mb: float = 0.0
    required_operators: list[str] = field(default_factory=list)
    architecture_family: str = "unknown"
    backend_support: dict[str, BackendSupport] = field(default_factory=dict)
    distributed_compatibility: str = "none"
    supported_runtimes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "total_params": self.total_params,
            "layer_count": self.layer_count,
            "layers": [
                {
                    "index": l.index, "name": l.name, "layer_type": l.layer_type,
                    "param_count": l.param_count, "output_shape": l.output_shape,
                    "required_ops": l.required_ops, "byte_size": l.byte_size,
                    "quantizable": l.quantizable, "notes": l.notes,
                }
                for l in self.layers
            ],
            "quantization_format": self.quantization_format,
            "estimated_fp16_mb": self.estimated_fp16_mb,
            "estimated_int4_mb": self.estimated_int4_mb,
            "required_operators": self.required_operators,
            "architecture_family": self.architecture_family,
            "backend_support": {k: v.value for k, v in self.backend_support.items()},
            "distributed_compatibility": self.distributed_compatibility,
            "supported_runtimes": self.supported_runtimes,
            "notes": self.notes,
        }


class ModelAnalyzer:
    """Analyzes model descriptions to produce structured analysis results.

    Uses the capability registry for backend compatibility checks.
    Falls back to heuristic analysis when a model is not in the registry.
    """

    def __init__(self, capability_registry: ModelCapabilityRegistry | None = None):
        self._lock = threading.RLock()
        self._registry = capability_registry
        self._analysis_cache: dict[str, AnalyzeResult] = {}

    def set_registry(self, registry: ModelCapabilityRegistry) -> None:
        """Set or update the capability registry."""
        with self._lock:
            self._registry = registry

    def analyze(self, model_id: str, layers: list[dict],
                quantization: str = "int4",
                metadata: dict[str, Any] | None = None) -> AnalyzeResult:
        """Analyze a model from its layer description.

        Args:
            model_id: Unique model identifier.
            layers: List of layer dicts with keys: name, type, params,
                    shape, ops, byte_size.
            quantization: Target quantization format.
            metadata: Optional extra model metadata (architecture, runtimes, etc.).

        Returns:
            AnalyzeResult with complete analysis.
        """
        with self._lock:
            if model_id in self._analysis_cache:
                cached = self._analysis_cache[model_id]
                logger.debug("Returning cached analysis for %s", model_id)
                return cached

            result = self._do_analyze(model_id, layers, quantization, metadata)
            self._analysis_cache[model_id] = result
            logger.info("Analyzed %s: %d layers, %d params, %.1f MB (int4)",
                        model_id, result.layer_count, result.total_params,
                        result.estimated_int4_mb)
            return result

    def _do_analyze(self, model_id: str, layers: list[dict],
                    quantization: str,
                    metadata: dict[str, Any] | None) -> AnalyzeResult:
        """Perform the actual analysis."""
        metadata = metadata or {}
        model_name = metadata.get("model_name", model_id)

        # Check capability registry first
        profile = None
        if self._registry:
            profile = self._registry.get(model_id)

        # Build layer info
        layer_infos = []
        all_ops: set[str] = set()
        total_params = 0
        total_fp16_bytes = 0
        total_int4_bytes = 0

        for i, layer in enumerate(layers):
            li = LayerInfo(
                index=i,
                name=layer.get("name", f"layer_{i}"),
                layer_type=layer.get("type", layer.get("layer_type", "unknown")),
                param_count=layer.get("params", 0),
                output_shape=layer.get("shape", []),
                required_ops=layer.get("ops", []),
                byte_size=layer.get("byte_size", 0),
                quantizable=layer.get("quantizable", True),
            )
            layer_infos.append(li)
            total_params += li.param_count
            all_ops.update(li.required_ops)

            # Estimate sizes if not provided
            if li.byte_size == 0 and li.param_count > 0:
                li.byte_size = li.param_count * 2  # fp16 default
            total_fp16_bytes += li.byte_size
            # int4 is ~0.25x fp16
            total_int4_bytes += li.byte_size // 4

        # Quantization size estimates
        quant_ratio = self._quant_ratio(quantization)
        estimated_fp16_mb = total_fp16_bytes / (1024 * 1024)
        estimated_int4_mb = (total_fp16_bytes * quant_ratio) / (1024 * 1024)

        # Backend support
        backend_support = self._assess_backend_support(all_ops, profile)

        # Distributed compatibility
        dist_compat = "none"
        supported_runtimes = []
        architecture_family = "unknown"
        if profile:
            dist_compat = profile.distributed_compatibility.value
            supported_runtimes = profile.supported_runtimes
            architecture_family = profile.architecture_family.value
        elif metadata:
            dist_compat = metadata.get("distributed_compatibility", "none")
            supported_runtimes = metadata.get("supported_runtimes", [])
            architecture_family = metadata.get("architecture_family", "unknown")

        notes = []
        if total_params > 1_000_000_000:
            notes.append("Model exceeds 1B parameters — distributed execution strongly recommended")
        if estimated_int4_mb > 8000:
            notes.append("Int4 model exceeds 8 GB — will require multi-device placement")
        if not supported_runtimes:
            notes.append("No runtime profiles registered — using heuristic estimates")

        return AnalyzeResult(
            model_id=model_id,
            model_name=model_name,
            total_params=total_params,
            layer_count=len(layers),
            layers=layer_infos,
            quantization_format=quantization,
            estimated_fp16_mb=round(estimated_fp16_mb, 1),
            estimated_int4_mb=round(estimated_int4_mb, 1),
            required_operators=sorted(all_ops),
            architecture_family=architecture_family,
            backend_support=backend_support,
            distributed_compatibility=dist_compat,
            supported_runtimes=supported_runtimes,
            notes=notes,
        )

    def _quant_ratio(self, fmt: str) -> float:
        """Return bytes-per-param ratio relative to fp16 for a quantization format."""
        ratios = {
            "fp16": 1.0, "bf16": 1.0,
            "int8": 0.5, "int4": 0.25,
            "gptq": 0.25, "awq": 0.25,
            "gguf_q4": 0.25, "gguf_q8": 0.5,
        }
        return ratios.get(fmt.lower(), 0.5)

    def _assess_backend_support(self, ops: set[str],
                                profile: ModelCapabilities | None) -> dict[str, BackendSupport]:
        """Assess which backends can handle the required operators."""
        backends = {
            "cpu": BackendSupport.FULL,
            "npu": BackendSupport.PARTIAL,
            "gpu": BackendSupport.PARTIAL,
        }

        # If we have a profile, check preferred accelerators
        if profile:
            for backend in backends:
                if backend in profile.preferred_accelerators:
                    backends[backend] = BackendSupport.FULL
                else:
                    backends[backend] = BackendSupport.NONE

        # NPU/GPU typically can't handle every custom op
        unsupported_on_accel = {"expert_routing", "custom_flash_attention"}
        if unsupported_on_accel & ops:
            for backend in ("npu", "gpu"):
                if backends[backend] == BackendSupport.FULL:
                    backends[backend] = BackendSupport.PARTIAL

        return backends

    def clear_cache(self) -> None:
        """Clear the analysis cache."""
        with self._lock:
            self._analysis_cache.clear()

    @property
    def cached_count(self) -> int:
        with self._lock:
            return len(self._analysis_cache)

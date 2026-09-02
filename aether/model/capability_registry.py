"""
Model Capability Registry — machine-readable profiles for every supported model.

Phase 7 §6-7: capability-driven model integration system.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class QuantizationFormat(str, Enum):
    FP32 = "fp32"
    FP16 = "fp16"
    BF16 = "bf16"
    INT8 = "int8"
    INT4 = "int4"
    GPTQ = "gptq"
    AWQ = "awq"
    GGUF_Q4 = "gguf_q4"
    GGUF_Q8 = "gguf_q8"


class ArchitectureFamily(str, Enum):
    TRANSFORMER = "transformer"
    LLAMA = "llama"
    MISTRAL = "mistral"
    GEMMA = "gemma"
    PHI = "phi"
    BERT = "bert"
    WHISPER = "whisper"
    MOE = "moe"
    DIFFUSION = "diffusion"


class DistributedCompatibility(str, Enum):
    NONE = "none"
    PIPELINE = "pipeline"
    TENSOR = "tensor"
    HYBRID = "hybrid"
    EXPERT = "expert"


class DataType(str, Enum):
    FLOAT32 = "float32"
    FLOAT16 = "float16"
    BFLOAT16 = "bfloat16"
    INT8 = "int8"
    INT4 = "int4"


@dataclass
class ModelCapabilities:
    """Machine-readable capability profile for a model."""

    model_id: str
    model_name: str
    architecture_family: ArchitectureFamily
    supported_runtimes: list[str] = field(default_factory=list)
    supported_data_types: list[DataType] = field(default_factory=list)
    quantization_formats: list[QuantizationFormat] = field(default_factory=list)
    required_operators: list[str] = field(default_factory=list)
    preferred_accelerators: list[str] = field(default_factory=list)
    minimum_memory_mb: int = 0
    distributed_compatibility: DistributedCompatibility = DistributedCompatibility.NONE
    known_limitations: list[str] = field(default_factory=list)
    context_length_profile: dict[str, int] = field(default_factory=dict)
    memory_footprint_mb: dict[str, int] = field(default_factory=dict)
    optimization_profiles: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "architecture_family": self.architecture_family.value,
            "supported_runtimes": self.supported_runtimes,
            "supported_data_types": [dt.value for dt in self.supported_data_types],
            "quantization_formats": [qf.value for qf in self.quantization_formats],
            "required_operators": self.required_operators,
            "preferred_accelerators": self.preferred_accelerators,
            "minimum_memory_mb": self.minimum_memory_mb,
            "distributed_compatibility": self.distributed_compatibility.value,
            "known_limitations": self.known_limitations,
            "context_length_profile": self.context_length_profile,
            "memory_footprint_mb": self.memory_footprint_mb,
            "optimization_profiles": self.optimization_profiles,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelCapabilities:
        return cls(
            model_id=data["model_id"],
            model_name=data["model_name"],
            architecture_family=ArchitectureFamily(data["architecture_family"]),
            supported_runtimes=data.get("supported_runtimes", []),
            supported_data_types=[DataType(dt) for dt in data.get("supported_data_types", [])],
            quantization_formats=[QuantizationFormat(qf) for qf in data.get("quantization_formats", [])],
            required_operators=data.get("required_operators", []),
            preferred_accelerators=data.get("preferred_accelerators", []),
            minimum_memory_mb=data.get("minimum_memory_mb", 0),
            distributed_compatibility=DistributedCompatibility(data.get("distributed_compatibility", "none")),
            known_limitations=data.get("known_limitations", []),
            context_length_profile=data.get("context_length_profile", {}),
            memory_footprint_mb=data.get("memory_footprint_mb", {}),
            optimization_profiles=data.get("optimization_profiles", {}),
        )


class ModelCapabilityRegistry:
    """Thread-safe registry of model capability profiles."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._profiles: dict[str, ModelCapabilities] = {}

    def register(self, profile: ModelCapabilities) -> None:
        with self._lock:
            self._profiles[profile.model_id] = profile
            logger.info("Registered model capability: %s (%s)", profile.model_id, profile.model_name)

    def unregister(self, model_id: str) -> None:
        with self._lock:
            self._profiles.pop(model_id, None)

    def get(self, model_id: str) -> ModelCapabilities | None:
        with self._lock:
            return self._profiles.get(model_id)

    def list_all(self) -> list[ModelCapabilities]:
        with self._lock:
            return list(self._profiles.values())

    def list_supported(self, runtime: str | None = None, accelerator: str | None = None,
                       max_memory_mb: int = 0) -> list[ModelCapabilities]:
        with self._lock:
            results = []
            for profile in self._profiles.values():
                if runtime and runtime not in profile.supported_runtimes:
                    continue
                if accelerator and accelerator not in profile.preferred_accelerators:
                    continue
                if max_memory_mb > 0 and profile.minimum_memory_mb > max_memory_mb:
                    continue
                results.append(profile)
            return results

    def get_distributed_compatible(self, compatibility: DistributedCompatibility | None = None
                                    ) -> list[ModelCapabilities]:
        with self._lock:
            target = compatibility or DistributedCompatibility.PIPELINE
            return [p for p in self._profiles.values()
                    if p.distributed_compatibility != DistributedCompatibility.NONE
                    and (compatibility is None or p.distributed_compatibility == target)]

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {mid: p.to_dict() for mid, p in self._profiles.items()}

    def load_from_dict(self, data: dict[str, Any]) -> None:
        with self._lock:
            for model_id, profile_data in data.items():
                self._profiles[model_id] = ModelCapabilities.from_dict(profile_data)

    def count(self) -> int:
        with self._lock:
            return len(self._profiles)


def register_builtin_models(registry: ModelCapabilityRegistry) -> None:
    """Register well-known model capability profiles."""

    registry.register(ModelCapabilities(
        model_id="llama3-8b",
        model_name="LLaMA 3 8B",
        architecture_family=ArchitectureFamily.LLAMA,
        supported_runtimes=["llama.cpp", "ollama", "vllm", "mlc"],
        supported_data_types=[DataType.FLOAT16, DataType.BFLOAT16, DataType.INT8, DataType.INT4],
        quantization_formats=[QuantizationFormat.INT4, QuantizationFormat.INT8, QuantizationFormat.FP16],
        required_operators=["embedding", "attention", "ffn", "rmsnorm", "rope"],
        preferred_accelerators=["cpu", "npu", "gpu"],
        minimum_memory_mb=5200,
        distributed_compatibility=DistributedCompatibility.PIPELINE,
        known_limitations=["INT4 may lose quality on math tasks"],
        context_length_profile={"4k": 4096, "8k": 8192, "16k": 16384},
        memory_footprint_mb={"fp16": 16000, "int4": 5200, "int8": 8200},
    ))

    registry.register(ModelCapabilities(
        model_id="llama3-70b",
        model_name="LLaMA 3 70B",
        architecture_family=ArchitectureFamily.LLAMA,
        supported_runtimes=["llama.cpp", "ollama", "vllm"],
        supported_data_types=[DataType.FLOAT16, DataType.BFLOAT16, DataType.INT8, DataType.INT4],
        quantization_formats=[QuantizationFormat.INT4, QuantizationFormat.GPTQ, QuantizationFormat.AWQ],
        required_operators=["embedding", "attention", "ffn", "rmsnorm", "rope"],
        preferred_accelerators=["cpu", "gpu"],
        minimum_memory_mb=40000,
        distributed_compatibility=DistributedCompatibility.HYBRID,
        known_limitations=["Requires distributed memory for full model"],
        context_length_profile={"8k": 8192, "16k": 16384},
        memory_footprint_mb={"fp16": 140000, "int4": 40000},
    ))

    registry.register(ModelCapabilities(
        model_id="mistral-7b",
        model_name="Mistral 7B",
        architecture_family=ArchitectureFamily.MISTRAL,
        supported_runtimes=["llama.cpp", "ollama"],
        supported_data_types=[DataType.FLOAT16, DataType.INT4, DataType.INT8],
        quantization_formats=[QuantizationFormat.INT4, QuantizationFormat.INT8, QuantizationFormat.FP16],
        required_operators=["embedding", "attention", "ffn", "rmsnorm", "rope", "sliding_window"],
        preferred_accelerators=["cpu", "npu", "gpu"],
        minimum_memory_mb=4500,
        distributed_compatibility=DistributedCompatibility.PIPELINE,
        known_limitations=[],
        context_length_profile={"8k": 8192, "32k": 32768},
        memory_footprint_mb={"fp16": 14000, "int4": 4500},
    ))

    registry.register(ModelCapabilities(
        model_id="phi3-mini",
        model_name="Phi-3 Mini",
        architecture_family=ArchitectureFamily.PHI,
        supported_runtimes=["ollama", "llama.cpp"],
        supported_data_types=[DataType.FLOAT16, DataType.INT4],
        quantization_formats=[QuantizationFormat.INT4, QuantizationFormat.FP16],
        required_operators=["embedding", "attention", "ffn", "rmsnorm", "rope"],
        preferred_accelerators=["cpu", "npu"],
        minimum_memory_mb=2500,
        distributed_compatibility=DistributedCompatibility.NONE,
        known_limitations=[],
        context_length_profile={"4k": 4096, "128k": 131072},
        memory_footprint_mb={"fp16": 8000, "int4": 2500},
    ))

    registry.register(ModelCapabilities(
        model_id="gemma-2b",
        model_name="Gemma 2B",
        architecture_family=ArchitectureFamily.GEMMA,
        supported_runtimes=["ollama", "llama.cpp"],
        supported_data_types=[DataType.FLOAT16, DataType.INT4],
        quantization_formats=[QuantizationFormat.INT4, QuantizationFormat.FP16],
        required_operators=["embedding", "attention", "ffn", "rmsnorm", "rope", "geglu"],
        preferred_accelerators=["cpu", "npu"],
        minimum_memory_mb=1500,
        distributed_compatibility=DistributedCompatibility.NONE,
        known_limitations=[],
        context_length_profile={"8k": 8192},
        memory_footprint_mb={"fp16": 5000, "int4": 1500},
    ))

    registry.register(ModelCapabilities(
        model_id="mixtral-8x7b",
        model_name="Mixtral 8x7B MoE",
        architecture_family=ArchitectureFamily.MOE,
        supported_runtimes=["vllm", "ollama"],
        supported_data_types=[DataType.FLOAT16, DataType.INT4],
        quantization_formats=[QuantizationFormat.INT4, QuantizationFormat.FP16],
        required_operators=["embedding", "attention", "ffn", "rmsnorm", "rope", "expert_routing"],
        preferred_accelerators=["cpu", "gpu"],
        minimum_memory_mb=35000,
        distributed_compatibility=DistributedCompatibility.EXPERT,
        known_limitations=["Expert parallelism requires compatible runtime"],
        context_length_profile={"32k": 32768},
        memory_footprint_mb={"fp16": 100000, "int4": 35000},
    ))

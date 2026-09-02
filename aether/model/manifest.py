"""
Aether Model — Partitioning and Model Placement Manifest.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from aether.memory.segment import SegmentPriority

logger = logging.getLogger(__name__)


# ─── Model Placement Manifest ───────────────────────────────────────────────

@dataclass
class ManifestEntry:
    tensor_id: str
    tensor_name: str = ""
    dtype: str = "int4"
    shape: list[int] = field(default_factory=list)
    byte_size: int = 0
    primary_device: str = "local"
    replica_device: str = ""
    residency_priority: str = "warm"
    required_backend: str = ""
    checksum: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ModelManifest:
    """Complete placement manifest for one model."""
    model_id: str
    model_name: str = ""
    version: str = "1.0"
    created_at: float = field(default_factory=time.time)
    total_params: int = 0
    layer_count: int = 0
    quantization_format: str = "unknown"
    entries: list[ManifestEntry] = field(default_factory=list)

    def add_entry(self, entry: ManifestEntry):
        self.entries.append(entry)

    def total_size_mb(self) -> float:
        return sum(e.byte_size for e in self.entries) / (1024 * 1024)

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "version": self.version,
            "created_at": self.created_at,
            "total_params": self.total_params,
            "layer_count": self.layer_count,
            "quantization_format": self.quantization_format,
            "entries": [e.to_dict() for e in self.entries],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, data: str) -> "ModelManifest":
        obj = json.loads(data)
        entries = [ManifestEntry(**e) for e in obj.pop("entries", [])]
        m = cls(**obj)
        m.entries = entries
        return m


# ─── Model Partitioner ──────────────────────────────────────────────────────

@dataclass
class PartitionPlan:
    model_id: str
    strategy: str
    placements: list[dict] = field(default_factory=list)
    estimated_compute_ms: float = 0.0
    estimated_transfer_mb: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class ModelPartitioner:
    """Phase 1 partitioner: memory-only and layer-offload strategies."""

    def __init__(self, scheduler):
        self.scheduler = scheduler

    def create_manifest(
        self, model_id: str, model_name: str,
        layers: list[dict], quantization: str = "int4",
    ) -> ModelManifest:
        manifest = ModelManifest(
            model_id=model_id,
            model_name=model_name,
            quantization_format=quantization,
            total_params=sum(l.get("params", 0) for l in layers),
            layer_count=len(layers),
        )
        for i, layer in enumerate(layers):
            entry = ManifestEntry(
                tensor_id=f"{model_id}_layer_{i}",
                tensor_name=layer.get("name", f"layer_{i}"),
                dtype=quantization,
                shape=layer.get("shape", []),
                byte_size=layer.get("byte_size", 0),
                required_backend=",".join(layer.get("ops", [])),
            )
            manifest.add_entry(entry)
        logger.info("Manifest for %s: %d layers, %.1f MB",
                     model_id, len(layers), manifest.total_size_mb())
        return manifest

    def partition(
        self, manifest: ModelManifest, device_ids: list[str],
        strategy: str = "memory_only", local_device: str = "laptop",
    ) -> PartitionPlan:
        if strategy == "memory_only":
            return self._partition_memory_only(manifest, device_ids, local_device)
        elif strategy == "layer_offload":
            return self._partition_layer_offload(manifest, device_ids, local_device)
        raise ValueError(f"Unknown strategy: {strategy}")

    def _partition_memory_only(
        self, manifest: ModelManifest, device_ids: list[str], local_device: str,
    ) -> PartitionPlan:
        workers = device_ids
        placements = []
        if not workers:
            for entry in manifest.entries:
                placements.append({"tensor_id": entry.tensor_id, "device": local_device, "mode": "local"})
            return PartitionPlan(model_id=manifest.model_id, strategy="memory_only", placements=placements)
        for i, entry in enumerate(manifest.entries):
            worker = workers[i % len(workers)]
            placements.append({
                "tensor_id": entry.tensor_id, "device": worker,
                "mode": "remote_resident", "compute_device": local_device,
            })
        logger.info("Memory-only: %.1f MB across %d workers", manifest.total_size_mb(), len(workers))
        return PartitionPlan(
            model_id=manifest.model_id, strategy="memory_only",
            placements=placements, estimated_transfer_mb=manifest.total_size_mb(),
        )

    def _partition_layer_offload(
        self, manifest: ModelManifest, device_ids: list[str], local_device: str,
    ) -> PartitionPlan:
        n = len(manifest.entries)
        workers = device_ids
        placements = []
        if not workers or n <= 2:
            for entry in manifest.entries:
                placements.append({"tensor_id": entry.tensor_id, "device": local_device, "mode": "local"})
            return PartitionPlan(model_id=manifest.model_id, strategy="layer_offload", placements=placements)
        wi = 0
        for i, entry in enumerate(manifest.entries):
            if i == 0 or i == n - 1:
                device, mode = local_device, "local"
            else:
                device, mode = workers[wi % len(workers)], "layer_offload"
                wi += 1
            placements.append({"tensor_id": entry.tensor_id, "device": device, "mode": mode})
        logger.info("Layer-offload: %d entries across %d devices", n, len(set(p["device"] for p in placements)))
        return PartitionPlan(model_id=manifest.model_id, strategy="layer_offload", placements=placements)

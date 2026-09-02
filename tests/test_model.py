"""
Tests for aether.model — ModelManifest and ModelPartitioner.
"""
from __future__ import annotations

import pytest

from aether.model.manifest import (
    ManifestEntry, ModelManifest, ModelPartitioner, PartitionPlan,
)


def _make_layers(n=4):
    return [
        {"name": f"layer_{i}", "shape": [128, 128], "byte_size": 65536, "params": 16384, "ops": ["matmul"]}
        for i in range(n)
    ]


class TestManifestEntry:
    def test_create_entry(self):
        e = ManifestEntry(tensor_id="t1", tensor_name="foo", byte_size=1024)
        assert e.tensor_id == "t1"
        assert e.byte_size == 1024
        assert e.dtype == "int4"

    def test_to_dict(self):
        e = ManifestEntry(tensor_id="t1", tensor_name="foo", byte_size=1024)
        d = e.to_dict()
        assert d["tensor_id"] == "t1"
        assert d["byte_size"] == 1024


class TestModelManifest:
    def test_create_manifest(self):
        m = ModelManifest(model_id="m1", model_name="TestModel")
        assert m.model_id == "m1"
        assert m.total_size_mb() == 0.0

    def test_add_entries(self):
        m = ModelManifest(model_id="m1")
        m.add_entry(ManifestEntry(tensor_id="t1", byte_size=1024))
        m.add_entry(ManifestEntry(tensor_id="t2", byte_size=2048))
        expected_mb = (1024 + 2048) / (1024 * 1024)
        assert m.total_size_mb() == pytest.approx(expected_mb)

    def test_to_json_roundtrip(self):
        m = ModelManifest(model_id="m1", model_name="Test", quantization_format="int4")
        m.add_entry(ManifestEntry(tensor_id="t1", byte_size=1024))
        json_str = m.to_json()
        m2 = ModelManifest.from_json(json_str)
        assert m2.model_id == "m1"
        assert m2.quantization_format == "int4"
        assert len(m2.entries) == 1

    def test_from_json_requires_list(self):
        m = ModelManifest(model_id="m1")
        data = m.to_json()
        import json
        obj = json.loads(data)
        obj["entries"] = "not_a_list"
        with pytest.raises(Exception):
            ModelManifest.from_json(json.dumps(obj))


class TestModelPartitioner:
    def test_create_manifest_from_layers(self):
        partitioner = ModelPartitioner(scheduler=None)
        manifest = partitioner.create_manifest("model_1", "TestModel", _make_layers(4))
        assert manifest.layer_count == 4
        assert len(manifest.entries) == 4
        assert manifest.total_params == 65536

    def test_memory_only_no_workers(self):
        partitioner = ModelPartitioner(scheduler=None)
        manifest = partitioner.create_manifest("m1", "Test", _make_layers(4))
        plan = partitioner.partition(manifest, [], strategy="memory_only", local_device="laptop")
        assert plan.strategy == "memory_only"
        assert all(p["device"] == "laptop" for p in plan.placements)

    def test_memory_only_with_workers(self):
        partitioner = ModelPartitioner(scheduler=None)
        manifest = partitioner.create_manifest("m1", "Test", _make_layers(4))
        workers = ["phone_1", "phone_2"]
        plan = partitioner.partition(manifest, workers, strategy="memory_only", local_device="laptop")
        assert plan.strategy == "memory_only"
        assert len(plan.placements) == 4
        devices = [p["device"] for p in plan.placements]
        assert set(devices) == {"phone_1", "phone_2"}

    def test_layer_offload_keeps_ends_local(self):
        partitioner = ModelPartitioner(scheduler=None)
        manifest = partitioner.create_manifest("m1", "Test", _make_layers(4))
        workers = ["phone_1", "phone_2"]
        plan = partitioner.partition(manifest, workers, strategy="layer_offload", local_device="laptop")
        assert plan.placements[0]["device"] == "laptop"
        assert plan.placements[-1]["device"] == "laptop"
        assert plan.placements[0]["mode"] == "local"
        assert plan.placements[-1]["mode"] == "local"

    def test_layer_offload_falls_back_when_few_layers(self):
        partitioner = ModelPartitioner(scheduler=None)
        manifest = partitioner.create_manifest("m1", "Test", _make_layers(2))
        workers = ["phone_1"]
        plan = partitioner.partition(manifest, workers, strategy="layer_offload", local_device="laptop")
        assert all(p["device"] == "laptop" for p in plan.placements)

    def test_unknown_strategy_raises(self):
        partitioner = ModelPartitioner(scheduler=None)
        manifest = partitioner.create_manifest("m1", "Test", _make_layers(4))
        with pytest.raises(ValueError):
            partitioner.partition(manifest, ["p1"], strategy="unknown")

    def test_partition_plan_to_dict(self):
        plan = PartitionPlan(model_id="m1", strategy="memory_only", placements=[{"t1": "p1"}])
        d = plan.to_dict()
        assert d["model_id"] == "m1"
        assert d["strategy"] == "memory_only"


class TestModelManifestDefaults:
    def test_defaults(self):
        m = ModelManifest(model_id="m1")
        assert m.model_name == ""
        assert m.version == "1.0"
        assert m.quantization_format == "unknown"
        assert m.entries == []

    def test_created_at_is_float(self):
        import time
        m = ModelManifest(model_id="m1")
        assert isinstance(m.created_at, float)
        assert m.created_at <= time.time()

"""
Tests for aether.model.analyzer — Model Analyzer.
"""
from __future__ import annotations

import unittest

from aether.model.analyzer import ModelAnalyzer, AnalyzeResult, LayerInfo, BackendSupport
from aether.model.capability_registry import (
    ModelCapabilityRegistry, ModelCapabilities,
    ArchitectureFamily, DistributedCompatibility, DataType, QuantizationFormat,
)


def _make_layers(n=4):
    return [
        {"name": f"layer_{i}", "type": "attention", "params": 16384,
         "shape": [128, 128], "ops": ["matmul", "rmsnorm"], "byte_size": 65536}
        for i in range(n)
    ]


class TestLayerInfo(unittest.TestCase):
    def test_create_layer(self):
        li = LayerInfo(index=0, name="attn", layer_type="attention", param_count=1024)
        assert li.index == 0
        assert li.param_count == 1024
        assert li.output_shape == []

    def test_defaults(self):
        li = LayerInfo(index=1)
        assert li.name == ""
        assert li.layer_type == ""
        assert li.required_ops == []
        assert li.quantizable is True


class TestAnalyzeResult(unittest.TestCase):
    def test_create_result(self):
        r = AnalyzeResult(model_id="m1", total_params=1000, layer_count=4)
        assert r.model_id == "m1"
        assert r.total_params == 1000
        assert r.estimated_fp16_mb == 0.0
        assert r.quantization_format == "int4"

    def test_to_dict(self):
        r = AnalyzeResult(model_id="m1", total_params=5000, layer_count=2)
        d = r.to_dict()
        assert d["model_id"] == "m1"
        assert d["total_params"] == 5000
        assert d["layer_count"] == 2
        assert d["layers"] == []


class TestModelAnalyzer(unittest.TestCase):
    def test_analyze_basic(self):
        analyzer = ModelAnalyzer()
        result = analyzer.analyze("test_model", _make_layers(4))
        assert result.model_id == "test_model"
        assert result.layer_count == 4
        assert result.total_params == 65536
        assert len(result.layers) == 4

    def test_analyze_empty_layers(self):
        analyzer = ModelAnalyzer()
        result = analyzer.analyze("empty", [])
        assert result.layer_count == 0
        assert result.total_params == 0

    def test_analyze_quantization_estimates(self):
        analyzer = ModelAnalyzer()
        result = analyzer.analyze("q_test", _make_layers(4), quantization="fp16")
        # fp16 should be ~0.25 MB (4 * 65536 bytes / 4 bytes per param)
        assert result.estimated_fp16_mb > 0
        assert result.estimated_int4_mb > 0

    def test_analyze_caching(self):
        analyzer = ModelAnalyzer()
        r1 = analyzer.analyze("cached_model", _make_layers(2))
        r2 = analyzer.analyze("cached_model", _make_layers(2))
        assert r1 is r2  # Same object from cache
        assert analyzer.cached_count == 1

    def test_analyze_with_registry(self):
        registry = ModelCapabilityRegistry()
        registry.register(ModelCapabilities(
            model_id="known_model",
            model_name="Known",
            architecture_family=ArchitectureFamily.LLAMA,
            supported_runtimes=["llama.cpp"],
            quantization_formats=[QuantizationFormat.INT4],
            distributed_compatibility=DistributedCompatibility.PIPELINE,
            preferred_accelerators=["cpu", "npu"],
        ))
        analyzer = ModelAnalyzer(registry)
        result = analyzer.analyze("known_model", _make_layers(4))
        assert result.distributed_compatibility == "pipeline"
        assert "cpu" in result.backend_support

    def test_backend_assessment_no_accelerator_ops(self):
        analyzer = ModelAnalyzer()
        layers = [{"name": "l0", "type": "attention", "params": 1000,
                    "ops": ["matmul", "rmsnorm"]}]
        result = analyzer.analyze("backend_test", layers)
        assert result.backend_support["cpu"] == BackendSupport.FULL

    def test_large_model_note(self):
        """Models with >1B params should generate a note."""
        analyzer = ModelAnalyzer()
        # Simulate large model
        layers = [{"name": f"l{i}", "type": "attn", "params": 500_000_000,
                    "ops": ["matmul"]} for i in range(10)]
        result = analyzer.analyze("big_model", layers)
        assert len(result.notes) > 0

    def test_clear_cache(self):
        analyzer = ModelAnalyzer()
        analyzer.analyze("m1", _make_layers(2))
        assert analyzer.cached_count == 1
        analyzer.clear_cache()
        assert analyzer.cached_count == 0

    def test_metadata_override(self):
        analyzer = ModelAnalyzer()
        result = analyzer.analyze("m1", _make_layers(2), metadata={
            "model_name": "Custom Name",
            "architecture_family": "mistral",
            "supported_runtimes": ["ollama"],
        })
        assert result.model_name == "Custom Name"
        assert result.architecture_family == "mistral"

    def test_operators_collected(self):
        analyzer = ModelAnalyzer()
        layers = [
            {"name": "l0", "type": "attn", "params": 100, "ops": ["matmul"]},
            {"name": "l1", "type": "ffn", "params": 200, "ops": ["matmul", "silu"]},
        ]
        result = analyzer.analyze("ops_test", layers)
        assert "matmul" in result.required_operators
        assert "silu" in result.required_operators


class TestBackendSupport(unittest.TestCase):
    def test_backend_values(self):
        assert BackendSupport.FULL.value == "full"
        assert BackendSupport.PARTIAL.value == "partial"
        assert BackendSupport.NONE.value == "none"


if __name__ == "__main__":
    unittest.main()

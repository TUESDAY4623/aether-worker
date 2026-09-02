"""
Tests for aether.intelligence.workload_analyzer — Workload Analyzer.
"""
from __future__ import annotations

import unittest

from aether.intelligence.workload_analyzer import (
    WorkloadAnalyzer, WorkloadProfile, WorkloadPhase, WorkloadType,
)


class TestWorkloadProfile(unittest.TestCase):
    def test_create_profile(self):
        p = WorkloadProfile(workload_id="w1")
        assert p.workload_id == "w1"
        assert p.workload_type == WorkloadType.CHAT
        assert p.context_length == 4096
        assert p.current_phase == WorkloadPhase.IDLE

    def test_to_dict(self):
        p = WorkloadProfile(
            workload_id="w1", workload_type=WorkloadType.CODE_GENERATION,
            context_length=8192, expected_output_length=256,
        )
        d = p.to_dict()
        assert d["workload_id"] == "w1"
        assert d["workload_type"] == "code_generation"
        assert d["context_length"] == 8192
        assert "progress_pct" in d

    def test_progress_calculation(self):
        analyzer = WorkloadAnalyzer()
        profile = analyzer.analyze("w1", expected_output_length=100)
        profile.tokens_generated = 50
        d = profile.to_dict()
        assert d["progress_pct"] == 50.0

    def test_progress_zero_expected(self):
        p = WorkloadProfile(workload_id="w1", expected_output_length=0)
        p.tokens_generated = 0
        d = p.to_dict()
        assert d["progress_pct"] == 0.0


class TestWorkloadAnalyzer(unittest.TestCase):
    def test_analyze_chat(self):
        analyzer = WorkloadAnalyzer()
        profile = analyzer.analyze("w1", model_id="llama3-8b", context_length=4096)
        assert profile.workload_id == "w1"
        assert profile.estimated_prefill_ms > 0
        assert profile.estimated_decode_ms_per_token > 0
        assert profile.memory_requirements_mb > 0

    def test_analyze_code_generation(self):
        analyzer = WorkloadAnalyzer()
        profile = analyzer.analyze(
            "w1", model_id="code-7b", context_length=8192,
            expected_output_length=512, workload_type="code_generation",
        )
        assert profile.workload_type == WorkloadType.CODE_GENERATION
        assert profile.context_length == 8192

    def test_analyze_large_model(self):
        analyzer = WorkloadAnalyzer()
        profile = analyzer.analyze("w1", model_id="big-model", model_size_b=13.0)
        assert profile.preferred_accelerator in ("gpu", "npu", "cpu")
        assert profile.requires_quantization is True

    def test_analyze_small_model(self):
        analyzer = WorkloadAnalyzer()
        profile = analyzer.analyze("w1", model_id="small", model_size_b=2.0)
        assert profile.preferred_accelerator == "npu"
        assert profile.requires_quantization is False

    def test_analyze_memory_bound(self):
        analyzer = WorkloadAnalyzer()
        profile = analyzer.analyze("w1", model_size_b=70.0, context_length=32768)
        assert profile.is_memory_bound is True

    def test_kv_cache_scales(self):
        analyzer = WorkloadAnalyzer()
        p_small = analyzer.analyze("w1", context_length=4096)
        p_large = analyzer.analyze("w2", context_length=16384)
        assert p_large.kv_cache_requirements_mb > p_small.kv_cache_requirements_mb

    def test_analyze_with_metadata(self):
        analyzer = WorkloadAnalyzer()
        profile = analyzer.analyze(
            "w1", model_id="m1", metadata={"architecture": "moe", "gpu_available": True}
        )
        assert profile.model_architecture == "moe"

    def test_phase_detection_prefill(self):
        analyzer = WorkloadAnalyzer()
        analyzer.analyze("w1", expected_output_length=100)
        phase = analyzer.detect_phase_change("w1", tokens_generated=0, is_prefill_active=True)
        assert phase == WorkloadPhase.PREFILL

    def test_phase_detection_decode(self):
        analyzer = WorkloadAnalyzer()
        analyzer.analyze("w1", expected_output_length=100)
        # First call with prefill active
        p1 = analyzer.detect_phase_change("w1", tokens_generated=0, is_prefill_active=True)
        assert p1 == WorkloadPhase.PREFILL
        # Transition to decode
        p2 = analyzer.detect_phase_change("w1", tokens_generated=1, is_prefill_active=False)
        assert p2 == WorkloadPhase.MIXED
        # Continue decoding
        p3 = analyzer.detect_phase_change("w1", tokens_generated=50, is_prefill_active=False)
        assert p3 == WorkloadPhase.DECODE

    def test_phase_detection_completed(self):
        analyzer = WorkloadAnalyzer()
        analyzer.analyze("w1", expected_output_length=10)
        analyzer.detect_phase_change("w1", tokens_generated=5)
        phase = analyzer.detect_phase_change("w1", tokens_generated=10)
        assert phase == WorkloadPhase.COMPLETED

    def test_phase_detection_unknown(self):
        analyzer = WorkloadAnalyzer()
        phase = analyzer.detect_phase_change("unknown", tokens_generated=5)
        assert phase == WorkloadPhase.IDLE

    def test_phase_history(self):
        analyzer = WorkloadAnalyzer()
        analyzer.analyze("w1", expected_output_length=10)
        analyzer.detect_phase_change("w1", tokens_generated=0, is_prefill_active=True)
        analyzer.detect_phase_change("w1", tokens_generated=5)
        history = analyzer.get_phase_history("w1")
        assert len(history) >= 1

    def test_get_profile(self):
        analyzer = WorkloadAnalyzer()
        analyzer.analyze("w1")
        profile = analyzer.get_profile("w1")
        assert profile is not None
        assert profile.workload_id == "w1"

    def test_get_profile_missing(self):
        analyzer = WorkloadAnalyzer()
        assert analyzer.get_profile("nonexistent") is None

    def test_list_profiles(self):
        analyzer = WorkloadAnalyzer()
        analyzer.analyze("w1")
        analyzer.analyze("w2")
        profiles = analyzer.list_profiles()
        assert len(profiles) == 2

    def test_active_count(self):
        analyzer = WorkloadAnalyzer()
        analyzer.analyze("w1", expected_output_length=10)
        assert analyzer.active_count == 0  # IDLE
        analyzer.detect_phase_change("w1", tokens_generated=5)
        assert analyzer.active_count == 1

    def test_batch_scales_time(self):
        analyzer = WorkloadAnalyzer()
        p1 = analyzer.analyze("w1", batch_size=1)
        p2 = analyzer.analyze("w2", batch_size=4)
        assert p2.estimated_prefill_ms > p1.estimated_prefill_ms

    def test_invalid_type_defaults_chat(self):
        analyzer = WorkloadAnalyzer()
        profile = analyzer.analyze("w1", workload_type="unknown_type")
        assert profile.workload_type == WorkloadType.CHAT


class TestWorkloadPhase(unittest.TestCase):
    def test_values(self):
        assert WorkloadPhase.IDLE.value == "idle"
        assert WorkloadPhase.PREFILL.value == "prefill"
        assert WorkloadPhase.DECODE.value == "decode"
        assert WorkloadPhase.MIXED.value == "mixed"
        assert WorkloadPhase.COMPLETED.value == "completed"

    def test_unique(self):
        values = [p.value for p in WorkloadPhase]
        assert len(values) == len(set(values))


class TestWorkloadType(unittest.TestCase):
    def test_values(self):
        assert WorkloadType.CHAT.value == "chat"
        assert WorkloadType.CODE_GENERATION.value == "code_generation"
        assert WorkloadType.EMBEDDING.value == "embedding"


if __name__ == "__main__":
    unittest.main()

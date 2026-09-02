"""
Tests for aether.scheduler — RuleBasedScheduler.
"""

from __future__ import annotations

import pytest

from aether.scheduler.rule_based import DeviceScore, RuleBasedScheduler
from aether.telemetry.collector import DeviceTelemetry, TelemetryCollector
from aether.thermal.manager import ThermalManager


def make_system():
    tel = TelemetryCollector()
    therm = ThermalManager(telemetry=tel)
    sched = RuleBasedScheduler(thermal_manager=therm, telemetry=tel)
    return sched, tel, therm


class TestScheduler:
    def test_score_cool_high_memory(self):
        sched, tel, therm = make_system()
        tel.report(DeviceTelemetry(
            device_id="phone_1", temperature_c=40.0,
            memory_total_mb=8192, memory_available_mb=4096,
            battery_pct=80.0, cpu_utilization_pct=10.0,
        ))
        score = sched._score_for_segment("phone_1", 0)
        assert score.score > 0
        assert score.thermal_score == 100.0

    def test_score_hot_device_penalized(self):
        sched, tel, therm = make_system()
        tel.report(DeviceTelemetry(
            device_id="hot", temperature_c=75.0,
            memory_total_mb=4096, memory_available_mb=2048,
            battery_pct=30.0, cpu_utilization_pct=80.0,
        ))
        therm.update_device("hot")
        score = sched._score_for_segment("hot", 0)
        assert score.thermal_score < 50.0

    def test_select_device(self):
        sched, tel, therm = make_system()
        tel.report(DeviceTelemetry(
            device_id="phone_1", temperature_c=40.0,
            memory_total_mb=8192, memory_available_mb=4096,
            battery_pct=80.0, cpu_utilization_pct=10.0,
        ))
        tel.report(DeviceTelemetry(
            device_id="tablet_1", temperature_c=45.0,
            memory_total_mb=8192, memory_available_mb=2048,
            battery_pct=60.0, cpu_utilization_pct=20.0,
        ))
        best = sched.select_device_for_segment(["phone_1", "tablet_1"], 0)
        assert best is not None
        assert best.device_id in ("phone_1", "tablet_1")

    def test_no_candidates(self):
        sched, tel, therm = make_system()
        assert sched.select_device_for_segment([], 0) is None

    def test_low_battery_penalty(self):
        sched, tel, therm = make_system()
        tel.report(DeviceTelemetry(
            device_id="low", temperature_c=40.0,
            memory_total_mb=4096, memory_available_mb=2048,
            battery_pct=15.0, cpu_utilization_pct=10.0,
        ))
        score = sched._score_for_segment("low", 0)
        assert score.power_score == 20.0

    def test_oversized_segment_penalty(self):
        sched, tel, therm = make_system()
        tel.report(DeviceTelemetry(
            device_id="small", temperature_c=40.0,
            memory_total_mb=4096, memory_available_mb=256,
            battery_pct=80.0, cpu_utilization_pct=10.0,
        ))
        score = sched._score_for_segment("small", 512)
        assert score.memory_score < 50.0

    def test_score_all(self):
        sched, tel, therm = make_system()
        tel.report(DeviceTelemetry(
            device_id="d1", temperature_c=40.0,
            memory_total_mb=4096, memory_available_mb=2048,
            battery_pct=50.0,
        ))
        scores = sched.score_all(["d1", "nonexistent"])
        assert "d1" in scores
        assert scores["d1"].score > 0

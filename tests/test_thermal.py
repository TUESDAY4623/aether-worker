"""
Tests for aether.thermal — ThermalManager state machine.
"""

from __future__ import annotations

import time
import pytest

from aether.telemetry.collector import DeviceTelemetry, TelemetryCollector
from aether.thermal.manager import ThermalManager, ThermalState


def make_manager():
    tel = TelemetryCollector()
    mgr = ThermalManager(telemetry=tel)
    return mgr, tel


class TestThermalManager:
    def test_initial_state_normal(self):
        mgr, tel = make_manager()
        assert mgr.update_device("device_1") == ThermalState.NORMAL

    def test_normal_temperature(self):
        mgr, tel = make_manager()
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=40.0))
        assert mgr.update_device("d1") == ThermalState.NORMAL

    def test_warm_threshold(self):
        mgr, tel = make_manager()
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=62.0))
        assert mgr.update_device("d1") == ThermalState.WARM

    def test_hot_threshold(self):
        mgr, tel = make_manager()
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=72.0))
        assert mgr.update_device("d1") == ThermalState.HOT

    def test_critical_threshold(self):
        mgr, tel = make_manager()
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=85.0))
        assert mgr.update_device("d1") == ThermalState.CRITICAL

    def test_can_compute(self):
        mgr, tel = make_manager()
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=40.0))
        mgr.update_device("d1")
        assert mgr.can_compute("d1")
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=85.0))
        mgr.update_device("d1")
        assert not mgr.can_compute("d1")

    def test_can_resident_memory(self):
        mgr, tel = make_manager()
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=85.0))
        mgr.update_device("d1")
        assert not mgr.can_resident_memory("d1")

    def test_concurrency_limits(self):
        mgr, tel = make_manager()
        limits = {"normal": 4, "warm": 2, "hot": 1, "critical": 0, "recovery": 1}
        for state_str, expected in limits.items():
            temp = {"normal": 40, "warm": 62, "hot": 72, "critical": 85, "recovery": 45}[state_str]
            tel.report(DeviceTelemetry(device_id="d1", temperature_c=temp))
            mgr.update_device("d1")
            assert mgr.concurrency_limit("d1") == expected

    def test_thermal_event_listener(self):
        events = []
        mgr, tel = make_manager()
        mgr.add_listener(lambda e: events.append(e))
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=40.0))
        mgr.update_device("d1")
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=72.0))
        mgr.update_device("d1")
        assert len(events) == 1
        assert events[0].new_state == ThermalState.HOT

    def test_recovery_state(self):
        mgr, tel = make_manager()
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=75.0))
        mgr.update_device("d1")
        assert mgr.get_state("d1") == ThermalState.HOT
        tel.report(DeviceTelemetry(device_id="d1", temperature_c=45.0))
        mgr.update_device("d1")
        assert mgr.get_state("d1") == ThermalState.RECOVERY

    def test_temperature_trend(self):
        mgr, tel = make_manager()
        now = time.time()
        for i in range(5):
            tel.report(DeviceTelemetry(
                device_id="d1", temperature_c=40.0 + i * 5,
                timestamp=now + i * 10,
            ))
        trend = tel.temperature_trend("d1", window_s=60)
        assert trend > 0

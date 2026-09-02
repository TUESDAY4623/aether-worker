"""
Tests for aether.workers.registry — uncovered lines.
"""
from __future__ import annotations

import time
import unittest

from aether.workers.registry import WorkerCapabilities, WorkerDevice, WorkerRegistry


class TestWorkerCapabilities(unittest.TestCase):
    def test_defaults(self):
        cap = WorkerCapabilities()
        assert cap.cpu_cores == 0
        assert cap.has_npu is False
        assert cap.supported_ops == []
        assert cap.transport_types == []

    def test_custom_values(self):
        cap = WorkerCapabilities(
            device_model="Exynos 2200",
            cpu_cores=8,
            cpu_arch="arm64",
            total_ram_mb=8000,
            has_npu=True,
            supported_ops=["conv2d", "matmul"],
            transport_types=["wifi", "bt"],
        )
        assert cap.device_model == "Exynos 2200"
        assert cap.cpu_cores == 8
        assert cap.has_npu is True
        assert "conv2d" in cap.supported_ops


class TestWorkerDevice(unittest.TestCase):
    def test_create_device(self):
        device = WorkerDevice(device_id="phone-1", display_name="My Phone")
        assert device.device_id == "phone-1"
        assert device.display_name == "My Phone"
        assert device.available is True
        assert device.paired is False
        assert device.thermal_state == "normal"

    def test_device_with_capabilities(self):
        cap = WorkerCapabilities(cpu_cores=4, total_ram_mb=4000)
        device = WorkerDevice(device_id="tablet-1", display_name="Tablet",
                              capabilities=cap)
        assert device.capabilities.cpu_cores == 4
        assert device.capabilities.total_ram_mb == 4000


class TestWorkerRegistry(unittest.TestCase):
    def _registry(self):
        return WorkerRegistry(discovery_timeout_s=10)

    def test_register_new_worker(self):
        reg = self._registry()
        device = WorkerDevice(device_id="d1", display_name="Device 1")
        result = reg.register(device)
        assert result is True
        assert reg.count == 1

    def test_register_duplicate_updates(self):
        reg = self._registry()
        d1 = WorkerDevice(device_id="d1", display_name="Old Name")
        reg.register(d1)
        d2 = WorkerDevice(device_id="d1", display_name="New Name",
                          capabilities=WorkerCapabilities(cpu_cores=8))
        reg.register(d2)
        assert reg.count == 1  # not duplicated
        assert reg.get("d1").display_name == "New Name"
        assert reg.get("d1").capabilities.cpu_cores == 8

    def test_register_duplicate_preserves_capabilities_if_empty(self):
        """If new worker has no model, keep existing capabilities."""
        reg = self._registry()
        d1 = WorkerDevice(device_id="d1", display_name="D1",
                          capabilities=WorkerCapabilities(cpu_cores=4))
        reg.register(d1)
        d2 = WorkerDevice(device_id="d1", display_name="D1")  # no capabilities
        reg.register(d2)
        assert reg.get("d1").capabilities.cpu_cores == 4  # preserved

    def test_unregister(self):
        reg = self._registry()
        reg.register(WorkerDevice(device_id="d1"))
        assert reg.count == 1
        reg.unregister("d1")
        assert reg.count == 0

    def test_unregister_nonexistent(self):
        reg = self._registry()
        reg.unregister("nonexistent")  # should not raise

    def test_get(self):
        reg = self._registry()
        reg.register(WorkerDevice(device_id="d1", display_name="D1"))
        device = reg.get("d1")
        assert device is not None
        assert device.display_name == "D1"

    def test_get_missing(self):
        reg = self._registry()
        assert reg.get("nonexistent") is None

    def test_get_paired(self):
        reg = self._registry()
        reg.register(WorkerDevice(device_id="d1", paired=True, available=True))
        reg.register(WorkerDevice(device_id="d2", paired=False, available=True))
        reg.register(WorkerDevice(device_id="d3", paired=True, available=False))
        paired = reg.get_paired()
        assert len(paired) == 1
        assert paired[0].device_id == "d1"

    def test_get_available(self):
        reg = self._registry()
        reg.register(WorkerDevice(device_id="d1", available=True))
        reg.register(WorkerDevice(device_id="d2", available=False))
        reg.register(WorkerDevice(device_id="d3", available=True))
        available = reg.get_available()
        assert len(available) == 2
        ids = {d.device_id for d in available}
        assert ids == {"d1", "d3"}

    def test_mark_unavailable(self):
        reg = self._registry()
        reg.register(WorkerDevice(device_id="d1", available=True))
        reg.mark_unavailable("d1")
        assert reg.get("d1").available is False

    def test_mark_available(self):
        reg = self._registry()
        device = WorkerDevice(device_id="d1", available=False)
        reg.register(device)
        device.last_seen = 0  # stale
        reg.mark_available("d1")
        assert reg.get("d1").available is True
        assert reg.get("d1").last_seen > 0  # updated

    def test_check_stale(self):
        reg = self._registry(discovery_timeout_s=5)
        d1 = WorkerDevice(device_id="d1")
        d1.last_seen = time.time() - 100  # very old
        d2 = WorkerDevice(device_id="d2")
        d2.last_seen = time.time()  # fresh
        reg.register(d1)
        reg.register(d2)
        stale = reg.check_stale()
        assert "d1" in stale
        assert "d2" not in stale
        assert reg.get("d1").available is False  # marked unavailable

    def test_check_stale_no_false_positives(self):
        reg = self._registry(discovery_timeout_s=10)
        d1 = WorkerDevice(device_id="d1")
        d1.last_seen = time.time() - 2  # recent
        reg.register(d1)
        stale = reg.check_stale()
        assert stale == []

    def test_update_thermal(self):
        reg = self._registry()
        reg.register(WorkerDevice(device_id="d1"))
        reg.update_thermal("d1", "hot")
        assert reg.get("d1").thermal_state == "hot"

    def test_update_thermal_nonexistent(self):
        reg = self._registry()
        reg.update_thermal("nonexistent", "critical")  # should not raise

    def test_count_property(self):
        reg = self._registry()
        assert reg.count == 0
        reg.register(WorkerDevice(device_id="d1"))
        reg.register(WorkerDevice(device_id="d2"))
        assert reg.count == 2

    def test_all_workers_property(self):
        reg = self._registry()
        reg.register(WorkerDevice(device_id="d1", display_name="D1"))
        reg.register(WorkerDevice(device_id="d2", display_name="D2"))
        workers = reg.all_workers
        assert len(workers) == 2
        names = {w.display_name for w in workers}
        assert names == {"D1", "D2"}


if __name__ == "__main__":
    unittest.main()

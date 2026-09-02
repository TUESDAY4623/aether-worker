"""
Tests for aether.memory — MemoryManager and Segment.
"""

from __future__ import annotations

import pytest

from aether.memory.manager import MemoryManager
from aether.memory.segment import (
    Segment, SegmentPriority, SegmentType, ResidencyState,
)


class TestSegment:
    def test_create_segment_defaults(self):
        seg = Segment(name="test", size_bytes=1024 * 1024)
        assert seg.segment_id
        assert seg.name == "test"
        assert seg.size_bytes == 1024 * 1024
        assert seg.residency == ResidencyState.LOCAL
        assert not seg.pinned
        assert seg.size_mb == 1.0
        assert not seg.is_remote

    def test_segment_auto_name(self):
        seg = Segment(size_bytes=0)
        assert seg.name.startswith("seg_")

    def test_is_remote(self):
        for state in (ResidencyState.REMOTE_RESIDENT, ResidencyState.IN_TRANSFER,
                       ResidencyState.EXECUTING):
            seg = Segment(residency=state, size_bytes=0)
            assert seg.is_remote

    def test_to_dict(self):
        seg = Segment(name="w1", size_bytes=2048)
        d = seg.to_dict()
        assert d["name"] == "w1"
        assert d["size_bytes"] == 2048
        assert "segment_id" in d


class TestMemoryManager:
    def test_allocate(self):
        mgr = MemoryManager()
        seg = mgr.allocate("weights", 100 * 1024 * 1024, SegmentType.MODEL_WEIGHTS)
        assert seg.name == "weights"
        assert seg.size_bytes == 100 * 1024 * 1024
        assert seg.seg_type == SegmentType.MODEL_WEIGHTS
        assert mgr.segment_count == 1
        assert mgr.total_allocated_bytes == 100 * 1024 * 1024

    def test_release(self):
        mgr = MemoryManager()
        seg = mgr.allocate("test", 1024)
        assert mgr.segment_count == 1
        assert mgr.release(seg.segment_id)
        assert mgr.segment_count == 0
        assert mgr.total_allocated_bytes == 0

    def test_release_unknown(self):
        mgr = MemoryManager()
        assert not mgr.release("nonexistent")

    def test_pin_unpin(self):
        mgr = MemoryManager()
        seg = mgr.allocate("test", 1024)
        assert mgr.pin(seg.segment_id)
        assert not mgr.release(seg.segment_id)
        assert mgr.unpin(seg.segment_id)
        assert mgr.release(seg.segment_id)

    def test_place(self):
        mgr = MemoryManager()
        seg = mgr.allocate("test", 1024)
        assert mgr.place(seg.segment_id, "phone_1")
        assert seg.owner_device == "phone_1"
        assert seg.residency == ResidencyState.REMOTE_RESIDENT

    def test_mark_states(self):
        mgr = MemoryManager()
        seg = mgr.allocate("test", 1024)
        mgr.mark_in_transfer(seg.segment_id, "tablet_1")
        assert seg.residency == ResidencyState.IN_TRANSFER
        mgr.mark_resident(seg.segment_id, "tablet_1")
        assert seg.residency == ResidencyState.REMOTE_RESIDENT
        mgr.mark_executing(seg.segment_id)
        assert seg.residency == ResidencyState.EXECUTING
        mgr.mark_evictable(seg.segment_id)
        assert seg.residency == ResidencyState.EVICTABLE
        mgr.mark_invalid(seg.segment_id)
        assert seg.residency == ResidencyState.INVALID

    def test_get_by_tensor(self):
        mgr = MemoryManager()
        s1 = mgr.allocate("a", 1024, tensor_id="t1")
        s2 = mgr.allocate("b", 2048, tensor_id="t2")
        s3 = mgr.allocate("c", 4096, tensor_id="t1")
        assert len(mgr.get_by_tensor("t1")) == 2

    def test_get_by_device(self):
        mgr = MemoryManager()
        s1 = mgr.allocate("a", 1024)
        mgr.place(s1.segment_id, "device_A")
        assert len(mgr.get_by_device("device_A")) == 1
        assert len(mgr.get_by_device("device_B")) == 0

    def test_device_memory_used(self):
        mgr = MemoryManager()
        s1 = mgr.allocate("a", 1024)
        s2 = mgr.allocate("b", 2048)
        mgr.place(s1.segment_id, "dev1")
        mgr.place(s2.segment_id, "dev1")
        assert mgr.device_memory_used("dev1") == 3072

    def test_get_remote_segments(self):
        mgr = MemoryManager()
        local = mgr.allocate("local", 1024)
        remote = mgr.allocate("remote", 2048)
        mgr.place(remote.segment_id, "worker_1")
        remote_segs = mgr.get_remote_segments()
        assert len(remote_segs) == 1

    def test_evictable_and_invalid(self):
        mgr = MemoryManager()
        s1 = mgr.allocate("a", 1024)
        s2 = mgr.allocate("b", 2048)
        mgr.mark_evictable(s1.segment_id)
        mgr.mark_invalid(s2.segment_id)
        assert len(mgr.get_evictable()) == 1
        assert len(mgr.get_invalid()) == 1

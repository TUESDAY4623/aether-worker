"""
Tests for aether.transport.streaming — Streaming Tensor Transfer.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from aether.transport.streaming import (
    LinkMetrics, StreamingTensorTransfer, TransferPool, TransferPriority,
    TransferTask,
)


class TestTransferPool(unittest.TestCase):
    def test_acquire_buffer(self):
        pool = TransferPool(buffer_size=1024, pool_size=4)
        buf = pool.acquire()
        assert len(buf) == 1024
        assert pool.available == 3

    def test_release_buffer(self):
        pool = TransferPool(buffer_size=1024, pool_size=4)
        buf = pool.acquire()
        pool.release(buf)
        assert pool.available == 4

    def test_acquire_all_release_all(self):
        pool = TransferPool(buffer_size=512, pool_size=3)
        bufs = [pool.acquire() for _ in range(3)]
        assert pool.available == 0
        for buf in bufs:
            pool.release(buf)
        assert pool.available == 3

    def test_acquire_beyond_pool_size(self):
        pool = TransferPool(buffer_size=512, pool_size=2)
        b1 = pool.acquire()
        b2 = pool.acquire()
        b3 = pool.acquire()  # Should allocate new buffer
        assert len(b3) == 512
        pool.release(b1)
        pool.release(b2)
        pool.release(b3)


class TestLinkMetrics(unittest.TestCase):
    def test_create_metrics(self):
        lm = LinkMetrics(device_id="phone_1")
        assert lm.device_id == "phone_1"
        assert lm.bandwidth_mbps == 0.0
        assert lm.active_transfers == 0

    def test_update_metrics(self):
        lm = LinkMetrics(device_id="phone_1")
        lm.bandwidth_mbps = 50.0
        lm.latency_ms = 20.0
        lm.active_transfers = 3
        assert lm.bandwidth_mbps == 50.0
        assert lm.latency_ms == 20.0
        assert lm.active_transfers == 3


class TestStreamingTensorTransfer(unittest.TestCase):
    def test_create_transfer(self):
        stt = StreamingTensorTransfer()
        assert stt.active_count == 0
        assert stt.queued_count == 0
        assert stt.total_completed == 0

    def test_enqueue_task(self):
        stt = StreamingTensorTransfer()
        task_id = stt.enqueue(
            "tensor_1", b"test data", "phone_1",
            priority=TransferPriority.HIGH,
        )
        assert len(task_id) == 12
        assert stt.queued_count == 1
        assert stt.active_count == 0

    def test_enqueue_priority(self):
        stt = StreamingTensorTransfer()
        stt.enqueue("t1", b"low", "p1", priority=TransferPriority.LOW)
        stt.enqueue("t2", b"high", "p1", priority=TransferPriority.HIGH)
        assert stt.queued_count == 2

    def test_cancel_queued_transfer(self):
        stt = StreamingTensorTransfer()
        task_id = stt.enqueue("t1", b"data", "p1")
        result = stt.cancel(task_id)
        assert result is True
        assert stt.queued_count == 0

    def test_cancel_nonexistent(self):
        stt = StreamingTensorTransfer()
        result = stt.cancel("nonexistent")
        assert result is False

    def test_get_link_metrics_creates(self):
        stt = StreamingTensorTransfer()
        lm = stt.get_link_metrics("phone_1")
        assert lm.device_id == "phone_1"

    def test_update_link_metrics(self):
        stt = StreamingTensorTransfer()
        stt.update_link_metrics("phone_1", bandwidth_mbps=80.0, latency_ms=15.0)
        lm = stt.get_link_metrics("phone_1")
        assert lm.bandwidth_mbps == 80.0
        assert lm.latency_ms == 15.0

    def test_summary(self):
        stt = StreamingTensorTransfer()
        summary = stt.summary()
        assert "running" in summary
        assert "active" in summary
        assert "queued_high" in summary
        assert "completed" in summary

    def test_summary_after_enqueue(self):
        stt = StreamingTensorTransfer()
        stt.enqueue("t1", b"data", "p1", priority=TransferPriority.HIGH)
        stt.enqueue("t2", b"data", "p1", priority=TransferPriority.MEDIUM)
        summary = stt.summary()
        assert summary["queued_high"] == 1
        assert summary["queued_medium"] == 1
        assert summary["queued_low"] == 0

    def test_on_complete_callback(self):
        stt = StreamingTensorTransfer()
        callback = MagicMock()
        task_id = stt.enqueue("t1", b"data", "p1", on_complete=callback)
        # Callback won't fire until transfer completes, just verify registration
        assert task_id in stt._callbacks

    def test_congestion_adjustment(self):
        stt = StreamingTensorTransfer(max_concurrent=4, congestion_threshold=4)
        # Fill up queue to trigger congestion
        for i in range(10):
            stt.enqueue(f"t{i}", b"data" * 1000, "p1")
        assert stt.queued_count == 10
        assert stt.max_concurrent < 4  # Should have reduced


class TestTransferTask(unittest.TestCase):
    def test_create_task(self):
        task = TransferTask(
            task_id="t1", tensor_id="tensor_1", data=b"hello",
            destination="phone_1", priority=TransferPriority.MEDIUM,
        )
        assert task.task_id == "t1"
        assert task.priority == TransferPriority.MEDIUM
        assert task.completed is False
        assert task.bytes_sent == 0

    def test_task_defaults(self):
        task = TransferTask(task_id="t1", tensor_id="t1", data=b"x", destination="p1")
        assert task.chunk_size == 4 * 1024 * 1024
        assert task.cancelled is False
        assert task.error == ""


class TestTransferPriority(unittest.TestCase):
    def test_priority_values(self):
        assert TransferPriority.HIGH.value == "high"
        assert TransferPriority.MEDIUM.value == "medium"
        assert TransferPriority.LOW.value == "low"

    def test_priority_ordering(self):
        priorities = [TransferPriority.LOW, TransferPriority.HIGH, TransferPriority.MEDIUM]
        ordered = sorted(priorities, key=lambda p: p.value)
        assert ordered[0] == TransferPriority.HIGH
        assert ordered[1] == TransferPriority.LOW
        assert ordered[2] == TransferPriority.MEDIUM


if __name__ == "__main__":
    unittest.main()

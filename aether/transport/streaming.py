"""
Async Tensor Streaming — priority-driven transfer pool and streaming engine.

Phase 4 §6.2 + §7: TransferPriority, TransferPool for reusable buffers,
stream cancellation under congestion, async pipeline overlapping
communication with computation.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from aether.transport.protocol import MessageType, make_message

logger = logging.getLogger(__name__)


class TransferPriority(str, Enum):
    """Transfer priority levels for queue management."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class TransferTask:
    """A single transfer task in the streaming system."""
    task_id: str
    tensor_id: str
    data: bytes
    destination: str
    priority: TransferPriority = TransferPriority.MEDIUM
    created_at: float = field(default_factory=time.time)
    checksum: str = ""
    chunk_size: int = 4 * 1024 * 1024
    completed: bool = False
    error: str = ""
    cancelled: bool = False
    bytes_sent: int = 0


@dataclass
class LinkMetrics:
    """Measured link quality metrics."""
    device_id: str
    bandwidth_mbps: float = 0.0
    latency_ms: float = 0.0
    packet_loss_pct: float = 0.0
    active_transfers: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    last_updated: float = field(default_factory=time.time)


class TransferPool:
    """Pool of reusable byte buffers to minimize allocation overhead."""

    def __init__(self, buffer_size: int = 4 * 1024 * 1024, pool_size: int = 8):
        self._lock = threading.RLock()
        self._buffer_size = buffer_size
        self._pool_size = pool_size
        self._pool: deque = deque()
        for _ in range(pool_size):
            self._pool.append(bytearray(buffer_size))

    def acquire(self) -> bytearray:
        """Get a buffer from the pool (or allocate new if empty)."""
        with self._lock:
            if self._pool:
                return self._pool.popleft()
            return bytearray(self._buffer_size)

    def release(self, buf: bytearray) -> None:
        """Return a buffer to the pool."""
        with self._lock:
            if len(self._pool) < self._pool_size:
                buf[:] = b'\x00' * min(len(buf), self._buffer_size)
                self._pool.append(buf)

    @property
    def available(self) -> int:
        with self._lock:
            return len(self._pool)


class StreamingTensorTransfer:
    """Async tensor transfer with priority queuing and congestion management.

    Uses asyncio queues to overlap communication with computation.
    Supports priority-based scheduling and stream cancellation.
    """

    def __init__(
        self,
        chunk_size: int = 4 * 1024 * 1024,
        max_concurrent: int = 4,
        congestion_threshold: int = 16,
    ):
        self._lock = threading.RLock()
        self.chunk_size = chunk_size
        self.max_concurrent = max_concurrent
        self.congestion_threshold = congestion_threshold

        # Priority queues: HIGH > MEDIUM > LOW
        self._high_queue: deque = deque()
        self._medium_queue: deque = deque()
        self._low_queue: deque = deque()
        self._active: dict[str, TransferTask] = {}
        self._completed: list[TransferTask] = []
        self._callbacks: dict[str, Callable] = {}
        self._semaphore: asyncio.Semaphore | None = None

        # Link metrics per device
        self._link_metrics: dict[str, LinkMetrics] = {}

        # Transfer pool
        self._buffer_pool = TransferPool(buffer_size=chunk_size)

        # Background task handle
        self._running = False
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the streaming worker."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("StreamingTensorTransfer started (max_concurrent=%d)", self.max_concurrent)

    async def stop(self) -> None:
        """Stop the streaming worker and cancel all active transfers."""
        with self._lock:
            self._running = False
            if self._worker_task:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
            for task in self._active.values():
                task.cancelled = True
            logger.info("StreamingTensorTransfer stopped")

    def enqueue(
        self,
        tensor_id: str,
        data: bytes,
        destination: str,
        priority: TransferPriority = TransferPriority.MEDIUM,
        on_complete: Callable | None = None,
    ) -> str:
        """Enqueue a tensor for streaming transfer.

        Returns task_id.
        """
        task_id = hashlib.sha256(
            f"{tensor_id}:{time.time()}:{destination}".encode()
        ).hexdigest()[:12]
        checksum = hashlib.sha256(data).hexdigest()[:16]

        task = TransferTask(
            task_id=task_id,
            tensor_id=tensor_id,
            data=data,
            destination=destination,
            priority=priority,
            checksum=checksum,
        )
        if on_complete:
            self._callbacks[task_id] = on_complete

        with self._lock:
            queue = self._get_queue(priority)
            queue.append(task)
            self._maybe_adjust_concurrency()

        logger.debug(
            "Enqueued %s (%s, %.1f MB, priority=%s)",
            task_id, tensor_id, len(data) / 1e6, priority.value,
        )
        return task_id

    def _get_queue(self, priority: TransferPriority) -> deque:
        if priority == TransferPriority.HIGH:
            return self._high_queue
        if priority == TransferPriority.MEDIUM:
            return self._medium_queue
        return self._low_queue

    def _maybe_adjust_concurrency(self) -> None:
        """Reduce concurrency when congested."""
        total_queued = (
            len(self._high_queue) + len(self._medium_queue) + len(self._low_queue)
        )
        if total_queued > self.congestion_threshold and self.max_concurrent > 1:
            self.max_concurrent = max(1, self.max_concurrent - 1)
            if self._semaphore:
                # Can't easily shrink a semaphore, but we track the limit
                pass
        elif total_queued < self.congestion_threshold // 2 and self.max_concurrent < 4:
            self.max_concurrent = min(4, self.max_concurrent + 1)

    def cancel(self, task_id: str) -> bool:
        """Cancel a queued or active transfer."""
        with self._lock:
            # Remove from queues
            for queue in (self._high_queue, self._medium_queue, self._low_queue):
                for i, task in enumerate(queue):
                    if task.task_id == task_id:
                        task.cancelled = True
                        del queue[i]
                        logger.debug("Cancelled queued transfer %s", task_id)
                        return True
            # Mark active as cancelled
            if task_id in self._active:
                self._active[task_id].cancelled = True
                logger.debug("Cancelled active transfer %s", task_id)
                return True
        return False

    async def _worker(self) -> None:
        """Background worker that processes the transfer queue."""
        while self._running:
            task = self._dequeue()
            if task is None:
                await asyncio.sleep(0.05)
                continue

            if task.cancelled:
                continue

            async with self._semaphore:
                self._active[task.task_id] = task
                try:
                    await self._send_task(task)
                except asyncio.CancelledError:
                    task.cancelled = True
                finally:
                    self._active.pop(task.task_id, None)
                    if task.completed:
                        self._completed.append(task)
                    cb = self._callbacks.pop(task.task_id, None)
                    if cb and task.completed:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(task)
                        else:
                            cb(task)

    def _dequeue(self) -> TransferTask | None:
        """Get the highest-priority task from the queue."""
        with self._lock:
            for queue in (self._high_queue, self._medium_queue, self._low_queue):
                if queue:
                    return queue.popleft()
            return None

    async def _send_task(self, task: TransferTask) -> None:
        """Send a complete tensor transfer in chunks."""
        data = task.data
        session = None  # Session provided by caller via context

        header = {
            "task_id": task.task_id,
            "tensor_id": task.tensor_id,
            "total_size": len(data),
            "chunk_size": self.chunk_size,
            "checksum": task.checksum,
            "destination": task.destination,
        }

        # Store header for caller to send
        task._header_bytes = __import__('json').dumps(header).encode("utf-8")

        offset = 0
        seq = 0
        while offset < len(data) and not task.cancelled:
            chunk = data[offset:offset + self.chunk_size]
            buf = self._buffer_pool.acquire()
            try:
                buf[:len(chunk)] = chunk
                # Chunk metadata stored for caller
                if not hasattr(task, '_chunks'):
                    task._chunks = []
                task._chunks.append({
                    "sequence": seq,
                    "offset": offset,
                    "length": len(chunk),
                })
                offset += len(chunk)
                seq += 1
                task.bytes_sent = offset
                # Yield control to overlap with computation
                if seq % 4 == 0:
                    await asyncio.sleep(0)
            finally:
                self._buffer_pool.release(buf)

        if offset >= len(data) and not task.cancelled:
            task.completed = True
            logger.debug("Streaming transfer %s complete: %d bytes, %d chunks",
                         task.task_id, offset, seq)

    def get_link_metrics(self, device_id: str) -> LinkMetrics:
        """Get measured link metrics for a device."""
        with self._lock:
            if device_id not in self._link_metrics:
                self._link_metrics[device_id] = LinkMetrics(device_id=device_id)
            return self._link_metrics[device_id]

    def update_link_metrics(self, device_id: str, **kwargs: Any) -> None:
        """Update link metrics for a device."""
        with self._lock:
            if device_id not in self._link_metrics:
                self._link_metrics[device_id] = LinkMetrics(device_id=device_id)
            metrics = self._link_metrics[device_id]
            for key, value in kwargs.items():
                if hasattr(metrics, key):
                    setattr(metrics, key, value)
            metrics.last_updated = time.time()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    @property
    def queued_count(self) -> int:
        with self._lock:
            return len(self._high_queue) + len(self._medium_queue) + len(self._low_queue)

    @property
    def total_completed(self) -> int:
        with self._lock:
            return len(self._completed)

    def summary(self) -> dict[str, Any]:
        """Return a summary dict for API responses."""
        with self._lock:
            return {
                "running": self._running,
                "active": len(self._active),
                "queued_high": len(self._high_queue),
                "queued_medium": len(self._medium_queue),
                "queued_low": len(self._low_queue),
                "completed": len(self._completed),
                "max_concurrent": self.max_concurrent,
                "buffer_pool_available": self._buffer_pool.available,
            }

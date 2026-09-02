"""
Memory manager with segment allocation, residency tracking, and eviction.
"""
from __future__ import annotations
import threading
from typing import Optional
from collections import defaultdict

from aether.memory.segment import Segment, SegmentType, ResidencyState


class MemoryManager:
    def __init__(self, capacity_mb: int = 4096):
        self.capacity_bytes = capacity_mb * 1024 * 1024
        self._segments: dict[str, Segment] = {}
        self._lock = threading.RLock()
        self._tensor_index: dict[str, list[str]] = defaultdict(list)
        self._device_index: dict[str, list[str]] = defaultdict(list)

    @property
    def segment_count(self) -> int:
        return len(self._segments)

    @property
    def total_allocated_bytes(self) -> int:
        return sum(s.size_bytes for s in self._segments.values())

    @property
    def used_bytes(self) -> int:
        return self.total_allocated_bytes

    @property
    def free_bytes(self) -> int:
        return max(0, self.capacity_bytes - self.total_allocated_bytes)

    def allocate(
        self,
        name: str,
        size_bytes: int,
        seg_type: SegmentType = SegmentType.MISC,
        tensor_id: Optional[str] = None,
    ) -> Segment:
        with self._lock:
            seg = Segment(
                name=name,
                size_bytes=size_bytes,
                seg_type=seg_type,
                tensor_id=tensor_id,
            )
            self._segments[seg.segment_id] = seg
            if tensor_id:
                self._tensor_index[tensor_id].append(seg.segment_id)
            return seg

    def release(self, segment_id: str) -> bool:
        with self._lock:
            seg = self._segments.pop(segment_id, None)
            if seg is None:
                return False
            if seg.pinned:
                self._segments[segment_id] = seg
                return False
            if seg.tensor_id and segment_id in self._tensor_index.get(seg.tensor_id, []):
                self._tensor_index[seg.tensor_id].remove(segment_id)
            if seg.owner_device and segment_id in self._device_index.get(seg.owner_device, []):
                self._device_index[seg.owner_device].remove(segment_id)
            return True

    def pin(self, segment_id: str) -> bool:
        with self._lock:
            seg = self._segments.get(segment_id)
            if seg is None:
                return False
            seg.pinned = True
            return True

    def unpin(self, segment_id: str) -> bool:
        with self._lock:
            seg = self._segments.get(segment_id)
            if seg is None:
                return False
            seg.pinned = False
            return True

    def place(self, segment_id: str, device_id: str) -> bool:
        with self._lock:
            seg = self._segments.get(segment_id)
            if seg is None:
                return False
            if seg.owner_device and seg.owner_device != device_id:
                if segment_id in self._device_index.get(seg.owner_device, []):
                    self._device_index[seg.owner_device].remove(segment_id)
            seg.owner_device = device_id
            seg.residency = ResidencyState.REMOTE_RESIDENT
            self._device_index[device_id].append(segment_id)
            return True

    def mark_in_transfer(self, segment_id: str, device_id: str) -> None:
        with self._lock:
            seg = self._segments.get(segment_id)
            if seg:
                seg.residency = ResidencyState.IN_TRANSFER
                seg.owner_device = device_id
                self._device_index[device_id].append(segment_id)

    def mark_resident(self, segment_id: str, device_id: str) -> None:
        with self._lock:
            seg = self._segments.get(segment_id)
            if seg:
                seg.residency = ResidencyState.REMOTE_RESIDENT
                seg.owner_device = device_id

    def mark_executing(self, segment_id: str) -> None:
        with self._lock:
            seg = self._segments.get(segment_id)
            if seg:
                seg.residency = ResidencyState.EXECUTING

    def mark_evictable(self, segment_id: str) -> None:
        with self._lock:
            seg = self._segments.get(segment_id)
            if seg:
                seg.residency = ResidencyState.EVICTABLE

    def mark_invalid(self, segment_id: str) -> None:
        with self._lock:
            seg = self._segments.get(segment_id)
            if seg:
                seg.residency = ResidencyState.INVALID

    def get_by_tensor(self, tensor_id: str) -> list[Segment]:
        with self._lock:
            return [self._segments[sid] for sid in self._tensor_index.get(tensor_id, []) if sid in self._segments]

    def get_by_device(self, device_id: str) -> list[Segment]:
        with self._lock:
            return [self._segments[sid] for sid in self._device_index.get(device_id, []) if sid in self._segments]

    def device_memory_used(self, device_id: str) -> int:
        return sum(s.size_bytes for s in self.get_by_device(device_id))

    def get_remote_segments(self) -> list[Segment]:
        return [s for s in self._segments.values() if s.residency == ResidencyState.REMOTE_RESIDENT]

    def get_evictable(self) -> list[Segment]:
        return [s for s in self._segments.values() if s.residency == ResidencyState.EVICTABLE]

    def get_invalid(self) -> list[Segment]:
        return [s for s in self._segments.values() if s.residency == ResidencyState.INVALID]

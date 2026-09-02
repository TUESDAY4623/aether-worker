"""Advanced KV-Cache Fabric — distributed key-value cache for transformer attention.

Phase 8 §15: enables multi-device context sharing without re-computing attention history.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class KVCacheBlock:
    block_id: str
    device_id: str
    layer_index: int
    token_count: int = 0
    max_tokens: int = 2048
    data: bytes = b""
    last_accessed: float = 0.0
    pinned: bool = False


@dataclass
class CacheFragmentationReport:
    total_blocks: int = 0
    pinned_blocks: int = 0
    evictable_blocks: int = 0
    fragmentation_pct: float = 0.0
    wasted_mb: float = 0.0


@dataclass
class CacheTransferResult:
    block_id: str
    from_device: str
    to_device: str
    bytes_transferred: int = 0
    transfer_ms: float = 0.0
    success: bool = True


class KVCacheFabric:
    def __init__(self, max_total_blocks: int = 1024) -> None:
        self._lock = threading.RLock()
        self._max_total_blocks = max_total_blocks
        self._blocks: dict[str, KVCacheBlock] = {}
        self._by_device: dict[str, list[str]] = {}

    def allocate_block(self, device_id: str, layer_index: int,
                       max_tokens: int = 2048) -> KVCacheBlock | None:
        with self._lock:
            if len(self._blocks) >= self._max_total_blocks:
                evicted = self._evict_lru()
                if not evicted:
                    return None
            import time
            block_id = "kv_" + device_id + "_" + str(layer_index) + "_" + str(int(time.time() * 1000))
            block = KVCacheBlock(
                block_id=block_id,
                device_id=device_id,
                layer_index=layer_index,
                max_tokens=max_tokens,
                last_accessed=time.time(),
            )
            self._blocks[block_id] = block
            if device_id not in self._by_device:
                self._by_device[device_id] = []
            self._by_device[device_id].append(block_id)
            return block

    def get_block(self, block_id: str) -> KVCacheBlock | None:
        with self._lock:
            block = self._blocks.get(block_id)
            if block:
                block.last_accessed = datetime.utcnow().timestamp()
            return block

    def pin_block(self, block_id: str) -> bool:
        with self._lock:
            block = self._blocks.get(block_id)
            if block:
                block.pinned = True
                return True
            return False

    def unpin_block(self, block_id: str) -> bool:
        with self._lock:
            block = self._blocks.get(block_id)
            if block:
                block.pinned = False
                return True
            return False

    def transfer_block(self, block_id: str, target_device_id: str) -> CacheTransferResult | None:
        with self._lock:
            block = self._blocks.get(block_id)
            if not block:
                return None
            block.device_id = target_device_id
            block.last_accessed = datetime.utcnow().timestamp()
            return CacheTransferResult(
                block_id=block_id,
                from_device=block.device_id,
                to_device=target_device_id,
                bytes_transferred=len(block.data),
                transfer_ms=len(block.data) / (1024 * 1024) * 10.0,
            )

    def get_fragmentation_report(self) -> CacheFragmentationReport:
        with self._lock:
            total = len(self._blocks)
            pinned = sum(1 for b in self._blocks.values() if b.pinned)
            evictable = total - pinned
            frag_pct = (evictable / max(total, 1)) * 100.0
            return CacheFragmentationReport(
                total_blocks=total,
                pinned_blocks=pinned,
                evictable_blocks=evictable,
                fragmentation_pct=frag_pct,
            )

    def get_device_blocks(self, device_id: str) -> list[KVCacheBlock]:
        with self._lock:
            block_ids = self._by_device.get(device_id, [])
            return [self._blocks[bid] for bid in block_ids if bid in self._blocks]

    def _evict_lru(self) -> str | None:
        candidates = [(b.last_accessed, bid) for bid, b in self._blocks.items() if not b.pinned]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        evict_id = candidates[0][1]
        block = self._blocks.pop(evict_id)
        if block.device_id in self._by_device:
            try:
                self._by_device[block.device_id].remove(evict_id)
            except ValueError:
                pass
        logger.info("Evicted KV block %s from device %s", evict_id, block.device_id)
        return evict_id

# Aether Memory — Distributed Memory Management

Manages tensor segment allocation, residency tracking, and eviction across devices.

## Modules

| File | Purpose |
|---|---|
| `segment.py` | Segment data model (enums, Segment dataclass) |
| `manager.py` | Memory manager (allocate, release, pin, place, evict) |

## Segment Model (`segment.py`)

### Residency States

| State | Meaning |
|---|---|
| `local` | Segment resides on the host device |
| `remote_resident` | Segment is on a remote worker |
| `in_transfer` | Segment is currently being transferred |
| `executing` | Segment is actively being computed on |
| `evictable` | Segment can be evicted to free memory |
| `invalid` | Segment data is stale/invalid |

### Segment Types

| Type | Purpose |
|---|---|
| `MODEL_WEIGHTS` | Model parameter tensors |
| `ACTIVATION` | Intermediate activation tensors |
| `GRADIENT` | Training gradient tensors |
| `MISC` | Other data |

### Segment Priorities

| Priority | Value |
|---|---|
| `HIGH` | 1 — never evict without explicit instruction |
| `MEDIUM` | 2 — normal eviction candidate |
| `LOW` | 3 — first to be evicted |

## Memory Manager (`manager.py`)

The `MemoryManager` provides thread-safe segment management:

### Operations

| Method | Purpose |
|---|---|
| `allocate(name, size, type)` | Create a new segment |
| `release(segment_id)` | Free a segment (blocked if pinned) |
| `pin(segment_id)` | Mark segment as non-evictable |
| `unpin(segment_id)` | Mark segment as evictable |
| `place(segment_id, device_id)` | Assign segment to a device |
| `mark_in_transfer(segment_id, device_id)` | Mark as being transferred |
| `mark_resident(segment_id, device_id)` | Mark as resident on device |
| `mark_executing(segment_id)` | Mark as actively computing |
| `mark_evictable(segment_id)` | Mark as eviction candidate |
| `mark_invalid(segment_id)` | Mark as stale |

### Indexing

- **Tensor index:** Maps `tensor_id → [segment_id, ...]`
- **Device index:** Maps `device_id → [segment_id, ...]`

### Queries

| Method | Returns |
|---|---|
| `get_by_tensor(tensor_id)` | All segments for a tensor |
| `get_by_device(device_id)` | All segments on a device |
| `device_memory_used(device_id)` | Total bytes on device |
| `get_remote_segments()` | All remote-resident segments |
| `get_evictable()` | All evictable segments |
| `get_invalid()` | All invalid segments |

## Thread Safety

All operations use `threading.RLock()` for reentrant locking, safe for concurrent access from the async event loop and background threads.

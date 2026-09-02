# Aether Intelligence — AI-Assisted Orchestration

Autonomous planning, self-healing, KV-cache fabric, and device hierarchy.

## Modules

| File | Purpose |
|---|---|
| `planner.py` | Autonomous execution plan generator |
| `self_healing.py` | Health monitoring + automatic failover |
| `kv_fabric.py` | Distributed KV-cache fabric for transformer attention |
| `hierarchy.py` | Supervisor-subordinate device hierarchy |

## Autonomous Planner (`planner.py`)

### Planning Strategies

| Strategy | Goal |
|---|---|
| `AUTOMATIC` | Balance all factors |
| `LOW_LATENCY` | Minimize inference latency |
| `THROUGHPUT` | Maximize requests/second |
| `ENERGY_EFFICIENT` | Minimize battery drain |
| `THERMAL_SAFE` | Avoid thermal throttle |

The planner takes a `ResourceSnapshot` per device and produces an `ExecutionPlan` with:
- Per-device layer assignments
- Estimated latency and energy consumption
- Confidence score (0.0–1.0)
- Fallback plan string

### ResourceSnapshot

```python
@dataclass
class ResourceSnapshot:
    device_id: str
    cpu_cores: int
    cpu_utilization_pct: float
    memory_available_mb: int
    memory_total_mb: int
    npu_available: bool
    gpu_available: bool
    bandwidth_mbps: float
    temperature_c: float
    battery_pct: float
    is_charging: bool
    latency_to_controller_ms: float
```

## Self-Healing Engine (`self_healing.py`)

### Health States

| Status | Meaning |
|---|---|
| `healthy` | Device operating normally |
| `degraded` | Partial failure, reduced capability |
| `failing` | Repeated failures, needs failover |
| `recovering` | Failover in progress |
| `offline` | Device unreachable |

### Failure Types

| Type | Trigger |
|---|---|
| `TRANSPORT_DISCONNECT` | TCP connection lost |
| `THERMAL_THROTTLE` | Device exceeded thermal limits |
| `MEMORY_EXHAUSTION` | Out of memory on device |
| `COMPUTE_ERROR` | Inference runtime error |
| `DEVICE_UNAVAILABLE` | Device not responding |

### Failover Actions

The engine automatically migrates layers from a failing device to a healthy one:

```python
action = self_healing.attempt_recovery(
    device_id="failed-worker",
    target_device_id="backup-worker",
    layers=[12, 13, 14, 15, 16, 17, 18],
)
```

If ≥50% of devices are degraded, the engine triggers `local_only` fallback.

## KV-Cache Fabric (`kv_fabric.py`)

Manages distributed key-value cache blocks for transformer attention:

- **Max blocks:** 1024 (configurable)
- **Block allocation:** Per-device, per-layer
- **Pinning:** Prevents eviction of active blocks
- **LRU eviction:** Evicts least-recently-used unpinned blocks when full
- **Transfer:** `transfer_block()` migrates a block between devices

### Fragmentation Report

```python
report = kv_fabric.get_fragmentation_report()
# report.total_blocks, report.pinned_blocks, report.fragmentation_pct
```

## Device Hierarchy (`hierarchy.py`)

Multi-level coordination for cluster-scale deployment:

| Role | Description |
|---|---|
| `super` | Top-level orchestrator (the controller) |
| `primary` | First-level coordinator (e.g., a powerful tablet) |
| `secondary` | Mid-level coordinator |
| `worker` | Leaf compute node (e.g., phone) |
| `standby` | Inactive but available |

The hierarchy supports:
- Node registration with automatic parent assignment
- Role promotion/demotion
- Parent reassignment
- Descendant tree traversal

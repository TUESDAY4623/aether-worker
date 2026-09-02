# Aether Scheduler — Workload Scheduling

Determines which worker device should handle each inference segment or compute task.

## Module

| File | Purpose |
|---|---|
| `rule_based.py` | Weighted rule-based device scoring and selection |

## RuleBasedScheduler

Phase 1 deterministic scheduler using weighted factor scoring:

### Scoring Weights

| Factor | Weight | Description |
|---|---|---|
| Compute | 0.25 | CPU/core availability |
| Memory | 0.25 | Free RAM ratio |
| Thermal | 0.20 | Thermal state (normal→100, critical→0) |
| Latency | 0.15 | Network latency to device |
| Power | 0.10 | Battery level / charging status |
| Utilization | 0.05 | Inverse of CPU utilization |

### DeviceScore

```python
@dataclass
class DeviceScore:
    device_id: str
    score: float                    # Total weighted score (0–100)
    compute_score: float
    memory_score: float
    thermal_score: float
    latency_score: float
    power_score: float
    utilization_score: float
    details: dict                   # Free ratio, thermal state, battery %
```

### Selection Methods

| Method | Use Case |
|---|---|
| `select_device_for_segment(device_ids, segment_size_mb)` | Choose best device for memory segment placement |
| `select_device_for_compute(device_ids, min_memory_mb, required_ops)` | Choose best device for compute task |
| `score_all(device_ids)` | Score all devices for dashboard display |

### Thermal Score Mapping

| Thermal State | Score |
|---|---|
| `normal` | 100.0 |
| `warm` | 70.0 |
| `hot` | 30.0 |
| `critical` | 0.0 |
| `recovery` | 50.0 |

### Power Score Logic

- `is_charging or battery_pct > 50` → 50.0
- Otherwise → 20.0 (conserves battery)

## Future: ML-Based Scheduler

Phase 3 will replace this with a reinforcement learning scheduler that learns optimal placements from historical telemetry data.

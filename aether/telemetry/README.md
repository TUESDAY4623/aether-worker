# Aether Telemetry — Device Metrics Collection

Collects, stores, and analyzes telemetry data from all connected devices.

## Module

| File | Purpose |
|---|---|
| `collector.py` | DeviceTelemetry dataclass, TelemetryCollector |

## DeviceTelemetry

```python
@dataclass
class DeviceTelemetry:
    device_id: str
    timestamp: float              # Unix epoch
    temperature_c: float           # Device temperature
    memory_total_mb: int           # Total RAM
    memory_available_mb: int       # Free RAM
    memory_aether_reserved_mb: int # Aether-managed reserved memory
    cpu_utilization_pct: float     # CPU usage 0-100
    npu_utilization_pct: float     # NPU usage 0-100
    battery_pct: float             # Battery level 0-100
    is_charging: bool              # Charging status
    power_state: str               # "charging", "discharging", "full"
    network_latency_ms: float      # Round-trip latency
    tensor_bandwidth_mbps: float   # Tensor transfer throughput
    available: bool                # Device availability
```

## TelemetryCollector

### Storage

- **Rolling history:** Last 1000 snapshots per device (configurable)
- **Latest cache:** O(1) lookup of most recent telemetry per device

### Methods

| Method | Returns | Purpose |
|---|---|---|
| `report(telemetry)` | — | Store a new telemetry snapshot |
| `get_latest(device_id)` | `DeviceTelemetry \| None` | Most recent snapshot |
| `get_history(device_id, count)` | `list[DeviceTelemetry]` | Last N snapshots |
| `temperature_trend(device_id, window_s)` | `float` | Degrees/sec trend (positive = heating) |
| `all_latest()` | `dict[str, DeviceTelemetry]` | Latest for all devices |

### Temperature Trend Calculation

Uses linear regression over the last `window_s` seconds:

```
trend = (n * Σ(xy) - Σx * Σy) / (n * Σ(x²) - (Σx)²)
```

Where `x` = time, `y` = temperature. Returns degrees Celsius per second.

### Integration

The telemetry collector is populated by:
- **Worker → Controller:** `TELEMETRY_REPORT` messages over TCP
- **Controller → REST API:** `/telemetry/{device_id}` endpoint
- **Scheduler:** Reads telemetry for device scoring
- **Thermal Manager:** Uses telemetry for thermal state transitions

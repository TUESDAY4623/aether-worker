# Aether Workers — Worker Device Registry

Tracks all discovered and paired worker devices.

## Module

| File | Purpose |
|---|---|
| `registry.py` | WorkerRegistry, WorkerDevice, WorkerCapabilities |

## WorkerCapabilities

Describes the hardware and software capabilities of a worker device:

```python
@dataclass
class WorkerCapabilities:
    device_model: str           # e.g., "SM-X620"
    cpu_cores: int              # Number of CPU cores
    cpu_arch: str               # e.g., "arm64-v8a"
    total_ram_mb: int           # Total device RAM
    available_ram_mb: int       # Currently available RAM
    has_npu: bool               # NPU available
    supported_ops: list[str]    # Supported NN operations
    supported_dtypes: list[str] # Supported data types
    max_tensor_dim: int         # Max tensor dimension
    estimated_compute_mbps: float # Estimated throughput
    transport_types: list[str]  # Supported transports (wifi, usb, bt)
```

## WorkerDevice

```python
@dataclass
class WorkerDevice:
    device_id: str               # Unique device identifier
    display_name: str            # Human-readable name
    capabilities: WorkerCapabilities
    connected_at: float          # Unix timestamp
    last_seen: float             # Last telemetry timestamp
    paired: bool                 # Pairing status
    session_id: str              # Transport session ID
    thermal_state: str           # Current thermal state
    available: bool              # Accepting work
    transport: str               # "wifi", "usb", "bt"
    peer_addr: str               # IP:port
```

## WorkerRegistry

### Methods

| Method | Purpose |
|---|---|
| `register(worker)` | Add or update a worker |
| `unregister(device_id)` | Remove a worker |
| `get(device_id)` | Get specific worker |
| `get_paired()` | All paired + available workers |
| `get_available()` | All available workers |
| `mark_unavailable(device_id)` | Mark as not accepting work |
| `mark_available(device_id)` | Mark as accepting work |
| `check_stale()` | Find workers exceeding discovery timeout |
| `update_thermal(device_id, state)` | Update thermal state |
| `count` | Total registered workers |
| `all_workers` | List of all workers |

### Stale Detection

`check_stale()` returns device IDs where `now - last_seen > discovery_timeout_s`. The controller's background loop calls this periodically and marks stale workers unavailable.

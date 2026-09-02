# Aether Execution — Compute Scheduling

Orchestrates how inference workloads are distributed across devices.

## Modules

| File | Purpose |
|---|---|
| `pipeline.py` | Execution pipeline orchestration |
| `accelerator.py` | Accelerator manager (CPU, GPU, NPU, TPU, DSP) |
| `topology.py` | Topology optimizer + placement strategies |
| `simulation.py` | Simulation environment for partition plans |
| `resource_pool.py` | Resource pool manager |

## Accelerator Abstraction (`accelerator.py`)

The `AcceleratorManager` provides a unified interface for heterogeneous compute:

| Accelerator Type | Notes |
|---|---|
| `cpu` | General-purpose, always available |
| `gpu` | OpenGL ES / Vulkan compute |
| `npu` | Android NNAPI / Samsung NPU |
| `tpu` | Coral / Edge TPU |
| `dsp` | Qualcomm Hexagon DSP |

Each accelerator reports:
- Peak TOPS (tera-operations per second)
- Available memory
- Thermal throttle temperature
- Runtime availability status

## Topology Optimization (`topology.py`)

### Placement Strategies

| Strategy | Description |
|---|---|
| `greedy` | Assign layers to first available device |
| `balanced` | Distribute evenly across all devices |
| `memory_aware` | Prioritize devices with most free RAM |
| `thermal_safe` | Avoid devices near thermal throttle |

The optimizer builds a topology graph from device list, then optimizes layer placement to minimize total estimated latency.

## Simulation (`simulation.py`)

The `SimulationEnvironment` allows testing partition plans without real hardware:

```python
sim = SimulationEnvironment()
partitions = [SimulatedPartition(device_id="worker-1", layers=[0,1,2]), ...]
result = sim.simulate_partition("sim_001", partitions)
# result.total_latency_ms, result.feasible, result.bottleneck_device
```

## Resource Pool (`resource_pool.py`)

Manages per-device resource reservations:

- Tracks CPU cores, memory, NPU/GPU availability
- Supports allocation strategies: `FILL`, `SPREAD`, `BIN_PACK`
- Thread-safe device registry with thermal state tracking

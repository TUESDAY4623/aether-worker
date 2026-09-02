"""Accelerator Abstraction Layer — CPU, NPU, GPU abstraction."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AcceleratorType(str, Enum):
    CPU = "cpu"
    NPU = "npu"
    GPU = "gpu"
    TPU = "tpu"
    DSP = "dsp"


class AcceleratorState(str, Enum):
    IDLE = "idle"
    ACTIVE = "active"
    THROTTLED = "throttled"
    OVERHEATING = "overheating"
    UNAVAILABLE = "unavailable"


@dataclass
class AcceleratorCapabilities:
    accelerator_type: AcceleratorType
    device_id: str
    model_name: str
    peak_tops: float = 0.0
    memory_mb: int = 0
    operator_support: list[str] = field(default_factory=list)
    max_power_w: float = 0.0
    thermal_throttle_c: float = 80.0
    runtime_available: bool = False
    runtime_name: str = ""
    driver_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class AcceleratorRuntime:
    accelerator_type: AcceleratorType
    device_id: str
    capabilities: AcceleratorCapabilities

    def is_available(self) -> bool:
        return False

    def execute(self, op_name: str, inputs: list, **kwargs) -> Any:
        raise NotImplementedError

    def get_throughput(self, op_name: str) -> float:
        return 0.0

    def get_memory_usage_mb(self) -> int:
        return 0

    def get_temperature_c(self) -> float:
        return 45.0


class CPUAcceleratorRuntime(AcceleratorRuntime):
    def __init__(self, capabilities: AcceleratorCapabilities) -> None:
        super().__init__(AcceleratorType.CPU, capabilities.device_id, capabilities)

    def is_available(self) -> bool:
        return True

    def execute(self, op_name: str, inputs: list, **kwargs) -> Any:
        return inputs[0] if inputs else None

    def get_throughput(self, op_name: str) -> float:
        return 1.0


class NPUAcceleratorRuntime(AcceleratorRuntime):
    def __init__(self, capabilities: AcceleratorCapabilities) -> None:
        super().__init__(AcceleratorType.NPU, capabilities.device_id, capabilities)
        self._available = capabilities.runtime_available
        self._last_benchmark: dict[str, float] = {}

    def is_available(self) -> bool:
        return self._available and self.capabilities.runtime_available

    def execute(self, op_name: str, inputs: list, **kwargs) -> Any:
        if not self.is_available():
            raise RuntimeError("NPU not available")
        if op_name not in self.capabilities.operator_support:
            raise RuntimeError("Operator not supported on NPU")
        return inputs[0] if inputs else None

    def get_throughput(self, op_name: str) -> float:
        return self._last_benchmark.get(op_name, 0.0)

    def benchmark_operator(self, op_name: str, warmup: int = 3, runs: int = 10) -> float:
        import time
        for _ in range(warmup):
            try:
                self.execute(op_name, [None])
            except Exception:
                return 0.0
        start = time.perf_counter()
        for _ in range(runs):
            try:
                self.execute(op_name, [None])
            except Exception:
                return 0.0
        elapsed = time.perf_counter() - start
        ops_per_sec = runs / elapsed
        self._last_benchmark[op_name] = ops_per_sec
        logger.info("NPU benchmark %s: ops/s", op_name)
        return ops_per_sec

    def should_use_npu(self, op_name: str, tensor_size_mb: float, cpu_throughput: float) -> bool:
        npu_throughput = self.get_throughput(op_name)
        if npu_throughput == 0.0:
            return False
        transfer_ms = tensor_size_mb * 0.05
        npu_time = (1.0 / npu_throughput) * 1000 + transfer_ms
        cpu_time = (1.0 / cpu_throughput) * 1000 if cpu_throughput > 0 else float("inf")
        return npu_time < cpu_time


class GPUAcceleratorRuntime(AcceleratorRuntime):
    def __init__(self, capabilities: AcceleratorCapabilities) -> None:
        super().__init__(AcceleratorType.GPU, capabilities.device_id, capabilities)
        self._available = capabilities.runtime_available

    def is_available(self) -> bool:
        return self._available and self.capabilities.runtime_available

    def execute(self, op_name: str, inputs: list, **kwargs) -> Any:
        if not self.is_available():
            raise RuntimeError("GPU not available")
        return inputs[0] if inputs else None


class AcceleratorManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._capabilities: dict[str, AcceleratorCapabilities] = {}
        self._runtimes: dict[str, AcceleratorRuntime] = {}

    def register_capabilities(self, caps: AcceleratorCapabilities) -> AcceleratorRuntime:
        with self._lock:
            self._capabilities[caps.device_id] = caps
            if caps.accelerator_type == AcceleratorType.CPU:
                runtime = CPUAcceleratorRuntime(caps)
            elif caps.accelerator_type == AcceleratorType.NPU:
                runtime = NPUAcceleratorRuntime(caps)
            elif caps.accelerator_type == AcceleratorType.GPU:
                runtime = GPUAcceleratorRuntime(caps)
            else:
                raise ValueError("Unsupported accelerator type")
            self._runtimes[caps.device_id] = runtime
            logger.info("Registered accelerator: %s (%s)", caps.device_id, caps.accelerator_type.value)
            return runtime

    def get_runtime(self, device_id: str) -> AcceleratorRuntime | None:
        with self._lock:
            return self._runtimes.get(device_id)

    def list_available(self) -> list[str]:
        with self._lock:
            return [did for did, rt in self._runtimes.items() if rt.is_available()]

    def select_for_operation(self, op_name: str, tensor_size_mb: float = 0.0,
                             preferred_type: AcceleratorType | None = None
                             ) -> tuple[str, AcceleratorRuntime] | None:
        with self._lock:
            candidates = []
            for did, rt in self._runtimes.items():
                if not rt.is_available():
                    continue
                if preferred_type and rt.accelerator_type != preferred_type:
                    continue
                throughput = rt.get_throughput(op_name)
                candidates.append((throughput, did, rt))
            candidates.sort(key=lambda x: x[0], reverse=True)
            if candidates:
                _, did, rt = candidates[0]
                return did, rt
            return None
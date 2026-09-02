"""
Aether REST API — FastAPI server for control-plane operations.

Production-ready with structured errors, request IDs, health probes, and
config-driven initialization.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import os
from pathlib import Path

from aether.config import CONTROLLER_HOST, CONTROLLER_PORT
from aether.telemetry.collector import DeviceTelemetry
from aether.thermal.manager import ThermalManager
from aether.scheduler.rule_based import RuleBasedScheduler
from aether.workers.registry import WorkerRegistry, WorkerDevice, WorkerCapabilities
from aether.model.manifest import ModelManifest, ModelPartitioner, PartitionPlan
from aether.intelligence.self_healing import HealthStatus

logger = logging.getLogger(__name__)


# ─── Request/Response Models ────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    """Structured error response for API consumers."""
    error: str
    detail: str
    request_id: str
    timestamp: float

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "error": "not_initialized",
                    "detail": "API services have not been initialized",
                    "request_id": "abc12345",
                    "timestamp": 1690000000.0,
                }
            ]
        }
    }


class WorkerInfo(BaseModel):
    device_id: str
    display_name: str
    paired: bool
    available: bool
    thermal_state: str
    transport: str
    peer_addr: str
    last_seen: float
    capabilities: Optional[dict] = None


class TelemetryInfo(BaseModel):
    device_id: str
    temperature_c: float
    battery_pct: float
    is_charging: bool
    cpu_utilization_pct: float
    npu_utilization_pct: float
    memory_available_mb: int
    memory_total_mb: int
    tensor_bandwidth_mbps: float
    network_latency_ms: float
    timestamp: float


class PartitionRequest(BaseModel):
    model_id: str
    model_name: str
    layers: list[dict]
    quantization: str = "int4"
    device_ids: list[str]
    strategy: str = "memory_only"
    local_device: str = "laptop"


class PartitionResponse(BaseModel):
    model_id: str
    strategy: str
    placements: list[dict]
    estimated_compute_ms: float
    estimated_transfer_mb: float


class HealthResponse(BaseModel):
    status: str
    version: str
    workers_connected: int
    workers_paired: int


class HealthDetailResponse(BaseModel):
    status: str
    checks: dict[str, str]


# ─── API App ────────────────────────────────────────────────────────────────

api = FastAPI(
    title="Aether Control API",
    description="REST API for Aether distributed AI fabric — control plane for distributed memory, scheduling, and inference.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_telemetry: "TelemetryCollector | None" = None
_thermal: "ThermalManager | None" = None
_scheduler: "RuleBasedScheduler | None" = None
_registry: "WorkerRegistry | None" = None
_partitioner: "ModelPartitioner | None" = None
_model_registry: Any = None
_accelerator_mgr: Any = None
_resource_pool_mgr: Any = None
_topology_optimizer: Any = None
_simulation_env: Any = None
_planner: Any = None
_self_healing_engine: Any = None
_kv_fabric: Any = None
_hierarchy: Any = None
_started_at: float = time.time()

# Serve the dashboard frontend from the dashboard directory
_dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"
if _dashboard_dir.exists():
    api.mount("/static", StaticFiles(directory=str(_dashboard_dir)), name="dashboard-static")

    @api.get("/", include_in_schema=False)
    async def serve_dashboard():
        from fastapi.responses import FileResponse
        return FileResponse(str(_dashboard_dir / "index.html"))


def init_api(telemetry, thermal, scheduler, registry, partitioner=None,
             model_registry=None, accelerator_mgr=None, resource_pool_mgr=None,
             topology_optimizer=None, simulation_env=None, planner=None,
             self_healing_engine=None, kv_fabric=None, hierarchy=None):
    """Initialize API dependencies from the controller."""
    global _telemetry, _thermal, _scheduler, _registry, _partitioner
    global _model_registry, _accelerator_mgr, _resource_pool_mgr
    global _topology_optimizer, _simulation_env, _planner
    global _self_healing_engine, _kv_fabric, _hierarchy
    _telemetry = telemetry
    _thermal = thermal
    _scheduler = scheduler
    _registry = registry
    _partitioner = partitioner
    _model_registry = model_registry
    _accelerator_mgr = accelerator_mgr
    _resource_pool_mgr = resource_pool_mgr
    _topology_optimizer = topology_optimizer
    _simulation_env = simulation_env
    _planner = planner
    _self_healing_engine = self_healing_engine
    _kv_fabric = kv_fabric
    _hierarchy = hierarchy


@api.middleware("http")
async def add_request_id(request: Request, call_next):
    """Generate or propagate X-Request-ID for request tracing."""
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@api.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Return structured 422 for validation errors."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.warning("Validation error: %s", exc, extra={"request_id": request_id})
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="validation_error",
            detail=str(exc),
            request_id=request_id,
            timestamp=time.time(),
        ).model_dump(),
    )


@api.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Return structured 500 without exposing internals."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error("Unhandled exception: %s", exc, exc_info=True, extra={"request_id": request_id})
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            detail="An unexpected error occurred. Please check server logs.",
            request_id=request_id,
            timestamp=time.time(),
        ).model_dump(),
    )


def _check_initialized() -> None:
    """Raise 503 if API dependencies are not initialized."""
    if not all([_telemetry, _thermal, _scheduler, _registry]):
        raise HTTPException(
            status_code=503,
            detail="API services have not been initialized. The controller is still starting up.",
        )


def _get_model_registry():
    """Get or create model capability registry."""
    global _model_registry
    if _model_registry is None:
        from aether.model.capability_registry import ModelCapabilityRegistry
        _model_registry = ModelCapabilityRegistry()
    return _model_registry


def _get_accelerator_manager():
    """Get or create accelerator manager."""
    global _accelerator_mgr
    if _accelerator_mgr is None:
        from aether.execution.accelerator import AcceleratorManager
        _accelerator_mgr = AcceleratorManager()
    return _accelerator_mgr


def _get_resource_pool_manager():
    """Get or create resource pool manager."""
    global _resource_pool_mgr
    if _resource_pool_mgr is None:
        from aether.execution.resource_pool import ResourcePoolManager
        _resource_pool_mgr = ResourcePoolManager()
    return _resource_pool_mgr


def _get_topology_optimizer():
    """Get or create topology optimizer."""
    global _topology_optimizer
    if _topology_optimizer is None:
        from aether.execution.topology import TopologyOptimizer
        _topology_optimizer = TopologyOptimizer()
    return _topology_optimizer


def _get_simulation_environment():
    """Get or create simulation environment."""
    global _simulation_env
    if _simulation_env is None:
        from aether.execution.simulation import SimulationEnvironment
        _simulation_env = SimulationEnvironment()
    return _simulation_env


def _get_planner():
    """Get or create autonomous planner."""
    global _planner
    if _planner is None:
        from aether.intelligence.planner import AutonomousPlanner
        _planner = AutonomousPlanner()
    return _planner


def _get_self_healing_engine():
    """Get or create self-healing engine."""
    global _self_healing_engine
    if _self_healing_engine is None:
        from aether.intelligence.self_healing import SelfHealingEngine
        _self_healing_engine = SelfHealingEngine()
    return _self_healing_engine


def _get_kv_fabric():
    """Get or create KV-cache fabric."""
    global _kv_fabric
    if _kv_fabric is None:
        from aether.intelligence.kv_fabric import KVCacheFabric
        _kv_fabric = KVCacheFabric()
    return _kv_fabric


def _get_hierarchy():
    """Get or create hierarchy."""
    global _hierarchy
    if _hierarchy is None:
        from aether.intelligence.hierarchy import Hierarchy
        _hierarchy = Hierarchy()
    return _hierarchy


@api.get("/health", response_model=HealthResponse)
async def health():
    """Basic liveness check — returns 200 if API is running."""
    paired = len(_registry.get_paired()) if _registry else 0
    return HealthResponse(
        status="ok",
        version="0.1.0",
        workers_connected=_registry.count if _registry else 0,
        workers_paired=paired,
    )


@api.get("/health/ready", response_model=HealthDetailResponse)
async def health_ready():
    """Readiness check — returns 200 only if all subsystems are initialized."""
    checks: dict[str, str] = {}
    if not _telemetry:
        checks["telemetry"] = "not_initialized"
    else:
        checks["telemetry"] = "ok"
    if not _thermal:
        checks["thermal"] = "not_initialized"
    else:
        checks["thermal"] = "ok"
    if not _scheduler:
        checks["scheduler"] = "not_initialized"
    else:
        checks["scheduler"] = "ok"
    if not _registry:
        checks["registry"] = "not_initialized"
    else:
        checks["registry"] = "ok"

    if all(v == "ok" for v in checks.values()):
        return HealthDetailResponse(status="ready", checks=checks)
    return JSONResponse(
        status_code=503,
        content=HealthDetailResponse(status="not_ready", checks=checks).model_dump(),
    )


@api.get("/health/live")
async def health_live():
    """Liveness probe — always returns 200 if the process is running."""
    return {"status": "alive", "uptime_s": round(time.time() - _started_at, 1)}


@api.get("/workers", response_model=list[WorkerInfo])
async def list_workers():
    _check_initialized()
    result = []
    for w in _registry.all_workers:
        result.append(WorkerInfo(
            device_id=w.device_id,
            display_name=w.display_name,
            paired=w.paired,
            available=w.available,
            thermal_state=w.thermal_state,
            transport=w.transport,
            peer_addr=w.peer_addr,
            last_seen=w.last_seen,
            capabilities=w.capabilities.to_dict() if w.capabilities.device_model else None,
        ))
    return result


@api.get("/workers/{device_id}", response_model=WorkerInfo)
async def get_worker(device_id: str):
    _check_initialized()
    w = _registry.get(device_id)
    if not w:
        raise HTTPException(status_code=404, detail=f"Worker {device_id} not found")
    return WorkerInfo(
        device_id=w.device_id,
        display_name=w.display_name,
        paired=w.paired,
        available=w.available,
        thermal_state=w.thermal_state,
        transport=w.transport,
        peer_addr=w.peer_addr,
        last_seen=w.last_seen,
        capabilities=w.capabilities.to_dict() if w.capabilities.device_model else None,
    )


@api.get("/telemetry/{device_id}", response_model=TelemetryInfo)
async def get_telemetry(device_id: str):
    _check_initialized()
    tel = _telemetry.get_latest(device_id)
    if not tel:
        raise HTTPException(status_code=404, detail=f"No telemetry for {device_id}")
    return TelemetryInfo(
        device_id=tel.device_id,
        temperature_c=tel.temperature_c,
        battery_pct=tel.battery_pct,
        is_charging=tel.is_charging,
        cpu_utilization_pct=tel.cpu_utilization_pct,
        npu_utilization_pct=tel.npu_utilization_pct,
        memory_available_mb=tel.memory_available_mb,
        memory_total_mb=tel.memory_total_mb,
        tensor_bandwidth_mbps=tel.tensor_bandwidth_mbps,
        network_latency_ms=tel.network_latency_ms,
        timestamp=tel.timestamp,
    )


@api.post("/partition", response_model=PartitionResponse)
async def partition_model(req: PartitionRequest):
    _check_initialized()
    if _partitioner is None:
        raise HTTPException(status_code=503, detail="Partitioner not initialized")
    manifest = _partitioner.create_manifest(
        req.model_id, req.model_name, req.layers, req.quantization,
    )
    plan = _partitioner.partition(manifest, req.device_ids, req.strategy, req.local_device)
    return PartitionResponse(
        model_id=plan.model_id,
        strategy=plan.strategy,
        placements=plan.placements,
        estimated_compute_ms=plan.estimated_compute_ms,
        estimated_transfer_mb=plan.estimated_transfer_mb,
    )


@api.get("/scheduler/scores")
async def scheduler_scores():
    _check_initialized()
    device_ids = [w.device_id for w in _registry.get_available()]
    scores = _scheduler.score_all(device_ids)
    return {
        did: {
            "score": round(s.score, 1),
            "thermal": s.details.get("thermal", "unknown"),
            "battery_pct": s.details.get("battery_pct", 0),
        }
        for did, s in scores.items()
    }


@api.post("/workers/{device_id}/pair")
async def trigger_pairing(device_id: str):
    _check_initialized()
    w = _registry.get(device_id)
    if not w:
        raise HTTPException(status_code=404, detail=f"Worker {device_id} not found")
    return {
        "status": "pairing_initiated",
        "device_id": device_id,
        "message": "Pairing code displayed on controller",
    }


# ─── Phase 7 Advanced Endpoints ────────────────────────────────────────────

@api.get("/models/capabilities")
async def list_model_capabilities():
    from aether.model.capability_registry import ModelCapabilityRegistry
    registry = _get_model_registry()
    profiles = registry.list_all()
    return [p.to_dict() for p in profiles]


@api.get("/models/{model_id}/capabilities")
async def get_model_capability(model_id: str):
    from aether.model.capability_registry import ModelCapabilityRegistry
    registry = _get_model_registry()
    profile = registry.get(model_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
    return profile.to_dict()


@api.get("/accelerators")
async def list_accelerators():
    from aether.execution.accelerator import AcceleratorManager
    mgr = _get_accelerator_manager()
    return mgr.to_dict()


@api.get("/resources/pool")
async def get_resource_pool():
    from aether.execution.resource_pool import ResourcePoolManager
    mgr = _get_resource_pool_manager()
    devices = {}
    for did, dev in mgr._devices.items():
        devices[did] = {
            "cpu_cores": dev.cpu_cores,
            "cpu_utilization_pct": dev.cpu_utilization_pct,
            "memory_total_mb": dev.memory_total_mb,
            "memory_available_mb": dev.memory_available_mb,
            "npu_available": dev.npu_available,
            "gpu_available": dev.gpu_available,
            "thermal_state": dev.thermal_state,
        }
    return devices


@api.post("/topology/optimize")
async def optimize_topology(request: dict):
    from aether.execution.topology import TopologyOptimizer, PlacementStrategy
    optimizer = _get_topology_optimizer()
    devices = request.get("devices", [])
    model_layers = request.get("model_layers", 32)
    strategy = PlacementStrategy(request.get("strategy", "greedy"))
    optimizer.set_strategy(strategy)
    graph = optimizer.build_topology(devices)
    result = optimizer.optimize(graph, model_layers)
    return {
        "strategy": result.strategy.value,
        "placements": [
            {
                "device_id": p.device_id,
                "layers": p.layers,
                "estimated_latency_ms": p.estimated_latency_ms,
                "thermal_risk": round(p.thermal_risk, 3),
            }
            for p in result.placements
        ],
        "total_estimated_ms": round(result.total_estimated_ms, 1),
        "feasible": result.feasible,
    }


@api.post("/simulation/run")
async def run_simulation(request: dict):
    from aether.execution.simulation import SimulationEnvironment, SimulatedPartition
    sim = _get_simulation_environment()
    partitions_data = request.get("partitions", [])
    partitions = [SimulatedPartition(**p) for p in partitions_data]
    sim_id = request.get("simulation_id", "sim_default")
    result = sim.simulate_partition(sim_id, partitions)
    return {
        "simulation_id": result.simulation_id,
        "total_latency_ms": round(result.total_latency_ms, 1),
        "max_temperature_c": round(result.max_temperature_c, 1),
        "thermal_violation": result.any_thermal_violation,
        "score": round(result.score, 1),
        "warnings": result.warnings,
    }


# ─── Phase 8 Autonomous Endpoints ─────────────────────────────────────────

@api.post("/planner/create")
async def create_execution_plan(request: dict):
    from aether.intelligence.planner import AutonomousPlanner, PlanningStrategy
    from aether.intelligence.planner import ResourceSnapshot
    planner = _get_planner()
    resources_data = request.get("resources", [])
    resources = [ResourceSnapshot(**r) for r in resources_data]
    strategy_str = request.get("strategy")
    strategy = PlanningStrategy(strategy_str) if strategy_str else None
    plan = planner.create_plan(
        model_id=request.get("model_id", ""),
        resources=resources,
        model_layers=request.get("model_layers", 32),
        strategy=strategy,
    )
    return {
        "plan_id": plan.plan_id,
        "model_id": plan.model_id,
        "strategy": plan.strategy.value,
        "device_assignments": plan.device_assignments,
        "estimated_latency_ms": round(plan.estimated_latency_ms, 1),
        "estimated_energy_j": round(plan.estimated_energy_j, 2),
        "confidence": round(plan.confidence, 2),
        "fallback_plan": plan.fallback_plan,
    }


@api.get("/health/devices")
async def get_all_device_health():
    from aether.intelligence.self_healing import SelfHealingEngine
    engine = _get_self_healing_engine()
    results = {}
    for device_id in engine._health:
        record = engine.get_health(device_id)
        if record:
            results[device_id] = {
                "status": record.status.value,
                "failure_count": record.failure_count,
                "last_failure": record.last_failure,
                "recovery_attempts": record.recovery_attempts,
            }
    return results


@api.post("/health/devices/{device_id}/report")
async def report_device_health(device_id: str, request: dict):
    from aether.intelligence.self_healing import SelfHealingEngine, FailureType, HealthStatus
    engine = _get_self_healing_engine()
    status_str = request.get("status", "healthy")
    failure_str = request.get("failure_type")
    failure_type = FailureType(failure_str) if failure_str else None
    engine.update_health(device_id, HealthStatus(status_str), failure_type)
    return {"status": "recorded", "device_id": device_id}


@api.get("/kv-cache/fragmentation")
async def get_kv_cache_fragmentation():
    from aether.intelligence.kv_fabric import KVCacheFabric
    fabric = _get_kv_fabric()
    report = fabric.get_fragmentation_report()
    return {
        "total_blocks": report.total_blocks,
        "pinned_blocks": report.pinned_blocks,
        "evictable_blocks": report.evictable_blocks,
        "fragmentation_pct": round(report.fragmentation_pct, 1),
        "wasted_mb": round(report.wasted_mb, 1),
    }


@api.get("/hierarchy")
async def get_hierarchy():
    from aether.intelligence.hierarchy import Hierarchy
    hier = _get_hierarchy()
    nodes = {}
    for node_id in hier.list_nodes():
        node = hier.get_node(node_id)
        if node:
            nodes[node_id] = {
                "role": node.role.value,
                "parent_id": node.parent_id,
                "children": node.children,
                "max_children": node.max_children,
            }
    return {
        "super_node": hier._super_node,
        "node_count": len(nodes),
        "role_summary": hier.get_role_summary(),
        "nodes": nodes,
    }

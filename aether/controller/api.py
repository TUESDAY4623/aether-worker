"""
Aether Controller REST API — FastAPI application.

Production-ready endpoints for health, workers, telemetry, transfers, and pairing.
Serves the Aether dashboard frontend at the root path.
"""
from __future__ import annotations

import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Body

# Phase 7/8 subsystems (lazy-initialized singletons)
try:
    from aether.model.capability_registry import ModelCapabilityRegistry, register_builtin_models
except Exception:  # pragma: no cover
    ModelCapabilityRegistry = None
    register_builtin_models = None

try:
    from aether.execution.accelerator import AcceleratorManager
except Exception:  # pragma: no cover
    AcceleratorManager = None

try:
    from aether.execution.resource_pool import ResourcePoolManager, ResourceType, AllocationStrategy
except Exception:  # pragma: no cover
    ResourcePoolManager = None
    ResourceType = None
    AllocationStrategy = None

try:
    from aether.execution.simulation import SimulationEnvironment
except Exception:  # pragma: no cover
    SimulationEnvironment = None

try:
    from aether.intelligence.planner import (
        AutonomousPlanner, PlanningStrategy, ResourceSnapshot,
    )
except Exception:  # pragma: no cover
    AutonomousPlanner = None
    PlanningStrategy = None
    ResourceSnapshot = None

try:
    from aether.intelligence.self_healing import (
        SelfHealingEngine, HealthStatus, FailureType,
    )
except Exception:  # pragma: no cover
    SelfHealingEngine = None
    HealthStatus = None
    FailureType = None

try:
    from aether.intelligence.hierarchy import Hierarchy, HierarchyRole
except Exception:  # pragma: no cover
    Hierarchy = None
    HierarchyRole = None

# Lazy singletons
_model_registry = None
_accel_manager = None
_resource_pool = None
_simulation_env = None
_planner = None
_healing = None
_hierarchy = None


def _get_model_registry():
    global _model_registry
    if _model_registry is None and ModelCapabilityRegistry is not None:
        _model_registry = ModelCapabilityRegistry()
        if register_builtin_models is not None:
            try:
                register_builtin_models(_model_registry)
            except Exception as exc:
                logger.warning("register_builtin_models failed: %s", exc)
    return _model_registry


def _get_accel_manager():
    global _accel_manager
    if _accel_manager is None and AcceleratorManager is not None:
        _accel_manager = AcceleratorManager()
    return _accel_manager


def _get_resource_pool():
    global _resource_pool
    if _resource_pool is None and ResourcePoolManager is not None:
        _resource_pool = ResourcePoolManager()
    return _resource_pool


def _get_simulation_env():
    global _simulation_env
    if _simulation_env is None and SimulationEnvironment is not None:
        _simulation_env = SimulationEnvironment()
    return _simulation_env


def _get_planner():
    global _planner
    if _planner is None and AutonomousPlanner is not None:
        _planner = AutonomousPlanner()
    return _planner


def _get_healing():
    global _healing
    if _healing is None and SelfHealingEngine is not None:
        _healing = SelfHealingEngine()
    return _healing


def _get_hierarchy():
    global _hierarchy
    if _hierarchy is None and Hierarchy is not None:
        _hierarchy = Hierarchy()
    return _hierarchy
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Aether Controller API",
    description="REST API for the Aether distributed AI fabric controller.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# ── Dashboard static files ──────────────────────────────────────────────────
if hasattr(sys, "_MEIPASS"):
    # Running inside PyInstaller exe
    _dashboard_dir = Path(sys._MEIPASS) / "dashboard"
else:
    # Running from source
    _dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"

if _dashboard_dir.exists():
    _css_dir = _dashboard_dir / "css"
    _js_dir = _dashboard_dir / "js"
    if _css_dir.exists():
        app.mount("/css", StaticFiles(directory=str(_css_dir)), name="dashboard-css")
    if _js_dir.exists():
        app.mount("/js", StaticFiles(directory=str(_js_dir)), name="dashboard-js")
    _worker_file = _dashboard_dir / "worker.html"
    if _worker_file.exists():
        @app.get("/worker.html", include_in_schema=False)
        async def serve_worker():
            return FileResponse(str(_worker_file))

    @app.get("/", include_in_schema=False)
    async def serve_dashboard_index():
        """Serve the dashboard HTML at the root path."""
        return FileResponse(str(_dashboard_dir / "index.html"))

# ── Startup/shutdown hooks ──────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    """Initialize shared resources at startup."""
    app.state.start_time = time.time()
    app.state.config = None
    app.state.workers = None
    app.state.telemetry = None
    app.state.thermal = None
    app.state.transfer_mgr = None
    app.state.key_manager = None
    app.state.pairing = None
    app.state._sessions = {}
    logger.info("Aether API started", extra={"docs": "/api/docs"})


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Clean up resources."""
    logger.info("Aether API stopped")


# ── Health endpoints ────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall health status: healthy, degraded, unhealthy")
    uptime_s: float = Field(..., description="Controller uptime in seconds")
    timestamp: str = Field(..., description="ISO-8601 timestamp of the health check")
    version: str = Field("0.1.0", description="Aether Controller version")
    components: dict[str, str] = Field(default_factory=dict, description="Component-level health")


class ReadinessResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]
    timestamp: str


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health() -> HealthResponse:
    """Liveness probe — returns 200 if the controller process is running."""
    uptime = time.time() - app.state.start_time
    return HealthResponse(
        status="healthy",
        uptime_s=round(uptime, 3),
        timestamp=datetime.now(timezone.utc).isoformat(),
        version="0.1.0",
    )


@app.get("/health/ready", response_model=ReadinessResponse, tags=["Health"])
async def readiness() -> ReadinessResponse:
    """Readiness probe — returns 200 only if the controller is fully initialized."""
    checks = {
        "config_loaded": getattr(app.state, 'config', None) is not None,
        "transport_running": getattr(app.state, 'transport_running', False),
    }
    all_ready = all(checks.values())
    status_code = 200 if all_ready else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "ready": all_ready,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.get("/health/live", response_model=HealthResponse, tags=["Health"])
async def liveness() -> HealthResponse:
    """Liveness alias for Kubernetes livenessProbe."""
    return await health()


# ── Worker endpoints ────────────────────────────────────────────────────────

class WorkerResponse(BaseModel):
    device_id: str
    display_name: str
    state: str
    paired: bool
    last_seen: Optional[str] = None
    peer_addr: Optional[str] = None
    thermal_state: Optional[str] = None


@app.get("/api/v1/workers", response_model=list[WorkerResponse], tags=["Workers"])
async def list_workers() -> list[WorkerResponse]:
    """List all known workers."""
    workers = getattr(app.state, 'workers', None)
    if workers is None:
        return []
    return [
        WorkerResponse(
            device_id=w.device_id,
            display_name=w.display_name,
            state=w.state.value if hasattr(w.state, 'value') else str(w.state),
            paired=w.paired,
            last_seen=datetime.fromtimestamp(w.last_seen, tz=timezone.utc).isoformat() if w.last_seen else None,
            peer_addr=w.peer_addr,
            thermal_state=getattr(w, 'thermal_state', None),
        )
        for w in workers.all_workers
    ]


@app.get("/api/v1/workers/{device_id}", response_model=WorkerResponse, tags=["Workers"])
async def get_worker(device_id: str) -> WorkerResponse:
    """Get details for a specific worker."""
    workers = getattr(app.state, 'workers', None)
    if workers is None:
        raise HTTPException(status_code=404, detail="No workers registered")
    worker = next((w for w in workers.all_workers if w.device_id == device_id), None)
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker {device_id} not found")
    return WorkerResponse(
        device_id=worker.device_id,
        display_name=worker.display_name,
        state=worker.state.value if hasattr(worker.state, 'value') else str(worker.state),
        paired=worker.paired,
        last_seen=datetime.fromtimestamp(worker.last_seen, tz=timezone.utc).isoformat() if worker.last_seen else None,
        peer_addr=worker.peer_addr,
        thermal_state=getattr(worker, 'thermal_state', None),
    )


# ── Telemetry endpoints ─────────────────────────────────────────────────────

@app.get("/api/v1/telemetry", tags=["Telemetry"])
async def get_telemetry(device_id: Optional[str] = None) -> dict:
    """Get latest telemetry for all workers or a specific device."""
    telemetry = getattr(app.state, 'telemetry', None)
    if telemetry is None:
        return {"telemetry": {}}
    if device_id:
        data = telemetry.get_latest(device_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"No telemetry for {device_id}")
        return {"device_id": device_id, "telemetry": data.to_dict()}
    return {"telemetry": {k: v.to_dict() for k, v in telemetry.all_latest().items()}}


# ── Thermal endpoints ──────────────────────────────────────────────────────

@app.get("/api/v1/thermal", tags=["Thermal"])
async def get_thermal() -> dict:
    """Get thermal status for all known devices."""
    thermal = getattr(app.state, 'thermal', None)
    if thermal is None:
        return {"devices": {}}
    return {"devices": thermal.get_all_states()}


# ── Transfer endpoints ─────────────────────────────────────────────────────

@app.get("/api/v1/transfers", tags=["Transfers"])
async def list_transfers() -> dict:
    """List active tensor transfers."""
    transfer_mgr = getattr(app.state, 'transfer_mgr', None)
    if transfer_mgr is None:
        return {"active": []}
    return {"active": transfer_mgr.list_active()}


# ── Metrics endpoint ────────────────────────────────────────────────────────

@app.get("/metrics", tags=["Metrics"])
async def metrics() -> dict:
    """Prometheus-format metrics summary."""
    workers = getattr(app.state, 'workers', None)
    telemetry = getattr(app.state, 'telemetry', None)
    uptime = time.time() - app.state.start_time
    active_sessions = len(getattr(app.state, '_sessions', {}))

    worker_count = len(workers.all_workers) if workers else 0
    paired_count = sum(1 for w in (workers.all_workers if workers else []) if w.paired)
    telemetry_count = len(telemetry.all_latest()) if telemetry else 0

    return {
        "uptime_seconds": round(uptime, 3),
        "workers_total": worker_count,
        "workers_paired": paired_count,
        "workers_available": sum(1 for w in (workers.all_workers if workers else []) if getattr(w, 'available', False)),
        "active_sessions": active_sessions,
        "telemetry_reports": telemetry_count,
    }


# ── Error handlers ──────────────────────────────────────────────────────────

@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "Bad Request", "detail": str(exc), "type": "ValueError"},
    )


@app.exception_handler(404)
async def not_found_handler(request, exc) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "Not Found", "detail": str(exc.detail) if hasattr(exc, 'detail') else "Not found"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7 — Model Registry
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/models", tags=["Models"])
async def list_models() -> dict:
    """List all registered model capability profiles."""
    registry = _get_model_registry()
    if registry is None:
        return {"models": []}
    items = []
    for m in registry.list_all():
        d = m.to_dict()
        d.setdefault("architecture_family", getattr(m, "architecture_family", None))
        items.append(d)
    return {"models": items, "count": len(items)}


@app.get("/api/v1/models/distributed-compatible", tags=["Models"])
async def list_distributed_models() -> dict:
    """List models that support distributed inference."""
    registry = _get_model_registry()
    if registry is None:
        return {"models": []}
    compat = getattr(registry, "get_distributed_compatible", lambda: [])()
    return {"models": [m.to_dict() for m in compat], "count": len(compat)}


@app.get("/api/v1/models/{model_id}", tags=["Models"])
async def get_model(model_id: str) -> dict:
    """Get capability profile for a specific model."""
    registry = _get_model_registry()
    if registry is None:
        raise HTTPException(status_code=404, detail="Model registry not available")
    model = registry.get(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    return {"model": model.to_dict()}


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7 — Accelerators
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/accelerators", tags=["Accelerators"])
async def list_accelerators() -> dict:
    """List all accelerator devices (CPU, NPU, GPU, TPU, DSP)."""
    mgr = _get_accel_manager()
    if mgr is None:
        return {"accelerators": []}
    items = []
    try:
        for acc in mgr.list_accelerators():
            d = {
                "accelerator_type": getattr(acc, "accelerator_type", None),
                "device_id": getattr(acc, "device_id", None),
                "model_name": getattr(acc, "model_name", None),
                "peak_tops": getattr(acc, "peak_tops", None),
                "memory_mb": getattr(acc, "memory_mb", None),
                "state": getattr(getattr(acc, "state", None), "value", "unknown"),
                "temperature_c": getattr(acc, "temperature_c", None),
                "thermal_throttle_c": getattr(acc, "thermal_throttle_c", None),
                "available": getattr(acc, "runtime_available", False),
            }
            items.append(d)
    except Exception as exc:
        logger.debug("list_accelerators error: %s", exc)
    return {"accelerators": items, "count": len(items)}


@app.get("/api/v1/accelerators/{device_id}", tags=["Accelerators"])
async def get_accelerator(device_id: str) -> dict:
    """Get details for a specific accelerator."""
    mgr = _get_accel_manager()
    if mgr is None:
        raise HTTPException(status_code=404, detail="Accelerator manager not available")
    try:
        acc = mgr.get(device_id)
        if acc is None:
            raise HTTPException(status_code=404, detail=f"Accelerator '{device_id}' not found")
        d = {
            "accelerator_type": getattr(acc, "accelerator_type", None),
            "device_id": getattr(acc, "device_id", None),
            "model_name": getattr(acc, "model_name", None),
            "peak_tops": getattr(acc, "peak_tops", None),
            "memory_mb": getattr(acc, "memory_mb", None),
            "operator_support": getattr(acc, "operator_support", []),
            "max_power_w": getattr(acc, "max_power_w", None),
            "thermal_throttle_c": getattr(acc, "thermal_throttle_c", None),
            "runtime_available": getattr(acc, "runtime_available", False),
            "runtime_name": getattr(acc, "runtime_name", None),
            "driver_version": getattr(acc, "driver_version", None),
        }
        return {"accelerator": d}
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug("get_accelerator error: %s", exc)
        raise HTTPException(status_code=404, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7 — Resource Pool
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/resources", tags=["Resources"])
async def list_resources() -> dict:
    """Get resource pool overview: devices, reservations, and utilization."""
    pool = _get_resource_pool()
    if pool is None:
        return {"devices": {}, "reservations": [], "total": {}}
    devices = {}
    try:
        for dev_id in list(getattr(pool, "_devices", {}).keys()):
            dev = pool.get_device(dev_id)
            if dev is None:
                continue
            devices[dev_id] = {
                "device_id": dev.device_id,
                "cpu_cores": dev.cpu_cores,
                "cpu_utilization_pct": dev.cpu_utilization_pct,
                "memory_total_mb": dev.memory_total_mb,
                "memory_available_mb": dev.memory_available_mb,
                "bandwidth_mbps": dev.bandwidth_mbps,
                "npu_available": dev.npu_available,
                "gpu_available": dev.gpu_available,
                "thermal_state": dev.thermal_state,
            }
    except Exception as exc:
        logger.debug("list_resources error: %s", exc)
    return {
        "devices": devices,
        "reservation_count": len(getattr(pool, "_reservations", {})),
    }


@app.get("/api/v1/resources/{device_id}", tags=["Resources"])
async def get_device_resources(device_id: str) -> dict:
    """Get resource details for a specific device."""
    pool = _get_resource_pool()
    if pool is None:
        raise HTTPException(status_code=404, detail="Resource pool not available")
    dev = pool.get_device(device_id)
    if dev is None:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found in pool")
    return {"device": {
        "device_id": dev.device_id,
        "cpu_cores": dev.cpu_cores,
        "cpu_utilization_pct": dev.cpu_utilization_pct,
        "memory_total_mb": dev.memory_total_mb,
        "memory_available_mb": dev.memory_available_mb,
        "bandwidth_mbps": dev.bandwidth_mbps,
        "npu_available": dev.npu_available,
        "gpu_available": dev.gpu_available,
        "thermal_state": dev.thermal_state,
    }}


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 7 — Simulation
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/simulation", tags=["Simulation"])
async def list_simulations() -> dict:
    """List completed simulation results."""
    env = _get_simulation_env()
    if env is None:
        return {"simulations": []}
    results = []
    try:
        for sim_id, result in getattr(env, "_results", {}).items():
            results.append({
                "simulation_id": sim_id,
                "total_latency_ms": result.total_latency_ms,
                "max_temperature_c": result.max_temperature_c,
                "any_thermal_violation": result.any_thermal_violation,
                "warnings": result.warnings,
                "score": result.score,
                "partition_count": len(result.partitions),
            })
    except Exception as exc:
        logger.debug("list_simulations error: %s", exc)
    return {"simulations": results}


@app.get("/api/v1/simulation/{simulation_id}", tags=["Simulation"])
async def get_simulation(simulation_id: str) -> dict:
    """Get details for a specific simulation."""
    env = _get_simulation_env()
    if env is None:
        raise HTTPException(status_code=404, detail="Simulation environment not available")
    result = env.get_result(simulation_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Simulation '{simulation_id}' not found")
    return {"simulation": {
        "simulation_id": simulation_id,
        "total_latency_ms": result.total_latency_ms,
        "max_temperature_c": result.max_temperature_c,
        "any_thermal_violation": result.any_thermal_violation,
        "warnings": result.warnings,
        "score": result.score,
        "partitions": [
            {
                "device_id": p.device_id,
                "layers": p.layers,
                "compute_ms": p.compute_ms,
                "transfer_ms": p.transfer_ms,
                "temperature_c": p.temperature_c,
            }
            for p in result.partitions
        ],
    }}


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8 — Planner
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/plans", tags=["Planner"])
async def list_plans() -> dict:
    """List all execution plans."""
    planner = _get_planner()
    if planner is None:
        return {"plans": []}
    try:
        items = []
        for plan_id, plan in getattr(planner, "_plans", {}).items():
            items.append({
                "plan_id": plan.plan_id,
                "model_id": plan.model_id,
                "strategy": plan.strategy.value if hasattr(plan.strategy, "value") else str(plan.strategy),
                "device_assignments": plan.device_assignments,
                "estimated_latency_ms": plan.estimated_latency_ms,
                "estimated_energy_j": plan.estimated_energy_j,
                "max_temperature_c": plan.max_temperature_c,
                "confidence": plan.confidence,
                "fallback_plan": plan.fallback_plan,
            })
        return {"plans": items, "count": len(items)}
    except Exception as exc:
        logger.debug("list_plans error: %s", exc)
        return {"plans": []}


@app.post("/api/v1/plans", tags=["Planner"])
async def create_plan(
    model_id: str = Body(..., description="Model identifier"),
    model_layers: int = Body(..., description="Total number of model layers"),
    strategy: Optional[str] = Body(None, description="Planning strategy: automatic, low_latency, throughput, energy_efficient, thermal_safe"),
) -> dict:
    """Generate an autonomous execution plan."""
    planner = _get_planner()
    if planner is None:
        raise HTTPException(status_code=503, detail="Planner not available")

    # Build resource snapshots from telemetry/workers
    workers = getattr(app.state, 'workers', None)
    telemetry = getattr(app.state, 'telemetry', None)
    resources: list = []
    if workers:
        for w in workers.all_workers:
            snap = {
                "device_id": w.device_id,
                "cpu_cores": 4,
                "cpu_utilization_pct": 0.0,
                "memory_available_mb": 2048,
                "memory_total_mb": 4096,
                "npu_available": False,
                "gpu_available": False,
                "bandwidth_mbps": 100.0,
                "temperature_c": 45.0,
                "battery_pct": 100.0,
                "is_charging": True,
                "latency_to_controller_ms": 50.0,
            }
            if telemetry:
                t = telemetry.get_latest(w.device_id)
                if t and hasattr(t, "to_dict"):
                    td = t.to_dict()
                    snap["cpu_utilization_pct"] = td.get("cpu_percent", 0.0)
                    snap["memory_available_mb"] = td.get("memory_available_mb", 2048)
                    snap["temperature_c"] = td.get("temperature_c", 45.0)
            resources.append(snap)

    try:
        plan_strategy = None
        if strategy and PlanningStrategy is not None:
            try:
                plan_strategy = PlanningStrategy(strategy)
            except ValueError:
                plan_strategy = None
        plan = planner.create_plan(model_id, resources, model_layers, plan_strategy)
        return {
            "plan_id": plan.plan_id,
            "model_id": plan.model_id,
            "strategy": plan.strategy.value if hasattr(plan.strategy, "value") else str(plan.strategy),
            "device_assignments": plan.device_assignments,
            "estimated_latency_ms": plan.estimated_latency_ms,
            "estimated_energy_j": plan.estimated_energy_j,
            "max_temperature_c": plan.max_temperature_c,
            "confidence": plan.confidence,
            "fallback_plan": plan.fallback_plan,
        }
    except Exception as exc:
        logger.debug("create_plan error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8 — Self-Healing
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/healing", tags=["Self-Healing"])
async def get_healing_status() -> dict:
    """Get health status and failover history for all devices."""
    engine = _get_healing()
    if engine is None:
        return {"health": {}, "degraded": [], "failover_history": []}
    try:
        health_map = {}
        for dev_id, record in getattr(engine, "_health", {}).items():
            health_map[dev_id] = {
                "device_id": record.device_id,
                "status": record.status.value if hasattr(record.status, "value") else str(record.status),
                "last_check": record.last_check,
                "failure_count": record.failure_count,
                "last_failure": record.last_failure,
                "last_failure_time": record.last_failure_time,
                "recovery_attempts": record.recovery_attempts,
                "degraded_capabilities": record.degraded_capabilities,
            }
        degraded = engine.get_degraded_devices() if hasattr(engine, "get_degraded_devices") else []
        degraded_ids = [d.device_id if hasattr(d, "device_id") else str(d) for d in degraded]
        history = []
        for action in getattr(engine, "_failover_history", []):
            history.append({
                "action_id": action.action_id,
                "failed_device_id": action.failed_device_id,
                "action_type": action.action_type,
                "target_device_id": action.target_device_id,
                "migrated_layers": action.migrated_layers,
                "estimated_recovery_ms": action.estimated_recovery_ms,
                "success": action.success,
            })
        return {
            "health": health_map,
            "degraded_devices": degraded_ids,
            "failover_history": history,
        }
    except Exception as exc:
        logger.debug("get_healing_status error: %s", exc)
        return {"health": {}, "degraded": [], "failover_history": []}


@app.post("/api/v1/healing/{device_id}/fail", tags=["Self-Healing"])
async def report_failure(
    device_id: str,
    failure_type: Optional[str] = Body(None, description="Type: transport_disconnect, thermal_throttle, memory_exhaustion, compute_error, device_unavailable"),
) -> dict:
    """Report a failure for a device and trigger recovery."""
    engine = _get_healing()
    if engine is None:
        raise HTTPException(status_code=503, detail="Self-healing engine not available")
    if HealthStatus is None or FailureType is None:
        raise HTTPException(status_code=503, detail="Health enums not available")
    ftype = FailureType.UNKNOWN
    if failure_type:
        try:
            ftype = FailureType(failure_type)
        except ValueError:
            pass
    engine.register_device(device_id)
    engine.update_health(device_id, HealthStatus.FAILING, ftype)
    action = engine.attempt_recovery(device_id)
    return {
        "device_id": device_id,
        "failure_type": ftype.value,
        "recovery": {
            "action_id": action.action_id,
            "action_type": action.action_type,
            "target_device_id": action.target_device_id,
            "migrated_layers": action.migrated_layers,
            "success": action.success,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 8 — Hierarchy
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/hierarchy", tags=["Hierarchy"])
async def get_hierarchy() -> dict:
    """Get the full device hierarchy tree and role summary."""
    hier = _get_hierarchy()
    if hier is None:
        return {"nodes": {}, "role_summary": {}, "events": []}
    try:
        nodes = {}
        for node_id, node in getattr(hier, "_nodes", {}).items():
            nodes[node_id] = {
                "node_id": node.node_id,
                "role": node.role.value if hasattr(node.role, "value") else str(node.role),
                "parent_id": node.parent_id,
                "children": node.children,
                "max_children": node.max_children,
                "metadata": node.metadata,
            }
        summary = hier.get_role_summary() if hasattr(hier, "get_role_summary") else {}
        events = []
        for evt in getattr(hier, "_events", [])[-20:]:
            events.append({
                "event_id": evt.event_id,
                "event_type": evt.event_type,
                "node_id": evt.node_id,
                "old_role": evt.old_role.value if hasattr(evt.old_role, "value") else str(evt.old_role),
                "new_role": evt.new_role.value if hasattr(evt.new_role, "value") else str(evt.new_role),
                "timestamp": evt.timestamp,
                "reason": evt.reason,
            })
        return {"nodes": nodes, "role_summary": summary, "events": events}
    except Exception as exc:
        logger.debug("get_hierarchy error: %s", exc)
        return {"nodes": {}, "role_summary": {}, "events": []}


@app.post("/api/v1/hierarchy/nodes", tags=["Hierarchy"])
async def register_hierarchy_node(
    node_id: str = Body(..., description="Unique node identifier"),
    role: str = Body("worker", description="Role: super, primary, secondary, worker, standby"),
    parent_id: str = Body("", description="Parent node ID (empty = attached to super node)"),
) -> dict:
    """Register a new node in the hierarchy."""
    hier = _get_hierarchy()
    if hier is None or HierarchyRole is None:
        raise HTTPException(status_code=503, detail="Hierarchy not available")
    try:
        role_enum = HierarchyRole(role)
    except ValueError:
        role_enum = HierarchyRole.WORKER
    node = hier.register_node(node_id, role_enum, parent_id or "")
    return {"node_id": node.node_id, "role": node.role.value, "parent_id": node.parent_id}


@app.get("/api/v1/hierarchy/nodes/{node_id}", tags=["Hierarchy"])
async def get_hierarchy_node(node_id: str) -> dict:
    """Get details for a specific hierarchy node."""
    hier = _get_hierarchy()
    if hier is None:
        raise HTTPException(status_code=404, detail="Hierarchy not available")
    node = hier.get_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    return {
        "node_id": node.node_id,
        "role": node.role.value if hasattr(node.role, "value") else str(node.role),
        "parent_id": node.parent_id,
        "children": node.children,
        "max_children": node.max_children,
        "metadata": node.metadata,
    }

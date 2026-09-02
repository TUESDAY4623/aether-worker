# Aether API — REST Control Plane

FastAPI application exposing the Aether Controller's control plane over HTTP.

## Contents

| File | Purpose |
|---|---|
| `server.py` | FastAPI app, request/response models, all REST endpoints |

## Endpoints

| Path | Method | Description |
|---|---|---|
| `/` | GET | Serve dashboard HTML |
| `/health` | GET | Liveness probe |
| `/health/ready` | GET | Readiness probe (all subsystems initialized) |
| `/health/live` | GET | Liveness alias for K8s probes |
| `/workers` | GET | List all known workers |
| `/workers/{device_id}` | GET | Get specific worker details |
| `/telemetry/{device_id}` | GET | Latest telemetry for a device |
| `/partition` | POST | Partition a model across devices |
| `/scheduler/scores` | GET | Scheduler scores for all available devices |
| `/workers/{device_id}/pair` | POST | Initiate pairing with a worker |
| `/models/capabilities` | GET | List all model capability profiles |
| `/models/{model_id}/capabilities` | GET | Get specific model capabilities |
| `/accelerators` | GET | List all accelerator devices |
| `/resources/pool` | GET | Resource pool overview |
| `/topology/optimize` | POST | Optimize device topology for model placement |
| `/simulation/run` | POST | Run a partition simulation |
| `/metrics` | GET | Prometheus-style metrics summary |

## Initialization

```python
from aether.api.server import init_api
init_api(telemetry, thermal, scheduler, registry,
         partitioner=partitioner, model_registry=registry)
```

## Error Handling

All errors return structured JSON:

```json
{
  "error": "not_initialized",
  "detail": "API services have not been initialized",
  "request_id": "abc12345",
  "timestamp": 1690000000.0
}
```

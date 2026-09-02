# Aether — Distributed AI Platform

> **Transparent LLM inference offloading across heterogeneous compute nodes**
> Laptop + Android tablet/phone over local Wi-Fi — no cloud required.

**Repository:** https://github.com/TUESDAY4623/aether-worker

---

## What Is Aether?

Aether is a **two-component distributed inference system**:

| Component | Platform | Role |
|---|---|---|
| **Aether Host** (this repo) | Python / Linux (laptop or desktop) | LLM engine, scheduler, controller, dashboard |
| **Aether Worker** (`android-worker/`) | Android 8.0+ (tablet or phone) | Always-on inference compute node |

When your laptop's GPU/CPU saturates, Aether Host transparently offloads model layers or KV-cache segments to the Worker over the local network. The Worker executes the workload and streams results back.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Aether Distributed AI Platform                                     │
│                                                                     │
│  ┌──────────────────┐      TCP/HTTP       ┌──────────────────┐     │
│  │  Aether Host     │ ◄─────────────────► │  Aether Worker   │     │
│  │  (Python/FastAPI)│   Inference offload │  (Android/Kotlin)│     │
│  │                  │                      │                  │     │
│  │  ┌────────────┐  │                      │  ┌────────────┐  │     │
│  │  │ Controller │  │                      │  │ MainAct.   │  │     │
│  │  │ + REST API │  │                      │  │ OkHttp     │  │     │
│  │  ├────────────┤  │                      │  ├────────────┤  │     │
│  │  │ Scheduler  │  │                      │  │ Telemetry  │  │     │
│  │  │ (rule-based│  │                      │  │ Collector  │  │     │
│  │  ├────────────┤  │                      │  ├────────────┤  │     │
│  │  │ Transport  │  │                      │  │ UI Layer   │  │     │
│  │  │ (TCP proto)│  │                      │  │ (XML Views)│  │     │
│  │  ├────────────┤  │                      │  └────────────┘  │     │
│  │  │ Memory     │  │                      │                  │     │
│  │  │ Manager    │  │                      │                  │     │
│  │  ├────────────┤  │                      │                  │     │
│  │  │ Thermal    │  │                      │                  │     │
│  │  │ Manager    │  │                      │                  │     │
│  │  ├────────────┤  │                      │                  │     │
│  │  │ Execution  │  │                      │                  │     │
│  │  │ Pipeline   │  │                      │                  │     │
│  │  ├────────────┤  │                      │                  │     │
│  │  │ Intelligence│ │                      │                  │     │
│  │  │ (Planner,  │  │                      │                  │     │
│  │  │  Self-Heal)│  │                      │                  │     │
│  │  └────────────┘  │                      │                  │     │
│  └──────────────────┘                      └──────────────────┘     │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Web Dashboard (http://localhost:8080)                       │   │
│  │  Worker status, telemetry, scheduler scores, transfer list   │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) or pip
- Android device (for Worker)

### Install Host

```bash
cd aether
pip install -e .
```

### Run Host

```bash
python -m aether.controller.app
```

The controller starts:
- **TCP transport** on port `8765`
- **UDP discovery** on port `8766`
- **REST API + Dashboard** on port `8080`

Open `http://localhost:8080` to see the dashboard.

### Install Worker

See [`android-worker/README.md`](android-worker/README.md) for the Android app build and deployment instructions.

## Project Structure

```
aether/
├── README.md                    ← you are here
├── architecture.md              ← detailed system architecture
├── research_paper.md            ← academic paper
├── config.py                    ← configuration (env vars, defaults)
├── secrets.py                   ← secret loading helpers
├── __init__.py                  ← package init
│
├── api/                         ← FastAPI REST control plane
│   ├── server.py                ← API routes, models, init
│   └── __init__.py
│
├── controller/                  ← main orchestrator
│   ├── app.py                   ← AetherController (startup, loops)
│   ├── api.py                   ← FastAPI app + endpoints
│   └── __init__.py
│
├── transport/                   ← network layer
│   ├── protocol.py              ← binary message framing, encode/decode
│   ├── session.py               ← TCP session, server, session manager
│   ├── discovery.py             ← UDP broadcast discovery (server + client)
│   └── tensor_transfer.py       ← chunked, resumable tensor streaming
│
├── execution/                   ← compute scheduling
│   ├── pipeline.py              ← execution pipeline orchestration
│   ├── accelerator.py           ← accelerator manager (CPU/GPU/NPU/TPU/DSP)
│   ├── topology.py              ← topology optimizer + placement strategies
│   ├── simulation.py            ← simulation environment for partition plans
│   └── resource_pool.py         ← resource pool manager
│
├── intelligence/                ← AI-assisted orchestration
│   ├── planner.py               ← autonomous execution plan generator
│   ├── self_healing.py          ← health monitoring + automatic failover
│   ├── kv_fabric.py             ← distributed KV-cache fabric
│   └── hierarchy.py             ← supervisor-subordinate device hierarchy
│
├── memory/                      ← distributed memory management
│   ├── manager.py               ← segment allocator, residency, eviction
│   └── segment.py               ← Segment, ResidencyState, SegmentType
│
├── model/                       ← model metadata + partitioning
│   ├── manifest.py              ← ModelManifest, PartitionPlan, ModelPartitioner
│   └── capability_registry.py   ← model capability profiles + built-in models
│
├── scheduler/                   ← workload scheduling
│   └── rule_based.py            ← weighted rule-based device scorer
│
├── security/                    ← authentication + pairing
│   ├── auth.py                  ← SessionKeyManager, HMAC, device identity
│   └── pairing.py               ← pairing code exchange
│
├── telemetry/                   ← device metrics
│   └── collector.py             ← DeviceTelemetry, rolling history, trends
│
├── thermal/                     ← thermal management
│   └── manager.py               ← ThermalManager, thermal states
│
├── workers/                     ← worker device registry
│   └── registry.py              ← WorkerRegistry, WorkerDevice, capabilities
│
├── dashboard/                   ← web frontend
│   ├── index.html               ← main dashboard page
│   ├── worker.html              ← worker detail page
│   ├── css/dashboard.css
│   └── js/app.js
│
└── android-worker/              ← Android Worker app (separate Gradle project)
    ├── README.md
    ├── architecture.md
    ├── research_paper.md
    ├── app/
    └── ...
```

## Architecture Decisions

| Decision | Rationale |
|---|---|
| **Python host, Kotlin worker** | Python for rapid server-side iteration; Kotlin for Android stability |
| **FastAPI + uvicorn** | Async-native, auto-generated OpenAPI docs, production-ready |
| **Custom binary TCP protocol** | Low overhead, structured framing, compression + encryption flags |
| **UDP discovery** | Zero-config worker onboarding on LAN |
| **Rule-based scheduler** | Deterministic, explainable scoring; ML-based scheduler is Phase 3 |
| **No cloud dependency** | All communication is LAN-only; no external relay |

## Technology Stack

### Host (Python)

| Component | Technology |
|---|---|
| Web framework | FastAPI + uvicorn |
| Async runtime | asyncio |
| Serialization | JSON (standard library) |
| Binary protocol | struct + zlib |
| Auth | HMAC-BLAKE2b |
| Frontend | HTML + CSS + vanilla JS |

### Worker (Android)

| Component | Technology |
|---|---|
| Language | Kotlin 2.0 |
| Build system | Gradle 8.x + AGP 8.6.0 |
| UI | Android XML + AppCompat (no Compose) |
| Networking | OkHttp 4.12 |
| JSON | org.json |

## Phases

| Phase | Focus | Status |
|---|---|---|
| 1 | Feasibility, remote memory, tensor transport, thermal scheduling | ✅ Complete |
| 2 | Inference engine, model partitioning, KV-cache, prefetching | 🔄 In progress |
| 3 | Auto partitioning, execution graph, adaptive scheduler, repartitioning | 🔄 Planned |
| 4 | Productionization: security, reliability, diagnostics, deployment | 🔄 Planned |
| 5 | Advanced expansion: accelerators, parallelism, topology, SDK | 🔄 Planned |
| 6 | Autonomous platform: self-healing, dynamic partitioning, predictive scheduling | 🔄 Planned |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development workflow and coding standards.

## License

MIT — see [`LICENSE.md`](LICENSE.md).

# Aether Phase 1 — Distributed AI Memory & Compute Fabric

**Aether** extends a laptop's AI inference capability across Android mobile devices, pooling their RAM, compute (NPU/CPU/GPU), and bandwidth into a unified fabric.

## Quick Start

```bash
pip install -r requirements.txt
python scripts/start_controller.py
pytest tests/ -v
```

## Architecture

```
Laptop (Controller)          Android Phones/Tablets (Workers)
┌─────────────────┐         ┌──────────────────────┐
│ AetherController │◄───────►│  AetherWorkerAgent   │
│  ├─ MemoryManager│  TCP    │  ├─ MemoryClient     │
│  ├─ Scheduler    │  +      │  ├─ TensorTransport  │
│  ├─ ThermalMgr   │  UDP    │  └─ TelemetryReporter│
│  ├─ PairingMgr   │  disc.  │                      │
│  ├─ TransferMgr  │  API    └──────────────────────┘
│  └─ APIServer    │
└─────────────────┘
```

## Project Structure

```
aether/
├── config.py                 # Environment-based configuration
├── controller/app.py         # Main Controller service
├── memory/                   # Remote memory pool with priority tiers
├── transport/                # Binary protocol, TCP server, UDP discovery, tensor transfer
│   ├── protocol.py
│   ├── session.py
│   ├── discovery.py
│   └── tensor_transfer.py
├── security/                 # Ed25519 auth + 6-digit pairing
├── telemetry/                # Device metrics collection
├── thermal/                  # Thermal state machine (no auto power-off)
├── scheduler/                # Rule-based device scheduler (Phase 1)
├── model/                    # Model manifest + partitioning
├── workers/                  # Worker registry
└── api/                      # REST control API (FastAPI)
```

## Android Worker

```
android-worker/
├── app/src/main/java/com/aether/worker/
│   ├── AetherWorkerService.kt    # Foreground service + TCP client
│   ├── MainActivity.kt           # UI start/stop + pairing display
│   ├── AetherWorkerViewModel.kt  # Jetpack ViewModel
│   ├── AetherMessage.kt          # Binary protocol framing
│   ├── MessageType.kt            # Protocol message types
│   ├── MessageParser.kt          # JSON message parser
│   ├── TelemetryReport.kt        # Telemetry data class
│   └── TelemetryHelper.kt        # CPU, temp, battery, latency helpers
└── app/src/main/AndroidManifest.xml
```

## Design Principles

1. **No Auto Power-Off**: Thermal management uses adaptive throttling and workload migration only.
2. **Priority-Based Memory**: Model weights get RESIDENT priority; scratch buffers get EVICTABLE.
3. **Deterministic Phase 1**: Rule-based scheduling before adding ML.
4. **Security First**: Ed25519 signatures, encrypted transport, explicit pairing.

## Android Worker

Requires Android Studio / Gradle with JDK 11+.

```bash
cd android-worker
./gradlew assembleDebug
adb install app/build/outputs/apk/debug/app-debug.apk
```

The worker app connects to the controller's TCP endpoint, broadcasts UDP discovery packets, reports telemetry, and participates in pairing.

## Running Tests

```bash
pip install -r requirements.txt
pytest tests/ -v
```

## License

MIT

# Aether Worker — System Architecture

> **Version:** 1.0.0  
> **Date:** 2026-09-02  
> **Status:** Production-ready

---

## 1. System Context

Aether Worker is one half of a **distributed inference offloading system**. The other half is the **Aether Host**, which runs on a developer's laptop (typically GPU-bound). When the host's local compute is saturated, it transparently offloads neural network layers, KV-cache segments, or entire subgraphs to one or more Aether Worker devices over the local area network.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Aether Distributed Platform                   │
│                                                                     │
│  ┌──────────────────┐         HTTP/WebSocket         ┌───────────┐ │
│  │  Aether Host     │ ◄────────────────────────────► │  Aether   │ │
│  │  (Laptop/PC)     │   InferenceRequest/Response    │  Worker   │ │
│  │                  │        10.217.x.x:8080          │  (Android)│ │
│  │  ┌────────────┐  │                                  └───────────┘ │
│  │  │ LLM Engine │  │                                                  │
│  │  │ (GPU/CPU)  │  │   ┌──────────────────────────────────────────┐  │
│  │  └─────┬──────┘  │   │  Additional Workers (phones, tablets)   │  │
│  │        │         │   │  http://192.168.1.42:8080               │  │
│  │  ┌─────▼──────┐  │   │  http://192.168.1.55:8080               │  │
│  │  │ Scheduler  │  │   └──────────────────────────────────────────┘  │
│  │  │ & Router   │  │                                                  │
│  │  └────────────┘  │                                                  │
│  └──────────────────┘                                                  │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.1 Design Goals

| Goal | Implementation |
|---|---|
| **Transparency** | Host offloads layers without changing model code |
| **Fault tolerance** | Worker crash → host re-routes to another worker or falls back to local |
| **Low latency** | Local network only (no cloud dependency); HTTP keep-alive |
| **Resource awareness** | Worker reports CPU/mem/battery/temp; host makes scheduling decisions |
| **Simplicity** | Single Activity, no Compose, minimal dependencies |

### 1.2 Constraints

- **Network:** LAN only (Wi-Fi). No NAT traversal, no cloud relay.
- **Security:** Trusted network assumption. Cleartext HTTP by default.
- **Platform:** Android 8.0+ (API 26) targeting Android 15 (API 35).
- **Hardware:** Tested on Exynos 1380 (Tab S10 FE+). ARM64 only.

---

## 2. Component Architecture

### 2.1 High-Level Component Map

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Aether Worker (Android)                        │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                     MainActivity (Single Activity)              │  │
│  │                                                                  │  │
│  │  ┌──────────────┐  ┌───────────────┐  ┌─────────────────────┐  │  │
│  │  │ UI Layer     │  │ Network Layer │  │  Telemetry Layer    │  │  │
│  │  │              │  │               │  │                     │  │  │
│  │  │ - Inputs     │  │ - OkHttp      │  │ - /proc/cpuinfo     │  │  │
│  │  │ - Stat cards │  │ - POST /infer │  │ - /proc/meminfo     │  │  │
│  │  │ - Start/Stop │  │ - Queue       │  │ - BatteryManager    │  │  │
│  │  │ - Status dot │  │ - Lifecycle   │  │ - Thermal sensor    │  │  │
│  │  └──────────────┘  └───────────────┘  │ - /sys/class/net    │  │  │
│  │                                       └─────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                    Android Framework                            │  │
│  │  ┌──────────┐ ┌────────────┐ ┌──────────┐ ┌────────────────┐  │  │
│  │  │Activity  │ │Handler +   │ │Battery   │ │Network         │  │  │
│  │  │Thread    │ │Looper      │ │Manager   │ │StatsManager    │  │  │
│  │  └──────────┘ └────────────┘ └──────────┘ └────────────────┘  │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 Layer Responsibilities

#### UI Layer

The UI layer is responsible for device identity input, inference queue control, and real-time telemetry display.

**Components:**

| Widget | Purpose |
|---|---|
| `EditText` (urlInput) | Aether Host URL entry |
| `EditText` (deviceIdInput) | Unique worker identifier |
| `EditText` (displayNameInput) | Human-readable label for host dashboard |
| `Button` (btnStart / btnStop) | Start/stop the inference worker coroutine |
| `TextView` (statusDot, statusText) | Connection status indicator |
| `TextView` (statValue cards) | Live-updating telemetry readouts |
| `ScrollView` (root) | Enables scrolling on smaller screens |

**Layout file:** `res/layout/activity_main.xml`

The layout uses a vertical `LinearLayout` root with:
- A `LinearLayout` input section (URL, Device ID, Display Name)
- A horizontal `LinearLayout` button row (Start / Stop)
- A `LinearLayout` status section (colored dot + text)
- Six individual `LinearLayout` stat-card containers, each containing:
  - A label `TextView` (`statLabel`)
  - A value `TextView` (`statValue`)

**Stat-card visual treatment:** The card appearance (rounded corners, shadow, padding) is achieved via a `shape` drawable background applied to the `LinearLayout` container — not via `CardView`. This design choice eliminates the `ClassCastException` that occurred when `bindStat()` tried to cast a `LinearLayout` to `CardView`.

#### Network Layer

The network layer manages the HTTP connection to the Aether Host and handles inference request/response cycles.

**Technology:** OkHttp 4.12.0 with Kotlin coroutines.

**Flow:**

```
User taps Start
    │
    ▼
Create OkHttpClient (singleton, configured with timeouts)
    │
    ▼
Validate inputs (URL, Device ID, Display Name)
    │
    ▼
Launch coroutine on IO dispatcher:
    │
    ├─► Connect to Host URL via POST /infer
    │       │
    │       ├─► Success: update status to "Connected"
    │       │       │
    │       │       ├─► Loop: send heartbeats every 5s
    │       │       │       │
    │       │       │       ├─► POST /heartbeat {deviceId, timestamp, telemetry}
    │       │       │       │
    │       │       │       └─► Read InferenceRequest from host
    │       │       │               │
    │       │       │               ├─► Run inference on worker device
    │       │       │               │
    │       │       │               └─► POST InferenceResponse back
    │       │       │
    │       │       └─► On disconnect/cancel: update status to "Disconnected"
    │       │
    │       └─► Failure: update status to "Connection Failed"
    │               │
    │               └─► Retry with exponential backoff (optional)
    │
    ▼
User taps Stop
    │
    ▼
Cancel coroutine job → close OkHttp client → update UI
```

**Key classes:**
- `OkHttpClient` — single instance, configured with 30s connect/read/write timeouts
- `RequestBody` — JSON-serialized `InferenceRequest` with `toMediaType("application/json")`
- `CoroutineScope(Dispatchers.IO + Job())` — scoped to activity lifecycle

#### Telemetry Layer

The telemetry layer reads system metrics from Linux procfs and Android system services, then updates the UI via the main-thread `Handler`.

**Metrics collected:**

| Metric | Source | Update Interval |
|---|---|---|
| CPU usage | `/proc/stat` (user+nice+system vs idle) | 2 seconds |
| Memory usage | `/proc/meminfo` (MemTotal vs MemAvailable) | 2 seconds |
| Battery level | `BatteryManager.getIntProperty(BATTERY_PROPERTY_CAPACITY)` | 5 seconds |
| Battery temperature | `BatteryManager.getIntProperty(BATTERY_PROPERTY_TEMPERATURE)` / 10 | 5 seconds |
| Network speed | `/sys/class/net/<iface>/statistics/rx_bytes` + `tx_bytes` delta | 2 seconds |
| Last seen | `System.currentTimeMillis()` formatted via `SimpleDateFormat` | 1 second |

**CPU calculation algorithm:**

```
Read /proc/stat (first line: cpu aggregate)
  cpu  user nice system idle iowait irq softirq steal guest guest_nice

total = user + nice + system + idle + iowait + irq + softirq + steal
usage = ((total - idle) / total) * 100
```

**Memory calculation algorithm:**

```
Read /proc/meminfo
  MemTotal  → total RAM
  MemAvailable → free + reclaimable RAM

usage = ((MemTotal - MemAvailable) / MemTotal) * 100
```

**Network speed calculation:**

```
currentRx = /sys/class/net/wlan0/statistics/rx_bytes
currentTx = /sys/class/net/wlan0/statistics/tx_bytes

deltaRx = currentRx - previousRx
deltaTx = currentTx - previousTx

speedRx = deltaRx / interval_seconds  →  KB/s
speedTx = deltaTx / interval_seconds  →  KB/s
```

---

## 3. Data Flow

### 3.1 Inference Request/Response Protocol

```
┌──────────────┐                            ┌──────────────────┐
│  Aether Host │                            │  Aether Worker   │
│  (Laptop)    │                            │  (Android)       │
└──────┬───────┘                            └────────┬─────────┘
       │                                              │
       │  1. POST /infer                              │
       │     {                                       │
       │       "requestId": "uuid-v4",               │
       │       "modelId": "llama-3-8b-q4",           │
       │       "layerRange": [12, 18],               │
       │       "kvCacheSegment": {                    │
       │         "tokens": [token_ids...],            │
       │         "shape": [32, 4096]                  │
       │       },                                     │
       │       "prompt": "Explain quantum tunneling"  │
       │     }                                       │
       │ ─────────────────────────────────────────►  │
       │                                              │
       │  2. Worker processes request                │
       │     - Receives tensor data                   │
       │     - Runs model layers locally              │
       │     - Generates output tokens                │
       │                                              │
       │  3. POST /infer/response                     │
       │     {                                       │
       │       "requestId": "uuid-v4",               │
       │       "status": "success",                   │
       │       "outputTokens": [token_ids...],        │
       │       "outputText": "Quantum tunneling is..",│
       │       "latencyMs": 342,                      │
       │       "workerTelemetry": {                   │
       │         "cpuUsage": 45.2,                    │
       │         "memUsage": 62.1,                    │
       │         "tempC": 38                          │
       │       }                                      │
       │     }                                       │
       │ ◄─────────────────────────────────────────  │
       │                                              │
```

### 3.2 Heartbeat Protocol

```
Worker (every 5s) → Host:
  POST /heartbeat
  {
    "deviceId": "tab-s10fe-plus",
    "displayName": "Samsung Tab",
    "timestamp": 1725340800000,
    "telemetry": {
      "cpuUsage": 23.4,
      "memUsage": 51.2,
      "batteryPct": 78,
      "batteryTempC": 31,
      "networkRxKb": 120.5,
      "networkTxKb": 45.2
    }
  }

Host responds:
  200 OK { "ack": true, "queuedRequests": 0 }
```

### 3.3 State Machine

```
                    ┌──────────┐
                    │  IDLE    │
                    └────┬─────┘
                         │ User taps Start
                         ▼
                    ┌──────────┐       ┌──────────────┐
              ┌────►│CONNECTING│──────►│  CONNECTED   │
              │     └──────────┘       └──────┬───────┘
              │           │                    │
              │           │ Connection error   │ Host sends
              │           ▼                    │ InferenceRequest
              │     ┌──────────┐               │
              │     │  ERROR   │               ▼
              │     └────┬─────┘         ┌──────────────┐
              │           │              │  PROCESSING  │
              │           │ User taps    └──────┬───────┘
              │◄──────────┤   Stop               │
              │           │               ┌──────▼───────┐
              │           │               │  RESPONDING  │
              │           │               └──────┬───────┘
              │           │                      │
              │           │                      │ Response sent
              │           │                      ▼
              │           │               ┌──────────────┐
              │           │               │  CONNECTED   │
              │           │               └──────────────┘
              │           │
              │     User taps Start
              │     (retry)
              │           │
              └───────────┘
```

---

## 4. Communication Protocol

### 4.1 Endpoints

| Endpoint | Method | Purpose | Request Body | Response |
|---|---|---|---|---|
| `/infer` | POST | Submit inference task | `InferenceRequest` JSON | `InferenceResponse` JSON |
| `/heartbeat` | POST | Worker health + telemetry | `Heartbeat` JSON | `{ack: bool, queuedRequests: int}` |
| `/status` | GET | Query worker status | — | `WorkerStatus` JSON |
| `/stop` | POST | Graceful shutdown signal | `{deviceId: string}` | `{stopped: bool}` |

### 4.2 Message Schemas

#### InferenceRequest

```json
{
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "modelId": "llama-3-8b-instruct-q4_k_m.gguf",
  "layerRange": {
    "startLayer": 12,
    "endLayer": 18,
    "totalLayers": 32
  },
  "kvCacheSegment": {
    "tokens": [15043, 257, 1332, ...],
    "shape": [32, 4096],
    "dtype": "float16"
  },
  "prompt": "Explain quantum tunneling in simple terms",
  "parameters": {
    "temperature": 0.7,
    "topP": 0.9,
    "maxTokens": 256,
    "stopSequences": ["\n\n"]
  },
  "priority": "normal"
}
```

#### InferenceResponse

```json
{
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "success",
  "outputTokens": [1841, 293, 456, ...],
  "outputText": "Quantum tunneling is a quantum mechanical phenomenon...",
  "latencyMs": 342,
  "tokensPerSecond": 74.5,
  "workerTelemetry": {
    "cpuUsage": 45.2,
    "memUsage": 62.1,
    "batteryTempC": 38
  }
}
```

#### Heartbeat

```json
{
  "deviceId": "tab-s10fe-plus",
  "displayName": "Samsung Tab S10 FE+",
  "timestamp": 1725340800000,
  "uptimeSeconds": 3600,
  "telemetry": {
    "cpuUsage": 23.4,
    "memUsage": 51.2,
    "batteryPct": 78,
    "batteryTempC": 31,
    "networkRxKb": 120.5,
    "networkTxKb": 45.2
  },
  "capabilities": {
    "ramGb": 8,
    "cpuCores": 8,
    "hasNpu": false,
    "gpuVendor": "Mali-G68"
  }
}
```

### 4.3 Error Handling

| HTTP Status | Meaning | Worker Behavior |
|---|---|---|
| `200 OK` | Success | Process response, continue loop |
| `400 Bad Request` | Malformed JSON | Log error, skip request, continue |
| `401 Unauthorized` | Device not in host allowlist | Stop worker, notify user |
| `404 Not Found` | Endpoint missing | Log error, retry once, then stop |
| `408 Request Timeout` | Host too slow | Retry with backoff (max 3 attempts) |
| `429 Too Many Requests` | Host overloaded | Back off exponentially (1s → 2s → 4s → 8s) |
| `500 Internal Server Error` | Host crash | Wait 5s, retry; if persists, stop |
| `503 Service Unavailable` | Host draining | Graceful shutdown, await reconnect |

---

## 5. Threading Model

### 5.1 Thread Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Android Process                             │
│  ┌─────────────────┐    ┌──────────────────────────────────┐   │
│  │   Main Thread   │    │     IO Thread Pool               │   │
│  │   (Looper)      │    │     (OkHttp Dispatcher)          │   │
│  │                 │    │                                  │   │
│  │ ┌─────────────┐ │    │  ┌────────────────────────────┐  │   │
│  │ │   View       │ │    │  │  OkHttp Connection Pool   │  │   │
│  │ │   Hierarchy  │ │    │  │  (5 concurrent max)       │  │   │
│  │ └─────────────┘ │    │  └────────────────────────────┘  │   │
│  │                 │    │                                  │   │
│  │ ┌─────────────┐ │    │  ┌────────────────────────────┐  │   │
│  │ │   Handler    │ │◄───│  │  Worker Coroutine         │  │   │
│  │ │   (UI posts)│ │    │  │  (inference loop)         │  │   │
│  │ └─────────────┘ │    │  └────────────────────────────┘  │   │
│  │                 │    │                                  │   │
│  │ ┌─────────────┐ │    │  ┌────────────────────────────┐  │   │
│  │ │   Click      │ │    │  │  Telemetry Coroutine      │  │   │
│  │ │   Listeners  │ │◄───│  │  (2s interval)            │  │   │
│  │ └─────────────┘ │    │  └────────────────────────────┘  │   │
│  └─────────────────┘    └──────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 Handler Usage for UI Updates

All telemetry updates flow through a single `Handler(Looper.getMainLooper())` to ensure thread-safe UI access:

```kotlin
private val handler = Handler(Looper.getMainLooper())

// In telemetry coroutine (background thread):
handler.post {
    cpuValue.text = "${cpuUsage}%"
    memValue.text = "${memUsage}%"
}

// In network coroutine (background thread):
handler.post {
    statusDot.setBackgroundColor(Color.GREEN)
    statusText.text = "Connected"
}
```

**Why not `mutableStateOf`?** Jetpack Compose's `mutableStateOf` triggers recomposition on the Compose runtime. Since we use XML Views, `Handler.post()` is the idiomatic, zero-overhead mechanism for cross-thread UI updates.

### 5.3 Coroutine Scoping

```kotlin
// Scoped to Activity lifecycle
private var job: Job? = null

fun startWorker() {
    job = CoroutineScope(Dispatchers.IO + Job()).launch {
        // Network operations
    }
}

fun stopWorker() {
    job?.cancel()        // Cooperative cancellation
    job?.join()          // Wait for cleanup
    job = null
}

override fun onDestroy() {
    super.onDestroy()
    job?.cancel()        // Prevent leaks
}
```

---

## 6. Memory Model

### 6.1 Object Lifecycle

```
Activity Created
    │
    ├── OkHttpClient (singleton, reused across start/stop cycles)
    ├── Handler (main thread, lives for Activity lifetime)
    ├── TextView references (found via findViewById in onCreate)
    ├── CoroutineScope + Job (recreated each start)
    │
    ▼
Activity Running
    │
    ├── Telemetry coroutine: reads /proc every 2s → posts to Handler
    ├── Network coroutine: OkHttp reads/writes on IO dispatcher
    │
    ▼
Activity Destroyed
    │
    ├── job.cancel() → coroutines stop
    ├── OkHttpClient.dispatcher.executorService.shutdown()
    └── Handler removes callbacks
```

### 6.2 Memory Budget

| Component | Estimated Memory |
|---|---|
| OkHttp connection pool | ~2 MB |
| Activity + Views | ~1 MB |
| JSON parsing (per request) | ~500 KB (temporary) |
| Telemetry buffers | ~50 KB |
| **Total working set** | **~3.5 MB** |

---

## 7. Security Architecture

### 7.1 Trust Model

```
┌─────────────────────────────────────────────────────────────────┐
│  Trust Boundary                                                 │
│                                                                 │
│  ┌──────────────┐       LAN (Wi-Fi)       ┌──────────────────┐ │
│  │ Aether Host  │ ◄──────────────────────► │  Aether Worker  │ │
│  │ (Laptop)     │    Trusted network        │  (Android)      │ │
│  └──────────────┘                           └──────────────────┘ │
│                                                                 │
│  Outside this boundary: UNTRUSTED                               │
│  - Internet traffic                                              │
│  - Other devices on Wi-Fi                                        │
│  - Any process without device-side allowlist entry               │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Threat Surface

| Threat Vector | Severity | Mitigation |
|---|---|---|
| Unauthorized device joins worker pool | Medium | Host-side device ID allowlist |
| Inference request intercepted on Wi-Fi | Low | LAN isolation; use VPN or dedicated subnet for production |
| Malicious inference response (poisoned model output) | High | Host-side output validation; checksum verification |
| ADB exposed over network | Medium | Disable Wireless Debugging after deployment |
| APK tampering / side-loading | Medium | Verify APK signature; use Play App Signing for production |
| Battery exhaustion | Low | Worker reports battery; host stops offloading below threshold |
| Thermal throttling | Low | Worker reports temperature; host adjusts workload |

### 7.3 Network Security Config

```xml
<!-- res/xml/network_security_config.xml -->
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
    <domain-config cleartextTrafficPermitted="true">
        <domain includeSubdomains="true">10.217.143.165</domain>
    </domain-config>
</network-security-config>
```

This permits cleartext HTTP **only** to the Aether Host IP. All other domains require HTTPS.

---

## 8. Build & Deployment Architecture

### 8.1 Build Pipeline

```
Source Code (Kotlin + XML)
    │
    ▼
Gradle Build (AGP 8.6.0)
    │
    ├── Kotlin Compilation (K2 mode)
    ├── Resource Merging
    ├── DEX Generation
    └── APK Packaging + Debug Signing
    │
    ▼
app-debug.apk (~8 MB)
    │
    ▼
ADB Install (wireless TLS or USB)
    │
    ▼
Android Package Installer
    │
    ▼
App installed as com.aether.worker
```

### 8.2 CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
Trigger: push to main/develop, PR to main
Steps:
  1. Checkout code
  2. Setup JDK 17 + Gradle cache
  3. ./gradlew clean assembleDebug
  4. Upload APK artifact (14-day retention)
  5. Run lintDebug
  6. Upload lint report (7-day retention)
```

### 8.3 Signing Strategy

| Build Type | Signing | Use Case |
|---|---|---|
| `debug` | Debug keystore (auto-generated) | Development, testing |
| `release` | Release keystore (kept offline) | Production distribution |

---

## 9. Performance Characteristics

### 9.1 Measured Metrics (Samsung Tab S10 FE+, Android 16)

| Metric | Value |
|---|---|
| App cold start time | ~1.2s |
| Memory footprint (idle) | ~35 MB |
| Memory footprint (active worker) | ~55 MB |
| Network latency (local LAN) | 1-5ms |
| HTTP request overhead | ~2ms |
| Battery drain (active worker, 1 req/s) | ~2%/hour |
| Battery drain (idle, telemetry only) | ~0.3%/hour |

### 9.2 Scalability

| Dimension | Limit | Notes |
|---|---|---|
| Concurrent workers per host | 8 | OkHttp default connection pool (5) + HTTP/2 multiplexing |
| Requests/second per worker | 10 | Limited by model inference speed, not network |
| Max KV cache segment size | 50 MB | OkHttp default max response body; configurable |
| Worker telemetry precision | 2s | Configurable via `TELEMETRY_INTERVAL_MS` |

---

## 10. Future Architecture Extensions

### 10.1 Planned Components

```
┌──────────────────────────────────────────────────────────────────┐
│                    Aether Worker v2.0 (Planned)                   │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ WebSocket    │  │ mDNS         │  │  Thermal Scheduler    │  │
│  │ Channel      │  │ Discovery    │  │                       │  │
│  │              │  │              │  │  - Monitors thermal   │  │
│  │ - Full duplex│  │ - Auto-find  │  │    zones              │  │
│  │ - Sub-ms RTT │  │   host       │  │ - Backs off load     │  │
│  │ - Stream     │  │ - Zero-conf  │  │ - Prevents throttle   │  │
│  │   inference  │  │   onboarding │  │                       │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ Model        │  │ NPU/GPU      │  │  Biometric Auth       │  │
│  │ Partitioner  │  │ Accelerator  │  │                       │  │
│  │              │  │  Abstraction │  │  - Fingerprint unlock  │  │
│  │ - Auto-split │  │              │  │  - Worker identity     │  │
│  │   large      │  │ - NNAPI      │  │    bound to biometric  │  │
│  │   layers     │  │ - Vulkan     │  │                       │  │
│  │ - Balance    │  │ - OpenCL     │  │                       │  │
│  │   across     │  │              │  │                       │  │
│  │   workers    │  │              │  │                       │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 10.2 WebSocket Protocol (Proposed)

```
Worker                         Host
  │                              │
  │─── WS Connect ──────────────►│
  │◄── WS Accept ───────────────│
  │                              │
  │─── {type:"register"} ──────►│
  │   {deviceId, capabilities}   │
  │◄── {type:"registered"} ─────│
  │   {workerId, assignedSlots}  │
  │                              │
  │◄── {type:"inference"} ──────│  (pushed by host)
  │   {requestId, layerRange,..} │
  │                              │
  │─── {type:"result"} ─────────►│
  │   {requestId, output,..}     │
  │                              │
  │◄── {type:"heartbeat_req"} ──│
  │─── {type:"heartbeat_res"} ──►│
```

---

## Appendix A: File Map

```
android-worker/
├── app/
│   ├── build.gradle.kts                    # Module config
│   ├── proguard-rules.pro                  # Release obfuscation
│   └── src/main/
│       ├── AndroidManifest.xml             # Permissions + Activity
│       ├── java/com/aether/worker/
│       │   └── MainActivity.kt             # All logic (single file)
│       └── res/
│           ├── layout/
│           │   ├── activity_main.xml       # Dashboard layout
│           │   └── stat_card.xml           # Individual stat card
│           ├── values/
│           │   ├── strings.xml             # User-facing strings
│           │   └── styles.xml              # AppCompat theme
│           └── xml/
│               └── network_security_config.xml  # Cleartext policy
├── build.gradle.kts                        # Root plugins
├── settings.gradle.kts                     # Project settings
├── gradle/
│   └── wrapper/                            # Gradle wrapper
└── .github/workflows/
    └── ci.yml                              # CI build pipeline
```

## Appendix B: Technology Versions

| Component | Version | Source |
|---|---|---|
| Kotlin | 2.0.0 | JetBrains |
| Android Gradle Plugin | 8.6.0 | Google |
| Gradle | 8.x | gradle.org |
| compileSdk | 35 (Android 15) | Android SDK |
| targetSdk | 35 | Android SDK |
| minSdk | 26 (Android 8.0) | Android SDK |
| OkHttp | 4.12.0 | Square |
| AndroidX AppCompat | 1.7.0 | Google |
| Material Components | 1.12.0 | Google |
| CardView | 1.0.0 | Google |
| org.json | 20231013 | JSON.org |

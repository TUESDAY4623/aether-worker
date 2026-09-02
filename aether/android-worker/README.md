# Aether Worker

> **Distributed AI Inference Client for Android**
> Part of the Aether distributed computing platform — offloads inference workloads from your laptop to Android devices over the local network.

**Status:** Stable | **Platform:** Android 8.0+ (API 26) | **Target:** Android 15 (API 35)

---

## What It Does

Aether Worker turns your Android tablet or phone into an **inference compute node** for the Aether platform running on your laptop. When your laptop's GPU or CPU is saturated with a neural workload, Aether can transparently offload layers, KV-cache segments, or entire subgraphs to the worker device over Wi-Fi.

```
┌──────────────┐      HTTP/WebSocket      ┌──────────────────┐
│ Laptop       │ ◄──────────────────────► │ Android Device   │
│ Aether Host  │   Inference Offload      │ Aether Worker    │
│ (GPU-bound)  │   10.217.x.x:8080        │ (always-online)  │
└──────────────┘                           └──────────────────┘
```

## Features

- **HTTP Inference Endpoint** — accepts `InferenceRequest` and streams `InferenceResponse` back to the host
- **Live Telemetry Panel** — CPU, memory, battery, temperature, and network stats updated in real-time
- **Device Identity** — each worker has a unique ID and display name for host-side routing
- **Queue + Start/Stop Control** — pause/resume inference offload without dropping the connection
- **Dual-Mode ADB** — USB or wireless (`adb tls connect`) for deployment and logs
- **No Google Play Dependency** — sideload or self-host; uses direct OkHttp + plain XML Views

## Architecture

```
app/src/main/java/com/aether/worker/
├── MainActivity.kt        # Single Activity, XML Views, coroutine-based HTTP worker
└── res/layout/
    └── activity_main.xml  # Scrollable card-based dashboard
```

| Layer | Technology |
|---|---|
| UI | Android XML + AppCompat (no Jetpack Compose) |
| Networking | OkHttp 4.12 + Kotlin coroutines |
| JSON | org.json |
| Build | Gradle 8.x + Kotlin 2.0 + AGP 8.6.0 |

## Prerequisites

- **Android Studio Iguana** or newer (Gradle 8.x, Kotlin 2.0)
- **JDK 17** (required by AGP 8.6.0)
- **Android SDK 35** installed
- ADB in PATH for wireless deployment (`D:\developer\AndroidStudio\sdk\platform-tools`)

## Build

```bash
# Clone
git clone https://github.com/<your-username>/aether-worker.git
cd aether-worker/android-worker

# Clean + build debug APK
./gradlew clean assembleDebug

# Output
app/build/outputs/apk/debug/app-debug.apk
```

### Windows Build Script

```bat
:: build_native.bat — strips "compose" and "composeOptions" block, then builds
cd android-worker
cmd /c gradlew.bat clean assembleDebug
```

## Deploy to Device (Wireless ADB)

```bash
# 1. Enable Developer Options + Wireless debugging on your Android device
# 2. Note the IP:Port shown on the Wireless debugging screen (e.g. 192.168.1.42:5555)

# Connect
adb connect 192.168.1.42:5555

# Install
adb install -r app/build/outputs/apk/debug/app-debug.apk

# Launch
adb shell am start -n com.aether.worker/.MainActivity

# Live logs
adb logcat -s com.aether.worker
```

## Usage

1. Open **Aether Worker** on the Android device.
2. Enter the **Aether Host URL** (your laptop IP + port, e.g. `http://10.217.143.165:8080`).
3. Enter a **Device ID** — any unique string (e.g. `tab-s10fe-plus`).
4. Enter a **Display Name** — human-readable label for the host dashboard.
5. Tap **Start** — the worker connects and begins accepting inference offload tasks.
6. Watch the **telemetry cards** for CPU, memory, battery, temperature, network, and last-seen timestamps.

## Connecting to Aether Host

The Aether Host running on your laptop must be configured with:

```json
{
  "worker_endpoints": [
    { "id": "tab-s10fe-plus", "url": "http://192.168.1.42:8080" }
  ]
}
```

The host will send `InferenceRequest` objects over HTTP POST to `http://<device-ip>:8080/infer` and collect `InferenceResponse` results.

## Development

### Project Structure

```
android-worker/
├── app/
│   ├── build.gradle.kts          # Module config: SDK 35, min 26, OkHttp, no compose
│   ├── proguard-rules.pro        # ProGuard keep rules (release builds)
│   └── src/main/
│       ├── AndroidManifest.xml   # Single Activity, INTERNET + NETWORK_STATE + POST_NOTIFICATIONS
│       ├── java/com/aether/worker/
│       │   └── MainActivity.kt   # All UI + networking logic
│       └── res/
│           ├── layout/activity_main.xml
│           ├── values/styles.xml
│           └── xml/network_security_config.xml
├── build.gradle.kts              # Root plugins: AGP 8.6.0, Kotlin 2.0
└── gradle/
    └── wrapper/
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| **No Jetpack Compose** | Avoids runtime crashes on Android 16 / Samsung One UI 7. XML + Views is rock-solid. |
| **`findViewById<View>` instead of typed casts** | Prevents `ClassCastException` when layout hierarchy changes during iteration. |
| **Handler + Looper for UI updates** | Lightweight alternative to `mutableStateOf` / `LiveData` for a single Activity. |
| **OkHttp directly** | No Retrofit overhead; full control over timeouts and streaming. |
| **No in-app settings storage** | All configuration is in-memory; host manages worker identity. |

## Troubleshooting

| Issue | Fix |
|---|---|
| `ClassCastException: LinearLayout → CardView` | Fixed in v1.0 — use `findViewById<View>` not typed `CardView` casts. |
| `result code=-92` on launch | App not installed for current user profile — reinstall with `adb install -r`. |
| `Shell does not have permission to access user 150` | Device uses secondary user profiles — install via the main user (user 0). |
| `Analytics: Error while uploading payloads` | Samsung system analytics — not related to Aether Worker. |
| Compose crash on startup | Ensure `compose = false` in `buildFeatures`. |

## Roadmap

- [ ] WebSocket bidirectional channel (replace polling)
- [ ] Automatic host discovery via mDNS/Bonjour
- [ ] Model-partition negotiation (split large layers across multiple workers)
- [ ] Thermal-aware scheduling (back off when device hits thermal throttle)
- [ ] Rust/Tauri companion for cross-platform host orchestration
- [ ] Dockerized host for cloud/edge deployment

## License

MIT — see [LICENSE.md](LICENSE.md) for details.

## Acknowledgements

- Built as part of [Aether](https://github.com/<your-username>/aether) distributed AI platform.
- Tested on Samsung Galaxy Tab S10 FE+ (SM-X620) running Android 16.
- Stack: Kotlin 2.0 · Android SDK 35 · OkHttp 4.12 · Gradle 8.x.

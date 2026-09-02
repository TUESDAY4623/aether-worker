# Changelog

All notable changes to Aether Worker are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-09-02

### Added
- Initial release of Aether Worker for Android
- Single Activity with XML-based dashboard (no Compose runtime dependency)
- HTTP inference endpoint via OkHttp — accepts `InferenceRequest` / returns `InferenceResponse`
- Live telemetry panel: CPU, memory, battery, temperature, network speed, last seen
- Device identity fields: unique device ID + human-readable display name
- Start / Stop queue controls with coroutine-based worker lifecycle
- `android.permission.POST_NOTIFICATIONS` for status notifications
- Network security config for cleartext local HTTP (Aether host discovery)
- Dual-mode ADB deployment (USB + wireless TLS)

### Fixed
- `ClassCastException` — `LinearLayout cannot be cast to CardView` at `MainActivity.kt:57`
  - Root cause: `bindStat()` used typed `findViewById<CardView>` but stat card roots are `LinearLayout`
  - Fix: changed to generic `findViewById<View>` before traversing to `statValue` TextView

### Build
- AGP 8.6.0 with `isMinifyEnabled` (replaces deprecated `minify` flag)
- Kotlin 2.0.0, JVM target 17, compileSdk 35, minSdk 26
- No Compose, no data binding, no Hilt — zero heavy runtime dependencies

## [Unreleased]

### Planned
- WebSocket bidirectional inference channel (replaces HTTP polling)
- mDNS/Bonjour automatic host discovery
- Model-partition negotiation across multiple workers
- Thermal-aware scheduling with automatic back-off
- ProGuard/R8 rules for release builds
- Biometric auth for production deployment

# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.0.x | ✅ Active development |
| < 1.0 | ❌ No longer supported |

## Reporting a Vulnerability

If you discover a security vulnerability in Aether Worker, please report it
**privately** rather than opening a public issue.

**Email:** security@aether.dev  
**Subject:** `[SECURITY] Aether Worker — <brief description>`

Please include:
- Affected version(s)
- Steps to reproduce
- Impact assessment (data exposure, code execution, denial of service, etc.)

We aim to acknowledge reports within **72 hours** and provide a fix timeline
within **7 days** for critical issues.

## Security Considerations for Deployment

Aether Worker communicates over HTTP by default (no TLS) on the local network.
This is by design — the host/worker pair is intended for trusted LAN use only.

| Threat | Mitigation |
|---|---|
| Unauthorized device joins the worker pool | Configure the Aether Host allowlist with known device IDs |
| Inference requests intercepted on Wi-Fi | Use a VPN or isolate worker traffic on a dedicated subnet |
| Malicious APK installed on device | Only install builds signed by the project maintainers |
| Device rooted / ADB exposed | Disable Wireless Debugging after deployment; use `adb disconnect` |
| Battery drain from always-on worker | Configure Android Battery Optimization exemption per device |

## Dependencies

This project uses the following key dependencies:

| Dependency | Version | Notes |
|---|---|---|
| OkHttp | 4.12.0 | MIT License — keep updated for TLS fixes |
| AndroidX AppCompat | 1.7.0 | Maintained by Google |
| org.json | 20231013 | Public domain — no known vulnerabilities |

Run `./gradlew dependencyUpdates` periodically to check for outdated dependencies.

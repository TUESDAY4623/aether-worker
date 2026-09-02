# Contributing to Aether Worker

Thanks for your interest in contributing! This document covers the workflow,
coding standards, and PR requirements for the Aether Worker Android app.

---

## Code of Conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/2/0/code_of_conduct/).
Be respectful. Be constructive. Report unacceptable behavior to the maintainers.

---

## How to Contribute

### 1. Fork & Clone

```bash
git clone https://github.com/<your-username>/aether-worker.git
cd aether-worker/android-worker
```

### 2. Branch Naming

| Type | Prefix | Example |
|---|---|---|
| Feature | `feature/` | `feature/websocket-channel` |
| Bugfix | `fix/` | `fix/classcastexception-bindstat` |
| Refactor | `refactor/` | `refactor/networking-module` |
| Docs | `docs/` | `docs/contributing-guide` |

### 3. Build Before You PR

```bash
./gradlew clean assembleDebug
# Verify the APK installs and launches without crash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.aether.worker/.MainActivity
adb logcat -d | grep FATAL   # should be empty
```

### 4. Coding Standards

| Rule | Detail |
|---|---|
| Language | Kotlin only (no Java) |
| UI | XML layouts only — **do not introduce Jetpack Compose** |
| Casts | Use `findViewById<View>` — avoid typed `findViewById<SpecificView>` on container views |
| Coroutines | Use `lifecycleScope` or `CoroutineScope(Dispatchers.Main + Job())` — never `GlobalScope` |
| Networking | OkHttp only — no Retrofit, no Volley |
| Logging | `Log.d/w/e` with tag `AetherWorker` |
| Strings | All user-facing text in `res/values/strings.xml` — no hardcoded strings |

### 5. Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
fix: prevent ClassCastException in bindStat for LinearLayout containers
feat: add WebSocket inference channel
docs: update README with ADB wireless steps
chore: bump OkHttp to 4.12.0
```

### 6. Pull Request Checklist

- [ ] `./gradlew clean assembleDebug` passes locally
- [ ] APK installed and launched on at least one physical device
- [ ] No `FATAL EXCEPTION` in `adb logcat` within 10 seconds of launch
- [ ] `strings.xml` updated for any new user-facing text
- [ ] `CHANGELOG.md` updated with your change
- [ ] PR description explains *why* the change is needed, not just *what* changed

### 7. Areas We Need Help With

| Priority | Area | Why |
|---|---|---|
| High | WebSocket inference channel | Replaces HTTP polling, lower latency |
| High | mDNS host discovery | Zero-config worker onboarding |
| Medium | Thermal-aware scheduling | Prevents device throttling under sustained load |
| Medium | Release ProGuard rules | Shrink APK from ~8 MB to ~3 MB |
| Low | Dark theme support | Currently portrait-only, AppCompat Light theme |

---

## Questions?

Open a [GitHub Discussion](https://github.com/<your-username>/aether-worker/discussions) or file an issue.

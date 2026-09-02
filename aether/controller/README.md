# Aether Controller — Main Orchestrator

The `AetherController` class ties all subsystems together and manages the
lifecycle of the distributed fabric.

## Lifecycle

```
main() → init_config() → setup_logging() → AetherController() → asyncio.run(controller.run())
                                                                   │
                                                    ┌──────────────┴──────────────┐
                                                    │                             │
                                                  start()                     shutdown()
                                                    │                             │
                                         ┌────────────┼────────────┐                │
                                         │            │            │                │
                                    transport    discovery     REST API       Cancel tasks
                                    (TCP)        (UDP)       (FastAPI)       Close sessions
                                                                             Stop transport
                                                                             Stop discovery
```

## Subsystems Wired by Controller

| Subsystem | Module | Purpose |
|---|---|---|
| Transport | `aether.transport` | TCP server for binary protocol messages |
| Discovery | `aether.transport.discovery` | UDP broadcast worker discovery |
| REST API | `aether.controller.api` | FastAPI control plane |
| Memory | `aether.memory` | Segment allocation and residency tracking |
| Security | `aether.security` | Session keys, HMAC auth, pairing |
| Telemetry | `aether.telemetry` | Device metrics collection |
| Thermal | `aether.thermal` | Thermal state management |
| Tensor Transfer | `aether.transport.tensor_transfer` | Chunked tensor streaming |
| Scheduler | `aether.scheduler` | Rule-based device scoring and selection |
| Workers | `aether.workers` | Worker device registry |

## Message Handling

The controller's `_on_session_message` method dispatches incoming binary messages:

| MessageType | Action |
|---|---|
| `HELLO` | Send `HELLO_ACK` |
| `PAIRING_REQUEST` | Initiate pairing, register worker |
| `PAIRING_CONFIRM` | Confirm pairing, send session key |
| `TELEMETRY_REPORT` | Store telemetry, update worker last_seen |
| `GOODBYE` | Mark worker unavailable |

## Background Loops

| Loop | Interval | Purpose |
|---|---|---|
| `_thermal_loop` | 5s | Update thermal state for all devices |
| `_stale_check_loop` | `discovery_interval_s` | Mark stale workers unavailable |
| `_pairing_cleanup_loop` | 30s | Remove expired pairing codes |

## Graceful Shutdown

`shutdown(timeout=10.0)` enforces a 10-second timeout for each phase:
1. Cancel background tasks
2. Close all active TCP sessions
3. Stop REST API server
4. Stop transport and discovery servers

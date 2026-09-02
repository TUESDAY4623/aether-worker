# Aether Thermal — Thermal Management

Monitors device temperature and enforces thermal safety policies.

## Module

| File | Purpose |
|---|---|
| `manager.py` | ThermalManager, thermal states, event listeners |

## Thermal States

| State | Description | Action |
|---|---|---|
| `normal` | Device operating within safe range | Full compute allowed |
| `warm` | Elevated temperature | Compute allowed, monitor closely |
| `hot` | Approaching throttle threshold | Reduce workload, prefer cool devices |
| `critical` | Thermal throttle imminent | Withdraw compute, trigger failover |
| `recovery` | Cooling down after critical | Limited compute, accept new work only if cool |

## ThermalManager

### State Transitions

```
normal ──(temp rises)──► warm ──(temp rises)──► hot ──(temp critical)──► critical
  ▲                        │                        │                        │
  │                        │                        │                        │
  └──────(temp falls)──────┴──────(temp falls)──────┴──────(temp falls)───────┘
                              recovery ──(cooled)──► normal
```

### Methods

| Method | Purpose |
|---|---|
| `update_device(device_id)` | Re-evaluate thermal state from telemetry |
| `get_state(device_id)` | Current thermal state |
| `can_compute(device_id)` | Whether device can accept new work |
| `add_listener(callback)` | Register for thermal state change events |

### Event Listeners

The controller registers a listener that logs warnings when devices enter `critical` state:

```python
thermal.add_listener(self._on_thermal_event)
```

### Temperature Thresholds

| Threshold | Value | Configurable |
|---|---|---|
| Warm start | 40°C | Yes |
| Hot start | 50°C | Yes |
| Critical | 60°C | Yes |
| Recovery | 45°C | Yes |

*Thresholds are device-specific and should be tuned per SoC.*

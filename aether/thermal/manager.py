"""
Aether Thermal Manager — State machine with graceful degradation.
Never auto power-off; only adaptive throttling and workload migration.
"""

from __future__ import annotations

import logging
import time
from enum import Enum

from aether.telemetry.collector import TelemetryCollector

logger = logging.getLogger(__name__)


class ThermalState(str, Enum):
    NORMAL = "normal"
    WARM = "warm"
    HOT = "hot"
    CRITICAL = "critical"
    RECOVERY = "recovery"


class ThermalEvent:
    def __init__(self, device_id: str, old_state: ThermalState, new_state: ThermalState):
        self.device_id = device_id
        self.old_state = old_state
        self.new_state = new_state
        self.timestamp = time.time()

    def __str__(self):
        return f"ThermalEvent({self.device_id}: {self.old_state.value} -> {self.new_state.value})"


class ThermalManager:
    """Per-device thermal state machine with hysteresis."""

    def __init__(
        self, telemetry: TelemetryCollector,
        normal_max_c: float = 55.0, warn_c: float = 60.0,
        hot_c: float = 70.0, critical_c: float = 80.0,
        recovery_c: float = 50.0, trend_window_s: float = 60.0,
    ):
        self.telemetry = telemetry
        self.normal_max_c = normal_max_c
        self.warn_c = warn_c
        self.hot_c = hot_c
        self.critical_c = critical_c
        self.recovery_c = recovery_c
        self.trend_window_s = trend_window_s
        self._states: dict[str, ThermalState] = {}
        self._listeners: list = []

    def add_listener(self, callback):
        self._listeners.append(callback)

    def update_device(self, device_id: str) -> ThermalState:
        tel = self.telemetry.get_latest(device_id)
        if not tel:
            state = ThermalState.NORMAL
            self._states[device_id] = state
            return state
        temp = tel.temperature_c
        trend = self.telemetry.temperature_trend(device_id, self.trend_window_s)
        old_state = self._states.get(device_id, ThermalState.NORMAL)
        new_state = self._compute_state(temp, trend, old_state)
        if new_state != old_state:
            event = ThermalEvent(device_id, old_state, new_state)
            self._states[device_id] = new_state
            logger.warning("%s", event)
            for cb in self._listeners:
                try:
                    cb(event)
                except Exception:
                    logger.exception("Thermal listener error")
        return new_state

    def _compute_state(self, temp: float, trend: float, current: ThermalState) -> ThermalState:
        if temp >= self.critical_c or (temp >= self.hot_c and trend > 0.5):
            return ThermalState.CRITICAL
        if temp >= self.hot_c:
            return ThermalState.HOT
        if temp >= self.warn_c or (temp >= self.normal_max_c and trend > 0.2):
            return ThermalState.WARM
        # Recovery: device was previously hot/warm/critical, now cooled down
        if current in (ThermalState.WARM, ThermalState.HOT, ThermalState.CRITICAL):
            if temp <= self.recovery_c and trend <= 0.0:
                return ThermalState.RECOVERY
        return ThermalState.NORMAL

    def get_state(self, device_id: str) -> ThermalState:
        return self._states.get(device_id, ThermalState.NORMAL)

    def can_compute(self, device_id: str) -> bool:
        return self.get_state(device_id) in (
            ThermalState.NORMAL, ThermalState.WARM, ThermalState.RECOVERY,
        )

    def can_resident_memory(self, device_id: str) -> bool:
        return self.get_state(device_id) != ThermalState.CRITICAL

    def concurrency_limit(self, device_id: str) -> int:
        limits = {
            ThermalState.NORMAL: 4, ThermalState.WARM: 2, ThermalState.HOT: 1,
            ThermalState.CRITICAL: 0, ThermalState.RECOVERY: 1,
        }
        return limits.get(self.get_state(device_id), 0)

    @property
    def all_states(self) -> dict[str, ThermalState]:
        return dict(self._states)

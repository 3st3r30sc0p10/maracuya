from __future__ import annotations

from dataclasses import dataclass
import math
import time

from .config import BackendConfig


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _normalize(value: float, min_v: float, max_v: float) -> float:
    if max_v <= min_v:
        return 0.0
    return _clamp((value - min_v) / (max_v - min_v))


@dataclass
class SensorState:
    rubber_raw: float = 0.0
    fabric_raw: float = 0.0
    rubber_norm: float = 0.0
    fabric_norm: float = 0.0
    rubber_smooth: float = 0.0
    fabric_smooth: float = 0.0
    last_update_ts: float = 0.0


class SensorManager:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._state = SensorState()
        self._start_ts = time.monotonic()
        self._initialized = False

    @property
    def state(self) -> SensorState:
        return self._state

    def update_from_packet(self, packet: dict) -> SensorState:
        rubber_v = float(packet.get("rubber_v", 0.0))
        fabric_v = float(packet.get("fabric_v", 0.0))
        return self._apply_raw(rubber_v, fabric_v)

    def update_simulated(self) -> SensorState:
        now = time.monotonic()
        elapsed = now - self._start_ts
        rubber_norm = 0.5 + 0.5 * math.sin(2.0 * math.pi * self._config.sensor_sine_hz * elapsed)
        fabric_norm = _clamp(self._state.fabric_smooth + self._config.fabric_drift_per_sec)
        rubber_raw = self._config.sensor_min_v + rubber_norm * (
            self._config.sensor_max_v - self._config.sensor_min_v
        )
        fabric_raw = self._config.sensor_min_v + fabric_norm * (
            self._config.sensor_max_v - self._config.sensor_min_v
        )
        return self._apply_raw(rubber_raw, fabric_raw)

    def maybe_update(self) -> SensorState:
        if not self._config.simulate_sensors:
            return self._state
        now = time.monotonic()
        if now - self._state.last_update_ts >= self._config.sensor_timeout_sec:
            return self.update_simulated()
        return self._state

    def _apply_raw(self, rubber_raw: float, fabric_raw: float) -> SensorState:
        rubber_norm = _normalize(rubber_raw, self._config.sensor_min_v, self._config.sensor_max_v)
        fabric_norm = _normalize(fabric_raw, self._config.sensor_min_v, self._config.sensor_max_v)
        if not self._initialized:
            rubber_smooth = rubber_norm
            fabric_smooth = fabric_norm
            self._initialized = True
        else:
            rubber_smooth = (1.0 - self._config.rubber_alpha) * self._state.rubber_smooth + self._config.rubber_alpha * rubber_norm
            fabric_smooth = (1.0 - self._config.fabric_alpha) * self._state.fabric_smooth + self._config.fabric_alpha * fabric_norm
        self._state = SensorState(
            rubber_raw=rubber_raw,
            fabric_raw=fabric_raw,
            rubber_norm=rubber_norm,
            fabric_norm=fabric_norm,
            rubber_smooth=rubber_smooth,
            fabric_smooth=fabric_smooth,
            last_update_ts=time.monotonic(),
        )
        return self._state

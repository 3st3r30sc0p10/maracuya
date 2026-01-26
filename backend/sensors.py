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
        self._rubber_peak = 0.0
        self._rubber_peak_ts = self._start_ts
        self._rubber_gate_count = 0

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
        # Use sensor-specific voltage ranges for normalization
        rubber_norm = _normalize(rubber_raw, self._config.rubber_min_v, self._config.rubber_max_v)
        fabric_norm = _normalize(fabric_raw, self._config.fabric_min_v, self._config.fabric_max_v)
        
        # Apply dead zone to filter noise when relaxed
        dead_zone = getattr(self._config, 'rubber_dead_zone', 0.0)
        if rubber_norm < dead_zone:
            rubber_norm = 0.0
            self._rubber_gate_count = 0
        elif rubber_norm > 0.0:
            # Require two consecutive samples above dead zone to reduce jitter
            self._rubber_gate_count = min(self._rubber_gate_count + 1, 2)
            if self._rubber_gate_count < 2:
                rubber_norm = 0.0
        
        # Gentle spike limiter: catch any spikes that get through ESP32 median filter
        # Allow large changes for real stretching, but limit extreme jumps
        if self._initialized:
            prev_smooth = self._state.rubber_smooth
            jump = abs(rubber_norm - prev_smooth)
            max_jump = 0.65  # Allow up to 65% change per reading (catches spikes but allows fast stretching)
            if jump > max_jump:
                # Limit the change to max_jump in the direction of the new reading
                if rubber_norm > prev_smooth:
                    rubber_norm = prev_smooth + max_jump
                else:
                    rubber_norm = max(0.0, prev_smooth - max_jump)

        # Peak hold: keep high stretch for a short time, then decay gently
        now = time.monotonic()
        if not self._initialized:
            self._rubber_peak = rubber_norm
            self._rubber_peak_ts = now
        else:
            if rubber_norm >= self._rubber_peak:
                self._rubber_peak = rubber_norm
                self._rubber_peak_ts = now
            else:
                hold_ms = getattr(self._config, "rubber_peak_hold_ms", 0.0)
                if (now - self._rubber_peak_ts) * 1000.0 <= hold_ms:
                    rubber_norm = self._rubber_peak
                else:
                    decay = getattr(self._config, "rubber_peak_decay_per_sec", 0.0)
                    decay_amount = decay * (now - self._rubber_peak_ts)
                    self._rubber_peak = max(rubber_norm, self._rubber_peak - decay_amount)
                    self._rubber_peak_ts = now
                    rubber_norm = self._rubber_peak
        
        if not self._initialized:
            rubber_smooth = rubber_norm
            fabric_smooth = fabric_norm
            self._initialized = True
            # Log first sensor reading
            print(f"[sensors] first reading: rubber_v={rubber_raw:.3f} norm={rubber_norm:.3f} fabric_v={fabric_raw:.3f} norm={fabric_norm:.3f}", flush=True)
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
        # Log periodically (every 50 updates)
        if not hasattr(self, '_log_count'):
            self._log_count = 0
        self._log_count += 1
        if self._log_count % 50 == 0:
            print(f"[sensors] rubber_v={rubber_raw:.3f} norm={rubber_norm:.3f} smooth={rubber_smooth:.3f} | fabric_v={fabric_raw:.3f} norm={fabric_norm:.3f} smooth={fabric_smooth:.3f}", flush=True)
        return self._state

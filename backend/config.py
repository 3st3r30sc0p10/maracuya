from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class BackendConfig:
    # Paths
    model_path: Path
    ui_dir: Path
    simulated_frame_path: Path

    # Camera / inference
    camera_width: int
    camera_height: int
    inference_width: int
    inference_height: int
    stream_fps: float
    ui_fps: float
    min_box_size: int
    normalized_boxes: bool

    # Names
    name_a: str
    name_b: str

    # Policy thresholds
    t_min: float
    t_max: float
    hysteresis: float

    # Sensor normalization
    sensor_min_v: float
    sensor_max_v: float
    sensor_timeout_sec: float
    rubber_alpha: float
    fabric_alpha: float
    serial_port: str
    serial_baud: int

    # Balancing
    target_ratio_a: float
    bias_limit: float
    bias_lr: float
    bias_window: int

    # Logging
    ambiguous_log_interval: float

    # Simulation knobs
    simulate_camera: bool
    simulate_inference: bool
    simulate_sensors: bool
    sensor_sine_hz: float
    fabric_drift_per_sec: float


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value) if value else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> BackendConfig:
    repo_root = Path(__file__).resolve().parents[1]
    ui_dir = repo_root / "ui"
    return BackendConfig(
        model_path=_env_path("MARACUYA_HEF", Path("/hailo/maracuya_yolo.hef")),
        ui_dir=ui_dir,
        simulated_frame_path=_env_path("SIM_FRAME_PATH", repo_root / "test.jpg"),
        camera_width=_env_int("CAMERA_WIDTH", 512),
        camera_height=_env_int("CAMERA_HEIGHT", 512),
        inference_width=_env_int("INFER_WIDTH", 512),
        inference_height=_env_int("INFER_HEIGHT", 512),
        stream_fps=_env_float("STREAM_FPS", 20.0),
        ui_fps=_env_float("UI_FPS", 20.0),
        min_box_size=_env_int("MIN_BOX_SIZE", 6),
        normalized_boxes=_env_bool("NORMALIZED", False),
        name_a=os.getenv("NAME_A", "maracuya"),
        name_b=os.getenv("NAME_B", "passionfruit"),
        t_min=_env_float("T_MIN", 0.05),
        t_max=_env_float("T_MAX", 0.60),
        hysteresis=_env_float("HYSTERESIS", 0.02),
        sensor_min_v=_env_float("SENSOR_MIN_V", 0.0),
        sensor_max_v=_env_float("SENSOR_MAX_V", 3.3),
        sensor_timeout_sec=_env_float("SENSOR_TIMEOUT_SEC", 5.0),
        rubber_alpha=_env_float("RUBBER_ALPHA", 0.20),
        fabric_alpha=_env_float("FABRIC_ALPHA", 0.05),
        serial_port=os.getenv("SERIAL_PORT", "/dev/ttyACM0"),
        serial_baud=_env_int("SERIAL_BAUD", 115200),
        target_ratio_a=_env_float("TARGET_RATIO_A", 0.50),
        bias_limit=_env_float("BIAS_LIMIT", 0.25),
        bias_lr=_env_float("BIAS_LR", 0.002),
        bias_window=_env_int("BIAS_WINDOW", 200),
        ambiguous_log_interval=_env_float("AMBIG_LOG_SEC", 0.25),
        simulate_camera=_env_bool("SIM_CAMERA", False),
        simulate_inference=_env_bool("SIM_INFERENCE", False),
        simulate_sensors=_env_bool("SIM_SENSORS", True),
        sensor_sine_hz=_env_float("SENSOR_SINE_HZ", 0.08),
        fabric_drift_per_sec=_env_float("FABRIC_DRIFT_PER_SEC", 1.0 / (20.0 * 60.0)),
    )

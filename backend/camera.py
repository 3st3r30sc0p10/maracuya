from __future__ import annotations

import time
from typing import Optional, Tuple

import numpy as np

from .config import BackendConfig

try:
    from picamera2 import Picamera2
except Exception:  # pragma: no cover - optional dependency
    Picamera2 = None

try:
    import cv2
except Exception:  # pragma: no cover - optional dependency
    cv2 = None

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None


class Camera:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._picam: Optional[Picamera2] = None
        self._cap = None
        if not config.simulate_camera and Picamera2 is not None:
            self._picam = Picamera2()
            preview_config = self._picam.create_preview_configuration(
                main={"format": "RGB888", "size": (config.camera_width, config.camera_height)}
            )
            self._picam.configure(preview_config)
            self._picam.start()
            time.sleep(0.2)
        elif not config.simulate_camera and cv2 is not None:
            self._cap = cv2.VideoCapture(0)

    def set_awb(self, enabled: bool) -> None:
        if self._picam is None:
            return
        self._picam.set_controls({"AwbEnable": bool(enabled)})

    def set_colour_gains(self, red_gain: float, blue_gain: float) -> None:
        if self._picam is None:
            return
        self._picam.set_controls({"ColourGains": (float(red_gain), float(blue_gain))})

    def get_frame(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Return (rgb, bgr) frames as numpy arrays.
        """
        if self._picam is not None:
            rgb = self._picam.capture_array("main")
            if self._validate_rgb(rgb):
                if cv2 is not None:
                    return rgb, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                return rgb, rgb[..., ::-1]
        if self._cap is not None and cv2 is not None:
            ok, frame_bgr = self._cap.read()
            if ok and frame_bgr is not None:
                frame_bgr = cv2.resize(
                    frame_bgr, (self._config.camera_width, self._config.camera_height)
                )
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                return frame_rgb, frame_bgr
        rgb = self._load_simulated_frame()
        if cv2 is not None:
            return rgb, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return rgb, rgb[..., ::-1]

    def _validate_rgb(self, rgb: np.ndarray) -> bool:
        if not isinstance(rgb, np.ndarray):
            return False
        if rgb.shape != (self._config.camera_height, self._config.camera_width, 3):
            return False
        return rgb.dtype == np.uint8

    def _load_simulated_frame(self) -> np.ndarray:
        path = self._config.simulated_frame_path
        if cv2 is not None and path.exists():
            bgr = cv2.imread(str(path))
            if bgr is not None:
                bgr = cv2.resize(bgr, (self._config.camera_width, self._config.camera_height))
                return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if Image is not None and path.exists():
            with Image.open(path) as image:
                image = image.resize((self._config.camera_width, self._config.camera_height))
                return np.array(image.convert("RGB"))
        return np.zeros((self._config.camera_height, self._config.camera_width, 3), dtype=np.uint8)

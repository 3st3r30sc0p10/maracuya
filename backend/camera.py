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
        self._last_log = 0.0
        if not config.simulate_camera and Picamera2 is not None:
            self._picam = Picamera2()
            preview_config = self._picam.create_preview_configuration(
                main={"format": "RGB888", "size": (config.camera_width, config.camera_height)}
            )
            self._picam.configure(preview_config)
            self._picam.start()
            time.sleep(0.3)
            # Configure autofocus and color balance
            self._configure_camera_controls()
            print("[camera] picamera2 started")
        elif not config.simulate_camera and cv2 is not None:
            self._cap = cv2.VideoCapture(0)
            print("[camera] opencv capture started")

    def _configure_camera_controls(self) -> None:
        """Configure white balance, sharpness, and color settings."""
        if self._picam is None:
            return
        
        # Note: This IMX500 module doesn't have autofocus controls exposed
        # Focus is fixed at factory setting
        
        try:
            # Use auto white balance - manual gains don't work correctly on this camera
            # AWB Auto gave best results in testing: R=105.5 G=102.3 B=91.0
            self._picam.set_controls({
                "AwbEnable": True,
                "AwbMode": 0,  # Auto
            })
            print("[camera] white balance: auto (AWB enabled)")
        except Exception as e:
            print(f"[camera] AWB setup failed: {e}")
        
        try:
            # Increase sharpness to help with fixed-focus
            self._picam.set_controls({
                "Sharpness": 3.0,  # Higher sharpness (default 1.0, max 16.0)
            })
            print("[camera] sharpness: 3.0 (enhanced)")
        except Exception as e:
            print(f"[camera] sharpness setup failed: {e}")
        
        try:
            # Normal saturation
            self._picam.set_controls({
                "Saturation": 1.0,  # Normal saturation
            })
            print("[camera] saturation: 1.0 (normal)")
        except Exception as e:
            print(f"[camera] saturation setup failed: {e}")
        
        try:
            # Normal contrast
            self._picam.set_controls({
                "Contrast": 1.0,
            })
            print("[camera] contrast: 1.0 (normal)")
        except Exception as e:
            print(f"[camera] contrast setup failed: {e}")

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
        
        Note: Picamera2 with RGB888 format may actually output BGR on some systems.
        Testing shows R↔B swap symptoms, so we try treating capture as-is for BGR.
        """
        if self._picam is not None:
            frame = self._picam.capture_array("main")
            if self._is_rgb_array(frame):
                frame = self._normalize_rgb(frame)
                self._log_frame_stats("picamera2", frame)
                # Picamera2 RGB888 appears to output BGR on this system
                # So frame is already BGR, convert to RGB for the rgb return value
                if cv2 is not None:
                    bgr = frame
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    return rgb, bgr
                bgr = frame
                rgb = frame[..., ::-1]
                return rgb, bgr
        if self._cap is not None and cv2 is not None:
            ok, frame_bgr = self._cap.read()
            if ok and frame_bgr is not None:
                frame_bgr = cv2.resize(
                    frame_bgr, (self._config.camera_width, self._config.camera_height)
                )
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                self._log_frame_stats("opencv", frame_rgb)
                return frame_rgb, frame_bgr
        rgb = self._load_simulated_frame()
        self._log_frame_stats("sim", rgb)
        if cv2 is not None:
            return rgb, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return rgb, rgb[..., ::-1]

    def _log_frame_stats(self, source: str, rgb: np.ndarray) -> None:
        now = time.time()
        if now - self._last_log < 2.0:
            return
        self._last_log = now
        mean_val = float(rgb.mean())
        print(f"[camera] {source} frame shape={rgb.shape} mean={mean_val:.1f}")

    def _is_rgb_array(self, rgb: np.ndarray) -> bool:
        if not isinstance(rgb, np.ndarray):
            return False
        if rgb.ndim != 3 or rgb.shape[2] != 3:
            return False
        return rgb.dtype == np.uint8

    def _normalize_rgb(self, rgb: np.ndarray) -> np.ndarray:
        target = (self._config.camera_width, self._config.camera_height)
        if (rgb.shape[1], rgb.shape[0]) == target:
            return rgb
        if cv2 is not None:
            return cv2.resize(rgb, target)
        if Image is not None:
            image = Image.fromarray(rgb)
            image = image.resize(target)
            return np.array(image)
        return rgb

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

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

try:
    import hailo_platform as hpf  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    hpf = None


@dataclass
class DecodedOutput:
    scores_raw: Dict[str, float]
    boxes: Dict[str, List[float]]
    has_a: bool
    has_b: bool


class HailoInfer:
    def __init__(self, hef_path: str, simulate: bool = False) -> None:
        self._hef_path = hef_path
        self._simulate = simulate or hpf is None
        self._device = None
        self._ng = None
        self._input_name = None
        self._output_name = None
        self._in_params = None
        self._out_params = None
        if not self._simulate and hpf is not None:
            self._setup_pipeline()

    def _setup_pipeline(self) -> None:
        hef = hpf.HEF(self._hef_path)
        self._device = hpf.VDevice()
        configure_params = hpf.ConfigureParams.create_from_hef(
            hef, interface=hpf.HailoStreamInterface.PCIe
        )
        self._ng = self._device.configure(hef, configure_params)[0]
        self._in_params = hpf.InputVStreamParams.make_from_network_group(
            self._ng, quantized=True, format_type=hpf.FormatType.UINT8
        )
        self._out_params = hpf.OutputVStreamParams.make_from_network_group(
            self._ng, quantized=False, format_type=hpf.FormatType.FLOAT32
        )
        input_infos = self._ng.get_input_vstream_infos()
        output_infos = self._ng.get_output_vstream_infos()
        if input_infos:
            self._input_name = input_infos[0].name
        if output_infos:
            preferred = "maracuya_yolo/yolov8_nms_postprocess"
            match = next((info.name for info in output_infos if info.name == preferred), None)
            self._output_name = match or output_infos[0].name
        self._print_startup_info(input_infos, output_infos)

    def _print_startup_info(self, input_infos, output_infos) -> None:
        version = getattr(hpf, "__version__", "unknown")
        print(f"[hailo] hailo_platform version: {version}")
        print(f"[hailo] numpy version: {np.__version__}")
        print(f"[hailo] HEF path: {self._hef_path}")
        for info in input_infos:
            print(f"[hailo] input: {info.name} shape={info.shape} type={info.format.type}")
        for info in output_infos:
            print(f"[hailo] output: {info.name} shape={info.shape} type={info.format.type}")

    def infer_frame(
        self, frame_bgr: np.ndarray, normalized: bool, min_box_size: int
    ) -> DecodedOutput:
        if self._simulate:
            return self._simulate_output(frame_bgr, normalized, min_box_size)
        if self._ng is None or self._input_name is None:
            return DecodedOutput(scores_raw={"A": 0.0, "B": 0.0}, boxes={"A": [0, 0, 0, 0], "B": [0, 0, 0, 0]}, has_a=False, has_b=False)
        frame_rgb = self._to_rgb(frame_bgr)
        input_tensor = np.ascontiguousarray(frame_rgb[np.newaxis, ...], dtype=np.uint8)
        with self._ng.activate(self._ng.create_params()):
            with hpf.InferVStreams(self._ng, self._in_params, self._out_params) as pipe:
                result = pipe.infer({self._input_name: input_tensor})
        out_key = self._output_name or next(iter(result.keys()))
        return self._decode_output(result[out_key], frame_bgr.shape[1], frame_bgr.shape[0], normalized, min_box_size)

    def _to_rgb(self, frame_bgr: np.ndarray) -> np.ndarray:
        return frame_bgr[..., ::-1]

    def _decode_output(
        self, output, width: int, height: int, normalized: bool, min_box_size: int
    ) -> DecodedOutput:
        # Output format: list[batch] -> list[classes] -> ndarray (N,5)
        scores = {"A": 0.0, "B": 0.0}
        boxes = {"A": [0, 0, 0, 0], "B": [0, 0, 0, 0]}
        has_a = False
        has_b = False
        if not output or not output[0]:
            return DecodedOutput(scores_raw=scores, boxes=boxes, has_a=False, has_b=False)
        classes = output[0]
        for idx, class_arr in enumerate(classes):
            if class_arr is None or len(class_arr) == 0:
                continue
            best_row = class_arr[np.argmax(class_arr[:, 4])]
            x1, y1, x2, y2, score = [float(v) for v in best_row]
            if normalized:
                x1 *= width
                x2 *= width
                y1 *= height
                y2 *= height
            valid = abs(x2 - x1) >= min_box_size and abs(y2 - y1) >= min_box_size
            if idx == 0:
                scores["A"] = score
                has_a = True
                boxes["A"] = [x1, y1, x2, y2] if valid else [0, 0, 0, 0]
            else:
                scores["B"] = score
                has_b = True
                boxes["B"] = [x1, y1, x2, y2] if valid else [0, 0, 0, 0]
        return DecodedOutput(scores_raw=scores, boxes=boxes, has_a=has_a, has_b=has_b)

    def _simulate_output(
        self, frame_bgr: np.ndarray, normalized: bool, min_box_size: int
    ) -> DecodedOutput:
        height, width = frame_bgr.shape[:2]
        phase = (time.monotonic() % 2.0) / 2.0
        if phase < 0.25:
            s0, s1 = 0.85, 0.15
        elif phase < 0.5:
            s0, s1 = 0.55, 0.52
        elif phase < 0.75:
            s0, s1 = 0.25, 0.82
        else:
            s0, s1 = 0.48, 0.47
        size = int(min(width, height) * 0.4)
        x1 = int((width - size) * 0.5)
        y1 = int((height - size) * 0.4)
        x2 = x1 + size
        y2 = y1 + size
        valid = abs(x2 - x1) >= min_box_size and abs(y2 - y1) >= min_box_size
        box = [x1, y1, x2, y2] if valid else [0, 0, 0, 0]
        return DecodedOutput(
            scores_raw={"A": float(s0), "B": float(s1)},
            boxes={"A": box, "B": box},
            has_a=True,
            has_b=True,
        )


_HAILO: Optional[HailoInfer] = None


def init_hailo(hef_path: str) -> None:
    simulate = os.getenv("SIM_INFERENCE", "false").lower() in {"1", "true", "yes", "on"}
    global _HAILO
    _HAILO = HailoInfer(hef_path, simulate=simulate)


def infer_frame(
    frame_bgr: np.ndarray, normalized: bool, min_box_size: int
) -> DecodedOutput:
    if _HAILO is None:
        return DecodedOutput(scores_raw={"A": 0.0, "B": 0.0}, boxes={"A": [0, 0, 0, 0], "B": [0, 0, 0, 0]}, has_a=False, has_b=False)
    return _HAILO.infer_frame(frame_bgr, normalized, min_box_size)

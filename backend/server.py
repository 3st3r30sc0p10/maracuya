from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
import time
from typing import AsyncGenerator, Dict

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import BackendConfig

try:
    import cv2
except Exception:  # pragma: no cover - optional dependency
    cv2 = None

try:
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    Image = None

# Module-level flag for one-time debug logging
_box_draw_logged = False


@dataclass
class RuntimeState:
    config: BackendConfig
    sensors: object
    latest_bgr: np.ndarray | None = None
    latest_packet: Dict = field(default_factory=dict)
    last_jpeg_log: float = 0.0
    frame_id: int = 0  # Incremented for each new frame


def create_app(state: RuntimeState, lifespan=None) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.mount("/assets", StaticFiles(directory=str(state.config.ui_dir / "assets")), name="assets")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(state.config.ui_dir / "index.html"))

    @app.get("/styles.css")
    async def styles() -> FileResponse:
        return FileResponse(str(state.config.ui_dir / "styles.css"))

    @app.get("/app.js")
    async def app_js() -> FileResponse:
        return FileResponse(str(state.config.ui_dir / "app.js"))

    @app.get("/debug/frame")
    async def debug_frame() -> Dict:
        frame = state.latest_bgr
        if frame is None:
            return {"has_frame": False}
        return {
            "has_frame": True,
            "shape": list(frame.shape),
            "mean": float(frame.mean()),
        }

    @app.get("/debug.jpg")
    async def debug_jpeg() -> Response:
        frame = state.latest_bgr
        if frame is None:
            return Response(status_code=204)
        jpeg = await asyncio.to_thread(_encode_jpeg, frame)
        if not jpeg:
            return Response(status_code=500)
        return Response(content=jpeg, media_type="image/jpeg")

    @app.post("/sensors")
    async def sensors_endpoint(payload: Dict) -> Dict:
        state.sensors.update_from_packet(payload)
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """State WebSocket - sends JSON state packets at 10-30 Hz"""
        await websocket.accept()
        try:
            while True:
                # Build enhanced state packet for frontend compositor
                packet = state.latest_packet.copy() if state.latest_packet else {}
                
                # Add frame_id for synchronization
                packet["frame_id"] = state.frame_id
                
                # Extract confidence scores for frontend weight computation
                detections = packet.get("detections", [])
                conf_pass = 0.0  # passionfruit = B
                conf_mara = 0.0  # maracuya = A
                for det in detections:
                    if isinstance(det, dict):
                        if det.get("name") == "A":
                            conf_mara = det.get("score_cal", 0.0)
                        elif det.get("name") == "B":
                            conf_pass = det.get("score_cal", 0.0)
                
                packet["conf_pass"] = conf_pass
                packet["conf_mara"] = conf_mara
                
                # Add ambiguity score (0-1 based on how close confidences are)
                gap = abs(conf_mara - conf_pass)
                amb_score = max(0.0, 1.0 - gap * 5.0)  # Ambiguous when gap < 0.2
                packet["amb_score"] = amb_score
                
                # Include sensor values for frontend - use raw norm for instant response
                if state.sensors and state.sensors.state:
                    packet["rubber_k"] = state.sensors.state.rubber_norm  # Instant (raw)
                    packet["rubber_smooth"] = state.sensors.state.rubber_smooth  # Smoothed
                    packet["fabric_k"] = state.sensors.state.fabric_smooth
                
                # Normalize bounding boxes to 0-1 range for frontend
                bboxes = []
                for det in detections:
                    if isinstance(det, dict) and det.get("detected"):
                        box = det.get("box", [0, 0, 0, 0])
                        bboxes.append({
                            "x": box[0] / 512.0,
                            "y": box[1] / 512.0,
                            "w": (box[2] - box[0]) / 512.0,
                            "h": (box[3] - box[1]) / 512.0,
                            "label": det.get("label", ""),
                            "score": det.get("score_cal", 0.0),
                            "name": det.get("name", "")
                        })
                packet["bboxes"] = bboxes
                
                await websocket.send_text(json.dumps(packet))
                await asyncio.sleep(1.0 / max(state.config.ui_fps, 1.0))
        except WebSocketDisconnect:
            return

    @app.websocket("/ws/frames")
    async def websocket_frames(websocket: WebSocket) -> None:
        """Binary WebSocket - sends JPEG frames for WebGL texture"""
        await websocket.accept()
        last_frame_id = -1
        try:
            while True:
                frame = state.latest_bgr
                current_frame_id = state.frame_id
                
                # Only send if we have a new frame
                if frame is not None and current_frame_id != last_frame_id:
                    last_frame_id = current_frame_id
                    # Encode as JPEG without annotations (frontend will handle overlays)
                    jpeg = await asyncio.to_thread(_encode_jpeg, frame)
                    if jpeg:
                        # Send frame_id as 4-byte header + JPEG data
                        header = current_frame_id.to_bytes(4, 'big')
                        await websocket.send_bytes(header + jpeg)
                
                await asyncio.sleep(1.0 / max(state.config.stream_fps, 1.0))
        except WebSocketDisconnect:
            return

    @app.get("/stream.mjpg")
    async def stream() -> StreamingResponse:
        async def generator() -> AsyncGenerator[bytes, None]:
            frame_count = 0
            none_count = 0
            while True:
                frame = state.latest_bgr
                packet = state.latest_packet
                if frame is not None:
                    # Annotate frame with bounding boxes and labels
                    annotated = _annotate_frame(frame, packet)
                    jpeg = await asyncio.to_thread(_encode_jpeg, annotated)
                    if jpeg:
                        frame_count += 1
                        if frame_count == 1:
                            print(f"[stream] first frame sent, len={len(jpeg)}")
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                    else:
                        print("[stream] jpeg encode returned empty")
                else:
                    none_count += 1
                    if none_count == 1 or none_count % 20 == 0:
                        print(f"[stream] waiting for frame... (checks={none_count})")
                await asyncio.sleep(1.0 / max(state.config.stream_fps, 1.0))

        return StreamingResponse(generator(), media_type="multipart/x-mixed-replace; boundary=frame")

    return app


def _encode_jpeg(frame_bgr: np.ndarray) -> bytes:
    if cv2 is not None:
        ok, buffer = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if ok:
            return buffer.tobytes()
    if Image is not None:
        image = Image.fromarray(frame_bgr[..., ::-1])
        from io import BytesIO

        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        return buffer.getvalue()
    return b""


def _annotate_frame(frame_bgr: np.ndarray, packet: Dict) -> np.ndarray:
    detections = packet.get("detections") if isinstance(packet, dict) else None
    if not detections:
        return frame_bgr
    
    # Get policy state and winner to show correct label
    state = packet.get("state", "")
    winner = packet.get("winner", "")
    
    # Build labels dict from detections
    labels = {}
    for det in detections:
        if isinstance(det, dict):
            labels[det.get("name", "")] = det.get("label", "")
    
    height, width = frame_bgr.shape[:2]
    annotated = frame_bgr.copy()
    for det in detections:
        if not isinstance(det, dict):
            continue
        # Skip if not detected
        if not det.get("detected", False):
            continue
        box = det.get("box")
        if not box or len(box) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in box]
        if x2 - x1 <= 0 or y2 - y1 <= 0:
            continue
        # Boxes are already in pixel coordinates for the frame
        # Only rescale if frame dimensions differ from inference dimensions (512)
        scale_x = width / 512.0
        scale_y = height / 512.0
        left = int(x1 * scale_x)
        top = int(y1 * scale_y)
        right = int(x2 * scale_x)
        bottom = int(y2 * scale_y)
        # Debug: log first box drawn (use module-level flag)
        global _box_draw_logged
        if not _box_draw_logged:
            _box_draw_logged = True
            print(f"[annotate] drawing box: x1={x1:.1f} y1={y1:.1f} x2={x2:.1f} y2={y2:.1f} -> left={left} top={top} right={right} bottom={bottom}", flush=True)
        # Use policy winner for label, not raw AI label
        if state == "DECIDED" and winner:
            display_label = labels.get(winner, det.get("label", ""))
            color = (86, 255, 153) if winner == "A" else (255, 179, 71)  # Green for A, Orange for B
        elif state == "AMBIGUOUS":
            display_label = "maracuya? passionfruit?"
            color = (102, 224, 255)  # Yellow-ish
        else:
            display_label = det.get("label", "")
            color = (86, 255, 153) if det.get("name") == "A" else (255, 179, 71)
        
        score = det.get("score_cal")
        if isinstance(score, (int, float)):
            label = f"{display_label} {score:.2f}".strip()
        else:
            label = display_label
        if cv2 is not None:
            cv2.rectangle(annotated, (left, top), (right, bottom), color, 2)
            if label:
                cv2.rectangle(
                    annotated,
                    (left, max(top - 22, 0)),
                    (left + 8 + (len(label) * 8), top),
                    (0, 0, 0),
                    -1,
                )
                cv2.putText(
                    annotated,
                    label,
                    (left + 4, max(top - 6, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                    cv2.LINE_AA,
                )
        elif Image is not None:
            from PIL import ImageDraw, ImageFont

            image = Image.fromarray(annotated[..., ::-1])
            draw = ImageDraw.Draw(image)
            # color already set above based on policy winner
            draw.rectangle([left, top, right, bottom], outline=color, width=2)
            if label:
                draw.rectangle([left, max(top - 20, 0), left + (len(label) * 7) + 8, top], fill=(0, 0, 0))
                draw.text((left + 4, max(top - 18, 0)), label, fill=color)
            annotated = np.array(image)[..., ::-1]
    return annotated

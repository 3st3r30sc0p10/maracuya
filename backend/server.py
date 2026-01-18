from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncGenerator, Dict

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
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


@dataclass
class RuntimeState:
    config: BackendConfig
    sensors: object
    latest_bgr: np.ndarray | None = None
    latest_packet: Dict = field(default_factory=dict)


def create_app(state: RuntimeState) -> FastAPI:
    app = FastAPI()
    app.mount("/assets", StaticFiles(directory=str(state.config.ui_dir / "assets")), name="assets")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(str(state.config.ui_dir / "index.html"))

    @app.post("/sensors")
    async def sensors_endpoint(payload: Dict) -> Dict:
        state.sensors.update_from_packet(payload)
        return {"ok": True}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                await websocket.send_text(json.dumps(state.latest_packet))
                await asyncio.sleep(1.0 / max(state.config.ui_fps, 1.0))
        except WebSocketDisconnect:
            return

    @app.get("/stream.mjpg")
    async def stream() -> StreamingResponse:
        async def generator() -> AsyncGenerator[bytes, None]:
            while True:
                frame = state.latest_bgr
                if frame is not None:
                    jpeg = await asyncio.to_thread(_encode_jpeg, frame)
                    if jpeg:
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
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

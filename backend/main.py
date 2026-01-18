from __future__ import annotations

import asyncio

import json
import uvicorn

try:
    import serial  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    serial = None

from .camera import Camera
from .config import load_config
from .hailo_infer import init_hailo, infer_frame
from .policy import PolicyEngine
from .sensors import SensorManager
from .server import RuntimeState, create_app


async def run_pipeline(state: RuntimeState) -> None:
    policy = PolicyEngine(state.config)
    camera = Camera(state.config)
    while True:
        state.sensors.maybe_update()
        _frame_rgb, frame_bgr = await asyncio.to_thread(camera.get_frame)
        decoded = await asyncio.to_thread(
            infer_frame,
            frame_bgr,
            state.config.normalized_boxes,
            state.config.min_box_size,
        )
        packet = policy.evaluate(
            scores_raw=decoded.scores_raw,
            boxes=decoded.boxes,
            has_a=decoded.has_a,
            has_b=decoded.has_b,
            sensors=state.sensors.state,
        )
        state.latest_bgr = frame_bgr
        state.latest_packet = packet.packet
        await asyncio.sleep(1.0 / max(state.config.ui_fps, 1.0))


async def run_serial_reader(state: RuntimeState) -> None:
    if serial is None:
        return
    while True:
        try:
            with serial.Serial(
                state.config.serial_port, state.config.serial_baud, timeout=1
            ) as port:
                while True:
                    line = port.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        await asyncio.sleep(0.01)
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    state.sensors.update_from_packet(payload)
        except Exception:
            await asyncio.sleep(1.0)


def main() -> None:
    config = load_config()
    init_hailo(str(config.model_path))
    sensors = SensorManager(config)
    runtime = RuntimeState(config=config, sensors=sensors)
    app = create_app(runtime)

    async def app_with_tasks():
        asyncio.create_task(run_pipeline(runtime))
        asyncio.create_task(run_serial_reader(runtime))
        config_uvicorn = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
        server = uvicorn.Server(config_uvicorn)
        await server.serve()

    asyncio.run(app_with_tasks())


if __name__ == "__main__":
    main()

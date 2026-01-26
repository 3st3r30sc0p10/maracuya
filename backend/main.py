from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional

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

import uvicorn


async def run_pipeline(state: RuntimeState) -> None:
    policy = PolicyEngine(state.config)
    camera = None
    hailo_ready = False
    hailo_task: Optional[asyncio.Task] = None
    frame_count = 0
    while True:
        try:
            if camera is None:
                print("[pipeline] camera init start", flush=True)
                try:
                    camera = Camera(state.config)
                except Exception as exc:
                    print(f"[pipeline] camera init error: {exc}", flush=True)
                    await asyncio.sleep(1.0)
                    continue
                print("[pipeline] camera init ok", flush=True)

            if not hailo_ready:
                if hailo_task is None:
                    print("[pipeline] init_hailo start", flush=True)
                    hailo_task = asyncio.create_task(
                        asyncio.to_thread(init_hailo, str(state.config.model_path))
                    )
                if hailo_task.done():
                    try:
                        hailo_task.result()
                    except Exception as exc:
                        print(f"[pipeline] init_hailo error: {exc}", flush=True)
                        hailo_task = None
                    else:
                        print("[pipeline] init_hailo ok", flush=True)
                        hailo_ready = True

            state.sensors.maybe_update()

            # Run get_frame synchronously - we're in main event loop, it's OK to block briefly
            try:
                _frame_rgb, frame_bgr = camera.get_frame()
                if frame_count == 0:
                    print(f"[pipeline] get_frame returned, shape={frame_bgr.shape}", flush=True)
            except Exception as exc:
                print(f"[pipeline] get_frame error: {exc}", flush=True)
                await asyncio.sleep(0.5)
                continue

            decoded = None
            if hailo_ready:
                try:
                    decoded = await asyncio.to_thread(
                        infer_frame,
                        frame_bgr,
                        state.config.normalized_boxes,
                        state.config.min_box_size,
                    )
                except Exception as exc:
                    print(f"[pipeline] infer_frame error: {exc}", flush=True)

            try:
                packet = policy.evaluate(
                    scores_raw=decoded.scores_raw if decoded else {"A": 0.0, "B": 0.0},
                    boxes=decoded.boxes if decoded else {"A": [0, 0, 0, 0], "B": [0, 0, 0, 0]},
                    has_a=decoded.has_a if decoded else False,
                    has_b=decoded.has_b if decoded else False,
                    sensors=state.sensors.state,
                )
            except Exception as exc:
                print(f"[pipeline] policy.evaluate error: {exc}", flush=True)
                import traceback
                traceback.print_exc()
                await asyncio.sleep(0.5)
                continue

            state.latest_bgr = frame_bgr
            state.latest_packet = packet.packet
            state.frame_id += 1  # Increment frame ID for WebSocket sync
            frame_count += 1
            if frame_count == 1:
                print(f"[pipeline] first frame set, shape={frame_bgr.shape}, mean={frame_bgr.mean():.1f}", flush=True)
            elif frame_count % 100 == 0:
                print(f"[pipeline] frames processed: {frame_count}", flush=True)

            await asyncio.sleep(1.0 / max(state.config.ui_fps, 1.0))
        except Exception as exc:
            print(f"[pipeline] UNEXPECTED ERROR: {exc}", flush=True)
            import traceback
            traceback.print_exc()
            await asyncio.sleep(1.0)


async def run_serial_reader(state: RuntimeState) -> None:
    if serial is None:
        return
    while True:
        try:
            port = await asyncio.to_thread(
                serial.Serial,
                state.config.serial_port,
                state.config.serial_baud,
                timeout=1,
            )
            try:
                while True:
                    line = await asyncio.to_thread(port.readline)
                    line = line.decode("utf-8", errors="ignore").strip()
                    if not line:
                        await asyncio.sleep(0.01)
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    state.sensors.update_from_packet(payload)
            finally:
                port.close()
        except Exception:
            await asyncio.sleep(1.0)


# Global state for lifespan
_runtime: Optional[RuntimeState] = None
_pipeline_task: Optional[asyncio.Task] = None
_serial_task: Optional[asyncio.Task] = None


def main() -> None:
    global _runtime, _pipeline_task, _serial_task

    config = load_config()
    sensors = SensorManager(config)
    _runtime = RuntimeState(config=config, sensors=sensors)

    @asynccontextmanager
    async def lifespan(app):
        global _pipeline_task, _serial_task
        # Startup
        print("[main] starting background tasks", flush=True)
        _pipeline_task = asyncio.create_task(run_pipeline(_runtime))
        _serial_task = asyncio.create_task(run_serial_reader(_runtime))
        yield
        # Shutdown
        if _pipeline_task:
            _pipeline_task.cancel()
        if _serial_task:
            _serial_task.cancel()

    app = create_app(_runtime, lifespan=lifespan)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()

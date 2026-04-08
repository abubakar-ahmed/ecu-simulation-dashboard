from __future__ import annotations

import random
import threading
import time
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from simulation.actuator import ThrottleActuator
from simulation.pid import PID
from simulation.vehicle import clamp, update_vehicle


@dataclass
class ControlParams:
    target_speed: float = 120.0
    kp: float = 0.5
    ki: float = 0.1
    kd: float = 0.05


@dataclass
class TelemetryState:
    speed: float = 0.0
    target_speed: float = 120.0
    throttle: float = 0.0
    timestamp: float = 0.0


class ControlUpdate(BaseModel):
    target_speed: float = Field(..., ge=0.0)
    kp: float = Field(...)
    ki: float = Field(...)
    kd: float = Field(...)


class TelemetryResponse(BaseModel):
    speed: float
    target_speed: float
    throttle: float


class ControlResponse(BaseModel):
    target_speed: float
    kp: float
    ki: float
    kd: float


class SimulationService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

        self._params = ControlParams()
        self._telemetry = TelemetryState(timestamp=time.time())

        self._dt_s = 0.1
        self._mass_kg = 1200.0
        self._max_force_n = 4000.0
        self._drag_coeff = 0.3
        self._c_rr = 0.0
        self._g_m_s2 = 9.81
        self._noise_sigma_m_s = 0.0

        self._rng = random.Random()
        self._pid = PID(
            kp=self._params.kp,
            ki=self._params.ki,
            kd=self._params.kd,
        )
        self._actuator = ThrottleActuator(rate_limit_per_s=None, delay_steps=0)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def get_telemetry(self) -> TelemetryState:
        with self._lock:
            return TelemetryState(
                speed=self._telemetry.speed,
                target_speed=self._telemetry.target_speed,
                throttle=self._telemetry.throttle,
                timestamp=self._telemetry.timestamp,
            )

    def update_control(self, req: ControlUpdate) -> TelemetryState:
        with self._lock:
            self._params = ControlParams(
                target_speed=req.target_speed,
                kp=req.kp,
                ki=req.ki,
                kd=req.kd,
            )
            self._pid.kp = req.kp
            self._pid.ki = req.ki
            self._pid.kd = req.kd
            # Reset integrator state after retuning to avoid carrying old bias.
            self._pid.reset()
            self._actuator.reset()
            self._telemetry.target_speed = req.target_speed
            return TelemetryState(
                speed=self._telemetry.speed,
                target_speed=self._telemetry.target_speed,
                throttle=self._telemetry.throttle,
                timestamp=self._telemetry.timestamp,
            )

    def get_control(self) -> ControlParams:
        with self._lock:
            return ControlParams(
                target_speed=self._params.target_speed,
                kp=self._params.kp,
                ki=self._params.ki,
                kd=self._params.kd,
            )

    def _run_loop(self) -> None:
        speed_true_m_s = 0.0
        next_tick = time.perf_counter()
        while self._running.is_set():
            with self._lock:
                params = ControlParams(
                    target_speed=self._params.target_speed,
                    kp=self._params.kp,
                    ki=self._params.ki,
                    kd=self._params.kd,
                )

            if self._noise_sigma_m_s > 0.0:
                speed_measured_m_s = speed_true_m_s + self._rng.gauss(0.0, self._noise_sigma_m_s)
            else:
                speed_measured_m_s = speed_true_m_s

            throttle_cmd = self._pid.compute(
                params.target_speed,
                speed_measured_m_s,
                self._dt_s,
                u_min=0.0,
                u_max=1.0,
            )
            throttle_cmd = clamp(throttle_cmd, 0.0, 1.0)
            throttle_applied = self._actuator.step(throttle_cmd, self._dt_s)

            speed_true_m_s = update_vehicle(
                speed_true_m_s,
                throttle_applied,
                self._dt_s,
                mass_kg=self._mass_kg,
                max_force_n=self._max_force_n,
                drag_coeff=self._drag_coeff,
                c_rr=self._c_rr,
                g_m_s2=self._g_m_s2,
            )

            now = time.time()
            with self._lock:
                self._telemetry.speed = speed_true_m_s
                self._telemetry.target_speed = params.target_speed
                self._telemetry.throttle = throttle_applied
                self._telemetry.timestamp = now

            next_tick += self._dt_s
            sleep_s = max(0.0, next_tick - time.perf_counter())
            time.sleep(sleep_s)


service = SimulationService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    service.start()
    try:
        yield
    finally:
        service.stop()


app = FastAPI(title="ECU Simulation API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/telemetry/", response_model=TelemetryResponse)
def get_telemetry() -> TelemetryResponse:
    t = service.get_telemetry()
    return TelemetryResponse(speed=t.speed, target_speed=t.target_speed, throttle=t.throttle)


@app.put("/control/", response_model=TelemetryResponse)
def update_control(payload: ControlUpdate) -> TelemetryResponse:
    t = service.update_control(payload)
    return TelemetryResponse(speed=t.speed, target_speed=t.target_speed, throttle=t.throttle)


@app.get("/control/", response_model=ControlResponse)
def get_control() -> ControlResponse:
    c = service.get_control()
    return ControlResponse(
        target_speed=c.target_speed,
        kp=c.kp,
        ki=c.ki,
        kd=c.kd,
    )


@app.websocket("/ws/telemetry")
async def stream_telemetry(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            t = service.get_telemetry()
            await websocket.send_json(
                {
                    "speed": t.speed,
                    "target_speed": t.target_speed,
                    "throttle": t.throttle,
                    "timestamp": t.timestamp,
                }
            )
            await asyncio.sleep(service._dt_s)
    except WebSocketDisconnect:
        return

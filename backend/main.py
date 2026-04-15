from __future__ import annotations

import random
import threading
import time
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from .analysis import analyze_series, build_performance_plot, write_csv_text
from .tuning_suggest import suggest as tuning_suggest
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
    sim_time_s: float = 0.0


class ControlUpdate(BaseModel):
    target_speed: float = Field(..., ge=0.0)
    kp: float = Field(...)
    ki: float = Field(...)
    kd: float = Field(...)


class TelemetryResponse(BaseModel):
    speed: float
    target_speed: float
    throttle: float
    sim_time_s: float


class ControlResponse(BaseModel):
    target_speed: float
    kp: float
    ki: float
    kd: float


@dataclass
class LogSample:
    """One row of logged telemetry (Phase 6)."""

    timestamp: float
    speed_m_s: float
    target_m_s: float
    throttle: float
    error_m_s: float


class AnalysisSummaryResponse(BaseModel):
    sample_count: int
    duration_s: float
    target_ref_m_s: float | None
    overshoot_m_s: float | None
    settling_time_s: float | None
    steady_state_error_m_s: float | None
    tolerance_m_s: float | None = None
    mean_abs_error_m_s: float | None = None


class TuningSuggestRequest(BaseModel):
    """Use from_log=true (default) to consume the Phase 6 buffer; otherwise pass all gains + metrics."""

    model_config = ConfigDict(extra="ignore")

    from_log: bool = True
    kp: float | None = None
    ki: float | None = None
    kd: float | None = None
    target_speed_m_s: float | None = None
    dt_s: float | None = None
    steps: int | None = None
    noise_sigma: float | None = None
    overshoot_m_s: float | None = None
    settling_time_s: float | None = None
    steady_state_error_m_s: float | None = None
    mean_abs_error_m_s: float | None = None
    duration_s: float | None = None
    sample_count: int | None = None
    tolerance_m_s: float | None = None
    target_ref_m_s: float | None = None


class TuningSuggestResponse(BaseModel):
    action: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    rationale: str


_EXPLICIT_TUNING_FIELDS = (
    "kp",
    "ki",
    "kd",
    "target_speed_m_s",
    "dt_s",
    "steps",
    "noise_sigma",
    "overshoot_m_s",
    "steady_state_error_m_s",
    "mean_abs_error_m_s",
    "duration_s",
    "sample_count",
    "tolerance_m_s",
    "target_ref_m_s",
)


def _validate_explicit_tuning(req: TuningSuggestRequest) -> None:
    missing = [name for name in _EXPLICIT_TUNING_FIELDS if getattr(req, name) is None]
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "Explicit mode (from_log=false) requires gains and metrics; "
                f"missing: {', '.join(missing)}."
            ),
        )


def _run_tuning_suggest(req: TuningSuggestRequest) -> TuningSuggestResponse:
    if req.from_log:
        samples = service.get_log_series()
        if not samples:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Analysis log is empty; run the simulation to collect telemetry, "
                    "or set from_log to false and pass explicit metrics."
                ),
            )
        times_s = [s.timestamp for s in samples]
        speeds = [s.speed_m_s for s in samples]
        targets = [s.target_m_s for s in samples]
        throttles = [s.throttle for s in samples]
        metrics: dict[str, Any] = analyze_series(
            times_s=times_s,
            speeds_m_s=speeds,
            targets_m_s=targets,
            throttles=throttles,
        )
        c = service.get_control()
        dt_s, noise = service.get_sim_dt_noise()
        kp, ki, kd = c.kp, c.ki, c.kd
        target_speed_m_s = c.target_speed
        steps = int(metrics["sample_count"])
    else:
        _validate_explicit_tuning(req)
        metrics = {
            "sample_count": req.sample_count,
            "duration_s": req.duration_s,
            "target_ref_m_s": req.target_ref_m_s,
            "overshoot_m_s": req.overshoot_m_s,
            "settling_time_s": req.settling_time_s,
            "steady_state_error_m_s": req.steady_state_error_m_s,
            "tolerance_m_s": req.tolerance_m_s,
            "mean_abs_error_m_s": req.mean_abs_error_m_s,
        }
        kp = req.kp
        ki = req.ki
        kd = req.kd
        target_speed_m_s = req.target_speed_m_s
        dt_s = req.dt_s
        steps = req.steps
        noise = req.noise_sigma

    try:
        out = tuning_suggest(
            metrics=metrics,
            kp=kp,
            ki=ki,
            kd=kd,
            target_speed_m_s=target_speed_m_s,
            dt_s=dt_s,
            steps=steps,
            noise_sigma=noise,
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return TuningSuggestResponse(**out)


class SimulationService:
    _LOG_MAX = 12000

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = threading.Event()
        self._thread: threading.Thread | None = None

        self._params = ControlParams()
        self._telemetry = TelemetryState(timestamp=time.time(), sim_time_s=0.0)

        self._speed_true_m_s: float = 0.0
        self._sim_time_s: float = 0.0

        self._log: deque[LogSample] = deque(maxlen=self._LOG_MAX)
        self._log_t0: float | None = None

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
                sim_time_s=self._sim_time_s,
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
                sim_time_s=self._sim_time_s,
            )

    def get_control(self) -> ControlParams:
        with self._lock:
            return ControlParams(
                target_speed=self._params.target_speed,
                kp=self._params.kp,
                ki=self._params.ki,
                kd=self._params.kd,
            )

    def reset_log(self) -> None:
        with self._lock:
            self._log.clear()
            self._log_t0 = None

    def reset_run(self) -> TelemetryState:
        """Stop the current run: zero speed, reset PID/actuator, clear log, restart sim clock."""
        with self._lock:
            self._speed_true_m_s = 0.0
            self._sim_time_s = 0.0
            self._pid.kp = self._params.kp
            self._pid.ki = self._params.ki
            self._pid.kd = self._params.kd
            self._pid.reset()
            self._actuator.reset()
            now = time.time()
            self._telemetry = TelemetryState(
                speed=0.0,
                target_speed=self._params.target_speed,
                throttle=0.0,
                timestamp=now,
                sim_time_s=0.0,
            )
            self._log.clear()
            self._log_t0 = None
            return TelemetryState(
                speed=self._telemetry.speed,
                target_speed=self._telemetry.target_speed,
                throttle=self._telemetry.throttle,
                timestamp=self._telemetry.timestamp,
                sim_time_s=self._sim_time_s,
            )

    def get_log_series(self) -> list[LogSample]:
        with self._lock:
            return list(self._log)

    def get_sim_dt_noise(self) -> tuple[float, float]:
        with self._lock:
            return (self._dt_s, self._noise_sigma_m_s)

    def _run_loop(self) -> None:
        next_tick = time.perf_counter()
        while self._running.is_set():
            with self._lock:
                params = ControlParams(
                    target_speed=self._params.target_speed,
                    kp=self._params.kp,
                    ki=self._params.ki,
                    kd=self._params.kd,
                )
                speed_before = self._speed_true_m_s

                if self._noise_sigma_m_s > 0.0:
                    speed_measured_m_s = speed_before + self._rng.gauss(0.0, self._noise_sigma_m_s)
                else:
                    speed_measured_m_s = speed_before

                throttle_cmd = self._pid.compute(
                    params.target_speed,
                    speed_measured_m_s,
                    self._dt_s,
                    u_min=0.0,
                    u_max=1.0,
                )
                throttle_cmd = clamp(throttle_cmd, 0.0, 1.0)
                throttle_applied = self._actuator.step(throttle_cmd, self._dt_s)

                speed_after = update_vehicle(
                    speed_before,
                    throttle_applied,
                    self._dt_s,
                    mass_kg=self._mass_kg,
                    max_force_n=self._max_force_n,
                    drag_coeff=self._drag_coeff,
                    c_rr=self._c_rr,
                    g_m_s2=self._g_m_s2,
                )

                self._speed_true_m_s = speed_after
                self._sim_time_s += self._dt_s

                now = time.time()
                self._telemetry.speed = speed_after
                self._telemetry.target_speed = params.target_speed
                self._telemetry.throttle = throttle_applied
                self._telemetry.timestamp = now
                self._telemetry.sim_time_s = self._sim_time_s

                if self._log_t0 is None:
                    self._log_t0 = now
                t_rel = now - self._log_t0
                err = params.target_speed - speed_after
                self._log.append(
                    LogSample(
                        timestamp=t_rel,
                        speed_m_s=speed_after,
                        target_m_s=params.target_speed,
                        throttle=throttle_applied,
                        error_m_s=err,
                    )
                )

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
    return TelemetryResponse(
        speed=t.speed,
        target_speed=t.target_speed,
        throttle=t.throttle,
        sim_time_s=t.sim_time_s,
    )


@app.put("/control/", response_model=TelemetryResponse)
def update_control(payload: ControlUpdate) -> TelemetryResponse:
    t = service.update_control(payload)
    return TelemetryResponse(
        speed=t.speed,
        target_speed=t.target_speed,
        throttle=t.throttle,
        sim_time_s=t.sim_time_s,
    )


@app.post("/simulation/reset", response_model=TelemetryResponse)
def reset_simulation_run() -> TelemetryResponse:
    t = service.reset_run()
    return TelemetryResponse(
        speed=t.speed,
        target_speed=t.target_speed,
        throttle=t.throttle,
        sim_time_s=t.sim_time_s,
    )


@app.get("/control/", response_model=ControlResponse)
def get_control() -> ControlResponse:
    c = service.get_control()
    return ControlResponse(
        target_speed=c.target_speed,
        kp=c.kp,
        ki=c.ki,
        kd=c.kd,
    )


@app.post("/analysis/log/reset")
def reset_analysis_log() -> dict[str, str]:
    service.reset_log()
    return {"status": "ok", "message": "Telemetry log cleared; next sample starts a new time axis."}


@app.get("/analysis/summary", response_model=AnalysisSummaryResponse)
def get_analysis_summary() -> AnalysisSummaryResponse:
    samples = service.get_log_series()
    if not samples:
        return AnalysisSummaryResponse(
            sample_count=0,
            duration_s=0.0,
            target_ref_m_s=None,
            overshoot_m_s=None,
            settling_time_s=None,
            steady_state_error_m_s=None,
            tolerance_m_s=None,
            mean_abs_error_m_s=None,
        )
    times_s = [s.timestamp for s in samples]
    speeds = [s.speed_m_s for s in samples]
    targets = [s.target_m_s for s in samples]
    throttles = [s.throttle for s in samples]
    metrics = analyze_series(
        times_s=times_s,
        speeds_m_s=speeds,
        targets_m_s=targets,
        throttles=throttles,
    )
    return AnalysisSummaryResponse(
        sample_count=metrics["sample_count"],
        duration_s=metrics["duration_s"],
        target_ref_m_s=metrics["target_ref_m_s"],
        overshoot_m_s=metrics["overshoot_m_s"],
        settling_time_s=metrics["settling_time_s"],
        steady_state_error_m_s=metrics["steady_state_error_m_s"],
        tolerance_m_s=metrics.get("tolerance_m_s"),
        mean_abs_error_m_s=metrics.get("mean_abs_error_m_s"),
    )


@app.get("/analysis/export.csv")
def export_analysis_csv() -> Response:
    samples = service.get_log_series()
    if not samples:
        return Response(content="timestamp_s,speed_m_s,target_m_s,throttle,error_m_s\n", media_type="text/csv")
    times_s = [s.timestamp for s in samples]
    speeds = [s.speed_m_s for s in samples]
    targets = [s.target_m_s for s in samples]
    throttles = [s.throttle for s in samples]
    errors = [s.error_m_s for s in samples]
    text = write_csv_text(
        times_s=times_s,
        speeds_m_s=speeds,
        targets_m_s=targets,
        throttles=throttles,
        errors=errors,
    )
    return Response(
        content=text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="telemetry.csv"'},
    )


@app.get("/analysis/plot.png")
def export_analysis_plot() -> Response:
    samples = service.get_log_series()
    if len(samples) < 2:
        raise HTTPException(
            status_code=404,
            detail="Not enough samples. Let the simulation run, or POST /analysis/log/reset and collect more points.",
        )
    times_s = [s.timestamp for s in samples]
    speeds = [s.speed_m_s for s in samples]
    targets = [s.target_m_s for s in samples]
    throttles = [s.throttle for s in samples]
    png = build_performance_plot(
        times_s=times_s,
        speeds_m_s=speeds,
        targets_m_s=targets,
        throttles=throttles,
        title="ECU simulation (live log)",
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="performance.png"'},
    )


@app.post("/tuning/suggest", response_model=TuningSuggestResponse)
@app.post("/tuning/classify", response_model=TuningSuggestResponse)
def post_tuning_suggest(
    payload: TuningSuggestRequest | None = Body(default=None),
) -> TuningSuggestResponse:
    req = payload if payload is not None else TuningSuggestRequest()
    return _run_tuning_suggest(req)


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
                    "sim_time_s": t.sim_time_s,
                }
            )
            await asyncio.sleep(service._dt_s)
    except WebSocketDisconnect:
        return

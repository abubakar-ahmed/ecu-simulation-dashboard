# ECU Simulation Dashboard

Personal Projects v1

## Project Goal

A real-time dashboard for simulating and monitoring Engine Control Unit (ECU) behavior. The goal is to visualize simulated sensor data, control signals, and diagnostic outputs in a browser-based interface - useful for development, testing, and educational purposes without requiring physical hardware.

## Features (Planned)

- Real-time simulation of ECU parameters (RPM, throttle, temperature, fuel injection, etc.)
- Live dashboard with gauges, charts, and status indicators
- Fault injection - simulate sensor failures or out-of-range values
- Diagnostic Trouble Code (DTC) generation and display
- Start/stop/reset simulation controls
- Configurable simulation speed and parameters
- REST API for querying simulation state
- WebSocket support for live data streaming to the frontend

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React, Chart.js / Recharts |
| Backend | Python, FastAPI |
| Simulation | Python (custom ECU model) |
| Real-time comms | WebSockets |
| Data format | JSON |

## Full Project Roadmap
*Pit Wall Telemetry & ECU Dashboard*

🧭 PHASE 0 — Project Setup (1–2 days)

🎯 Goal:
Create a clean foundation so you don't get messy later.

✅ Tasks:
- Create GitHub repo: `ecu-simulation-dashboard/`
- Directory structure:
  ```
  /backend
  /simulation
  /frontend
  /docs
  ```
- Write a simple README:
  - Project goal
  - Features (planned)
  - Tech stack

PHASE 1 — Vehicle Simulation + ECU Core (CRITICAL)

🎯 Goal:
Build the heart of the system.

1. Vehicle Physics Model
   Implement:
   Speed update equation (fixed timestep):
   ```
   v[t+1] = v[t] + a * dt
   ```

   Acceleration:
   ```
   a = (F_engine - F_drag) / m
   ```

   Drag:
   ```
   F_drag = c_d * v^2
   ```

2. PID Controller
   Use:
   PID controller to produce throttle (0..1).

   Control loop:
   ```
   error = target_speed - current_speed
   output = PID(proportional, integral, derivative)  # throttle
   ```

3. Simulation Loop
   Run at fixed timestep:
   ```
   dt = 0.1  # 100 ms

   while True:
       throttle = pid.compute(speed)
       speed = update_vehicle(speed, throttle)
       print(speed, throttle)
   ```

**Output (End of Phase 1):**
- Stable speed control
- No UI yet
- Just console logs

**Run Phase 1:**
- Command (speed in **m/s**, mass in **kg**, force in **N**; see `--help`):
  `python simulation/main.py --target 30 --kp 0.5 --ki 0.1 --kd 0.05`
- Optional: sensor noise on the speed feedback (stresses the PID): `--noise-sigma 0.15` (m/s), plus `--seed 42` for repeatable runs.
- Optional: save telemetry to CSV: `--output-csv simulation/telemetry.csv` (includes Phase 2 fields when used: `throttle_commanded`, `throttle_applied`, `drag_multiplier`, `disturbance_active`, `f_disturbance_n`, etc.; see `--help`).
- Optional: save plots (needs `pip install -r requirements.txt`): `--plot simulation/phase1_speed.png` (two panels: speed vs time, control error vs time; red vertical lines mark disturbance window when set).
- The script prints periodic lines and a summary: overshoot, settling time, steady-state error (true vs measured when noise is on).

PHASE 2 — Realism and robustness (implemented in `simulation/`)

🎯 Goal:
Make the system behave more like real hardware: noisy sensors, limited actuators, disturbances, rolling resistance.

What is implemented:
- **Sensor noise** (already in Phase 1 path): `--noise-sigma` (m/s), `--seed`.
- **Rolling resistance**: `--c-rr` (dimensionless), with `F_rr = c_rr * m * g` (N), opposing motion when `v > 0`.
- **Disturbance window**: optional `[--disturb-start, --disturb-end)` in seconds; while active, aerodynamic drag is multiplied by `--disturb-drag-mult`, and an extra longitudinal force `--disturb-force-n` (N) can model braking or push.
- **Actuator**: `--throttle-rate-limit` (max change per second), `--throttle-delay-steps` (output lags the rate-limited command).
- **Scenarios** (presets; override any flag by passing it explicitly): `--scenario normal | noisy | disturbance | full`.
- **Telemetry**: extended CSV columns for analysis and later ML; plots include **error vs time** and disturbance markers.

Example experiments:
```bash
# Scenario 1: clean run (Phase-1-like)
python simulation/main.py --target 30 --kp 0.5 --ki 0.1 --kd 0.05 --noise-sigma 0

# Scenario 2: gust / extra drag between 10 s and 15 s
python simulation/main.py --disturb-start 10 --disturb-end 15 --disturb-drag-mult 2 --plot simulation/phase2_disturb.png

# Scenario 3: noisy sensor + rolling + rate-limited throttle
python simulation/main.py --noise-sigma 0.15 --c-rr 0.015 --throttle-rate-limit 0.2 --seed 42 --output-csv simulation/telemetry.csv --plot simulation/phase2.png
```

**Output:**
- Evaluate whether the PID recovers after disturbances, whether it oscillates, and how tuning (`Kp`, `Ki`, `Kd`) interacts with limits and noise.

PHASE 3 — Backend API (Django or FastAPI)

🎯 Goal:
Expose simulation data.

Build API endpoints:
1. Get telemetry
   - `GET /telemetry/`
   - Returns:
     ```json
     {
       "speed": 118.5,
       "target_speed": 120,
       "throttle": 0.72
     }
     ```
2. Update parameters
   - `PUT /control/`
   - Body:
     ```json
     {
       "target_speed": 130,
       "kp": 0.5,
       "ki": 0.1,
       "kd": 0.05
     }
     ```

Architecture:
- Simulation runs in a background thread/process
- API reads shared state

**Output:**
You can control the ECU from outside.

PHASE 4 — Dashboard UI

🎯 Goal:
Visualize and control the system.

Build:
1. Live graph
   - Speed vs time
   - Target vs actual
2. Gauge
   - Throttle %
3. Controls
   - Slider -> target speed
   - Sliders -> `Kp`, `Ki`, `Kd`

Tools:
- Flutter (recommended)
- React (optional)

**Output:**
- Real-time interaction
- "Pit wall" feel

PHASE 5 — Real-Time Communication

🎯 Goal:
Make it feel like a real telemetry system.

Upgrade:
- Use WebSockets (Django Channels or FastAPI websockets) instead of polling
- Stream data continuously

**Output:**
Smooth real-time updates.

PHASE 6 — Data Logging & Analysis

🎯 Goal:
Analyze system performance.

Store:
- `speed`
- `throttle`
- `error`
- `timestamp`

Compute:
1. Overshoot
2. Settling time
3. Steady-state error

**Output:**
- Graphs after each run
- Performance summary

PHASE 7 — Machine Learning Layer (Final Stage)

🎯 Goal:
Add intelligence (not direct control).

Ideas:
1. PID tuning model
   - Input: system behavior
   - Output: optimal `Kp`, `Ki`, `Kd`
2. Drag prediction model
   - Learn drag curve over time
3. Energy optimization (EV)
   - Minimize throttle usage

**Output:**
ML enhances the control system.

PHASE 8 — Advanced Features (Optional)

- Multiple driving modes
- Traction control
- Gear shifting logic
- Multi-car simulation

## Final Deliverable

You should end up with:

- GitHub repo:
  - Clean structure
  - Documented code
- Demo video:
  - Show the dashboard
  - Tune PID live
- README:
  - Explain system architecture
  - Include diagrams

## Timeline (Realistic)
- Phase 1-2: 1-2 weeks
- Phase 3-4: 1-2 weeks
- Phase 5-6: 1 week
- Phase 7+: optional
- Total: 3-5 weeks for a strong version

## Final Advice
If you do only this properly:
- Phase 1 + Phase 4 (with live tuning)
You already have a top-tier project.
Everything else is a bonus.

## Next Step
Let's not just plan.
Say: "start phase 1"
Then I will:
- Give you the exact equations
- Write the Python structure
- Help you build the simulation step-by-step
- Like a real engineering build

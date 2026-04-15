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

PHASE 3 — Backend API (FastAPI, implemented in `backend/main.py`)

🎯 Goal:
Expose live simulation data and retune control from outside the process.

What is implemented:
1. Telemetry endpoint
   - `GET /telemetry/`
   - Returns live values:
     ```json
     {
       "speed": 118.5,
       "target_speed": 120.0,
       "throttle": 0.72
     }
     ```
2. Control endpoint
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
- Simulation loop runs continuously in a background thread (`dt=0.1s`)
- API handlers read/write shared state guarded by a lock
- PID gains and target are applied immediately via `/control/`

Run Phase 3:
```bash
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Quick API checks:
```bash
curl http://127.0.0.1:8000/telemetry/
curl -X PUT http://127.0.0.1:8000/control/ -H "Content-Type: application/json" -d "{\"target_speed\":130,\"kp\":0.5,\"ki\":0.1,\"kd\":0.05}"
```

Start a **new test run** (zero speed, reset PID/actuator state, clear analysis log, restart simulation clock `sim_time_s`):

```bash
curl -X POST http://127.0.0.1:8000/simulation/reset
```

Telemetry JSON includes `sim_time_s` (seconds since last reset) for charting and CSV export still uses wall-clock `timestamp_s` in the analysis log.

PHASE 4 — Dashboard UI (React + Recharts, implemented in `frontend/`)

🎯 Goal:
Visualize telemetry and tune control live from the browser.

What is implemented:
1. Live graph (Recharts)
   - Actual speed vs time
   - Target speed vs time
2. Throttle gauge
   - Circular percentage gauge (`0-100%`)
3. Controls
   - Slider: `target_speed`
   - Sliders: `kp`, `ki`, `kd`
   - Changes are pushed to `PUT /control/` with a short debounce for smooth tuning

Backend integration:
- Polls `GET /telemetry/` every 250 ms
- Reads initial values from `GET /control/`
- CORS enabled in backend to allow frontend dev server access

Run Phase 4:
```bash
# Terminal 1
uvicorn backend.main:app --reload

# Terminal 2
cd frontend
npm install
npm run dev
```

PHASE 5 — Real-Time Communication

🎯 Goal:
Make it feel like a real telemetry system.

Upgrade (implemented):
- FastAPI WebSocket endpoint: `ws://127.0.0.1:8000/ws/telemetry`
- Backend pushes telemetry continuously at simulation cadence (`dt=0.1s`)
- Frontend dashboard consumes the stream directly (no polling loop for telemetry)
- Frontend auto-reconnects if the socket drops and shows connection status (`WS LIVE`, `CONNECTING`, `RECONNECTING`)

Run Phase 5:
```bash
# Terminal 1
uvicorn backend.main:app --reload

# Terminal 2
cd frontend
npm run dev
```

If the terminal shows `No supported WebSocket library detected` or `GET /ws/telemetry ... 404`, the server process is missing WebSocket support. Install extras in the **same** environment you use to run Uvicorn, then restart (stop the process and start again):

```bash
pip install "uvicorn[standard]"
```

**Output:**
Smooth real-time updates with lower request overhead than HTTP polling.

PHASE 6 — Data Logging & Analysis (implemented)

🎯 Goal:
Analyze system performance from the live simulation.

Store (ring buffer, max ~20 minutes at `dt=0.1s`):
- `speed` (m/s), `throttle` (0–1), `error` = `target - speed` (m/s), `timestamp` = seconds **since log start** (or call `POST /analysis/log/reset` to start a new axis)

Compute (see `backend/analysis.py`; metrics use **last target** in the buffer as setpoint reference):
1. Overshoot — max peak above that target
2. Settling time — first time speed stays within tolerance until end of buffer
3. Steady-state error — |mean(last 20% of speeds) − target|

**Output:**
- `GET /analysis/summary` — JSON performance summary
- `GET /analysis/export.csv` — logged columns: `timestamp_s`, `speed_m_s`, `target_m_s`, `throttle`, `error_m_s`
- `GET /analysis/plot.png` — matplotlib PNG (speed + target, throttle)
- `POST /analysis/log/reset` — clear buffer for a fresh run
- Dashboard panel **Phase 6 — Logging & analysis** — reset log, refresh summary, download CSV, embedded plot

PHASE 7 — Machine Learning Layer (Final Stage)

🎯 Goal:
Add intelligence (not direct control).

**PID tuning assistant (classification — in progress):**  
Recommend **which tuning action** to try next (e.g. reduce/increase `Kp` or `Ki`), not a full optimal triple. **Phase A (design)** is documented in:

- `docs/tuning_classifier_phase_a.md` — class labels, rule order, default thresholds, feature list.

**Phase B (dataset generation):** from repo root:

```bash
python ml/generate_tuning_dataset.py --output ml/data/tuning_runs.csv --n 2000 --seed 42
# Smaller grid (caps size): 
# python ml/generate_tuning_dataset.py --mode grid --max-runs 1500 --output ml/data/tuning_runs.csv --seed 42
```

- Labels: `backend/tuning_labels.py` (`label_run`) matches `docs/tuning_classifier_phase_a.md`.
- Features/metrics: `backend/analysis.py` (`analyze_series`), same as Phase 6.
- Script prints **class balance**; if one class is empty or tiny, widen sampling ranges (`--kp-min` / `--target-max`) or nudge thresholds in `backend/tuning_labels.py` / the doc. Example: **`increase_kp` at 0%** usually means almost every run **settles before** the “slow” threshold (`SETTLE_SLOW_S`, default **12s**); raising it toward your horizon (e.g. 18s) shrinks `increase_kp` again.

**Phase C (train & evaluate):** from repo root (requires `ml/data/tuning_runs.csv`):

```bash
pip install -r requirements.txt
python ml/train_tuning_classifier.py --data ml/data/tuning_runs.csv --out-dir ml/artifacts
```

**Notebook:** interactive step-through (same training + plots) — open `ml/tuning_walkthrough.ipynb` in Jupyter/VS Code; run from repo root so `ROOT` resolves. Optional: `%pip install pandas matplotlib` in the first code cell if needed.

- **80/20 split**, stratified by label when possible.
- **Baselines:** majority class (`DummyClassifier`); **LogisticRegression** + `StandardScaler` (balanced class weights).
- **Main model:** **RandomForestClassifier** (300 trees, balanced, `joblib` bundle with feature names).
- **Outputs:** `ml/artifacts/tuning_classifier.joblib`, `label_classes.json`, `tuning_logistic.joblib`, `metrics.json`, `feature_importances_rf.txt`, `logistic_coefficients.txt`.
- **Sanity:** rule-replay check vs `label_run` (may be &lt; 1.0 if CSV rounding moves borderline cases).

**Phase D (ship with app):** commit `ml/artifacts/tuning_classifier.joblib` plus `label_classes.json` (labels + feature names for operators / UI); `scikit-learn` and `joblib` are listed in `requirements.txt`.

**Phase E (API):** `POST /tuning/suggest` and `POST /tuning/classify` (same handler). Default body uses the Phase 6 log + current gains; set `"from_log": false` and pass gains + metrics to classify explicit features. Response: `action`, `probabilities`, `rationale`. If the artifact is missing or inference fails, the server falls back to Phase A rules (empty `probabilities`). Empty log with `from_log` true returns **503** with a clear message.

Next steps: optional dashboard button calling `POST /tuning/suggest`.

Other ideas (optional):
2. Drag prediction — learn drag curve over time  
3. Energy optimization (EV) — minimize throttle usage

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

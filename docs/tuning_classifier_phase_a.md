# Phase A — Tuning classifier (design lock)

This document fixes **what you are building** before you generate data (Phase B) or train a model (Phase C).

---

## 1. Problem statement

**Classifier input:** one closed-loop run, summarized by metrics + current PID gains + setpoint.  
**Classifier output:** **one recommended next tuning action** (not a full optimal triple).

The model learns to mimic **rule-based labels** first; later you can refine rules or add data.

---

## 2. Class labels (v1 — five classes)

| Label | Meaning (human) |
|-------|------------------|
| `no_change` | Performance is already acceptable for this run. |
| `reduce_kp` | Response is too aggressive / too much overshoot → ease proportional gain. |
| `increase_kp` | Response is too slow / long settling → raise proportional gain. |
| `increase_ki` | Persistent offset (steady-state error) dominates → raise integral gain. |
| `reduce_ki` | Integral is likely hurting (e.g. extra overshoot / oscillation with offset mostly gone) → lower integral gain. |

**Deferred (v2):** `increase_kd` / `reduce_kd` once you add a simple **oscillation proxy** (e.g. sign changes of error in the last segment of the run). Not required for Phase A.

**String IDs:** use exactly these names in CSV and in code so labels stay stable.

---

## 3. Metrics you already have

Aligned with `backend/analysis.py` → `analyze_series()`:

| Metric | Meaning |
|--------|---------|
| `target_ref_m_s` | Last target in the series (setpoint for metrics). |
| `overshoot_m_s` | `max(0, max(speed) − target_ref)`. |
| `settling_time_s` | First time after which speed stays within **tolerance** until end; **`None`** if never settled in the window. |
| `tolerance_m_s` | `max(0.5, 0.02 × |target_ref|)` (same as analysis). |
| `steady_state_error_m_s` | `|mean(last 20% of speeds) − target_ref|`. |
| `mean_abs_error_m_s` | Mean of `|target − speed|` over the run. |
| `duration_s` | Time span of the series. |
| `sample_count` | Number of samples. |

---

## 4. Rule-based labeling (for training data in Phase B)

**Inputs to the rules:** the metrics above, plus **`kp`, `ki`, `kd`** (for edge cases only; primary signal is behavior).

**Evaluation order:** apply rules **top to bottom**; **first match wins**. That makes debugging and interviews easy.

### 4.1 Threshold constants (starting defaults — calibrate in Phase B)

These are **starting points** when `target_ref` is on the order of **10–40 m/s** and run length is **~20–40 s**. Adjust after you plot label distributions.

| Constant | Default | Role |
|----------|---------|------|
| `DURATION_MIN_S` | `8.0` | Ignore “too short” runs for sluggish/offset rules. |
| `OVERSHOOT_HIGH` | `max(1.5, 1.5 × tolerance_m_s)` | Strong overshoot → `reduce_kp`. |
| `OVERSHOOT_LOW` | `max(0.3, 0.35 × tolerance_m_s)` | “Mild” overshoot band. |
| `SETTLE_SLOW_S` | `18.0` | If settled slower than this → sluggish candidate. |
| `SS_ERR_HIGH` | `max(0.6, 0.025 × |target_ref|)` | Clear offset → `increase_ki`. |
| `SS_ERR_LOW` | `max(0.25, 0.01 × |target_ref|)` | Offset mostly removed. |

### 4.2 Rules (v1)

1. **`no_change`** — all of:
   - `overshoot_m_s ≤ OVERSHOOT_LOW`
   - `steady_state_error_m_s ≤ SS_ERR_LOW`
   - `settling_time_s` is not `None` **and** `settling_time_s ≤ SETTLE_SLOW_S`
   - `duration_s ≥ DURATION_MIN_S`

2. **`reduce_kp`** —  
   - `overshoot_m_s > OVERSHOOT_HIGH`

3. **`increase_kp`** —  
   - `overshoot_m_s ≤ OVERSHOOT_LOW` **and**
   - (`settling_time_s is None` **or** `settling_time_s > SETTLE_SLOW_S`) **and**
   - `duration_s ≥ DURATION_MIN_S`

4. **`increase_ki`** —  
   - `steady_state_error_m_s > SS_ERR_HIGH` **and**
   - `overshoot_m_s ≤ OVERSHOOT_HIGH` (avoid pushing Ki when overshoot already screams “reduce Kp”)

5. **`reduce_ki`** —  
   - `overshoot_m_s > OVERSHOOT_LOW` **and**
   - `steady_state_error_m_s ≤ SS_ERR_LOW` (overshoot present but offset small → Ki may be contributing)

If nothing matches (rare), default to **`no_change`** or **`increase_kp`** depending on whether speed never approached target — **pick one policy** in Phase B and log it.

---

## 5. Feature vector for the ML model (same rows as labels)

**Minimum set (train + inference):**

| Feature | Source |
|---------|--------|
| `overshoot_m_s` | `analyze_series` |
| `settling_time_s` | use **sentinel** `-1.0` if `None` (document this) |
| `steady_state_error_m_s` | `analyze_series` |
| `mean_abs_error_m_s` | `analyze_series` |
| `duration_s` | `analyze_series` |
| `sample_count` | `analyze_series` |
| `tolerance_m_s` | `analyze_series` |
| `target_ref_m_s` | `analyze_series` |
| `kp`, `ki`, `kd` | Current gains for that run |

**Optional engineered features (Phase C+):**

- `overshoot_ratio` = `overshoot_m_s / max(tolerance_m_s, 1e-6)`
- `ss_err_ratio` = `steady_state_error_m_s / max(tolerance_m_s, 1e-6)`

---

## 6. What you do next (Phase B preview)

1. Implement these rules in a **pure function** `label_run(metrics, kp, ki, kd) -> str`.
2. Sweep simulations → CSV: **features + `label`**.
3. Check **class counts**; nudge thresholds if one class vanishes or dominates.

---

## 7. Interview one-liner

> “We cast PID help as **multiclass classification**: the model recommends **which gain to nudge next**, trained on **rule-labeled** simulation runs, using the same **overshoot / settling / steady-state** metrics as our dashboard.”

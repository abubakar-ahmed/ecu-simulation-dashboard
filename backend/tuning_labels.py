"""
Rule-based labels for PID tuning classifier (Phase A spec: docs/tuning_classifier_phase_a.md).
"""

from __future__ import annotations

from typing import Any, Mapping

# Phase A defaults (see docs/tuning_classifier_phase_a.md)
DURATION_MIN_S = 8.0
# "Sluggish" if never settled, or first time in-band is after this many seconds.
# 18s was too high for dt=0.1, steps=300 (30s runs): most loops settle before 18s, so
# `increase_kp` never fired. 12s matches "slow vs acceptable" better for this plant.
SETTLE_SLOW_S = 12.0

CLASS_NAMES = (
    "no_change",
    "reduce_kp",
    "increase_kp",
    "increase_ki",
    "reduce_ki",
)


def _overshoot_high(tolerance_m_s: float) -> float:
    return max(1.5, 1.5 * tolerance_m_s)


def _overshoot_low(tolerance_m_s: float) -> float:
    return max(0.3, 0.35 * tolerance_m_s)


def _ss_err_high(target_ref_m_s: float) -> float:
    return max(0.6, 0.025 * abs(target_ref_m_s))


def _ss_err_low(target_ref_m_s: float) -> float:
    return max(0.25, 0.01 * abs(target_ref_m_s))


def label_run(metrics: Mapping[str, Any], kp: float, ki: float, kd: float) -> str:
    """
    Assign one label from metrics (output of analyze_series) and current PID gains.
    Rules are evaluated in order; first match wins. kp, ki, kd reserved for future rules.

    If metrics are empty or invalid, returns 'no_change'.
    """
    _ = (kp, ki, kd)  # v1 rules use behavior only; gains kept for API stability

    n = metrics.get("sample_count") or 0
    if n == 0:
        return "no_change"

    target_ref = float(metrics["target_ref_m_s"])
    overshoot = float(metrics["overshoot_m_s"])
    ss_err = float(metrics["steady_state_error_m_s"])
    duration_s = float(metrics["duration_s"])
    tol = float(metrics["tolerance_m_s"])

    settling = metrics.get("settling_time_s")
    settling_s: float | None = float(settling) if settling is not None else None

    oh_high = _overshoot_high(tol)
    oh_low = _overshoot_low(tol)
    ss_hi = _ss_err_high(target_ref)
    ss_lo = _ss_err_low(target_ref)

    # 1. no_change
    if (
        overshoot <= oh_low
        and ss_err <= ss_lo
        and settling_s is not None
        and settling_s <= SETTLE_SLOW_S
        and duration_s >= DURATION_MIN_S
    ):
        return "no_change"

    # 2. reduce_kp
    if overshoot > oh_high:
        return "reduce_kp"

    # 3. increase_kp
    if (
        overshoot <= oh_low
        and (settling_s is None or settling_s > SETTLE_SLOW_S)
        and duration_s >= DURATION_MIN_S
    ):
        return "increase_kp"

    # 4. increase_ki
    if overshoot <= oh_high and ss_err > ss_hi:
        return "increase_ki"

    # 5. reduce_ki
    if overshoot > oh_low and ss_err <= ss_lo:
        return "reduce_ki"

    # Fallback (Phase A): conservative
    return "no_change"

"""
Phase E: load tuning classifier + build feature rows matching `ml/train_tuning_classifier.FEATURE_COLS`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np

from backend.tuning_labels import label_run

from ml.train_tuning_classifier import FEATURE_COLS

ARTIFACT_PATH = Path(__file__).resolve().parents[1] / "ml" / "artifacts" / "tuning_classifier.joblib"


@lru_cache(maxsize=1)
def load_classifier_bundle() -> dict[str, Any] | None:
    if not ARTIFACT_PATH.is_file():
        return None
    return joblib.load(ARTIFACT_PATH)


def settling_value_for_ml(metrics: Mapping[str, Any]) -> float:
    s = metrics.get("settling_time_s")
    if s is None:
        return -1.0
    return float(s)


def build_feature_vector(
    metrics: Mapping[str, Any],
    *,
    kp: float,
    ki: float,
    kd: float,
    target_speed_m_s: float,
    dt_s: float,
    steps: int,
    noise_sigma: float,
) -> np.ndarray:
    tol = float(metrics["tolerance_m_s"])
    oss = float(metrics["overshoot_m_s"])
    sse = float(metrics["steady_state_error_m_s"])
    overshoot_ratio = oss / max(tol, 1e-6)
    ss_err_ratio = sse / max(tol, 1e-6)
    st_ml = settling_value_for_ml(metrics)
    row: dict[str, float] = {
        "kp": kp,
        "ki": ki,
        "kd": kd,
        "target_speed_m_s": target_speed_m_s,
        "dt_s": dt_s,
        "steps": float(steps),
        "noise_sigma": noise_sigma,
        "overshoot_m_s": oss,
        "settling_time_s": st_ml,
        "steady_state_error_m_s": sse,
        "mean_abs_error_m_s": float(metrics["mean_abs_error_m_s"]),
        "duration_s": float(metrics["duration_s"]),
        "sample_count": float(metrics["sample_count"]),
        "tolerance_m_s": tol,
        "target_ref_m_s": float(metrics["target_ref_m_s"]),
        "overshoot_ratio": overshoot_ratio,
        "ss_err_ratio": ss_err_ratio,
    }
    X = np.zeros((1, len(FEATURE_COLS)), dtype=np.float64)
    for j, col in enumerate(FEATURE_COLS):
        X[0, j] = row[col]
    return X


def _rationale_from_model(
    bundle: dict[str, Any],
    X: np.ndarray,
    predicted_class: str,
) -> str:
    rf = bundle["model"]
    names: list[str] = list(bundle["feature_names"])
    idx = int(np.argmax(rf.feature_importances_))
    fname = names[idx]
    val = float(X[0, idx])
    return (
        f"The model predicts `{predicted_class}`; among training features, `{fname}` has the highest "
        f"Random Forest importance, and your current value there is {val:.4g}."
    )


def suggest(
    *,
    metrics: Mapping[str, Any],
    kp: float,
    ki: float,
    kd: float,
    target_speed_m_s: float,
    dt_s: float,
    steps: int,
    noise_sigma: float,
) -> dict[str, Any]:
    """
    Returns keys: action, probabilities, rationale.
    Falls back to rule-based action if the bundle is missing or prediction fails.
    """
    n = int(metrics.get("sample_count") or 0)
    if n <= 0:
        raise ValueError("metrics have no samples")

    rule_action = label_run(metrics, kp, ki, kd)
    bundle = load_classifier_bundle()
    if bundle is None:
        return {
            "action": rule_action,
            "probabilities": {},
            "rationale": (
                f"No classifier found at `{ARTIFACT_PATH}`; using Phase A rules → `{rule_action}`."
            ),
        }

    try:
        X = build_feature_vector(
            metrics,
            kp=kp,
            ki=ki,
            kd=kd,
            target_speed_m_s=target_speed_m_s,
            dt_s=dt_s,
            steps=steps,
            noise_sigma=noise_sigma,
        )
        rf = bundle["model"]
        pred = str(rf.predict(X)[0])
        probs = rf.predict_proba(X)[0]
        classes = [str(c) for c in rf.classes_]
        prob_dict = {c: float(p) for c, p in zip(classes, probs)}
        rationale = _rationale_from_model(bundle, X, pred)
        return {
            "action": pred,
            "probabilities": prob_dict,
            "rationale": rationale,
        }
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "action": rule_action,
            "probabilities": {},
            "rationale": (
                f"Classifier inference failed ({exc!s}); using Phase A rules → `{rule_action}`."
            ),
        }

"""
Phase C: train / evaluate PID tuning classifiers; save joblib artifacts.

Run from repository root (after Phase B CSV exists):
  python ml/train_tuning_classifier.py --data ml/data/tuning_runs.csv --out-dir ml/artifacts
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.tuning_labels import label_run

__all__ = [
    "FEATURE_COLS",
    "load_dataset",
    "rule_replay_accuracy",
    "row_dict_to_metrics",
    "train_and_save",
]

FEATURE_COLS = [
    "kp",
    "ki",
    "kd",
    "target_speed_m_s",
    "dt_s",
    "steps",
    "noise_sigma",
    "overshoot_m_s",
    "settling_time_s",
    "steady_state_error_m_s",
    "mean_abs_error_m_s",
    "duration_s",
    "sample_count",
    "tolerance_m_s",
    "target_ref_m_s",
    "overshoot_ratio",
    "ss_err_ratio",
]


def _float_cell(x: str) -> float:
    return float(x.strip())


def load_dataset(path: Path) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(dict(row))

    X = np.zeros((len(rows), len(FEATURE_COLS)), dtype=np.float64)
    y: list[str] = []
    for i, row in enumerate(rows):
        for j, col in enumerate(FEATURE_COLS):
            X[i, j] = _float_cell(row[col])
        y.append(row["label"].strip())
    return X, np.array(y, dtype=object), rows


def row_dict_to_metrics(row: dict[str, str]) -> dict[str, Any]:
    st_raw = _float_cell(row["settling_time_s"])
    settling: float | None = None if st_raw < 0 else st_raw
    return {
        "sample_count": int(_float_cell(row["sample_count"])),
        "target_ref_m_s": _float_cell(row["target_ref_m_s"]),
        "overshoot_m_s": _float_cell(row["overshoot_m_s"]),
        "steady_state_error_m_s": _float_cell(row["steady_state_error_m_s"]),
        "mean_abs_error_m_s": _float_cell(row["mean_abs_error_m_s"]),
        "duration_s": _float_cell(row["duration_s"]),
        "tolerance_m_s": _float_cell(row["tolerance_m_s"]),
        "settling_time_s": settling,
    }


def rule_replay_accuracy(rows: list[dict[str, Any]]) -> float:
    """Sanity: labels in CSV must match label_run(...) on reconstructed metrics."""
    ok = 0
    for row in rows:
        m = row_dict_to_metrics(row)
        kp = _float_cell(row["kp"])
        ki = _float_cell(row["ki"])
        kd = _float_cell(row["kd"])
        pred = label_run(m, kp, ki, kd)
        if pred == row["label"].strip():
            ok += 1
    return ok / len(rows) if rows else 0.0


def train_and_save(
    data_path: Path,
    out_dir: Path,
    *,
    test_size: float = 0.2,
    seed: int = 42,
    save_artifacts: bool = True,
) -> dict[str, Any]:
    """
    Train baselines + RF, optionally write joblib/metrics/text files.
    Returns a dict with models, predictions, and metrics (for notebooks / API).
    """
    if not data_path.is_file():
        raise FileNotFoundError(f"Dataset not found: {data_path}")

    X, y, rows = load_dataset(data_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    replay = rule_replay_accuracy(rows)

    stratify = y if len(np.unique(y)) > 1 else None
    try:
        X_train, X_val, y_train, y_val = train_test_split(
            X,
            y,
            test_size=test_size,
            random_state=seed,
            stratify=stratify,
        )
    except ValueError:
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=test_size, random_state=seed, stratify=None
        )

    dummy = DummyClassifier(strategy="most_frequent")
    dummy.fit(X_train, y_train)
    dummy_acc = accuracy_score(y_val, dummy.predict(X_val))

    log_pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=2000,
                    class_weight="balanced",
                    random_state=seed,
                ),
            ),
        ]
    )
    log_pipe.fit(X_train, y_train)
    log_pred = log_pipe.predict(X_val)
    log_acc = accuracy_score(y_val, log_pred)

    rf = RandomForestClassifier(
        n_estimators=300,
        random_state=seed,
        class_weight="balanced",
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)
    rf_pred = rf.predict(X_val)
    rf_acc = accuracy_score(y_val, rf_pred)

    labels_sorted = sorted(np.unique(y).tolist())

    report_rf = classification_report(
        y_val, rf_pred, labels=labels_sorted, output_dict=True, zero_division=0
    )
    cm_rf = confusion_matrix(y_val, rf_pred, labels=labels_sorted)

    metrics = {
        "n_total": len(rows),
        "n_train": int(len(y_train)),
        "n_val": int(len(y_val)),
        "test_size": test_size,
        "seed": seed,
        "rule_replay_accuracy_full": replay,
        "baseline_majority_val_accuracy": float(dummy_acc),
        "logistic_val_accuracy": float(log_acc),
        "random_forest_val_accuracy": float(rf_acc),
        "labels": labels_sorted,
        "classification_report_val_rf": report_rf,
        "confusion_matrix_val_rf": cm_rf.tolist(),
        "feature_names": FEATURE_COLS,
    }

    if save_artifacts:
        metrics_path = out_dir / "metrics.json"
        with metrics_path.open("w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        rf_bundle = {
            "kind": "random_forest",
            "model": rf,
            "feature_names": FEATURE_COLS,
            "classes": labels_sorted,
        }
        joblib.dump(rf_bundle, out_dir / "tuning_classifier.joblib")
        label_meta = {
            "labels": labels_sorted,
            "feature_names": FEATURE_COLS,
            "model_kind": "random_forest",
        }
        with (out_dir / "label_classes.json").open("w", encoding="utf-8") as f:
            json.dump(label_meta, f, indent=2)
        joblib.dump(
            {
                "kind": "logistic_regression",
                "model": log_pipe,
                "feature_names": FEATURE_COLS,
                "classes": labels_sorted,
            },
            out_dir / "tuning_logistic.joblib",
        )

        importances = rf.feature_importances_
        order = np.argsort(-importances)
        with (out_dir / "feature_importances_rf.txt").open("w", encoding="utf-8") as f:
            f.write("Random Forest feature importances (val model, full train fit)\n\n")
            for i in order:
                f.write(f"{FEATURE_COLS[i]:28s}  {importances[i]:.6f}\n")

        log_clf = log_pipe.named_steps["clf"]
        if hasattr(log_clf, "coef_"):
            with (out_dir / "logistic_coefficients.txt").open("w", encoding="utf-8") as f:
                f.write("Logistic regression coefficients (one-vs-rest layout for multinomial)\n")
                f.write(f"classes_: {getattr(log_clf, 'classes_', None)}\n\n")
                for c_idx, cls in enumerate(log_clf.classes_):
                    f.write(f"\n--- class {cls} ---\n")
                    for j, name in enumerate(FEATURE_COLS):
                        f.write(f"  {name:28s}  {log_clf.coef_[c_idx, j]:12.6f}\n")

    return {
        "metrics": metrics,
        "X_train": X_train,
        "X_val": X_val,
        "y_train": y_train,
        "y_val": y_val,
        "dummy": dummy,
        "log_pipe": log_pipe,
        "rf": rf,
        "rf_pred": rf_pred,
        "log_pred": log_pred,
        "labels_sorted": labels_sorted,
        "confusion_matrix": cm_rf,
        "feature_importances": rf.feature_importances_,
        "rows": rows,
        "rule_replay_accuracy": replay,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("ml/data/tuning_runs.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("ml/artifacts"))
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    result = train_and_save(
        args.data,
        args.out_dir,
        test_size=args.test_size,
        seed=args.seed,
        save_artifacts=True,
    )
    m = result["metrics"]
    replay = result["rule_replay_accuracy"]
    print(
        f"Rule replay accuracy (full dataset): {replay:.4f}  "
        "(~1.0; if lower, CSV rounding vs full-precision metrics in Phase B can flip borderline labels)"
    )
    print("\n=== Validation accuracy ===")
    print(f"  Majority baseline:  {m['baseline_majority_val_accuracy']:.4f}")
    print(f"  Logistic regression: {m['logistic_val_accuracy']:.4f}")
    print(f"  Random Forest:       {m['random_forest_val_accuracy']:.4f}")
    print(f"\nArtifacts: {args.out_dir}")
    print("  - tuning_classifier.joblib, label_classes.json, tuning_logistic.joblib, metrics.json")
    print("  - feature_importances_rf.txt, logistic_coefficients.txt")
    print("\nConfusion matrix (rows=true, cols=pred), labels:", m["labels"])
    print(np.array(result["confusion_matrix"]))


if __name__ == "__main__":
    main()

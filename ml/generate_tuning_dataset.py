"""
Phase B: generate labeled CSV for PID tuning classifier (offline).

Run from repository root:
  python ml/generate_tuning_dataset.py --output ml/data/tuning_runs.csv --n 500 --seed 42

Requires: same environment as simulation (see requirements.txt).
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from collections import Counter
from pathlib import Path

# Repository root on sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.analysis import analyze_series
from backend.tuning_labels import label_run
from simulation.main import run_simulation


def _step_range(start: float, step: float, end_inclusive: float) -> list[float]:
    out: list[float] = []
    t = start
    while t <= end_inclusive + 1e-9:
        out.append(round(t, 6))
        t += step
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate rule-labeled tuning dataset CSV")
    parser.add_argument("--output", type=Path, default=Path("ml/data/tuning_runs.csv"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--n",
        type=int,
        default=500,
        help="Number of runs in random mode (ignored for grid unless combined with --max-runs)",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=None,
        help="Cap total runs after building the list (subsample/shuffle). Useful for huge grids.",
    )
    parser.add_argument(
        "--mode",
        choices=("random", "grid"),
        default="random",
        help="random: sample (kp,ki,kd,target) uniformly; grid: full product of small lists",
    )
    parser.add_argument("--dt", type=float, default=0.1)
    parser.add_argument("--steps", type=int, default=300, help="Simulation steps (duration = steps*dt)")
    parser.add_argument("--noise-sigma", type=float, default=0.0)
    parser.add_argument("--kp-min", type=float, default=0.1)
    parser.add_argument("--kp-max", type=float, default=1.2)
    parser.add_argument("--ki-min", type=float, default=0.0)
    parser.add_argument("--ki-max", type=float, default=0.35)
    parser.add_argument("--kd-min", type=float, default=0.0)
    parser.add_argument("--kd-max", type=float, default=0.2)
    parser.add_argument("--target-min", type=float, default=15.0)
    parser.add_argument("--target-max", type=float, default=45.0)
    args = parser.parse_args()

    rng = random.Random(args.seed)

    # Fixed plant / scenario (clean runs for v1 dataset)
    mass_kg = 1200.0
    max_force_n = 4000.0
    drag_coeff = 0.3
    c_rr = 0.0
    g_m_s2 = 9.81
    disturb_start = None
    disturb_end = None
    disturb_drag_mult = 2.0
    disturb_force_n = 0.0
    throttle_rate = None
    throttle_delay = 0

    runs: list[tuple[float, float, float, float]] = []
    if args.mode == "random":
        for _ in range(args.n):
            kp = rng.uniform(args.kp_min, args.kp_max)
            ki = rng.uniform(args.ki_min, args.ki_max)
            kd = rng.uniform(args.kd_min, args.kd_max)
            target = rng.uniform(args.target_min, args.target_max)
            runs.append((kp, ki, kd, target))
    else:
        kps = _step_range(0.2, 0.2, 1.0)
        kis = _step_range(0.0, 0.05, 0.25)
        kds = _step_range(0.0, 0.02, 0.12)
        targets = _step_range(20.0, 5.0, 40.0)
        for kp in kps:
            for ki in kis:
                for kd in kds:
                    for target in targets:
                        runs.append((kp, ki, kd, target))
        rng.shuffle(runs)

    if args.max_runs is not None and len(runs) > args.max_runs:
        rng.shuffle(runs)
        runs = runs[: args.max_runs]

    args.output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "run_id",
        "seed",
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
        "label",
    ]

    labels: list[str] = []
    run_id = 0
    sim_rng = random.Random(args.seed)

    with args.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()

        for kp, ki, kd, target in runs:
            run_id += 1
            (
                times_s,
                speeds_true,
                _meas,
                throttles_applied,
                _err_c,
                _tcmd,
                _dm,
                _df,
                _fd,
            ) = run_simulation(
                kp=kp,
                ki=ki,
                kd=kd,
                target_speed_m_s=target,
                dt_s=args.dt,
                steps=args.steps,
                mass_kg=mass_kg,
                max_force_n=max_force_n,
                drag_coeff=drag_coeff,
                noise_sigma_m_s=args.noise_sigma,
                rng=sim_rng,
                c_rr=c_rr,
                g_m_s2=g_m_s2,
                disturb_start_s=disturb_start,
                disturb_end_s=disturb_end,
                disturb_drag_mult=disturb_drag_mult,
                disturb_force_n=disturb_force_n,
                throttle_rate_limit_per_s=throttle_rate,
                throttle_delay_steps=throttle_delay,
                verbose_every=0,
            )

            targets_m_s = [target] * len(times_s)
            metrics = analyze_series(
                times_s=times_s,
                speeds_m_s=speeds_true,
                targets_m_s=targets_m_s,
                throttles=throttles_applied,
            )

            tol = float(metrics["tolerance_m_s"] or 0.5)
            oss = float(metrics["overshoot_m_s"] or 0.0)
            sse = float(metrics["steady_state_error_m_s"] or 0.0)
            overshoot_ratio = oss / max(tol, 1e-6)
            ss_err_ratio = sse / max(tol, 1e-6)

            st = metrics.get("settling_time_s")
            settling_out = "-1.0" if st is None else f"{float(st):.6f}"

            label = label_run(metrics, kp, ki, kd)
            labels.append(label)

            w.writerow(
                {
                    "run_id": run_id,
                    "seed": args.seed,
                    "kp": f"{kp:.6f}",
                    "ki": f"{ki:.6f}",
                    "kd": f"{kd:.6f}",
                    "target_speed_m_s": f"{target:.6f}",
                    "dt_s": f"{args.dt:.6f}",
                    "steps": args.steps,
                    "noise_sigma": f"{args.noise_sigma:.6f}",
                    "overshoot_m_s": f"{oss:.6f}",
                    "settling_time_s": settling_out,
                    "steady_state_error_m_s": f"{sse:.6f}",
                    "mean_abs_error_m_s": f"{float(metrics['mean_abs_error_m_s']):.6f}",
                    "duration_s": f"{float(metrics['duration_s']):.6f}",
                    "sample_count": metrics["sample_count"],
                    "tolerance_m_s": f"{tol:.6f}",
                    "target_ref_m_s": f"{float(metrics['target_ref_m_s']):.6f}",
                    "overshoot_ratio": f"{overshoot_ratio:.6f}",
                    "ss_err_ratio": f"{ss_err_ratio:.6f}",
                    "label": label,
                }
            )

    counts = Counter(labels)
    print(f"Wrote {len(labels)} rows to {args.output}")
    print("Class balance:")
    for name in ("no_change", "reduce_kp", "increase_kp", "increase_ki", "reduce_ki"):
        c = counts.get(name, 0)
        pct = 100.0 * c / len(labels) if labels else 0.0
        print(f"  {name}: {c} ({pct:.1f}%)")


if __name__ == "__main__":
    main()

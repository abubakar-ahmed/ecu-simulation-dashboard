from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path
from statistics import mean
from typing import List, Optional, Sequence, Tuple

try:
    # Preferred when imported as part of the `simulation` namespace.
    from simulation.pid import PID
    from simulation.vehicle import clamp, update_vehicle
except ImportError:  # pragma: no cover
    # Works when running directly: `python simulation/main.py`
    from pid import PID
    from vehicle import clamp, update_vehicle


def compute_settling_time(
    speeds_m_s: Sequence[float],
    times_s: Sequence[float],
    target_m_s: float,
    *,
    tolerance_m_s: float,
) -> Optional[float]:
    """
    First time (s) after which true speed stays within tolerance_m_s of target for the rest of the run.
    `times_s[k]` must be the timestamp for `speeds_m_s[k]` (here: end-of-step times).
    """
    n = len(speeds_m_s)
    for i in range(n):
        if all(abs(s - target_m_s) <= tolerance_m_s for s in speeds_m_s[i:]):
            return float(times_s[i])
    return None


def run_simulation(
    *,
    kp: float,
    ki: float,
    kd: float,
    target_speed_m_s: float,
    dt_s: float,
    steps: int,
    mass_kg: float,
    max_force_n: float,
    drag_coeff: float,
    noise_sigma_m_s: float,
    rng: random.Random,
    verbose_every: int = 10,
) -> Tuple[
    List[float],
    List[float],
    List[float],
    List[float],
    List[float],
    List[float],
]:
    """
    Closed loop: ECU sees *measured* speed (true + optional sensor noise); plant integrates *true* speed.

    Units:
      - speed_m_s, target_speed_m_s: m/s
      - dt_s: s
      - noise_sigma_m_s: m/s (std dev of additive Gaussian noise on measured speed)
    """
    pid = PID(kp=kp, ki=ki, kd=kd)
    speed_true_m_s = 0.0

    times_s: List[float] = []
    speeds_true_m_s: List[float] = []
    speeds_measured_m_s: List[float] = []
    throttles: List[float] = []
    errors_control: List[float] = []

    for step in range(steps):
        # State at start of this step (ground truth).
        speed_true_before_m_s = speed_true_m_s
        # Sensor sees true speed plus noise (ECU does not see ground truth directly).
        if noise_sigma_m_s > 0.0:
            speed_measured_m_s = speed_true_before_m_s + rng.gauss(0.0, noise_sigma_m_s)
        else:
            speed_measured_m_s = speed_true_before_m_s

        throttle_cmd = pid.compute(
            target_speed_m_s,
            speed_measured_m_s,
            dt_s,
            u_min=0.0,
            u_max=1.0,
        )
        throttle = clamp(throttle_cmd, 0.0, 1.0)

        speed_true_after_m_s = update_vehicle(
            speed_true_before_m_s,
            throttle,
            dt_s,
            mass_kg=mass_kg,
            max_force_n=max_force_n,
            drag_coeff=drag_coeff,
        )
        speed_true_m_s = speed_true_after_m_s

        error_control = target_speed_m_s - speed_measured_m_s
        # Sample time at end of this integration step.
        t_end_s = (step + 1) * dt_s

        times_s.append(t_end_s)
        speeds_true_m_s.append(speed_true_after_m_s)
        speeds_measured_m_s.append(speed_measured_m_s)
        throttles.append(throttle)
        errors_control.append(error_control)

        if verbose_every > 0 and step % verbose_every == 0:
            print(
                f"t={t_end_s:6.2f}s | v_true={speed_true_after_m_s:7.2f} m/s | "
                f"v_meas={speed_measured_m_s:7.2f} m/s | "
                f"throttle={throttle:5.2f} | err={error_control:7.2f}"
            )

    return times_s, speeds_true_m_s, speeds_measured_m_s, throttles, errors_control


def write_telemetry_csv(
    path: Path,
    *,
    times_s: Sequence[float],
    speeds_true_m_s: Sequence[float],
    speeds_measured_m_s: Sequence[float],
    throttles: Sequence[float],
    errors_control: Sequence[float],
    target_m_s: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "time_s",
                "speed_true_m_s",
                "speed_measured_m_s",
                "target_m_s",
                "throttle",
                "error_control",
            ]
        )
        for i in range(len(times_s)):
            w.writerow(
                [
                    f"{times_s[i]:.6f}",
                    f"{speeds_true_m_s[i]:.6f}",
                    f"{speeds_measured_m_s[i]:.6f}",
                    f"{target_m_s:.6f}",
                    f"{throttles[i]:.6f}",
                    f"{errors_control[i]:.6f}",
                ]
            )


def plot_run(
    out_path: Path,
    *,
    times_s: Sequence[float],
    speeds_true_m_s: Sequence[float],
    speeds_measured_m_s: Sequence[float],
    target_m_s: float,
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Plotting requires matplotlib. Install with: pip install matplotlib"
        ) from e

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(times_s, speeds_true_m_s, label="Speed true (m/s)", color="C0", linewidth=1.5)
    ax.plot(
        times_s,
        speeds_measured_m_s,
        label="Speed measured (m/s)",
        color="C1",
        alpha=0.75,
        linewidth=1.0,
    )
    ax.axhline(target_m_s, color="k", linestyle="--", linewidth=1.0, label="Target (m/s)")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Speed (m/s)")
    ax.set_title("Phase 1: speed vs time (target vs actual)")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def summarize(
    speeds_true_m_s: List[float],
    speeds_measured_m_s: List[float],
    throttles: List[float],
    times_s: Sequence[float],
    *,
    target_speed_m_s: float,
    noise_sigma_m_s: float,
) -> None:
    final_true = speeds_true_m_s[-1]
    final_meas = speeds_measured_m_s[-1]
    max_true = max(speeds_true_m_s)
    overshoot = max(0.0, max_true - target_speed_m_s)

    tolerance_m_s = max(0.5, 0.02 * target_speed_m_s)  # 0.5 m/s or 2%
    settling_time_s = compute_settling_time(
        speeds_true_m_s,
        times_s,
        target_speed_m_s,
        tolerance_m_s=tolerance_m_s,
    )

    tail = max(1, len(speeds_true_m_s) // 5)
    steady_state_error_true = abs(mean(speeds_true_m_s[-tail:]) - target_speed_m_s)
    steady_state_error_meas = abs(mean(speeds_measured_m_s[-tail:]) - target_speed_m_s)

    print("\n=== Phase 1 Summary ===")
    print(f"Target speed        : {target_speed_m_s:.2f} m/s")
    if noise_sigma_m_s > 0.0:
        print(f"Sensor noise (sigma): {noise_sigma_m_s:.3f} m/s (Gaussian on feedback)")
    print(f"Final speed (true)  : {final_true:.2f} m/s")
    print(f"Final speed (meas.) : {final_meas:.2f} m/s")
    print(f"Max speed (true)    : {max_true:.2f} m/s")
    print(f"Overshoot (true)    : {overshoot:.2f} m/s")
    if settling_time_s is None:
        print(
            f"Settling time      : did not settle within tolerance={tolerance_m_s:.2f} m/s"
        )
    else:
        print(
            f"Settling time      : {settling_time_s:.2f} s "
            f"(within tolerance={tolerance_m_s:.2f} m/s, based on true speed)"
        )
    print(f"Steady-state |err| (true, last 20%):  {steady_state_error_true:.2f} m/s")
    print(f"Steady-state |err| (meas., last 20%): {steady_state_error_meas:.2f} m/s")
    print(f"Final throttle      : {throttles[-1]:.2f}")
    print("========================\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 1 PID throttle simulation (units: m/s, N, kg, s)"
    )
    parser.add_argument("--kp", type=float, default=0.5)
    parser.add_argument("--ki", type=float, default=0.1)
    parser.add_argument("--kd", type=float, default=0.05)
    parser.add_argument("--target", type=float, default=30.0, help="Target speed (m/s)")
    parser.add_argument("--dt", type=float, default=0.1, help="Timestep (s)")
    parser.add_argument("--steps", type=int, default=200, help="Number of simulation steps")
    parser.add_argument("--mass", type=float, default=1200.0, help="Vehicle mass (kg)")
    parser.add_argument("--max_force", type=float, default=4000.0, help="Max engine force (N)")
    parser.add_argument("--drag_coeff", type=float, default=0.3, help="Quadratic drag coeff (N·s²/m²)")
    parser.add_argument(
        "--noise-sigma",
        type=float,
        default=0.0,
        help="Sensor noise std dev on measured speed (m/s); 0 = perfect sensor",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for noise (optional)")
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        help="Write telemetry CSV (time_s, speed_true_m_s, speed_measured_m_s, target, throttle, error)",
    )
    parser.add_argument(
        "--plot",
        type=str,
        nargs="?",
        const="simulation/phase1_speed.png",
        default=None,
        help="Save speed plot PNG (default: simulation/phase1_speed.png). Requires matplotlib.",
    )
    parser.add_argument("--verbose-every", type=int, default=10, help="Print every N steps (0 disables)")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    times_s, speeds_true, speeds_measured, throttles, errors_control = run_simulation(
        kp=args.kp,
        ki=args.ki,
        kd=args.kd,
        target_speed_m_s=args.target,
        dt_s=args.dt,
        steps=args.steps,
        mass_kg=args.mass,
        max_force_n=args.max_force,
        drag_coeff=args.drag_coeff,
        noise_sigma_m_s=args.noise_sigma,
        rng=rng,
        verbose_every=args.verbose_every,
    )

    if args.output_csv:
        write_telemetry_csv(
            Path(args.output_csv),
            times_s=times_s,
            speeds_true_m_s=speeds_true,
            speeds_measured_m_s=speeds_measured,
            throttles=throttles,
            errors_control=errors_control,
            target_m_s=args.target,
        )
        print(f"Wrote telemetry to {args.output_csv}")

    if args.plot is not None:
        plot_path = Path(args.plot)
        try:
            plot_run(
                plot_path,
                times_s=times_s,
                speeds_true_m_s=speeds_true,
                speeds_measured_m_s=speeds_measured,
                target_m_s=args.target,
            )
            print(f"Wrote plot to {plot_path}")
        except RuntimeError as e:
            print(str(e))

    summarize(
        speeds_true,
        speeds_measured,
        throttles,
        times_s,
        target_speed_m_s=args.target,
        noise_sigma_m_s=args.noise_sigma,
    )


if __name__ == "__main__":
    main()

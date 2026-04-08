from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path
from statistics import mean
from typing import List, Optional, Sequence, Tuple

try:
    from simulation.actuator import ThrottleActuator
    from simulation.pid import PID
    from simulation.vehicle import clamp, update_vehicle
except ImportError:  # pragma: no cover
    from actuator import ThrottleActuator
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


def disturbance_active(
    t_end_s: float,
    *,
    start_s: Optional[float],
    end_s: Optional[float],
) -> bool:
    if start_s is None or end_s is None:
        return False
    return start_s <= t_end_s < end_s


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
    # Phase 2 plant
    c_rr: float,
    g_m_s2: float,
    disturb_start_s: Optional[float],
    disturb_end_s: Optional[float],
    disturb_drag_mult: float,
    disturb_force_n: float,
    # Phase 2 actuator
    throttle_rate_limit_per_s: Optional[float],
    throttle_delay_steps: int,
    verbose_every: int = 10,
) -> Tuple[
    List[float],
    List[float],
    List[float],
    List[float],
    List[float],
    List[float],
    List[float],
    List[int],
    List[float],
    List[float],
]:
    """
    Closed loop: measured speed feedback, optional noise, actuator, disturbances.

    Returns:
      times_s, speeds_true, speeds_measured, throttle_applied, errors_control,
      throttle_commanded, drag_multiplier_log, disturbance_flag, f_disturbance_n
    """
    pid = PID(kp=kp, ki=ki, kd=kd)
    actuator = ThrottleActuator(
        rate_limit_per_s=throttle_rate_limit_per_s,
        delay_steps=throttle_delay_steps,
    )
    speed_true_m_s = 0.0

    times_s: List[float] = []
    speeds_true_m_s: List[float] = []
    speeds_measured_m_s: List[float] = []
    throttles_applied: List[float] = []
    throttles_commanded: List[float] = []
    errors_control: List[float] = []
    drag_mult_log: List[float] = []
    disturb_flag: List[int] = []
    f_disturb_log: List[float] = []

    for step in range(steps):
        speed_true_before_m_s = speed_true_m_s
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
        throttle_cmd = clamp(throttle_cmd, 0.0, 1.0)

        throttle_applied_m = actuator.step(throttle_cmd, dt_s)

        t_end_s = (step + 1) * dt_s
        d_active = disturbance_active(
            t_end_s, start_s=disturb_start_s, end_s=disturb_end_s
        )
        drag_m = disturb_drag_mult if d_active else 1.0
        f_extra = disturb_force_n if d_active else 0.0

        speed_true_after_m_s = update_vehicle(
            speed_true_before_m_s,
            throttle_applied_m,
            dt_s,
            mass_kg=mass_kg,
            max_force_n=max_force_n,
            drag_coeff=drag_coeff,
            drag_multiplier=drag_m,
            c_rr=c_rr,
            g_m_s2=g_m_s2,
            f_disturbance_n=f_extra,
        )
        speed_true_m_s = speed_true_after_m_s

        error_control = target_speed_m_s - speed_measured_m_s

        times_s.append(t_end_s)
        speeds_true_m_s.append(speed_true_after_m_s)
        speeds_measured_m_s.append(speed_measured_m_s)
        throttles_applied.append(throttle_applied_m)
        throttles_commanded.append(throttle_cmd)
        errors_control.append(error_control)
        drag_mult_log.append(drag_m)
        disturb_flag.append(1 if d_active else 0)
        f_disturb_log.append(f_extra)

        if verbose_every > 0 and step % verbose_every == 0:
            print(
                f"t={t_end_s:6.2f}s | v_true={speed_true_after_m_s:7.2f} m/s | "
                f"v_meas={speed_measured_m_s:7.2f} m/s | "
                f"thr_cmd={throttle_cmd:5.2f} thr_appl={throttle_applied_m:5.2f} | "
                f"err={error_control:7.2f} | d={disturb_flag[-1]}"
            )

    return (
        times_s,
        speeds_true_m_s,
        speeds_measured_m_s,
        throttles_applied,
        errors_control,
        throttles_commanded,
        drag_mult_log,
        disturb_flag,
        f_disturb_log,
    )


def write_telemetry_csv(
    path: Path,
    *,
    times_s: Sequence[float],
    speeds_true_m_s: Sequence[float],
    speeds_measured_m_s: Sequence[float],
    throttles_applied: Sequence[float],
    throttles_commanded: Sequence[float],
    errors_control: Sequence[float],
    target_m_s: float,
    drag_multiplier: Sequence[float],
    disturbance_flag: Sequence[int],
    f_disturbance_n: Sequence[float],
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
                "throttle_commanded",
                "throttle_applied",
                "error_control",
                "drag_multiplier",
                "disturbance_active",
                "f_disturbance_n",
            ]
        )
        for i in range(len(times_s)):
            w.writerow(
                [
                    f"{times_s[i]:.6f}",
                    f"{speeds_true_m_s[i]:.6f}",
                    f"{speeds_measured_m_s[i]:.6f}",
                    f"{target_m_s:.6f}",
                    f"{throttles_commanded[i]:.6f}",
                    f"{throttles_applied[i]:.6f}",
                    f"{errors_control[i]:.6f}",
                    f"{drag_multiplier[i]:.6f}",
                    f"{disturbance_flag[i]}",
                    f"{f_disturbance_n[i]:.6f}",
                ]
            )


def plot_run(
    out_path: Path,
    *,
    times_s: Sequence[float],
    speeds_true_m_s: Sequence[float],
    speeds_measured_m_s: Sequence[float],
    errors_control: Sequence[float],
    target_m_s: float,
    disturb_start_s: Optional[float],
    disturb_end_s: Optional[float],
    title: str = "Simulation",
) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "Plotting requires matplotlib. Install with: pip install matplotlib"
        ) from e

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    ax0.plot(times_s, speeds_true_m_s, label="Speed true (m/s)", color="C0", linewidth=1.5)
    ax0.plot(
        times_s,
        speeds_measured_m_s,
        label="Speed measured (m/s)",
        color="C1",
        alpha=0.75,
        linewidth=1.0,
    )
    ax0.axhline(target_m_s, color="k", linestyle="--", linewidth=1.0, label="Target (m/s)")
    if disturb_start_s is not None and disturb_end_s is not None:
        ax0.axvline(disturb_start_s, color="r", linestyle=":", linewidth=1.2, label="Disturbance window")
        ax0.axvline(disturb_end_s, color="r", linestyle=":", linewidth=1.2)
    ax0.set_ylabel("Speed (m/s)")
    ax0.set_title(f"{title}: speed vs time")
    ax0.legend(loc="best", fontsize=8)
    ax0.grid(True, alpha=0.3)

    ax1.plot(times_s, errors_control, label="Control error (target - v_meas)", color="C2", linewidth=1.2)
    ax1.axhline(0.0, color="k", linestyle="-", linewidth=0.5, alpha=0.5)
    if disturb_start_s is not None and disturb_end_s is not None:
        ax1.axvline(disturb_start_s, color="r", linestyle=":", linewidth=1.2)
        ax1.axvline(disturb_end_s, color="r", linestyle=":", linewidth=1.2)
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Error (m/s)")
    ax1.set_title("Control error vs time")
    ax1.legend(loc="best", fontsize=8)
    ax1.grid(True, alpha=0.3)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def recovery_time_after_disturbance(
    times_s: Sequence[float],
    speeds_true_m_s: Sequence[float],
    target_m_s: float,
    *,
    disturb_end_s: float,
    tolerance_m_s: float,
) -> Optional[float]:
    """First time t > disturb_end_s after which true speed stays within tolerance until end of run."""
    for i, t in enumerate(times_s):
        if t <= disturb_end_s:
            continue
        if not all(
            abs(speeds_true_m_s[j] - target_m_s) <= tolerance_m_s
            for j in range(i, len(speeds_true_m_s))
        ):
            continue
        return float(t)
    return None


def summarize(
    speeds_true_m_s: List[float],
    speeds_measured_m_s: List[float],
    throttles_applied: List[float],
    times_s: Sequence[float],
    *,
    target_speed_m_s: float,
    noise_sigma_m_s: float,
    c_rr: float,
    disturb_start_s: Optional[float],
    disturb_end_s: Optional[float],
) -> None:
    final_true = speeds_true_m_s[-1]
    final_meas = speeds_measured_m_s[-1]
    max_true = max(speeds_true_m_s)
    overshoot = max(0.0, max_true - target_speed_m_s)

    tolerance_m_s = max(0.5, 0.02 * target_speed_m_s)
    settling_time_s = compute_settling_time(
        speeds_true_m_s,
        times_s,
        target_speed_m_s,
        tolerance_m_s=tolerance_m_s,
    )

    tail = max(1, len(speeds_true_m_s) // 5)
    steady_state_error_true = abs(mean(speeds_true_m_s[-tail:]) - target_speed_m_s)
    steady_state_error_meas = abs(mean(speeds_measured_m_s[-tail:]) - target_speed_m_s)

    print("\n=== Simulation summary ===")
    print(f"Target speed        : {target_speed_m_s:.2f} m/s")
    if noise_sigma_m_s > 0.0:
        print(f"Sensor noise (sigma): {noise_sigma_m_s:.3f} m/s (Gaussian on feedback)")
    if c_rr > 0.0:
        print(f"Rolling resistance c_rr: {c_rr:.4f} (F_rr = c_rr * m * g)")
    if disturb_start_s is not None and disturb_end_s is not None:
        print(
            f"Disturbance window  : [{disturb_start_s:.2f}s, {disturb_end_s:.2f}s) "
            "(drag mult / extra force when active)"
        )
        rec = recovery_time_after_disturbance(
            times_s,
            speeds_true_m_s,
            target_speed_m_s,
            disturb_end_s=disturb_end_s,
            tolerance_m_s=tolerance_m_s,
        )
        if rec is not None:
            print(f"Recovery (re-enter band): first time after window ~ {rec:.2f} s")
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
            f"(within tolerance={tolerance_m_s:.2f} m/s, true speed)"
        )
    print(f"Steady-state |err| (true, last 20%):  {steady_state_error_true:.2f} m/s")
    print(f"Steady-state |err| (meas., last 20%): {steady_state_error_meas:.2f} m/s")
    print(f"Final throttle (appl.): {throttles_applied[-1]:.2f}")
    print("============================\n")


def _argv_has(flag: str) -> bool:
    return flag in sys.argv


def apply_scenario_defaults(args: argparse.Namespace) -> None:
    """Apply curated presets unless the user already passed the matching flag."""
    sc = getattr(args, "scenario", "none") or "none"
    if sc == "none":
        return
    if sc == "normal":
        return
    if sc == "noisy":
        if not _argv_has("--noise-sigma"):
            args.noise_sigma = 0.15
    elif sc == "disturbance":
        if not _argv_has("--disturb-start"):
            args.disturb_start = 10.0
        if not _argv_has("--disturb-end"):
            args.disturb_end = 15.0
        if not _argv_has("--disturb-drag-mult"):
            args.disturb_drag_mult = 2.0
    elif sc == "full":
        if not _argv_has("--noise-sigma"):
            args.noise_sigma = 0.12
        if not _argv_has("--c-rr"):
            args.c_rr = 0.015
        if not _argv_has("--throttle-rate-limit"):
            args.throttle_rate_limit = 0.2
        if not _argv_has("--disturb-start"):
            args.disturb_start = 10.0
        if not _argv_has("--disturb-end"):
            args.disturb_end = 15.0
        if not _argv_has("--disturb-drag-mult"):
            args.disturb_drag_mult = 2.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vehicle simulation: Phase 1 (PID) + Phase 2 (realism). Units: m/s, N, kg, s."
    )
    parser.add_argument(
        "--scenario",
        choices=["none", "normal", "noisy", "disturbance", "full"],
        default="none",
        help="Curated presets (overridden by explicit flags you pass)",
    )
    parser.add_argument("--kp", type=float, default=0.5)
    parser.add_argument("--ki", type=float, default=0.1)
    parser.add_argument("--kd", type=float, default=0.05)
    parser.add_argument("--target", type=float, default=30.0, help="Target speed (m/s)")
    parser.add_argument("--dt", type=float, default=0.1, help="Timestep (s)")
    parser.add_argument("--steps", type=int, default=200, help="Number of simulation steps")
    parser.add_argument("--mass", type=float, default=1200.0, help="Vehicle mass (kg)")
    parser.add_argument("--max-force", type=float, default=4000.0, help="Max engine force (N)")
    parser.add_argument("--drag-coeff", type=float, default=0.3, help="Quadratic drag coeff (N*s^2/m^2)")
    parser.add_argument(
        "--noise-sigma",
        type=float,
        default=0.0,
        help="Sensor noise std dev on measured speed (m/s); 0 = perfect sensor",
    )
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for noise (optional)")
    parser.add_argument(
        "--c-rr",
        type=float,
        default=0.0,
        help="Rolling resistance coefficient (dimensionless); F_rr = c_rr * m * g [N]",
    )
    parser.add_argument("--g", type=float, default=9.81, help="Gravity (m/s^2)")
    parser.add_argument(
        "--disturb-start",
        type=float,
        default=None,
        help="Start time (s) of disturbance window [start, end); omit to disable",
    )
    parser.add_argument("--disturb-end", type=float, default=None, help="End time (s) of disturbance window")
    parser.add_argument(
        "--disturb-drag-mult",
        type=float,
        default=2.0,
        help="Multiply aerodynamic drag by this factor while disturbance is active",
    )
    parser.add_argument(
        "--disturb-force-n",
        type=float,
        default=0.0,
        help="Extra longitudinal force (N) during disturbance; negative = braking",
    )
    parser.add_argument(
        "--throttle-rate-limit",
        type=float,
        default=None,
        help="Max throttle change per second (1/s); omit for unlimited",
    )
    parser.add_argument(
        "--throttle-delay-steps",
        type=int,
        default=0,
        help="Actuator delay in simulation steps (0 = no delay)",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        help="Write extended telemetry CSV",
    )
    parser.add_argument(
        "--plot",
        type=str,
        nargs="?",
        const="simulation/phase1_speed.png",
        default=None,
        help="Save plot PNG (default: simulation/phase1_speed.png). Requires matplotlib.",
    )
    parser.add_argument("--verbose-every", type=int, default=10, help="Print every N steps (0 disables)")
    args = parser.parse_args()

    apply_scenario_defaults(args)

    if (args.disturb_start is None) != (args.disturb_end is None):
        parser.error("--disturb-start and --disturb-end must be set together (or both omitted)")

    rng = random.Random(args.seed)

    (
        times_s,
        speeds_true,
        speeds_measured,
        throttles_applied,
        errors_control,
        throttles_commanded,
        drag_mult_log,
        disturb_flag,
        f_disturb_log,
    ) = run_simulation(
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
        c_rr=args.c_rr,
        g_m_s2=args.g,
        disturb_start_s=args.disturb_start,
        disturb_end_s=args.disturb_end,
        disturb_drag_mult=args.disturb_drag_mult,
        disturb_force_n=args.disturb_force_n,
        throttle_rate_limit_per_s=args.throttle_rate_limit,
        throttle_delay_steps=args.throttle_delay_steps,
        verbose_every=args.verbose_every,
    )

    if args.output_csv:
        write_telemetry_csv(
            Path(args.output_csv),
            times_s=times_s,
            speeds_true_m_s=speeds_true,
            speeds_measured_m_s=speeds_measured,
            throttles_applied=throttles_applied,
            throttles_commanded=throttles_commanded,
            errors_control=errors_control,
            target_m_s=args.target,
            drag_multiplier=drag_mult_log,
            disturbance_flag=disturb_flag,
            f_disturbance_n=f_disturb_log,
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
                errors_control=errors_control,
                target_m_s=args.target,
                disturb_start_s=args.disturb_start,
                disturb_end_s=args.disturb_end,
                title="Phase 2" if (args.c_rr > 0 or args.disturb_start is not None or args.noise_sigma > 0) else "Phase 1",
            )
            print(f"Wrote plot to {plot_path}")
        except RuntimeError as e:
            print(str(e))

    summarize(
        speeds_true,
        speeds_measured,
        throttles_applied,
        times_s,
        target_speed_m_s=args.target,
        noise_sigma_m_s=args.noise_sigma,
        c_rr=args.c_rr,
        disturb_start_s=args.disturb_start,
        disturb_end_s=args.disturb_end,
    )


if __name__ == "__main__":
    main()

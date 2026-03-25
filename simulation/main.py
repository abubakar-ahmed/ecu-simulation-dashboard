from __future__ import annotations

import argparse
from statistics import mean
from typing import List, Optional, Tuple

try:
    # Preferred when imported as part of the `simulation` namespace.
    from simulation.pid import PID
    from simulation.vehicle import clamp, update_vehicle
except ImportError:  # pragma: no cover
    # Works when running directly: `python simulation/main.py`
    from pid import PID
    from vehicle import clamp, update_vehicle


def compute_settling_time(
    speeds: List[float],
    target: float,
    dt: float,
    *,
    tolerance: float,
) -> Optional[float]:
    """
    Settling time = first time index where the response stays within tolerance
    for all remaining steps.
    """

    n = len(speeds)
    for i in range(n):
        if all(abs(s - target) <= tolerance for s in speeds[i:]):
            return i * dt
    return None


def run_simulation(
    *,
    kp: float,
    ki: float,
    kd: float,
    target_speed: float,
    dt: float,
    steps: int,
    mass_kg: float,
    max_force_n: float,
    drag_coeff: float,
    verbose_every: int = 10,
) -> Tuple[List[float], List[float], List[float]]:
    pid = PID(kp=kp, ki=ki, kd=kd)
    speed = 0.0

    speeds: List[float] = []
    throttles: List[float] = []
    errors: List[float] = []

    for step in range(steps):
        throttle_cmd = pid.compute(target_speed, speed, dt, u_min=0.0, u_max=1.0)
        throttle = clamp(throttle_cmd, 0.0, 1.0)

        speed = update_vehicle(
            speed,
            throttle,
            dt,
            mass_kg=mass_kg,
            max_force_n=max_force_n,
            drag_coeff=drag_coeff,
        )

        error = target_speed - speed
        speeds.append(speed)
        throttles.append(throttle)
        errors.append(error)

        if verbose_every > 0 and step % verbose_every == 0:
            print(
                f"t={step * dt:6.2f}s | speed={speed:7.2f} m/s | "
                f"throttle={throttle:5.2f} | error={error:7.2f}"
            )

    return speeds, throttles, errors


def summarize(
    speeds: List[float],
    throttles: List[float],
    *,
    target_speed: float,
    dt: float,
) -> None:
    final_speed = speeds[-1]
    max_speed = max(speeds)
    overshoot = max(0.0, max_speed - target_speed)

    tolerance = max(0.5, 0.02 * target_speed)  # 0.5 m/s or 2%
    settling_time = compute_settling_time(speeds, target_speed, dt, tolerance=tolerance)

    tail = max(1, len(speeds) // 5)
    steady_state_error = abs(mean(speeds[-tail:]) - target_speed)

    print("\n=== Phase 1 Summary ===")
    print(f"Target speed        : {target_speed:.2f} m/s")
    print(f"Final speed         : {final_speed:.2f} m/s")
    print(f"Max speed           : {max_speed:.2f} m/s")
    print(f"Overshoot           : {overshoot:.2f} m/s")
    if settling_time is None:
        print(f"Settling time      : did not settle within tolerance={tolerance:.2f} m/s")
    else:
        print(
            f"Settling time      : {settling_time:.2f} s (within tolerance={tolerance:.2f} m/s)"
        )
    print(f"Steady-state error : {steady_state_error:.2f} m/s")
    print(f"Final throttle      : {throttles[-1]:.2f}")
    print("========================\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 PID throttle simulation")
    parser.add_argument("--kp", type=float, default=0.5)
    parser.add_argument("--ki", type=float, default=0.1)
    parser.add_argument("--kd", type=float, default=0.05)
    parser.add_argument("--target", type=float, default=30.0, help="Target speed (m/s)")
    parser.add_argument("--dt", type=float, default=0.1, help="Timestep (s)")
    parser.add_argument("--steps", type=int, default=200, help="Number of simulation steps")
    parser.add_argument("--mass", type=float, default=1200.0, help="Vehicle mass (kg)")
    parser.add_argument("--max_force", type=float, default=4000.0, help="Max engine force (N)")
    parser.add_argument("--drag_coeff", type=float, default=0.3, help="Quadratic drag coefficient")
    parser.add_argument("--verbose-every", type=int, default=10, help="Print every N steps (0 disables)")
    args = parser.parse_args()

    speeds, throttles, _ = run_simulation(
        kp=args.kp,
        ki=args.ki,
        kd=args.kd,
        target_speed=args.target,
        dt=args.dt,
        steps=args.steps,
        mass_kg=args.mass,
        max_force_n=args.max_force,
        drag_coeff=args.drag_coeff,
        verbose_every=args.verbose_every,
    )

    summarize(speeds, throttles, target_speed=args.target, dt=args.dt)


if __name__ == "__main__":
    main()


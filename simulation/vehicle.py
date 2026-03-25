from __future__ import annotations


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def update_vehicle(
    speed: float,
    throttle: float,
    dt: float,
    *,
    mass_kg: float = 1200.0,
    max_force_n: float = 4000.0,
    drag_coeff: float = 0.3,
) -> float:
    """
    Discrete longitudinal dynamics with quadratic drag.

    engine_force = throttle * max_force
    drag_force   = drag_coeff * speed^2
    acceleration  = (engine_force - drag_force) / mass
    v[t+1]        = v[t] + acceleration * dt
    """

    throttle = clamp(throttle, 0.0, 1.0)

    engine_force = throttle * max_force_n
    drag_force = drag_coeff * (speed**2)
    acceleration = (engine_force - drag_force) / mass_kg
    return speed + acceleration * dt


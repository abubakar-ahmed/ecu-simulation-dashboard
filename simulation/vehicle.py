from __future__ import annotations

# --- Physical units (SI) used throughout this module ---
# speed_m_s      : m/s   (longitudinal velocity)
# throttle       : 0..1  (dimensionless commanded fraction of max engine force)
# dt             : s     (simulation timestep)
# mass_kg        : kg    (vehicle mass)
# max_force_n    : N     (maximum engine force at full throttle)
# drag_coeff     : N·s²/m²  (quadratic drag: F_drag = drag_coeff * v²)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def update_vehicle(
    speed_m_s: float,
    throttle: float,
    dt_s: float,
    *,
    mass_kg: float = 1200.0,  # kg
    max_force_n: float = 4000.0,  # N
    drag_coeff: float = 0.3,  # N·s²/m² for F_drag = coeff * v²
) -> float:
    """
    One discrete step of longitudinal dynamics with quadratic aerodynamic drag.

    Units:
      - speed_m_s: m/s
      - throttle: dimensionless [0, 1]
      - dt_s: s
      - Returns: speed at t + dt_s, in m/s

    Equations (same timestep):
      F_engine = throttle * max_force_n          [N]
      F_drag   = drag_coeff * speed_m_s**2       [N]
      a        = (F_engine - F_drag) / mass_kg     [m/s²]
      v_next   = v + a * dt_s                     [m/s]
    """

    throttle = clamp(throttle, 0.0, 1.0)

    engine_force_n = throttle * max_force_n
    drag_force_n = drag_coeff * (speed_m_s**2)
    acceleration_m_s2 = (engine_force_n - drag_force_n) / mass_kg
    return speed_m_s + acceleration_m_s2 * dt_s


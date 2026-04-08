from __future__ import annotations

# --- Physical units (SI) used throughout this module ---
# speed_m_s      : m/s   (longitudinal velocity)
# throttle       : 0..1  (dimensionless commanded fraction of max engine force)
# dt             : s     (simulation timestep)
# mass_kg        : kg    (vehicle mass)
# max_force_n    : N     (maximum engine force at full throttle)
# drag_coeff     : N·s²/m²  (quadratic drag: F_drag = drag_coeff * v²)
# c_rr           : dimensionless rolling resistance coefficient; F_rr = c_rr * m * g
# f_disturbance_n: N     (extra longitudinal force; negative = braking / resistance)


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
    drag_multiplier: float = 1.0,  # multiplies aerodynamic drag (wind gust, etc.)
    c_rr: float = 0.0,  # rolling resistance coeff; 0 disables
    g_m_s2: float = 9.81,  # gravity (m/s²)
    f_disturbance_n: float = 0.0,  # N (extra push positive, braking negative)
) -> float:
    """
    One discrete step of longitudinal dynamics.

    Units:
      - speed_m_s: m/s
      - throttle: dimensionless [0, 1]
      - dt_s: s
      - Returns: speed at t + dt_s, in m/s

    Forces (N):
      F_engine = throttle * max_force_n
      F_drag   = drag_multiplier * drag_coeff * speed_m_s**2
      F_roll   = c_rr * mass_kg * g_m_s2  (opposes motion when v > 0)
      F_net    = F_engine - F_drag - F_roll + f_disturbance_n

    a = F_net / mass_kg,   v_next = v + a * dt_s
    """

    throttle = clamp(throttle, 0.0, 1.0)

    engine_force_n = throttle * max_force_n
    drag_force_n = drag_multiplier * drag_coeff * (speed_m_s**2)
    rolling_force_n = c_rr * mass_kg * g_m_s2 if speed_m_s > 1e-6 else 0.0

    f_net_n = engine_force_n - drag_force_n - rolling_force_n + f_disturbance_n
    acceleration_m_s2 = f_net_n / mass_kg
    return speed_m_s + acceleration_m_s2 * dt_s

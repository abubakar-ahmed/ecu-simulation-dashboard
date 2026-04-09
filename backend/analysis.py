from __future__ import annotations

from io import BytesIO
from statistics import mean
from typing import Any, Optional, Sequence


def compute_settling_time(
    speeds_m_s: Sequence[float],
    times_s: Sequence[float],
    target_m_s: float,
    *,
    tolerance_m_s: float,
) -> Optional[float]:
    """First time (s) after which speed stays within tolerance of target until end."""
    n = len(speeds_m_s)
    for i in range(n):
        if all(abs(s - target_m_s) <= tolerance_m_s for s in speeds_m_s[i:]):
            return float(times_s[i])
    return None


def analyze_series(
    *,
    times_s: Sequence[float],
    speeds_m_s: Sequence[float],
    targets_m_s: Sequence[float],
    throttles: Sequence[float],
) -> dict[str, Any]:
    """
    Metrics use target_ref = last target in the series (constant setpoint assumption).
    times_s should be monotonic (e.g. seconds since log start).
    """
    n = len(times_s)
    if n == 0:
        return {
            "sample_count": 0,
            "duration_s": 0.0,
            "target_ref_m_s": None,
            "overshoot_m_s": None,
            "settling_time_s": None,
            "steady_state_error_m_s": None,
        }

    target_ref = float(targets_m_s[-1])
    errors = [targets_m_s[i] - speeds_m_s[i] for i in range(n)]
    max_speed = max(speeds_m_s)
    overshoot = max(0.0, max_speed - target_ref)

    tolerance_m_s = max(0.5, 0.02 * abs(target_ref)) if target_ref != 0 else 0.5
    t0 = times_s[0]
    rel_times = [float(t) - t0 for t in times_s]
    settling = compute_settling_time(
        list(speeds_m_s),
        rel_times,
        target_ref,
        tolerance_m_s=tolerance_m_s,
    )

    tail = max(1, n // 5)
    ss_err = abs(mean(speeds_m_s[-tail:]) - target_ref)

    return {
        "sample_count": n,
        "duration_s": float(rel_times[-1]),
        "target_ref_m_s": target_ref,
        "overshoot_m_s": float(overshoot),
        "settling_time_s": settling,
        "steady_state_error_m_s": float(ss_err),
        "tolerance_m_s": float(tolerance_m_s),
        "mean_abs_error_m_s": float(mean(abs(e) for e in errors)),
    }


def build_performance_plot(
    *,
    times_s: Sequence[float],
    speeds_m_s: Sequence[float],
    targets_m_s: Sequence[float],
    throttles: Sequence[float],
    title: str = "Run performance",
) -> bytes:
    try:
        import matplotlib.pyplot as plt
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Plotting requires matplotlib. pip install matplotlib") from e

    t0 = times_s[0] if times_s else 0.0
    t_rel = [float(t) - t0 for t in times_s]

    fig = plt.figure(figsize=(10, 7))
    ax0 = fig.add_subplot(2, 1, 1)
    ax1 = fig.add_subplot(2, 1, 2, sharex=ax0)

    ax0.plot(t_rel, speeds_m_s, label="Speed (m/s)", color="C0", linewidth=1.5)
    ax0.plot(t_rel, targets_m_s, label="Target (m/s)", color="C1", linestyle="--", linewidth=1.2)
    ax0.set_ylabel("m/s")
    ax0.set_title(f"{title}: speed & target")
    ax0.legend(loc="upper right", fontsize=8)
    ax0.grid(True, alpha=0.3)

    ax1.plot(t_rel, throttles, label="Throttle", color="C2", linewidth=1.2)
    ax1.set_xlabel("Time (s) from run start")
    ax1.set_ylabel("Throttle (0–1)")
    ax1.set_title("Throttle vs time")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.3)

    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def write_csv_text(
    *,
    times_s: Sequence[float],
    speeds_m_s: Sequence[float],
    targets_m_s: Sequence[float],
    throttles: Sequence[float],
    errors: Sequence[float],
) -> str:
    lines = ["timestamp_s,speed_m_s,target_m_s,throttle,error_m_s"]
    for i in range(len(times_s)):
        lines.append(
            f"{times_s[i]:.6f},{speeds_m_s[i]:.6f},{targets_m_s[i]:.6f},{throttles[i]:.6f},{errors[i]:.6f}"
        )
    return "\n".join(lines) + "\n"

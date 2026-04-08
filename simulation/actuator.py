from __future__ import annotations

from typing import List

try:
    from simulation.vehicle import clamp
except ImportError:  # pragma: no cover
    from vehicle import clamp


class ThrottleActuator:
    """
    Maps ECU throttle command to actuator output with optional rate limit and delay.

    Units:
      - inputs/outputs: dimensionless throttle in [0, 1]
      - rate_limit_per_s: max change per second (1/s)
      - delay_steps: output lags commanded (after rate limiting) by this many steps
    """

    def __init__(
        self,
        *,
        rate_limit_per_s: float | None = None,
        delay_steps: int = 0,
    ) -> None:
        self.rate_limit_per_s = rate_limit_per_s
        self.delay_steps = max(0, delay_steps)
        self._after_rate_limit: float = 0.0
        self._history: List[float] = []

    def reset(self) -> None:
        self._after_rate_limit = 0.0
        self._history = []

    def step(self, commanded: float, dt_s: float) -> float:
        """Return throttle actually applied to the plant this step."""
        cmd = clamp(commanded, 0.0, 1.0)

        if self.rate_limit_per_s is not None and self.rate_limit_per_s > 0.0 and dt_s > 0.0:
            max_delta = self.rate_limit_per_s * dt_s
            delta = cmd - self._after_rate_limit
            delta = clamp(delta, -max_delta, max_delta)
            self._after_rate_limit += delta
        else:
            self._after_rate_limit = cmd

        self._history.append(self._after_rate_limit)
        idx = len(self._history) - 1 - self.delay_steps
        if idx < 0:
            return 0.0
        return self._history[idx]

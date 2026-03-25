from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PID:
    """
    Discrete PID controller with simple anti-windup for saturated actuators.

    Assumption:
    - output is directly clamped between u_min and u_max (like a throttle command).
    """

    kp: float
    ki: float
    kd: float

    prev_error: float = 0.0
    integral: float = 0.0
    initialized: bool = False

    def reset(self) -> None:
        self.prev_error = 0.0
        self.integral = 0.0
        self.initialized = False

    def compute(
        self,
        target: float,
        current: float,
        dt: float,
        *,
        u_min: float = 0.0,
        u_max: float = 1.0,
    ) -> float:
        error = target - current

        if not self.initialized:
            # Avoid derivative kick on the first step.
            self.prev_error = error
            self.integral = 0.0
            self.initialized = True

        derivative = (error - self.prev_error) / dt if dt > 0 else 0.0

        # Anti-windup via conditional integration:
        # If the controller would saturate and the error would push further into
        # that saturated direction, freeze the integral.
        proposed_integral = self.integral + error * dt
        u_proposed = self.kp * error + self.ki * proposed_integral + self.kd * derivative

        if (u_proposed > u_max) and (error > 0):
            u = self.kp * error + self.ki * self.integral + self.kd * derivative
        elif (u_proposed < u_min) and (error < 0):
            u = self.kp * error + self.ki * self.integral + self.kd * derivative
        else:
            self.integral = proposed_integral
            u = u_proposed

        self.prev_error = error
        return u


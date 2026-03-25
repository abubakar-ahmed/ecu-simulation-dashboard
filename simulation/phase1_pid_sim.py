"""
Backward-compatible wrapper for Phase 1.

The implementation moved to:
  - `vehicle.py` (physics)
  - `pid.py` (ECU logic)
  - `main.py` (closed-loop simulation + CLI)
"""

from main import main


if __name__ == "__main__":
    main()


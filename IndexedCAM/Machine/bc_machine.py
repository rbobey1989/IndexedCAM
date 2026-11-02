"""B+C head machine definition: axis limits, convention and tool vector.

Convention (see ``bc_head``): R = Rz(C) @ Ry(B); the tool axis is R @ (0, 0, 1).
Angles are degrees. B tilts the head (0 = vertical, 90 = horizontal), C rotates around Z. Real controllers may
use other signs, zeros or axis order; adapt this definition per machine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Tuple

from IndexedCAM.Machine.bc_head import Vector, bc_to_normal
from IndexedCAM.Machine.envelope import Envelope

Matrix3 = Tuple[Vector, Vector, Vector]


@dataclass(frozen=True)
class AxisLimits:
    """Closed travel interval of a rotary axis, in degrees."""

    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.minimum) and math.isfinite(self.maximum)):
            raise ValueError("axis limits must be finite")
        if self.minimum > self.maximum:
            raise ValueError("axis minimum must not exceed maximum")

    def contains(self, angle: float, tolerance: float = 1e-9) -> bool:
        """Return True if ``angle`` is inside the interval (within tolerance)."""
        return self.minimum - tolerance <= angle <= self.maximum + tolerance


@dataclass(frozen=True)
class BCMachine:
    """Kinematic definition of a B+C head machine (3+2 indexed only)."""

    b_limits: AxisLimits = AxisLimits(0.0, 180.0)
    c_limits: AxisLimits = AxisLimits(-360.0, 360.0)
    envelope: Envelope = field(default_factory=Envelope)

    def is_reachable(self, b: float, c: float) -> bool:
        """Return True if both B and C are within the axis limits."""
        if not (math.isfinite(b) and math.isfinite(c)):
            return False
        return self.b_limits.contains(b) and self.c_limits.contains(c)

    def validate(self, b: float, c: float) -> None:
        """Raise ValueError naming the violated axis if B/C are not reachable."""
        if not (math.isfinite(b) and math.isfinite(c)):
            raise ValueError("B and C must be finite")
        if not self.b_limits.contains(b):
            raise ValueError(
                "B={} outside limits [{}, {}]".format(
                    b, self.b_limits.minimum, self.b_limits.maximum
                )
            )
        if not self.c_limits.contains(c):
            raise ValueError(
                "C={} outside limits [{}, {}]".format(
                    c, self.c_limits.minimum, self.c_limits.maximum
                )
            )

    def tool_vector(self, b: float, c: float) -> Vector:
        """Unit tool-axis direction in machine coordinates for valid B and C."""
        self.validate(b, c)
        return bc_to_normal(b, c)

    def rotation_matrix(self, b: float, c: float) -> Matrix3:
        """Rotation matrix Rz(C) @ Ry(B) as row tuples, for valid B and C."""
        self.validate(b, c)
        sb, cb = math.sin(math.radians(b)), math.cos(math.radians(b))
        sc, cc = math.sin(math.radians(c)), math.cos(math.radians(c))
        return (
            (cc * cb, -sc, cc * sb),
            (sc * cb, cc, sc * sb),
            (-sb, 0.0, cb),
        )

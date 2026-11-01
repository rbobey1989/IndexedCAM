"""Kinematics of a B+C head machine (pure Python, no FreeCAD dependency).

Convention (machine coordinates, degrees in the public API):
    R = Rz(C) @ Ry(B) applied to ez = (0, 0, 1), hence
    n = (sin B cos C, sin B sin C, cos B).

Other machines may use different signs, axes or rotation order. Physical axis
limits are NOT enforced here; B is returned in [0, 180] and C in [-180, 180).
"""

from __future__ import annotations

import math
from typing import NamedTuple, Optional, Sequence, Tuple

Vector = Tuple[float, float, float]

SINGULARITY_TOLERANCE = 1e-9


class BCAngles(NamedTuple):
    """B and C angles in degrees."""

    b: float
    c: float


def _normalize(normal: Sequence[float]) -> Vector:
    if len(normal) != 3:
        raise ValueError("normal must have exactly 3 components")
    x, y, z = (float(v) for v in normal)
    if not all(math.isfinite(v) for v in (x, y, z)):
        raise ValueError("normal must have finite components")
    length = math.sqrt(x * x + y * y + z * z)
    if length == 0.0:
        raise ValueError("normal must not be a zero-length vector")
    return (x / length, y / length, z / length)


def _wrap_c(c: float) -> float:
    """Normalize an angle in degrees to [-180, 180)."""
    wrapped = (c + 180.0) % 360.0 - 180.0
    return wrapped


def normal_to_bc(
    normal: Sequence[float],
    previous_c: Optional[float] = None,
    tolerance: float = SINGULARITY_TOLERANCE,
) -> BCAngles:
    """Convert a tool-axis direction into B and C angles (degrees).

    At the singularity (normal parallel to Z, |sin B| < tolerance) C is
    undetermined: ``previous_c`` is kept if given, otherwise C = 0. A flipped
    vertical normal (B = 180) is equally singular.
    """
    nx, ny, nz = _normalize(normal)
    b = math.degrees(math.acos(max(-1.0, min(1.0, nz))))
    if math.sqrt(nx * nx + ny * ny) < tolerance:
        c = 0.0 if previous_c is None else _wrap_c(float(previous_c))
    else:
        c = _wrap_c(math.degrees(math.atan2(ny, nx)))
    return BCAngles(b, c)


def bc_to_normal(b: float, c: float) -> Vector:
    """Tool-axis direction for the given B and C angles (degrees)."""
    rb, rc = math.radians(b), math.radians(c)
    return (
        math.sin(rb) * math.cos(rc),
        math.sin(rb) * math.sin(rc),
        math.cos(rb),
    )


def verify_solution(
    normal: Sequence[float], angles: BCAngles, tolerance: float = 1e-9
) -> bool:
    """Check that B/C reconstruct the (normalized) normal within tolerance."""
    expected = _normalize(normal)
    actual = bc_to_normal(angles.b, angles.c)
    return all(abs(e - a) <= tolerance for e, a in zip(expected, actual))

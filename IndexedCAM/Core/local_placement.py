"""Pure math to place a part in a Setup's local frame (no FreeCAD needed).

A Setup's local frame has its origin and axes expressed in part coordinates
(Z = tool axis). CAM works with the tool along +Z, so the part is moved by the
inverse transform: ``p_local = R^T (p - origin)`` with R = [X Y Z] as columns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

from IndexedCAM.Core.indexed_setup import LocalFrame

Vector = Tuple[float, float, float]
Quaternion = Tuple[float, float, float, float]  # x, y, z, w


def frame_to_quaternion(frame: LocalFrame) -> Quaternion:
    """Unit quaternion (x, y, z, w) of the rotation with columns X, Y, Z axes."""
    (m00, m10, m20) = frame.x_axis
    (m01, m11, m21) = frame.y_axis
    (m02, m12, m22) = frame.z_axis
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        w, x, y, z = 0.25 * s, (m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        w, x, y, z = (m21 - m12) / s, 0.25 * s, (m01 + m10) / s, (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        w, x, y, z = (m02 - m20) / s, (m01 + m10) / s, 0.25 * s, (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
        w, x, y, z = (m10 - m01) / s, (m02 + m20) / s, (m12 + m21) / s, 0.25 * s
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    return (x / norm, y / norm, z / norm, w / norm)


@dataclass(frozen=True)
class LocalTransform:
    """Rigid transform part -> local frame: rotate by ``rotation``, then move."""

    rotation: Quaternion
    translation: Vector


def local_transform(frame: LocalFrame) -> LocalTransform:
    """Transform that maps part coordinates to the Setup's local coordinates."""
    qx, qy, qz, qw = frame_to_quaternion(frame)
    translation = tuple(
        -sum(a * b for a, b in zip(axis, frame.origin))
        for axis in (frame.x_axis, frame.y_axis, frame.z_axis)
    )
    return LocalTransform((-qx, -qy, -qz, qw), translation)  # type: ignore[arg-type]


def apply_transform(transform: LocalTransform, point: Vector) -> Vector:
    """Apply ``transform`` to a point (used by tests and diagnostics)."""
    qx, qy, qz, qw = transform.rotation
    px, py, pz = point
    tx = 2.0 * (qy * pz - qz * py)
    ty = 2.0 * (qz * px - qx * pz)
    tz = 2.0 * (qx * py - qy * px)
    rotated = (
        px + qw * tx + (qy * tz - qz * ty),
        py + qw * ty + (qz * tx - qx * tz),
        pz + qw * tz + (qx * ty - qy * tx),
    )
    # R^T p + (-R^T o) == R^T (p - o)
    return tuple(r + t for r, t in zip(rotated, transform.translation))  # type: ignore[return-value]


@dataclass(frozen=True)
class OperationHeights:
    """Heights CAM needs per operation, in local Z."""

    start_depth: float
    safe_height: float
    clearance_height: float


def heights_above(
    top: float, safe_offset: float = 5.0, clearance_offset: float = 10.0
) -> OperationHeights:
    """Start at the highest point of the part in the local frame.

    The Job has one stock for all Setups, so its heights are meaningless for a
    rotated Setup; they are derived from the local model instead.
    """
    if not math.isfinite(top):
        raise ValueError("top must be finite")
    if safe_offset < 0.0 or clearance_offset < safe_offset:
        raise ValueError("need 0 <= safe_offset <= clearance_offset")
    return OperationHeights(top, top + safe_offset, top + clearance_offset)

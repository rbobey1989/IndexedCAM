"""Tool, holder and head envelope of a B+C machine (no FreeCAD needed).

The envelope is a stack of coaxial cylinders along the tool axis, measured from
the tool tip toward the spindle: tool, holder, head. ``pivot_distance`` is the
distance from the tool tip to the B pivot along the axis (the gauge length of
the TCP model). All lengths are millimetres.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from IndexedCAM.Machine.bc_head import Vector, bc_to_normal

TOOL, SHANK, HOLDER, HEAD = "tool", "shank", "holder", "head"


def _positive(value: float, what: str) -> float:
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError("{} must be a positive finite number".format(what))
    return float(value)


@dataclass(frozen=True)
class Cylinder:
    """A named cylinder: ``radius`` and ``length`` along the tool axis."""

    name: str
    radius: float
    length: float

    def __post_init__(self) -> None:
        _positive(self.radius, self.name + " radius")
        _positive(self.length, self.name + " length")


@dataclass(frozen=True)
class CylinderPose:
    """A cylinder placed in space: axis from ``start`` to ``end`` (tip side first)."""

    name: str
    radius: float
    start: Vector
    end: Vector


@dataclass(frozen=True)
class Envelope:
    """Tool + holder + head stack and the B pivot position."""

    tool: Cylinder = Cylinder(TOOL, 5.0, 40.0)
    holder: Cylinder = Cylinder(HOLDER, 20.0, 50.0)
    head: Cylinder = Cylinder(HEAD, 60.0, 150.0)
    pivot_distance: float = 120.0
    cutting_length: Optional[float] = None
    shank_radius: Optional[float] = None

    def __post_init__(self) -> None:
        _positive(self.pivot_distance, "pivot_distance")
        if self.cutting_length is not None:
            _positive(self.cutting_length, "cutting_length")
        if self.shank_radius is not None:
            _positive(self.shank_radius, "shank_radius")

    def cylinders(self) -> Tuple[Cylinder, Cylinder, Cylinder]:
        return (self.tool, self.holder, self.head)

    @property
    def reach(self) -> float:
        """Length of the whole stack from the tip."""
        return sum(c.length for c in self.cylinders())

    def with_tool(
        self,
        radius: float,
        length: float,
        cutting_length: Optional[float] = None,
        shank_radius: Optional[float] = None,
    ) -> "Envelope":
        """Same machine with another tool (e.g. from the CAM tool controller).

        ``cutting_length`` is the flute length from the tip; the rest of the
        tool is shank (radius ``shank_radius``, default the tool radius), which
        must never touch the material.
        """
        return Envelope(
            Cylinder(TOOL, radius, length),
            self.holder,
            self.head,
            self.pivot_distance,
            cutting_length,
            shank_radius,
        )

    @property
    def cutter(self) -> Cylinder:
        """The cutting part of the tool (flutes), from the tip."""
        return self._stack()[0]

    def _stack(self) -> List[Cylinder]:
        """Cylinders from the tip: cutting part, shank (if any), holder, head."""
        cutting = self.cutting_length
        if cutting is None or cutting >= self.tool.length:
            return [self.tool, self.holder, self.head]
        shank = Cylinder(
            SHANK, self.shank_radius or self.tool.radius, self.tool.length - cutting
        )
        return [Cylinder(TOOL, self.tool.radius, cutting), shank, self.holder, self.head]

    def place(self, tip: Vector, b: float, c: float) -> List[CylinderPose]:
        """Cylinders for a tool tip at ``tip`` (part coordinates) and head angles B/C."""
        axis = bc_to_normal(b, c)
        poses: List[CylinderPose] = []
        offset = 0.0
        for cylinder in self._stack():
            poses.append(
                CylinderPose(
                    cylinder.name,
                    cylinder.radius,
                    _along(tip, axis, offset),
                    _along(tip, axis, offset + cylinder.length),
                )
            )
            offset += cylinder.length
        return poses

    def pivot(self, tip: Vector, b: float, c: float) -> Vector:
        """B pivot position for a tool tip and head angles."""
        return _along(tip, bc_to_normal(b, c), self.pivot_distance)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": [self.tool.radius, self.tool.length],
            "holder": [self.holder.radius, self.holder.length],
            "head": [self.head.radius, self.head.length],
            "pivot_distance": self.pivot_distance,
            "cutting_length": self.cutting_length,
            "shank_radius": self.shank_radius,
        }

    @classmethod
    def from_dict(cls, data: Optional[Mapping[str, Any]]) -> "Envelope":
        """Build from ``to_dict`` output; missing keys keep their defaults."""
        base = cls()
        if not data:
            return base

        def part(key: str, default: Cylinder) -> Cylinder:
            if key not in data:
                return default
            radius, length = data[key]
            return Cylinder(key, float(radius), float(length))

        return cls(
            part(TOOL, base.tool),
            part(HOLDER, base.holder),
            part(HEAD, base.head),
            float(data.get("pivot_distance", base.pivot_distance)),
            data.get("cutting_length"),
            data.get("shank_radius"),
        )


def _along(origin: Vector, axis: Vector, distance: float) -> Vector:
    return (
        origin[0] + axis[0] * distance,
        origin[1] + axis[1] * distance,
        origin[2] + axis[2] * distance,
    )

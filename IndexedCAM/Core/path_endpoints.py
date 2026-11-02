"""First and last tool positions of a CAM path, in the operation's local frame."""

from __future__ import annotations

import math
from typing import Any, Iterable, List, Optional, Tuple

Vector = Tuple[float, float, float]
Endpoints = Tuple[Vector, Vector]

_MOVES = {"G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"}
_ARCS = {"G2", "G02", "G3", "G03"}
_CLOCKWISE = {"G2", "G02"}


def path_endpoints(commands: Iterable[Any]) -> Optional[Endpoints]:
    """Return (first, last) XYZ of the motion commands, or None without motion.

    Axes a command omits keep the previous (modal) value; the axes missing
    before the first complete position default to 0.
    """
    position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    first: Optional[Vector] = None
    seen = False
    for command in commands:
        if str(command.Name).upper() not in _MOVES:
            continue
        for axis in position:
            if axis in command.Parameters:
                position[axis] = float(command.Parameters[axis])
        seen = True
        current = (position["X"], position["Y"], position["Z"])
        if first is None:
            first = current
    if not seen or first is None:
        return None
    return first, current


def _arc_points(
    start: Vector, end: Vector, centre: Tuple[float, float], clockwise: bool, step: float
) -> List[Vector]:
    """Points along an XY arc (Z interpolated), ending exactly at ``end``."""
    r_start = math.hypot(start[0] - centre[0], start[1] - centre[1])
    a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
    a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
    sweep = a1 - a0
    if clockwise and sweep >= 0:
        sweep -= 2 * math.pi
    elif not clockwise and sweep <= 0:
        sweep += 2 * math.pi
    count = max(1, math.ceil(abs(sweep) * r_start / step))
    points: List[Vector] = []
    for i in range(1, count):
        t = i / count
        angle = a0 + sweep * t
        points.append(
            (
                centre[0] + r_start * math.cos(angle),
                centre[1] + r_start * math.sin(angle),
                start[2] + (end[2] - start[2]) * t,
            )
        )
    points.append(end)
    return points


def path_points(commands: Iterable[Any], step: float = 5.0) -> List[Vector]:
    """Tool positions along a path, at most ``step`` mm apart.

    Straight moves are subdivided; G2/G3 arcs (XY plane, I/J centre) are
    tessellated. The first move starts from the first complete position.
    """
    if step <= 0:
        raise ValueError("step must be positive")
    position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    points: List[Vector] = []
    for command in commands:
        name = str(command.Name).upper()
        if name not in _MOVES:
            continue
        previous = (position["X"], position["Y"], position["Z"])
        for axis in position:
            if axis in command.Parameters:
                position[axis] = float(command.Parameters[axis])
        current = (position["X"], position["Y"], position["Z"])
        is_arc = name in _ARCS and ("I" in command.Parameters or "J" in command.Parameters)
        if points and is_arc:
            centre = (
                previous[0] + float(command.Parameters.get("I", 0.0)),
                previous[1] + float(command.Parameters.get("J", 0.0)),
            )
            points.extend(_arc_points(previous, current, centre, name in _CLOCKWISE, step))
            continue
        if points:
            length = math.dist(previous, current)
            count = max(1, math.ceil(length / step))
            for i in range(1, count):
                t = i / count
                points.append(tuple(a + (b - a) * t for a, b in zip(previous, current)))  # type: ignore[arg-type]
        points.append(current)
    return points

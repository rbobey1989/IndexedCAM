"""First and last tool positions of a CAM path, in the operation's local frame."""

from __future__ import annotations

import math
from typing import Any, Iterable, List, Optional, Tuple

Vector = Tuple[float, float, float]
Endpoints = Tuple[Vector, Vector]

_MOVES = {"G0", "G00", "G1", "G01", "G2", "G02", "G3", "G03"}


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


def path_points(commands: Iterable[Any], step: float = 5.0) -> List[Vector]:
    """Tool positions along a path, subdividing long moves to at most ``step`` mm.

    Arcs are approximated by their end points; the first move starts from the
    first complete position.
    """
    if step <= 0:
        raise ValueError("step must be positive")
    position = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    points: List[Vector] = []
    for command in commands:
        if str(command.Name).upper() not in _MOVES:
            continue
        previous = (position["X"], position["Y"], position["Z"])
        for axis in position:
            if axis in command.Parameters:
                position[axis] = float(command.Parameters[axis])
        current = (position["X"], position["Y"], position["Z"])
        if points:
            length = sum((a - b) ** 2 for a, b in zip(previous, current)) ** 0.5
            count = max(1, math.ceil(length / step))
            for i in range(1, count):
                t = i / count
                points.append(tuple(a + (b - a) * t for a, b in zip(previous, current)))  # type: ignore[arg-type]
        points.append(current)
    return points

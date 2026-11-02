"""First and last tool positions of a CAM path, in the operation's local frame."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple

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

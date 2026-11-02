"""Convert a face normal into a B/C orientation reachable by a machine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from IndexedCAM.Machine.bc_head import (
    SINGULARITY_TOLERANCE,
    BCAngles,
    normal_to_bc,
    verify_solution,
)
from IndexedCAM.Machine.bc_machine import BCMachine


class UnreachableOrientationError(ValueError):
    """No B/C pair within the machine limits aligns the tool with the normal."""


@dataclass(frozen=True)
class OrientationSolution:
    """Chosen B/C angles plus every other reachable equivalent solution."""

    angles: BCAngles
    alternatives: Tuple[BCAngles, ...]


class OrientationSolver:
    """Pick the best reachable B/C solution for a tool-axis direction.

    For a non-vertical normal two families of solutions exist:
    (B, C + 360k) and (-B, C + 180 + 360k). Candidates outside the machine
    limits are discarded. With ``previous`` the solution needing the least C
    (then B) travel wins; otherwise B >= 0 and the smallest |C| are preferred.
    """

    def __init__(self, machine: Optional[BCMachine] = None) -> None:
        self.machine = machine or BCMachine()

    def solve(
        self,
        normal: Sequence[float],
        previous: Optional[BCAngles] = None,
    ) -> OrientationSolution:
        previous_c = previous.c if previous is not None else None
        base = normal_to_bc(normal, previous_c=previous_c)
        candidates = self._candidates(base)
        reachable = [
            a
            for a in candidates
            if self.machine.is_reachable(a.b, a.c) and verify_solution(normal, a)
        ]
        if not reachable:
            raise UnreachableOrientationError(
                "normal {} is not reachable within B{} C{} limits".format(
                    tuple(normal),
                    (self.machine.b_limits.minimum, self.machine.b_limits.maximum),
                    (self.machine.c_limits.minimum, self.machine.c_limits.maximum),
                )
            )
        ordered = sorted(reachable, key=self._key(previous))
        return OrientationSolution(ordered[0], tuple(ordered[1:]))

    @staticmethod
    def _candidates(base: BCAngles) -> List[BCAngles]:
        singular = math.sin(math.radians(base.b)) < SINGULARITY_TOLERANCE
        found: List[BCAngles] = []
        for k in (-1, 0, 1):
            found.append(BCAngles(base.b, base.c + 360.0 * k))
            if not singular:
                found.append(BCAngles(-base.b, base.c + 180.0 + 360.0 * k))
        return found

    @staticmethod
    def _key(previous: Optional[BCAngles]):
        if previous is None:
            return lambda a: (a.b < 0, abs(a.c), a.c)
        return lambda a: (abs(a.c - previous.c), abs(a.b - previous.b), a.b < 0)

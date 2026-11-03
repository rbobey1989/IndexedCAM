"""Where an operation's tool path and tool lie in part coordinates (pure logic)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import local_to_part
from IndexedCAM.Core.path_endpoints import path_points
from IndexedCAM.Core.preview import decimate

Vector = Tuple[float, float, float]


@dataclass(frozen=True)
class OperationPose:
    """The path of an operation in part coordinates plus the tool's B/C."""

    points: List[Vector]
    b: float
    c: float

    @property
    def tip(self) -> Vector:
        return self.points[0]


def operation_pose(setup: IndexedSetup, commands: Sequence[Any]) -> OperationPose:
    """Path of ``commands`` (local frame of ``setup``) moved onto the part."""
    frame = setup.local_frame()
    points = [local_to_part(frame, p) for p in decimate(path_points(commands, step=2.0))]
    return OperationPose(points, setup.b, setup.c)

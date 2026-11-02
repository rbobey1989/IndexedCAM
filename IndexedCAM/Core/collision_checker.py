"""Collision checking of the tool/holder/head envelope with ``Part`` (FreeCAD).

``PartCollisionChecker`` implements the ``CollisionChecker`` protocol of the
transition planner. Obstacles are in part coordinates. *Cuttable* obstacles
(the model and the stock) are meant to be touched by the cutting tool, so while
machining the tool cylinder is not tested against them; the holder and the head
always are, and fixtures are tested against everything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

from IndexedCAM.Core.path_endpoints import path_points
from IndexedCAM.Core.local_placement import local_to_part
from IndexedCAM.Machine.envelope import TOOL, Envelope

Vector = Tuple[float, float, float]


@dataclass(frozen=True)
class Obstacle:
    name: str
    shape: Any
    cuttable: bool = False


class PartCollisionChecker:
    """Minimum-distance test of the envelope against the obstacles."""

    def __init__(
        self, envelope: Envelope, obstacles: Sequence[Obstacle], margin: float = 2.0
    ) -> None:
        if margin < 0 or not math.isfinite(margin):
            raise ValueError("margin must be a non-negative finite number")
        self._envelope = envelope
        self._obstacles = list(obstacles)
        self._margin = margin

    def collision(self, tip: Vector, b: float, c: float) -> Optional[str]:
        """Transit check: every cylinder against every obstacle."""
        return self._check(tip, b, c, cutting=False)

    def cutting_collision(self, tip: Vector, b: float, c: float) -> Optional[str]:
        """Machining check: the tool may touch the cuttable obstacles."""
        return self._check(tip, b, c, cutting=True)

    def _check(self, tip: Vector, b: float, c: float, cutting: bool) -> Optional[str]:
        import FreeCAD
        import Part

        for pose in self._envelope.place(tip, b, c):
            start = FreeCAD.Vector(*pose.start)
            axis = FreeCAD.Vector(*pose.end) - start
            body = Part.makeCylinder(pose.radius, axis.Length, start, axis)
            reach = body.BoundBox
            for obstacle in self._obstacles:
                if cutting and pose.name == TOOL and obstacle.cuttable:
                    continue
                box = obstacle.shape.BoundBox
                if _gap(reach, box) > self._margin:
                    continue
                distance = body.distToShape(obstacle.shape)[0]
                if distance < self._margin:
                    return "{} contra {} (distancia {:.2f} mm < margen {:.2f} mm)".format(
                        pose.name, obstacle.name, distance, self._margin
                    )
        return None


def _gap(a: Any, b: Any) -> float:
    """Distance between two bounding boxes along the worst axis (0 if they overlap)."""
    return max(
        0.0,
        max(a.XMin - b.XMax, b.XMin - a.XMax),
        max(a.YMin - b.YMax, b.YMin - a.YMax),
        max(a.ZMin - b.ZMax, b.ZMin - a.ZMax),
    )


def check_operation(
    check: Callable[[Vector, float, float], Optional[str]],
    commands: Iterable[Any],
    frame: Any,
    b: float,
    c: float,
    step: float = 5.0,
) -> Optional[str]:
    """First collision along an operation path, or None.

    ``frame`` is the Setup's ``LocalFrame``; path points are local and become
    part coordinates. Returns the message with the offending position.
    """
    for local in path_points(commands, step):
        tip = local_to_part(frame, local)
        hit = check(tip, b, c)
        if hit:
            return "en ({:.1f}, {:.1f}, {:.1f}): {}".format(*tip, hit)
    return None


def obstacles_from_job(source: Any, job: Any, fixtures: Iterable[Any] = ()) -> List[Obstacle]:
    """Model and stock (cuttable) plus any extra fixture objects."""
    result = [Obstacle(source.Label, source.Shape, cuttable=True)]
    stock = getattr(job, "Stock", None)
    if stock is not None and getattr(stock, "Shape", None) is not None:
        result.append(Obstacle("bruto", stock.Shape, cuttable=True))
    result.extend(Obstacle(f.Label, f.Shape) for f in fixtures)
    return result

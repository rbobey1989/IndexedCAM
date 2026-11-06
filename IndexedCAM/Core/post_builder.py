"""Turn chained program steps into a ``PostProgram`` (no FreeCAD needed).

The builder groups consecutive steps that share a Setup into one orientation,
attaches the tool and spindle of each operation and computes the two heights
the post needs, both as local Z (``safe_z`` is outside the safety sphere, so
the head can index there; ``clearance_z`` is where each orientation starts).
"""

from __future__ import annotations

from typing import Mapping, Optional, Protocol, Sequence

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.post_program import (
    PostMove,
    PostOperation,
    PostOrientation,
    PostProgram,
    PostTool,
)
from IndexedCAM.Core.program import ChainedStep
from IndexedCAM.Core.transition_planner import SafetySphere
from IndexedCAM.Machine.bc_head import Vector


class PostResources(Protocol):
    """What the builder needs from the document (faked in tests)."""

    def moves(self, operation: str) -> Sequence[PostMove]: ...

    def tool(self, operation: str) -> PostTool: ...

    def spindle(self, operation: str) -> Optional[int]: ...

    def coolant(self, operation: str) -> str: ...


def local_z(frame: object, point: Vector) -> float:
    """Z of a part point in a local frame (``origin``/``z_axis``)."""
    origin = getattr(frame, "origin")
    axis = getattr(frame, "z_axis")
    return sum((p - o) * a for p, o, a in zip(point, origin, axis))


def safe_height(frame: object, sphere: SafetySphere) -> float:
    """Local Z above which the tip is outside the safety sphere, whatever X/Y."""
    return local_z(frame, sphere.center) + sphere.radius


def clearance_height(moves: Sequence[PostMove], safe_z: float) -> float:
    """First Z of the path (where CAM sends the tool to start).

    Only used when it is a sane approach: between the face (local Z = 0) and
    ``safe_z``. A path that starts below the face would otherwise rapid into
    the part, so the approach stays at ``safe_z`` and the path descends itself.
    """
    for move in moves:
        for letter, value in move.words:
            if letter == "Z":
                return value if 0.0 <= value <= safe_z else safe_z
    return safe_z


class PostBuilder:
    """Chained steps + resources -> ``PostProgram``."""

    def __init__(
        self,
        setups: Mapping[str, IndexedSetup],
        resources: PostResources,
        sphere: SafetySphere,
        name: str = "",
    ) -> None:
        self._setups = setups
        self._resources = resources
        self._sphere = sphere
        self._name = name

    def build(self, items: Sequence[ChainedStep]) -> PostProgram:
        orientations = []
        for setup_name, operations in self._group(items):
            setup = self._setups[setup_name]
            frame = setup.local_frame()
            safe_z = safe_height(frame, self._sphere)
            first_moves = operations[0].moves if operations else ()
            orientations.append(
                PostOrientation(
                    name=setup.name,
                    b=setup.b,
                    c=setup.c,
                    wcs=setup.wcs,
                    origin=frame.origin,
                    x_axis=frame.x_axis,
                    y_axis=frame.y_axis,
                    z_axis=frame.z_axis,
                    safe_z=safe_z,
                    clearance_z=clearance_height(first_moves, safe_z),
                    operations=tuple(operations),
                )
            )
        return PostProgram(name=self._name, orientations=tuple(orientations))

    def _group(
        self, items: Sequence[ChainedStep]
    ) -> Sequence[tuple]:
        """(setup name, operations) runs, skipping steps without moves."""
        groups: list = []
        for item in items:
            operation = self._operation(item.step.operation)
            if not operation.moves:
                continue
            name = item.step.setup
            if groups and groups[-1][0] == name:
                groups[-1][1].append(operation)
            else:
                groups.append((name, [operation]))
        return groups

    def _operation(self, name: str) -> PostOperation:
        moves = tuple(self._resources.moves(name))
        return PostOperation(
            name=name,
            title=name,
            tool=self._resources.tool(name),
            moves=moves,
            spindle=self._resources.spindle(name),
            coolant=self._resources.coolant(name),
        )

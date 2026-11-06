"""Machine-independent model of the program to post (no FreeCAD needed).

A ``PostProgram`` is a flat list of orientations, each holding the operations
run in it. Moves are kept in the local frame of their orientation: under an
indexed work plane (``G68.2``) that is exactly what the controller expects, and
under machine coordinates it is the frame the post transforms from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from IndexedCAM.Machine.bc_head import Vector

MM, INCH = "mm", "in"


@dataclass(frozen=True)
class PostTool:
    """A cutting tool as the controller knows it."""

    number: int
    name: str = ""
    diameter: float = 0.0

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("tool number must be 1 or greater")

    def describe(self) -> str:
        text = "T{}".format(self.number)
        if self.name:
            text += " " + self.name
        if self.diameter > 0.0:
            text += " D{:g}".format(self.diameter)
        return text


@dataclass(frozen=True)
class PostMove:
    """One motion block: ``code`` plus its words, in order."""

    code: str
    words: Tuple[Tuple[str, float], ...] = ()
    comment: str = ""

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("move code must not be empty")

    @property
    def parameters(self) -> Dict[str, float]:
        return dict(self.words)

    def is_arc(self) -> bool:
        return self.code.upper() in ("G2", "G3")


@dataclass(frozen=True)
class PostOperation:
    """The moves of one CAM operation, in the local frame of its orientation."""

    name: str
    title: str
    tool: PostTool
    moves: Tuple[PostMove, ...]
    spindle: Optional[int] = None
    coolant: str = ""  # "", "flood" or "mist"

    def __post_init__(self) -> None:
        object.__setattr__(self, "moves", tuple(self.moves))
        if self.spindle is not None and self.spindle < 1:
            raise ValueError("spindle speed must be 1 or greater")
        if self.coolant not in ("", "flood", "mist"):
            raise ValueError("coolant must be '', 'flood' or 'mist'")


@dataclass(frozen=True)
class PostOrientation:
    """One indexed orientation: head angles, work plane and its operations."""

    name: str
    b: float
    c: float
    wcs: str
    origin: Vector
    x_axis: Vector
    y_axis: Vector
    z_axis: Vector
    safe_z: float
    clearance_z: float
    operations: Tuple[PostOperation, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "operations", tuple(self.operations))
        if not self.name.strip():
            raise ValueError("orientation name must not be empty")
        if not self.wcs.strip():
            raise ValueError("wcs must not be empty")
        if self.clearance_z > self.safe_z + 1e-9:
            raise ValueError("clearance must not be above the safe height")


@dataclass(frozen=True)
class PostProgram:
    """Orientations in program order, ready to be rendered as G-code."""

    name: str = ""
    orientations: Tuple[PostOrientation, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "orientations", tuple(self.orientations))

    def __len__(self) -> int:
        return len(self.orientations)

    @property
    def empty(self) -> bool:
        return not any(o.operations for o in self.orientations)

    def operations(self) -> List[Tuple[PostOrientation, PostOperation]]:
        return [(o, op) for o in self.orientations for op in o.operations]

    def tools(self) -> List[PostTool]:
        """Distinct tools in first-use order."""
        seen: Dict[int, PostTool] = {}
        for _, operation in self.operations():
            seen.setdefault(operation.tool.number, operation.tool)
        return list(seen.values())

    def moves(self) -> List[PostMove]:
        return [move for _, operation in self.operations() for move in operation.moves]


def moves_from_commands(commands: Sequence[object]) -> Tuple[PostMove, ...]:
    """Convert CAM ``Path.Command`` objects into ``PostMove`` (duck-typed).

    A feed of zero (CAM emits ``G0 F0`` on some retracts) is dropped: a
    controller would keep it as the modal feed of the next cutting move.
    """
    moves: List[PostMove] = []
    for command in commands:
        code = str(getattr(command, "Name", "")).strip()
        if not code:
            continue
        words = tuple(
            (str(letter), float(value))
            for letter, value in dict(getattr(command, "Parameters", {})).items()
            if not (str(letter) == "F" and float(value) <= 0.0)
        )
        moves.append(PostMove(code, words))
    return tuple(moves)

"""The operation program: an ordered chain of (Setup, operation) steps.

Pure logic, no FreeCAD. Each step continues from the end point of the previous
one; between steps of different Setups a transition (retract, B/C turn,
approach) is needed, which later issues plan and check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import local_to_part

Vector = Tuple[float, float, float]


class ProgramStorage(Protocol):
    def load(self) -> List[Dict[str, Any]]: ...

    def save(self, steps: Sequence[Mapping[str, Any]]) -> None: ...


class MemoryProgramStorage:
    def __init__(self) -> None:
        self._data: List[Dict[str, Any]] = []

    def load(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._data]

    def save(self, steps: Sequence[Mapping[str, Any]]) -> None:
        self._data = [dict(item) for item in steps]


@dataclass(frozen=True)
class Step:
    """One operation executed in one Setup."""

    setup: str
    operation: str


@dataclass(frozen=True)
class Pose:
    """Tool tip (part coordinates) with the head angles that hold it."""

    b: float
    c: float
    point: Vector


@dataclass(frozen=True)
class ChainedStep:
    """A step with where it starts/ends and how it joins the previous step."""

    step: Step
    start: Optional[Pose]
    end: Optional[Pose]
    previous: Optional[Pose]
    needs_transition: bool


class Program:
    """Ordered steps, persisted after every change."""

    def __init__(self, storage: ProgramStorage) -> None:
        self._storage = storage
        self._steps: List[Step] = [Step(d["setup"], d["operation"]) for d in storage.load()]

    def _persist(self) -> None:
        self._storage.save([{"setup": s.setup, "operation": s.operation} for s in self._steps])

    def steps(self) -> List[Step]:
        return list(self._steps)

    def __len__(self) -> int:
        return len(self._steps)

    def _index(self, operation: str) -> int:
        for i, step in enumerate(self._steps):
            if step.operation == operation:
                return i
        raise KeyError("operation not in program: {}".format(operation))

    def add(self, step: Step) -> None:
        if any(s.operation == step.operation for s in self._steps):
            raise ValueError("operation already in program: {}".format(step.operation))
        self._steps.append(step)
        self._persist()

    def remove(self, operation: str) -> None:
        del self._steps[self._index(operation)]
        self._persist()

    def move(self, operation: str, position: int) -> None:
        """Move a step to ``position`` (0-based, clamped)."""
        index = self._index(operation)
        position = max(0, min(position, len(self._steps) - 1))
        self._steps.insert(position, self._steps.pop(index))
        self._persist()

    def rename_setup(self, old: str, new: str) -> None:
        self._steps = [Step(new, s.operation) if s.setup == old else s for s in self._steps]
        self._persist()

    def sync(self, bound: Sequence[Step]) -> bool:
        """Follow the operations that exist (``bound``, in Job order).

        Steps whose operation is gone are dropped, operations not yet in the
        program are appended, and the setup of a kept step is refreshed. The
        user's order is preserved. Returns True if anything changed.
        """
        current = {s.operation: s for s in bound}
        steps = [current[s.operation] for s in self._steps if s.operation in current]
        known = {s.operation for s in steps}
        steps += [s for s in bound if s.operation not in known]
        if steps == self._steps:
            return False
        self._steps = steps
        self._persist()
        return True


def chain(
    program: Program,
    setups: Mapping[str, IndexedSetup],
    endpoints: Mapping[str, Optional[Tuple[Vector, Vector]]],
) -> List[ChainedStep]:
    """Resolve the program into chained steps.

    ``endpoints`` maps an operation name to its (first, last) local point (see
    ``path_endpoints``). ``previous`` is the end pose of the closest earlier
    step with motion (None for the first step, which starts from the initial
    safe position). A transition is needed when the Setup changes.
    """
    result: List[ChainedStep] = []
    previous: Optional[Pose] = None
    previous_setup: Optional[str] = None
    for step in program.steps():
        setup = setups[step.setup]
        frame = setup.local_frame()
        points = endpoints.get(step.operation)
        start = end = None
        if points is not None:
            start = Pose(setup.b, setup.c, local_to_part(frame, points[0]))
            end = Pose(setup.b, setup.c, local_to_part(frame, points[1]))
        result.append(
            ChainedStep(
                step=step,
                start=start,
                end=end,
                previous=previous,
                needs_transition=previous_setup is not None and previous_setup != step.setup,
            )
        )
        if end is not None:
            previous = end
        previous_setup = step.setup
    return result


def describe(item: ChainedStep, number: int) -> str:
    """One-line summary of a chained step for lists and logs."""
    text = "{}. {} → {}".format(number, item.step.setup, item.step.operation)
    if item.start is None:
        return text + "  (sin movimientos)"
    if item.previous is None:
        return text + "  [desde posición segura inicial]"
    if item.needs_transition:
        return text + "  [transición B{:.1f}/C{:.1f} → B{:.1f}/C{:.1f}]".format(
            item.previous.b, item.previous.c, item.start.b, item.start.c
        )
    return text + "  [continúa del paso anterior]"

"""Preview model: the tool poses to show for each step of the program.

Pure logic (no FreeCAD, no Coin3D). A ``Clip`` is a sequence of tool samples,
either the machining path of an operation or the transition between two steps.
Collisions are evaluated lazily per sample (and cached) so that building a clip
is cheap and the viewer only pays for the samples it actually shows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import local_to_part
from IndexedCAM.Core.program import ChainedStep
from IndexedCAM.Core.transition_planner import TransitionPlanner
from IndexedCAM.Machine.bc_head import Vector
from IndexedCAM.Machine.envelope import CylinderPose, Envelope

OPERATION, TRANSITION = "operation", "transition"
MAX_PATH_FRAMES = 400

Probe = Callable[[Vector, float, float], Optional[str]]


@dataclass(frozen=True)
class PreviewFrame:
    tip: Vector
    b: float
    c: float
    label: str = ""


@dataclass
class Clip:
    kind: str
    title: str
    step_index: int
    frames: List[PreviewFrame]
    envelope: Envelope
    probe: Probe
    error: Optional[str] = None
    tool: str = ""
    _cache: Dict[int, Optional[str]] = field(default_factory=dict, repr=False)

    def __len__(self) -> int:
        return len(self.frames)

    def poses(self, index: int) -> List[CylinderPose]:
        frame = self.frames[index]
        return self.envelope.place(frame.tip, frame.b, frame.c)

    def collision(self, index: int) -> Optional[str]:
        if index not in self._cache:
            frame = self.frames[index]
            self._cache[index] = self.probe(frame.tip, frame.b, frame.c)
        return self._cache[index]

    def first_collision(self) -> Optional[int]:
        """Index of the first colliding sample, or None."""
        for index in range(len(self.frames)):
            if self.collision(index):
                return index
        return None

    def tips(self) -> List[Vector]:
        return [f.tip for f in self.frames]


class StepResources(Protocol):
    """What the builder needs from the document (faked in tests)."""

    def envelope(self, operation: str) -> Envelope: ...

    def checker(self, operation: str) -> "StepChecker": ...

    def local_path(self, operation: str) -> Sequence[Vector]: ...


class StepChecker(Protocol):
    def collision(self, tip: Vector, b: float, c: float) -> Optional[str]: ...

    def cutting_collision(self, tip: Vector, b: float, c: float) -> Optional[str]: ...


def decimate(points: Sequence[Vector], limit: int = MAX_PATH_FRAMES) -> List[Vector]:
    """At most ``limit`` points, always keeping the first and the last."""
    if len(points) <= limit:
        return list(points)
    stride = (len(points) - 1) / (limit - 1)
    return [points[round(i * stride)] for i in range(limit)]


class PreviewBuilder:
    """Turns chained steps into clips: one per operation, plus one per transition."""

    def __init__(
        self,
        setups: Dict[str, IndexedSetup],
        resources: StepResources,
        planner_for: Callable[[str], TransitionPlanner],
    ) -> None:
        self._setups = setups
        self._resources = resources
        self._planner_for = planner_for

    def build(self, items: Sequence[ChainedStep]) -> List[Clip]:
        clips: List[Clip] = []
        for index, item in enumerate(items):
            if item.needs_transition and item.previous is not None and item.start is not None:
                clips.append(self._transition(index, item))
            clips.append(self._operation(index, item))
        return clips

    def _tool_label(self, operation: str) -> str:
        label = getattr(self._resources, "tool_label", None)
        return label(operation) if label is not None else describe_tool(self._resources.envelope(operation))

    def _transition(self, index: int, item: ChainedStep) -> Clip:
        assert item.previous is not None and item.start is not None
        operation = item.step.operation
        result = self._planner_for(operation).try_plan(item.previous, item.start)
        samples = result.shown.samples if result.shown is not None else ()
        frames = [PreviewFrame(s.tip, s.b, s.c, s.phase) for s in samples]
        return Clip(
            TRANSITION,
            "{}. Transición → {}".format(index + 1, item.step.setup),
            index,
            frames,
            self._resources.envelope(operation),
            self._resources.checker(operation).collision,
            result.error,
            self._tool_label(operation),
        )

    def _operation(self, index: int, item: ChainedStep) -> Clip:
        step = item.step
        setup = self._setups[step.setup]
        frame = setup.local_frame()
        points = decimate(self._resources.local_path(step.operation))
        frames = [PreviewFrame(local_to_part(frame, p), setup.b, setup.c) for p in points]
        return Clip(
            OPERATION,
            "{}. {} → {}".format(index + 1, step.setup, step.operation),
            index,
            frames,
            self._resources.envelope(step.operation),
            self._resources.checker(step.operation).cutting_collision,
            tool=self._tool_label(step.operation),
        )


def describe_tool(envelope: Envelope) -> str:
    """Short description of the cutting tool of ``envelope``."""
    tool = envelope.tool
    text = "Ø{:g} mm, largo {:g} mm".format(2 * tool.radius, tool.length)
    if envelope.cutting_length is not None:
        text += ", corte {:g} mm".format(envelope.cutting_length)
    return text


def sphere_for(bound_box: Tuple[Vector, Vector], envelope: Envelope, margin: float = 10.0):
    """Safety sphere around a bounding box given as (min corner, max corner)."""
    from IndexedCAM.Core.transition_planner import SafetySphere

    low, high = bound_box
    center = tuple((a + b) / 2.0 for a, b in zip(low, high))
    half_diagonal = sum((b - a) ** 2 for a, b in zip(low, high)) ** 0.5 / 2.0
    return SafetySphere.around(center, half_diagonal, envelope, margin)  # type: ignore[arg-type]

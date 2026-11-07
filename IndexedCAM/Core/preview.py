"""Preview model: the tool poses to show for each step of the program.

Pure logic (no FreeCAD, no Coin3D). A ``Clip`` is a sequence of tool samples,
either the machining path of an operation or the transition between two steps.
Collisions are evaluated lazily per sample (and cached) so that building a clip
is cheap and the viewer only pays for the samples it actually shows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.local_placement import local_to_part
from IndexedCAM.Core.program import ChainedStep
from IndexedCAM.Core.transition_planner import RETRACT, TURN, SafetySphere, TransitionPlanner
from IndexedCAM.Machine.bc_head import Vector, bc_to_normal
from IndexedCAM.Machine.envelope import CylinderPose, Envelope

OPERATION, TRANSITION, PARKING = "operation", "transition", "parking"
MAX_PATH_FRAMES = 400
RETRACT_STEP = 5.0
TURN_STEP = 2.0

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
    tool_mesh: Any = None
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
    """Turns chained steps into clips: one per operation, plus one per transition.

    When the program ends with the head tilted, a last ``PARKING`` clip shows
    what the post processor does then: retract along the tool axis and bring the
    head back to vertical, which is also why the head is not left tilted.
    """

    def __init__(
        self,
        setups: Dict[str, IndexedSetup],
        resources: StepResources,
        planner_for: Callable[[str], TransitionPlanner],
        sphere: Optional[SafetySphere] = None,
    ) -> None:
        self._setups = setups
        self._resources = resources
        self._planner_for = planner_for
        self._sphere = sphere

    def build(self, items: Sequence[ChainedStep]) -> List[Clip]:
        clips: List[Clip] = []
        for index, item in enumerate(items):
            if item.needs_transition and item.previous is not None and item.start is not None:
                clips.append(self._transition(index, item))
            clips.append(self._operation(index, item))
        parking = None
        if clips and items:
            parking = self._parking(len(items), clips[-1], self._setups[items[-1].step.setup])
        if parking is not None:
            clips.append(parking)
        return clips

    def _tool_mesh(self, operation: str) -> Any:
        mesh = getattr(self._resources, "tool_mesh", None)
        return mesh(operation) if mesh is not None else None

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
            self._tool_mesh(operation),
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
            tool_mesh=self._tool_mesh(step.operation),
        )


    def _parking(self, index: int, last: Clip, setup: IndexedSetup) -> Optional[Clip]:
        """Retract and bring the head back to vertical, as the post does.

        The retract is the same one the post emits: stay in the plane and raise
        the tip to the safety height (``safe_z``), then rotate with the tip held,
        which is what the controller does with an indexed head. Needs the safety
        sphere, both for that height and so nothing is shown turning inside the
        material.
        """
        if self._sphere is None or not last.frames:
            return None
        frame = last.frames[-1]
        if abs(frame.b) < 1e-9 and abs(frame.c) < 1e-9:
            return None
        from IndexedCAM.Core.post_builder import local_z

        local_frame = setup.local_frame()
        safe = local_z(local_frame, self._sphere.center) + self._sphere.radius
        axis = bc_to_normal(frame.b, frame.c)
        distance = max(0.0, safe - local_z(local_frame, frame.tip))
        frames: List[PreviewFrame] = []
        count = max(1, int(math.ceil(distance / RETRACT_STEP))) if distance else 0
        for i in range(1, count + 1):
            frames.append(
                PreviewFrame(
                    tuple(p + a * distance * i / count for p, a in zip(frame.tip, axis)),  # type: ignore[arg-type]
                    frame.b,
                    frame.c,
                    RETRACT,
                )
            )
        out = frames[-1].tip if frames else frame.tip
        steps = max(1, int(math.ceil(max(abs(frame.b), abs(frame.c)) / TURN_STEP)))
        for i in range(1, steps + 1):
            t = i / steps
            frames.append(PreviewFrame(out, frame.b * (1.0 - t), frame.c * (1.0 - t), TURN))
        return Clip(
            PARKING,
            "Fin: retirada y cabezal vertical",
            index,
            frames,
            last.envelope,
            last.probe,
            tool=last.tool,
            tool_mesh=last.tool_mesh,
        )


@dataclass(frozen=True)
class Playlist:
    """Frames of the clips the user ticked, in order.

    ``entries[position]`` is ``(clip index, frame index)``, so the player can
    run several clips one after another and the viewer still knows which clip
    (tool, envelope, stock) every frame belongs to.
    """

    entries: Tuple[Tuple[int, int], ...] = ()

    @classmethod
    def of(cls, clips: Sequence[Clip], selected: Optional[Sequence[int]] = None) -> "Playlist":
        indices = range(len(clips)) if selected is None else sorted(set(selected))
        return cls(
            tuple(
                (index, frame)
                for index in indices
                if 0 <= index < len(clips)
                for frame in range(len(clips[index]))
            )
        )

    def __len__(self) -> int:
        return len(self.entries)

    def at(self, position: int) -> Optional[Tuple[int, int]]:
        if not self.entries:
            return None
        return self.entries[max(0, min(position, len(self.entries) - 1))]

    def clips(self) -> List[int]:
        return sorted({index for index, _ in self.entries})

    def first_in(self, clip: int) -> Optional[int]:
        """Position of the first frame of ``clip``, or None if it is not played."""
        for position, (index, _) in enumerate(self.entries):
            if index == clip:
                return position
        return None


def describe_tool(envelope: Envelope) -> str:
    """Short description of the cutting tool of ``envelope``."""
    tool = envelope.tool
    text = "Ø{:g} mm, largo {:g} mm".format(2 * tool.radius, tool.length)
    if envelope.cutting_length is not None:
        text += ", corte {:g} mm".format(envelope.cutting_length)
    return text


def sphere_for(bound_box: Tuple[Vector, Vector], margin: float = 0.0):
    """Safety sphere around a bounding box given as (min corner, max corner).

    Its radius is the part's half-diagonal plus ``margin``: the tip turns on
    that sphere with the tool pointing outward, so this is the smallest radius
    that keeps the whole envelope clear of the part.
    """
    from IndexedCAM.Core.transition_planner import SafetySphere

    low, high = bound_box
    center = tuple((a + b) / 2.0 for a, b in zip(low, high))
    half_diagonal = sum((b - a) ** 2 for a, b in zip(low, high)) ** 0.5 / 2.0
    return SafetySphere.around(center, half_diagonal, margin)  # type: ignore[arg-type]

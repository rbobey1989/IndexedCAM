"""What the native CAM simulator needs to tilt its tool.

The plan maps each indexed operation to its head angles and to the transition
that leads to it; ``TiltScript`` turns that into the poses to show, one per
simulator tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from IndexedCAM.Core.preview import OPERATION, TRANSITION, Clip, PreviewFrame
from IndexedCAM.Core.program import ChainedStep


@dataclass(frozen=True)
class SimulationPlan:
    orientations: Dict[str, Tuple[float, float]]
    transitions: Dict[str, List[PreviewFrame]]

    def orientation(self, operation: str) -> Optional[Tuple[float, float]]:
        return self.orientations.get(operation)

    def transition(self, operation: str) -> List[PreviewFrame]:
        return list(self.transitions.get(operation, ()))


def plan_from_clips(items: Sequence[ChainedStep], clips: Sequence[Clip]) -> SimulationPlan:
    orientations: Dict[str, Tuple[float, float]] = {}
    transitions: Dict[str, List[PreviewFrame]] = {}
    for clip in clips:
        operation = items[clip.step_index].step.operation
        if clip.kind == TRANSITION:
            transitions[operation] = list(clip.frames)
        elif clip.kind == OPERATION and clip.frames:
            orientations[operation] = (clip.frames[0].b, clip.frames[0].c)
    return SimulationPlan(orientations, transitions)


@dataclass
class TiltScript:
    """Per-simulation state: plays the transition when an operation starts."""

    plan: SimulationPlan
    _current: Optional[str] = field(default=None, repr=False)
    _queue: List[PreviewFrame] = field(default_factory=list, repr=False)

    def reset(self) -> None:
        self._current = None
        self._queue = []

    def enter(self, operation: str) -> None:
        if operation != self._current:
            self._current = operation
            self._queue = self.plan.transition(operation)

    def next_transition_frame(self) -> Optional[PreviewFrame]:
        return self._queue.pop(0) if self._queue else None

    def pending(self) -> bool:
        return bool(self._queue)

    def skip(self) -> None:
        self._queue = []

    def orientation(self, operation: str) -> Optional[Tuple[float, float]]:
        return self.plan.orientation(operation)

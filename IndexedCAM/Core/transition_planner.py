"""Plan the move between two steps of different Setups (no FreeCAD needed).

Route: retract along the previous tool axis until the tip is outside the safety
sphere, go to the sphere, turn B/C with the tip sliding on the sphere and the
tool pointing radially outward, then approach along the next tool axis. Every
sample is validated (axis limits and an injected collision checker); a
transition that is not fully validated is never returned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple

from IndexedCAM.Core.program import ChainedStep, Pose
from IndexedCAM.Machine.bc_head import Vector, bc_to_normal
from IndexedCAM.Machine.bc_machine import BCMachine
from IndexedCAM.Machine.envelope import Envelope

RETRACT, TO_SPHERE, TURN, FROM_SPHERE, APPROACH = (
    "retract",
    "to_sphere",
    "turn",
    "from_sphere",
    "approach",
)


class CollisionChecker(Protocol):
    def collision(self, tip: Vector, b: float, c: float) -> Optional[str]:
        """Describe the obstacle hit by the envelope at this pose, or None."""


class TransitionError(ValueError):
    """No collision-free transition was found."""


@dataclass(frozen=True)
class SafetySphere:
    center: Vector
    radius: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.radius) or self.radius <= 0.0:
            raise ValueError("sphere radius must be a positive finite number")

    @classmethod
    def around(
        cls,
        center: Vector,
        half_diagonal: float,
        envelope: Envelope,
        margin: float = 10.0,
    ) -> "SafetySphere":
        """Stock half-diagonal + tool and holder length + margin."""
        return cls(center, half_diagonal + envelope.tool.length + envelope.holder.length + margin)

    def scaled(self, factor: float) -> "SafetySphere":
        return SafetySphere(self.center, self.radius * factor)


@dataclass(frozen=True)
class Sample:
    tip: Vector
    b: float
    c: float
    phase: str


@dataclass(frozen=True)
class Transition:
    samples: Tuple[Sample, ...]
    target_b: float
    target_c: float

    @property
    def turn(self) -> List[Sample]:
        return [s for s in self.samples if s.phase == TURN]


def _add(p: Vector, q: Vector, k: float = 1.0) -> Vector:
    return (p[0] + q[0] * k, p[1] + q[1] * k, p[2] + q[2] * k)


def _sub(p: Vector, q: Vector) -> Vector:
    return (p[0] - q[0], p[1] - q[1], p[2] - q[2])


def _dot(p: Vector, q: Vector) -> float:
    return p[0] * q[0] + p[1] * q[1] + p[2] * q[2]


def _norm(p: Vector) -> float:
    return math.sqrt(_dot(p, p))


def _lerp(p: Vector, q: Vector, t: float) -> Vector:
    return _add(p, _sub(q, p), t)


def exit_distance(tip: Vector, axis: Vector, sphere: SafetySphere) -> float:
    """Distance to travel from ``tip`` along ``axis`` to leave the sphere (0 if outside)."""
    d = _sub(tip, sphere.center)
    if _norm(d) >= sphere.radius:
        return 0.0
    along = _dot(d, axis)
    disc = along * along - (_dot(d, d) - sphere.radius ** 2)
    return -along + math.sqrt(disc)


def equivalent_targets(
    machine: BCMachine, b: float, c: float, start_b: float, start_c: float
) -> List[Tuple[float, float]]:
    """Reachable (B, C) giving the same tool axis, nearest to the start first.

    Covers C ±360° turns and the mirrored solution (−B, C+180°).
    """
    found = set()
    for base_b, base_c in ((b, c), (-b, c + 180.0)):
        for turns in range(-3, 4):
            candidate_c = base_c + 360.0 * turns
            if machine.is_reachable(base_b, candidate_c):
                found.add((round(base_b, 9), round(candidate_c, 9)))
    return sorted(found, key=lambda t: (abs(t[0] - start_b) + abs(t[1] - start_c), t))


@dataclass(frozen=True)
class PlanResult:
    """``transition`` is validated or None; ``shown`` is what to display."""

    transition: Optional[Transition]
    shown: Optional[Transition]
    error: Optional[str]


class TransitionPlanner:
    """Builds validated transitions between two poses."""

    def __init__(
        self,
        machine: BCMachine,
        checker: CollisionChecker,
        sphere: SafetySphere,
        angle_step: float = 2.0,
        linear_step: float = 5.0,
        sphere_scales: Sequence[float] = (1.0, 1.5),
    ) -> None:
        if angle_step <= 0 or linear_step <= 0:
            raise ValueError("steps must be positive")
        self._machine = machine
        self._checker = checker
        self._sphere = sphere
        self._angle_step = angle_step
        self._linear_step = linear_step
        self._scales = tuple(sphere_scales)

    def plan(self, start: Pose, end: Pose) -> Transition:
        """Transition from ``start`` (previous step end) to ``end`` (next step start)."""
        result = self.try_plan(start, end)
        if result.transition is None:
            raise TransitionError(result.error or "sin alternativas alcanzables")
        return result.transition

    def try_plan(self, start: Pose, end: Pose) -> "PlanResult":
        """Like ``plan`` but never raises: on failure ``shown`` is the first
        (unvalidated) route so it can be displayed with its collisions."""
        shown: Optional[Transition] = None
        failures: List[str] = []
        for scale in self._scales:
            sphere = self._sphere.scaled(scale)
            for b2, c2 in equivalent_targets(self._machine, end.b, end.c, start.b, start.c):
                transition = self._build(start, end, b2, c2, sphere)
                shown = shown or transition
                problem = self._validate(transition)
                if problem is None:
                    return PlanResult(transition, transition, None)
                failures.append(problem)
        error = "No hay transición libre de colisiones ({} alternativas probadas). Último fallo: {}".format(
            len(failures), failures[-1] if failures else "sin alternativas alcanzables"
        )
        return PlanResult(None, shown, error)

    def _validate(self, transition: Transition) -> Optional[str]:
        for sample in transition.samples:
            if not self._machine.is_reachable(sample.b, sample.c):
                return "{}: B={:.1f}/C={:.1f} fuera de límites".format(
                    sample.phase, sample.b, sample.c
                )
            if not self._machine.tip_in_travel(sample.tip, sample.b, sample.c):
                return "{} en ({:.1f}, {:.1f}, {:.1f}): fuera de la carrera lineal".format(
                    sample.phase, *sample.tip
                )
            hit = self._checker.collision(sample.tip, sample.b, sample.c)
            if hit:
                return "{} en ({:.1f}, {:.1f}, {:.1f}): {}".format(sample.phase, *sample.tip, hit)
        return None

    def _build(
        self, start: Pose, end: Pose, b2: float, c2: float, sphere: SafetySphere
    ) -> Transition:
        n1 = bc_to_normal(start.b, start.c)
        n2 = bc_to_normal(b2, c2)
        out1 = _add(start.point, n1, exit_distance(start.point, n1, sphere))
        out2 = _add(end.point, n2, exit_distance(end.point, n2, sphere))
        on1 = _add(sphere.center, n1, sphere.radius)
        on2 = _add(sphere.center, n2, sphere.radius)
        samples: List[Sample] = []

        def line(a: Vector, z: Vector, b: float, c: float, phase: str) -> None:
            count = max(1, math.ceil(_norm(_sub(z, a)) / self._linear_step))
            for i in range(count + 1):
                samples.append(Sample(_lerp(a, z, i / count), b, c, phase))

        line(start.point, out1, start.b, start.c, RETRACT)
        line(out1, on1, start.b, start.c, TO_SPHERE)
        steps = max(1, math.ceil(max(abs(b2 - start.b), abs(c2 - start.c)) / self._angle_step))
        for i in range(steps + 1):
            t = i / steps
            b = start.b + (b2 - start.b) * t
            c = start.c + (c2 - start.c) * t
            tip = _add(sphere.center, bc_to_normal(b, c), sphere.radius)
            samples.append(Sample(tip, b, c, TURN))
        line(on2, out2, b2, c2, FROM_SPHERE)
        line(out2, end.point, b2, c2, APPROACH)
        return Transition(tuple(samples), b2, c2)


def plan_program(
    items: Sequence[ChainedStep], planner: TransitionPlanner
) -> List[Optional[Transition]]:
    """One entry per chained step: its transition, or None if none is needed."""
    result: List[Optional[Transition]] = []
    for item in items:
        if item.needs_transition and item.previous is not None and item.start is not None:
            result.append(planner.plan(item.previous, item.start))
        else:
            result.append(None)
    return result

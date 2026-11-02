import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.program import ChainedStep, Pose, Step  # noqa: E402
from IndexedCAM.Core.transition_planner import (  # noqa: E402
    APPROACH,
    RETRACT,
    TURN,
    SafetySphere,
    TransitionError,
    TransitionPlanner,
    equivalent_targets,
    exit_distance,
    plan_program,
)
from IndexedCAM.Machine.bc_machine import AxisLimits, BCMachine  # noqa: E402
from IndexedCAM.Machine.envelope import Envelope  # noqa: E402

SPHERE = SafetySphere((0.0, 0.0, 0.0), 100.0)


class Free:
    def collision(self, tip, b, c):
        return None


class Ball:
    """Obstacle: forbids tips inside a ball."""

    def __init__(self, center, radius):
        self.center, self.radius = center, radius

    def collision(self, tip, b, c):
        d = math.dist(tip, self.center)
        return "bola" if d < self.radius else None


def planner(checker=None, machine=None, **kw):
    return TransitionPlanner(machine or BCMachine(), checker or Free(), SPHERE, **kw)


def test_exit_distance():
    assert exit_distance((0, 0, 0), (0, 0, 1), SPHERE) == pytest.approx(100.0)
    assert exit_distance((0, 0, 150), (0, 0, 1), SPHERE) == 0.0
    assert exit_distance((0, 0, 50), (0, 0, 1), SPHERE) == pytest.approx(50.0)


def test_sphere_around_and_validation():
    sphere = SafetySphere.around((1, 2, 3), 50.0, Envelope(), margin=10.0)
    assert sphere.radius == 50 + 40 + 50 + 10
    with pytest.raises(ValueError):
        SafetySphere((0, 0, 0), 0)


def test_equivalent_targets_sorted_and_limited():
    machine = BCMachine()
    targets = equivalent_targets(machine, 90.0, 10.0, 90.0, 10.0)
    assert targets[0] == (90.0, 10.0)
    assert (90.0, 370.0) not in targets  # outside the C limit of 360
    assert (90.0, -350.0) in targets
    # mirrored solution needs negative B, not allowed by the default limits
    assert all(b >= 0 for b, _ in targets)
    wide = BCMachine(b_limits=AxisLimits(-90, 90))
    assert (-90.0, 190.0) in equivalent_targets(wide, 90.0, 10.0, 90.0, 10.0)


def test_plan_phases_and_endpoints():
    start = Pose(0.0, 0.0, (10.0, 0.0, 40.0))
    end = Pose(90.0, 0.0, (60.0, 0.0, 20.0))
    t = planner().plan(start, end)
    phases = [s.phase for s in t.samples]
    assert phases[0] == RETRACT and phases[-1] == APPROACH
    assert t.samples[0].tip == pytest.approx(start.point)
    assert t.samples[-1].tip == pytest.approx(end.point)
    assert (t.target_b, t.target_c) == (90.0, 0.0)


def test_turn_slides_on_sphere_with_small_steps():
    t = planner().plan(Pose(0, 0, (0, 0, 120.0)), Pose(90.0, 90.0, (0, 120.0, 0)))
    turn = t.turn
    assert all(math.dist(s.tip, SPHERE.center) == pytest.approx(100.0) for s in turn)
    for a, b in zip(turn, turn[1:]):
        assert abs(b.b - a.b) <= 2.0 + 1e-9 and abs(b.c - a.c) <= 2.0 + 1e-9
    assert (turn[0].b, turn[-1].b, turn[-1].c) == (0, 90.0, 90.0)


def test_every_sample_is_checked():
    seen = []

    class Spy:
        def collision(self, tip, b, c):
            seen.append((tip, b, c))

    t = planner(Spy()).plan(Pose(0, 0, (0, 0, 0)), Pose(90.0, 0, (60, 0, 0)))
    assert len(seen) == len(t.samples)


def test_collision_on_all_routes_raises_with_detail():
    everything = Ball((0, 0, 0), 1e6)
    with pytest.raises(TransitionError, match="bola"):
        planner(everything).plan(Pose(0, 0, (0, 0, 120)), Pose(90.0, 0, (120, 0, 0)))


def test_alternative_direction_avoids_obstacle():
    # an obstacle sitting on the short C path (+x side, C~0..90) forces the long way round
    class Block:
        def collision(self, tip, b, c):
            return "bloque" if 20.0 < c < 70.0 and b > 45.0 else None

    start = Pose(90.0, 0.0, (0, 0, 0))
    end = Pose(90.0, 90.0, (0, 0, 0))
    t = planner(Block()).plan(start, end)
    assert t.target_c == pytest.approx(-270.0)


def test_unreachable_target_raises():
    machine = BCMachine(c_limits=AxisLimits(0.0, 10.0))
    with pytest.raises(TransitionError, match="sin alternativas"):
        planner(machine=machine).plan(Pose(0, 0, (0, 0, 120)), Pose(90.0, 90.0, (0, 0, 0)))


def test_larger_sphere_is_tried_when_first_fails():
    class Near:
        def collision(self, tip, b, c):
            return "x" if math.dist(tip, (0, 0, 0)) < 120.0 else None

    start, end = Pose(0, 0, (0, 0, 200)), Pose(90.0, 0, (200, 0, 0))
    t = planner(Near()).plan(start, end)
    assert all(math.dist(s.tip, (0, 0, 0)) >= 120.0 for s in t.turn)


def test_plan_program_only_where_needed():
    a = Pose(0, 0, (0, 0, 130))
    b = Pose(90.0, 0, (130, 0, 0))
    items = [
        ChainedStep(Step("A", "x"), a, a, None, False),
        ChainedStep(Step("B", "y"), b, b, a, True),
        ChainedStep(Step("B", "z"), b, b, b, False),
    ]
    result = plan_program(items, planner())
    assert result[0] is None and result[2] is None and result[1] is not None


def test_invalid_steps():
    with pytest.raises(ValueError):
        planner(angle_step=0)


def test_travel_limit_makes_transition_fail():
    from IndexedCAM.Machine.bc_machine import TravelBox

    tight = BCMachine(travel=TravelBox((-1000, -1000, -1000), (1000, 1000, 100)))
    with pytest.raises(TransitionError, match="carrera lineal"):
        planner(machine=tight).plan(Pose(0, 0, (0, 0, 130)), Pose(90.0, 0, (130, 0, 0)))

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.preview import (  # noqa: E402
    OPERATION,
    TRANSITION,
    PreviewBuilder,
    decimate,
    sphere_for,
)
from IndexedCAM.Core.program import MemoryProgramStorage, Program, Step, chain  # noqa: E402
from IndexedCAM.Core.transition_planner import TransitionPlanner  # noqa: E402
from IndexedCAM.Gui.tool_view import cylinder_orientation  # noqa: E402
from IndexedCAM.Machine.bc_machine import BCMachine  # noqa: E402
from IndexedCAM.Machine.envelope import Envelope  # noqa: E402


class Checker:
    def __init__(self, hit_below_z=None):
        self.hit = hit_below_z
        self.calls = 0

    def _test(self, tip):
        self.calls += 1
        return "choque" if self.hit is not None and tip[2] < self.hit else None

    def collision(self, tip, b, c):
        return self._test(tip)

    cutting_collision = collision


class Resources:
    def __init__(self, checker):
        self._checker = checker

    def envelope(self, operation):
        return Envelope()

    def checker(self, operation):
        return self._checker

    def local_path(self, operation):
        return [(0, 0, 10), (0, 0, 0), (5, 0, 0)]


def setups():
    return {
        "Top": IndexedSetup(name="Top", normal=(0, 0, 1), b=0, c=0, origin=(0, 0, 30)),
        "Side": IndexedSetup(name="Side", normal=(1, 0, 0), b=90, c=0, origin=(60, 0, 0)),
    }


def build(checker=None):
    checker = checker or Checker()
    program = Program(MemoryProgramStorage())
    for step in (Step("Top", "a"), Step("Side", "b")):
        program.add(step)
    s = setups()
    ends = {"a": ((0, 0, 10), (5, 0, 0)), "b": ((0, 0, 10), (5, 0, 0))}
    items = chain(program, s, ends)
    sphere = sphere_for(((0, 0, 0), (60, 40, 30)), Envelope())
    resources = Resources(checker)
    builder = PreviewBuilder(
        s, resources, lambda op: TransitionPlanner(BCMachine(), checker, sphere)
    )
    return builder.build(items), checker


def test_one_operation_clip_per_step_and_transition_between_setups():
    clips, _ = build()
    assert [c.kind for c in clips] == [OPERATION, TRANSITION, OPERATION]
    assert [c.step_index for c in clips] == [0, 1, 1]
    assert clips[1].error is None and len(clips[1]) > 10


def test_operation_frames_are_in_part_coordinates():
    clips, _ = build()
    top = clips[0].frames
    assert top[0].tip == pytest.approx((0, 0, 40)) and top[0].b == 0
    side = clips[2].frames
    assert side[0].tip == pytest.approx((70, 0, 0)) and side[0].b == 90


def test_collisions_are_lazy_and_cached():
    clips, checker = build(Checker(hit_below_z=-1e9))
    before = checker.calls
    clip = clips[0]
    assert clip.collision(0) is None
    assert clip.collision(0) is None
    assert checker.calls == before + 1


def test_first_collision_and_poses():
    clips, _ = build(Checker(hit_below_z=35))
    clip = clips[0]
    assert clip.first_collision() == 1  # second sample drops to z=30
    assert [p.name for p in clip.poses(0)] == ["tool", "holder", "head"]


def test_failed_transition_is_still_shown_with_error():
    clips, _ = build(Checker(hit_below_z=1e9))
    transition = clips[1]
    assert transition.error and "No hay transición" in transition.error
    assert len(transition) > 10 and transition.collision(0)


def test_decimate_keeps_ends_and_limit():
    points = [(float(i), 0.0, 0.0) for i in range(1000)]
    result = decimate(points, 100)
    assert len(result) == 100 and result[0] == points[0] and result[-1] == points[-1]
    assert decimate(points[:5], 100) == points[:5]


def test_sphere_for_box():
    sphere = sphere_for(((0, 0, 0), (60, 40, 30)), Envelope(), margin=10.0)
    assert sphere.center == (30.0, 20.0, 15.0)
    assert sphere.radius == pytest.approx(math.sqrt(60**2 + 40**2 + 30**2) / 2 + 40 + 50 + 10)


def test_cylinder_orientation():
    middle, length, direction = cylinder_orientation((0, 0, 0), (0, 0, 10))
    assert (middle, length, direction) == ((0, 0, 5), 10.0, (0.0, 0.0, 1.0))
    with pytest.raises(ValueError):
        cylinder_orientation((1, 1, 1), (1, 1, 1))


def test_describe_tool_includes_diameter_and_flute():
    from IndexedCAM.Core.preview import describe_tool
    from IndexedCAM.Machine.bc_machine import BCMachine

    envelope = BCMachine().envelope.with_tool(3.0, 40.0, 12.0)
    assert describe_tool(envelope) == "Ø6 mm, largo 40 mm, corte 12 mm"
    assert describe_tool(BCMachine().envelope.with_tool(2.5, 30.0)) == "Ø5 mm, largo 30 mm"

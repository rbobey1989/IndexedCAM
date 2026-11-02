import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Machine.bc_machine import BCMachine  # noqa: E402
from IndexedCAM.Machine.envelope import Cylinder, Envelope  # noqa: E402


def test_defaults_and_reach():
    env = Envelope()
    assert [c.name for c in env.cylinders()] == ["tool", "holder", "head"]
    assert env.reach == 40 + 50 + 150
    assert BCMachine().envelope == env


@pytest.mark.parametrize("bad", [0, -1, math.inf, math.nan])
def test_invalid_dimensions_rejected(bad):
    with pytest.raises(ValueError):
        Cylinder("tool", bad, 10)
    with pytest.raises(ValueError):
        Cylinder("tool", 1, bad)
    with pytest.raises(ValueError):
        Envelope(pivot_distance=bad)


def test_place_vertical_stacks_up_from_tip():
    poses = Envelope().place((1.0, 2.0, 3.0), 0.0, 0.0)
    assert poses[0].start == (1.0, 2.0, 3.0)
    assert poses[0].end == pytest.approx((1.0, 2.0, 43.0))
    assert poses[1].start == pytest.approx(poses[0].end)
    assert poses[2].end == pytest.approx((1.0, 2.0, 3.0 + 240.0))


def test_place_horizontal_points_along_axis():
    env = Envelope()
    poses = env.place((0.0, 0.0, 0.0), 90.0, 0.0)
    assert poses[0].end == pytest.approx((40.0, 0.0, 0.0), abs=1e-9)
    poses = env.place((0.0, 0.0, 0.0), 90.0, 90.0)
    assert poses[2].end == pytest.approx((0.0, 240.0, 0.0), abs=1e-9)
    assert env.pivot((0, 0, 0), 90.0, 90.0) == pytest.approx((0.0, 120.0, 0.0), abs=1e-9)


def test_with_tool_replaces_only_the_tool():
    env = Envelope().with_tool(3.0, 25.0)
    assert (env.tool.radius, env.tool.length) == (3.0, 25.0)
    assert env.holder == Envelope().holder


def test_dict_round_trip_and_defaults():
    env = Envelope().with_tool(4.0, 30.0)
    assert Envelope.from_dict(env.to_dict()) == env
    assert Envelope.from_dict(None) == Envelope()
    assert Envelope.from_dict({"pivot_distance": 99}).pivot_distance == 99


def test_cutting_length_splits_tool_into_flutes_and_shank():
    env = Envelope().with_tool(5.0, 50.0, cutting_length=20.0, shank_radius=4.0)
    poses = env.place((0, 0, 0), 0.0, 0.0)
    assert [p.name for p in poses] == ["tool", "shank", "holder", "head"]
    assert poses[0].end == pytest.approx((0, 0, 20.0))
    assert (poses[1].radius, poses[1].end) == (4.0, pytest.approx((0, 0, 50.0)))
    assert Envelope.from_dict(env.to_dict()) == env


def test_cutting_length_covering_tool_keeps_single_cylinder():
    env = Envelope().with_tool(5.0, 30.0, cutting_length=30.0)
    assert [p.name for p in env.place((0, 0, 0), 0, 0)] == ["tool", "holder", "head"]
    with pytest.raises(ValueError):
        Envelope(cutting_length=0)


def test_travel_box_limits_pivot():
    from IndexedCAM.Machine.bc_machine import TravelBox

    machine = BCMachine(travel=TravelBox((-100, -100, 0), (100, 100, 300)))
    assert machine.tip_in_travel((0, 0, 100), 0, 0)  # pivot at z=220
    assert not machine.tip_in_travel((0, 0, 200), 0, 0)  # pivot at z=320
    assert BCMachine().tip_in_travel((1e6, 0, 0), 0, 0)
    with pytest.raises(ValueError):
        TravelBox((1, 0, 0), (0, 0, 0))

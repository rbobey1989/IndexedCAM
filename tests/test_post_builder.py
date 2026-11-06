import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.post_builder import (  # noqa: E402
    PostBuilder,
    clearance_height,
    safe_height,
)
from IndexedCAM.Core.post_program import PostMove, PostTool  # noqa: E402
from IndexedCAM.Core.program import ChainedStep, Step  # noqa: E402
from IndexedCAM.Core.transition_planner import SafetySphere  # noqa: E402

T1 = PostTool(1, "Endmill", 12.0)
T2 = PostTool(2, "Ball", 6.0)


class Resources:
    """Fake document: moves, tool, spindle and coolant per operation."""

    def __init__(self, moves=None, tools=None, spindles=None, coolants=None):
        self._moves = moves or {}
        self._tools = tools or {}
        self._spindles = spindles or {}
        self._coolants = coolants or {}

    def moves(self, operation):
        return self._moves.get(operation, ())

    def tool(self, operation):
        return self._tools.get(operation, T1)

    def spindle(self, operation):
        return self._spindles.get(operation)

    def coolant(self, operation):
        return self._coolants.get(operation, "")


def setups():
    return {
        "Top": IndexedSetup(name="Top", normal=(0, 0, 1), b=0, c=0, origin=(0, 0, 30)),
        "Side": IndexedSetup(name="Side", normal=(1, 0, 0), b=90, c=0, origin=(60, 0, 0)),
    }


def steps(*names, setup="Top"):
    return [
        ChainedStep(Step(setup, name), None, None, None, False) for name in names
    ]


def path(*z_values):
    return tuple(PostMove("G0", (("Z", z),)) for z in z_values)


def build(items, resources, sphere=None, name="Test"):
    sphere = sphere or SafetySphere((0, 0, 30), 100.0)
    return PostBuilder(setups(), resources, sphere, name).build(items)


def test_consecutive_steps_of_one_setup_share_an_orientation():
    resources = Resources({"a": path(40.0), "b": path(50.0)})
    program = build(steps("a", "b"), resources)
    assert [o.name for o in program.orientations] == ["Top"]
    assert [op.name for op in program.orientations[0].operations] == ["a", "b"]


def test_a_change_of_setup_starts_a_new_orientation():
    resources = Resources({"a": path(40.0), "b": path(20.0)})
    program = build(steps("a") + steps("b", setup="Side"), resources)
    assert [o.name for o in program.orientations] == ["Top", "Side"]
    top, side = program.orientations
    assert (top.b, top.c) == (0, 0) and (side.b, side.c) == (90, 0)
    assert side.z_axis == pytest.approx((1.0, 0.0, 0.0), abs=1e-12)


def test_steps_without_moves_are_skipped():
    resources = Resources({"a": path(40.0), "c": path(30.0)})
    program = build(steps("a", "b", "c"), resources)
    assert [op.name for op in program.orientations[0].operations] == ["a", "c"]
    assert [m.words for m in program.moves()] == [(("Z", 40.0),), (("Z", 30.0),)]


def test_safe_height_is_outside_the_sphere_measured_along_the_tool_axis():
    frame = setups()["Top"].local_frame()
    top = safe_height(frame, SafetySphere((0, 0, 30), 100.0))
    assert top == pytest.approx(100.0)
    side_frame = setups()["Side"].local_frame()
    side = safe_height(side_frame, SafetySphere((0, 0, 30), 100.0))
    # the side plane's Z points along +X, so its origin is 60 mm away from the centre
    assert side == pytest.approx(40.0)


def test_safe_height_is_measured_from_the_setup_origin():
    # the Top setup origin sits at Z=30, so a sphere centred at Z=80 is 50 above it
    frame = setups()["Top"].local_frame()
    assert safe_height(frame, SafetySphere((0, 0, 80), 50.0)) == pytest.approx(100.0)


def test_clearance_is_the_first_z_of_the_path():
    moves = (PostMove("G0", (("X", 1.0),)), PostMove("G0", (("Z", 25.0),)))
    assert clearance_height(moves, 200.0) == 25.0


def test_clearance_is_capped_at_the_safe_height():
    moves = (PostMove("G0", (("Z", 400.0),)),)
    assert clearance_height(moves, 200.0) == 200.0


def test_clearance_never_rapids_below_the_face():
    moves = (PostMove("G1", (("Z", -5.0),)),)
    assert clearance_height(moves, 200.0) == 200.0


def test_clearance_falls_back_to_the_safe_height():
    assert clearance_height((PostMove("G1", (("X", 1.0),)),), 200.0) == 200.0


def test_orientation_keeps_the_wcs_of_its_setup():
    s = setups()
    s["Top"].wcs = "G55"
    sphere = SafetySphere((0, 0, 30), 100.0)
    program = PostBuilder(s, Resources({"a": path(40.0)}), sphere).build(steps("a"))
    assert program.orientations[0].wcs == "G55"


def test_operations_keep_their_tool_spindle_and_coolant():
    resources = Resources(
        {"a": path(40.0)},
        tools={"a": T2},
        spindles={"a": 8000},
        coolants={"a": "mist"},
    )
    operation = build(steps("a"), resources).orientations[0].operations[0]
    assert operation.tool == T2
    assert operation.spindle == 8000
    assert operation.coolant == "mist"


def test_tools_are_listed_once_in_first_use_order():
    resources = Resources({"a": path(1.0), "b": path(2.0), "c": path(3.0)},
                          tools={"a": T2, "b": T1, "c": T2})
    program = build(steps("a", "b", "c"), resources)
    assert [t.number for t in program.tools()] == [2, 1]


def test_empty_program_has_no_operations():
    program = build([], Resources())
    assert program.empty and len(program) == 0


def test_name_is_kept():
    assert build(steps("a"), Resources({"a": path(1.0)}), name="Job1").name == "Job1"


def test_clearance_above_the_safe_height_is_rejected():
    from IndexedCAM.Core.post_program import PostOrientation

    with pytest.raises(ValueError):
        PostOrientation("Top", 0, 0, "G54", (0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), 10.0, 20.0)


def test_tool_number_must_be_positive():
    with pytest.raises(ValueError):
        PostTool(0)


def test_bad_coolant_is_rejected():
    from IndexedCAM.Core.post_program import PostOperation

    with pytest.raises(ValueError):
        PostOperation("a", "a", T1, (), coolant="air")


def test_angle_and_axis_vectors_come_from_the_setup_frame():
    resources = Resources({"a": path(1.0)})
    orientation = build(steps("a", setup="Side"), resources).orientations[0]
    assert orientation.origin == (60.0, 0.0, 0.0)
    assert math.isclose(sum(v * v for v in orientation.z_axis), 1.0)
    assert orientation.y_axis == (0.0, 1.0, 0.0)

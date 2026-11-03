import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.operation_pose import operation_pose  # noqa: E402
from IndexedCAM.Gui.operation_tool import selected_operation  # noqa: E402


def cmd(name, **params):
    return SimpleNamespace(Name=name, Parameters=params)


def test_path_is_moved_onto_the_part_with_setup_angles():
    setup = IndexedSetup(name="X", normal=(1.0, 0.0, 0.0), b=90.0, c=0.0, origin=(60.0, 0.0, 0.0))
    pose = operation_pose(setup, [cmd("G0", X=0.0, Y=0.0, Z=10.0), cmd("G1", X=0.0, Y=0.0, Z=0.0)])
    assert (pose.b, pose.c) == (90.0, 0.0)
    assert pose.tip == (70.0, 0.0, 0.0) or all(abs(a - b) < 1e-9 for a, b in zip(pose.tip, (70.0, 0.0, 0.0)))
    assert abs(pose.points[-1][0] - 60.0) < 1e-9


def test_selected_operation_needs_exactly_one_bound_object():
    bound = SimpleNamespace(IndexedSetup="A")
    assert selected_operation([bound]) is bound
    assert selected_operation([bound, bound]) is None
    assert selected_operation([SimpleNamespace(IndexedSetup="")]) is None
    assert selected_operation([SimpleNamespace()]) is None
    assert selected_operation([]) is None

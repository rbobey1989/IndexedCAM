import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.local_placement import (
    OperationHeights,
    apply_transform,
    envelope_top,
    heights_above,
    local_transform,
)
from IndexedCAM.Machine.bc_head import normal_to_bc


def make_setup(normal, origin=(0.0, 0.0, 0.0)):
    angles = normal_to_bc(normal)
    return IndexedSetup(name="S", normal=normal, b=angles.b, c=angles.c, origin=origin)


def close(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))


@pytest.mark.parametrize(
    "normal",
    [(0, 0, 1), (1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0), (0, 0, -1), (1, 1, 1), (-0.3, 0.8, -0.5)],
)
def test_normal_maps_to_local_z(normal):
    length = math.sqrt(sum(v * v for v in normal))
    unit = tuple(v / length for v in normal)
    transform = local_transform(make_setup(unit).local_frame())
    assert close(apply_transform(transform, unit), (0.0, 0.0, 1.0), 1e-9)


def test_local_axes_map_to_unit_axes():
    setup = make_setup((0.6, 0.0, 0.8))
    frame = setup.local_frame()
    transform = local_transform(frame)
    origin = apply_transform(transform, (0.0, 0.0, 0.0))
    for axis, expected in ((frame.x_axis, (1, 0, 0)), (frame.y_axis, (0, 1, 0))):
        assert close(apply_transform(transform, axis), tuple(e + o for e, o in zip(expected, origin)), 1e-9)


def test_origin_maps_to_local_origin():
    origin = (10.0, -4.0, 7.0)
    transform = local_transform(make_setup((1, 0, 0), origin).local_frame())
    assert close(apply_transform(transform, origin), (0.0, 0.0, 0.0), 1e-9)


def test_point_on_face_plane_has_constant_local_z():
    normal = (1.0, 0.0, 0.0)
    transform = local_transform(make_setup(normal, (60.0, 0.0, 0.0)).local_frame())
    zs = [apply_transform(transform, (60.0, y, z))[2] for y in (0, 20, 40) for z in (0, 15, 30)]
    assert all(abs(z) < 1e-9 for z in zs)


def test_heights_above_top():
    assert heights_above(30.0) == OperationHeights(30.0, 35.0, 40.0)
    assert heights_above(-2.0, 1.0, 3.0) == OperationHeights(-2.0, -1.0, 1.0)


def test_heights_clear_the_stock_not_only_the_part():
    # the cut starts on the face, the rapids clear the stock
    assert heights_above(0.0, 5.0, 10.0, stock_top=63.0) == OperationHeights(0.0, 68.0, 73.0)
    # a stock below the part never lowers the heights
    assert heights_above(30.0, 5.0, 10.0, stock_top=10.0) == OperationHeights(30.0, 35.0, 40.0)


def test_envelope_top_of_a_leaning_box():
    # a 60x40x30 block on the +X Setup: its box top is at local Z 60
    transform = local_transform(make_setup((1.0, 0.0, 0.0)).local_frame())
    assert abs(envelope_top(transform, (0.0, 0.0, 0.0), (60.0, 40.0, 30.0)) - 60.0) < 1e-9


def test_envelope_top_above_the_part_in_a_chamfered_block():
    # the stock of a chamfered block leans: its box reaches far above the face
    transform = local_transform(
        make_setup((0.5, 0.0, 0.866), (0.0, 0.0, 0.0)).local_frame()
    )
    top = envelope_top(transform, (0.0, 0.0, -116.0), (236.0, 202.0, 0.0))
    assert top > 60.0


@pytest.mark.parametrize(
    "args", [(float("nan"),), (0.0, -1.0, 5.0), (0.0, 5.0, 2.0)]
)
def test_heights_reject_bad_values(args):
    with pytest.raises(ValueError):
        heights_above(*args)

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Gui.triad import (  # noqa: E402
    DEFAULT_SIZE,
    frame_to_quaternion,
    suggested_size,
)


def rotate(q, v):
    x, y, z, w = q
    # v' = v + 2w(q x v) + 2 q x (q x v)
    qv = (x, y, z)
    t = tuple(2 * c for c in (
        qv[1] * v[2] - qv[2] * v[1],
        qv[2] * v[0] - qv[0] * v[2],
        qv[0] * v[1] - qv[1] * v[0],
    ))
    u = (
        qv[1] * t[2] - qv[2] * t[1],
        qv[2] * t[0] - qv[0] * t[2],
        qv[0] * t[1] - qv[1] * t[0],
    )
    return tuple(v[i] + w * t[i] + u[i] for i in range(3))


@pytest.mark.parametrize(
    "normal, b, c",
    [
        ((0, 0, 1), 0, 0),
        ((1, 0, 0), 90, 0),
        ((0, 1, 0), 90, 90),
        ((-1, 0, 0), 90, 180),
        ((0, 0, -1), 180, 0),
        ((1, 1, 1), math.degrees(math.acos(1 / math.sqrt(3))), 45),
        ((-1, -2, -0.5), math.degrees(math.acos(-0.5 / 2.29128784747792)), -116.565051177078),
    ],
)
def test_quaternion_maps_axes_to_frame(normal, b, c):
    frame = IndexedSetup("t", normal, b, c).local_frame()
    q = frame_to_quaternion(frame)
    assert math.isclose(sum(v * v for v in q), 1.0)
    assert rotate(q, (1, 0, 0)) == pytest.approx(frame.x_axis, abs=1e-9)
    assert rotate(q, (0, 1, 0)) == pytest.approx(frame.y_axis, abs=1e-9)
    assert rotate(q, (0, 0, 1)) == pytest.approx(frame.z_axis, abs=1e-9)


def test_suggested_size():
    assert suggested_size(400.0) == pytest.approx(10.0)
    assert suggested_size(0.0) == DEFAULT_SIZE
    assert suggested_size(math.nan) == DEFAULT_SIZE
    assert suggested_size(0.01) == 1.0

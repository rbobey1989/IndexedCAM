import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Machine.bc_head import (  # noqa: E402
    BCAngles,
    bc_to_normal,
    normal_to_bc,
    verify_solution,
)


@pytest.mark.parametrize(
    "normal, b, c",
    [
        ((0, 0, 1), 0, 0),
        ((1, 0, 0), 90, 0),
        ((0, 1, 0), 90, 90),
        ((-1, 0, 0), 90, -180),
        ((0, -1, 0), 90, -90),
    ],
)
def test_principal_faces(normal, b, c):
    result = normal_to_bc(normal)
    assert result.b == pytest.approx(b)
    assert result.c == pytest.approx(c)


@pytest.mark.parametrize(
    "normal",
    [(1, 1, 1), (-1, 1, 1), (-1, -1, 1), (1, -1, 1), (1, 1, -1), (-2, 3, -0.5)],
)
def test_quadrants_roundtrip(normal):
    angles = normal_to_bc(normal)
    assert 0 <= angles.b <= 180
    assert -180 <= angles.c < 180
    assert verify_solution(normal, angles)


def test_normalizes_input():
    assert normal_to_bc((0, 0, 5)) == normal_to_bc((0, 0, 1))
    assert verify_solution((3, 0, 4), normal_to_bc((3, 0, 4)))


def test_singularity_default_and_previous_c():
    assert normal_to_bc((0, 0, 1)) == BCAngles(0.0, 0.0)
    assert normal_to_bc((0, 0, 1), previous_c=45).c == pytest.approx(45)
    flipped = normal_to_bc((0, 0, -1), previous_c=30)
    assert flipped.b == pytest.approx(180)
    assert flipped.c == pytest.approx(30)


@pytest.mark.parametrize(
    "bad", [(0, 0, 0), (math.nan, 0, 1), (math.inf, 0, 0), (1, 2), (1, 2, 3, 4)]
)
def test_invalid_vectors(bad):
    with pytest.raises(ValueError):
        normal_to_bc(bad)


def test_bc_to_normal_unit_length():
    assert math.isclose(math.sqrt(sum(v * v for v in bc_to_normal(37, -120))), 1.0)

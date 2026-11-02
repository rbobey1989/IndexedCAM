import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Machine.bc_machine import AxisLimits, BCMachine  # noqa: E402


def test_default_limits_match_machine_doc():
    machine = BCMachine()
    assert (machine.b_limits.minimum, machine.b_limits.maximum) == (-90.0, 90.0)
    assert (machine.c_limits.minimum, machine.c_limits.maximum) == (-360.0, 360.0)


@pytest.mark.parametrize(
    "b, c, expected",
    [
        (0, 0, True),
        (90, 360, True),
        (-90, -360, True),
        (90.1, 0, False),
        (-90.1, 0, False),
        (0, 360.1, False),
        (math.nan, 0, False),
        (0, math.inf, False),
    ],
)
def test_is_reachable(b, c, expected):
    assert BCMachine().is_reachable(b, c) is expected


def test_validate_names_violated_axis():
    with pytest.raises(ValueError, match="B=120"):
        BCMachine().validate(120, 0)
    with pytest.raises(ValueError, match="C=400"):
        BCMachine().validate(0, 400)
    with pytest.raises(ValueError, match="finite"):
        BCMachine().validate(math.nan, 0)


@pytest.mark.parametrize(
    "b, c, expected",
    [(0, 0, (0, 0, 1)), (90, 0, (1, 0, 0)), (90, 90, (0, 1, 0)), (-90, 0, (-1, 0, 0))],
)
def test_tool_vector(b, c, expected):
    assert BCMachine().tool_vector(b, c) == pytest.approx(expected, abs=1e-12)


def test_tool_vector_rejects_unreachable():
    with pytest.raises(ValueError):
        BCMachine().tool_vector(100, 0)


def test_rotation_matrix_last_column_is_tool_vector():
    machine = BCMachine()
    matrix = machine.rotation_matrix(35, -120)
    column = tuple(row[2] for row in matrix)
    assert column == pytest.approx(machine.tool_vector(35, -120))


def test_rotation_matrix_is_orthonormal():
    m = BCMachine().rotation_matrix(40, 70)
    for i in range(3):
        for j in range(3):
            dot = sum(m[i][k] * m[j][k] for k in range(3))
            assert dot == pytest.approx(1.0 if i == j else 0.0, abs=1e-12)


def test_custom_limits():
    machine = BCMachine(b_limits=AxisLimits(0, 120), c_limits=AxisLimits(-180, 180))
    assert machine.is_reachable(110, 180)
    assert not machine.is_reachable(-1, 0)


def test_invalid_axis_limits():
    with pytest.raises(ValueError):
        AxisLimits(10, -10)
    with pytest.raises(ValueError):
        AxisLimits(math.nan, 10)

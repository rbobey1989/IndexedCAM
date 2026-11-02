import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.orientation_solver import (  # noqa: E402
    OrientationSolver,
    UnreachableOrientationError,
)
from IndexedCAM.Machine.bc_head import BCAngles, verify_solution  # noqa: E402
from IndexedCAM.Machine.bc_machine import AxisLimits, BCMachine  # noqa: E402


@pytest.mark.parametrize(
    "normal, b, c",
    [((0, 0, 1), 0, 0), ((1, 0, 0), 90, 0), ((0, 1, 0), 90, 90)],
)
def test_acceptance_faces(normal, b, c):
    angles = OrientationSolver().solve(normal).angles
    assert angles.b == pytest.approx(b)
    assert angles.c == pytest.approx(c)


def test_solution_aligns_tool_and_is_reachable():
    machine = BCMachine()
    for normal in [(1, 1, 1), (-1, 1, 1), (-0.72, 0, 0.69), (0, -1, 0.2)]:
        angles = OrientationSolver(machine).solve(normal).angles
        assert machine.is_reachable(angles.b, angles.c)
        assert verify_solution(normal, angles)


SYMMETRIC = BCMachine(b_limits=AxisLimits(-90, 90))


def test_default_machine_has_no_negative_b_solution():
    solution = OrientationSolver().solve((1, 0, 1))
    assert solution.angles.b == pytest.approx(45)
    assert solution.angles.c == pytest.approx(0)
    assert all(a.b >= 0 and a.c % 360 == 0 for a in solution.alternatives)


def test_alternative_solution_with_negative_b():
    solution = OrientationSolver(SYMMETRIC).solve((1, 0, 1))
    assert solution.angles.b == pytest.approx(45)
    assert solution.angles.c == pytest.approx(0)
    assert any(
        a.b == pytest.approx(-45) and a.c == pytest.approx(180)
        for a in solution.alternatives
    )


def test_previous_selects_nearest_c():
    previous = BCAngles(-45, 180)
    angles = OrientationSolver(SYMMETRIC).solve((1, 0, 1), previous=previous).angles
    assert angles.b == pytest.approx(-45)
    assert angles.c == pytest.approx(180)


def test_downward_normal_reachable_with_b_above_90():
    angles = OrientationSolver().solve((0, 0, -1)).angles
    assert angles.b == pytest.approx(180)
    assert OrientationSolver().solve((1, 0, -1)).angles.b == pytest.approx(135)


def test_downward_normal_unreachable_when_b_limited_to_90():
    machine = BCMachine(b_limits=AxisLimits(0, 90))
    with pytest.raises(UnreachableOrientationError):
        OrientationSolver(machine).solve((0, 0, -1))
    with pytest.raises(UnreachableOrientationError):
        OrientationSolver(SYMMETRIC).solve((1, 0, -1))


def test_horizontal_normal_reachable_both_ways():
    solution = OrientationSolver(SYMMETRIC).solve((-1, 0, 0))
    assert solution.angles.b == pytest.approx(90)
    assert any(a.b == pytest.approx(-90) for a in solution.alternatives)


def test_singularity_keeps_previous_c():
    angles = OrientationSolver().solve((0, 0, 1), previous=BCAngles(10, 45)).angles
    assert angles.b == pytest.approx(0)
    assert angles.c == pytest.approx(45)


def test_c_limits_filter_candidates():
    machine = BCMachine(b_limits=AxisLimits(-90, 90), c_limits=AxisLimits(-90, 90))
    angles = OrientationSolver(machine).solve((-1, 0, 1)).angles
    assert angles.b == pytest.approx(-45)
    assert angles.c == pytest.approx(0)
    with pytest.raises(UnreachableOrientationError):
        OrientationSolver(BCMachine(b_limits=AxisLimits(-90, 90), c_limits=AxisLimits(0, 10))).solve((0, -1, 1))


@pytest.mark.parametrize("bad", [(0, 0, 0), (math.nan, 0, 1), (1, 2)])
def test_invalid_normal(bad):
    with pytest.raises(ValueError):
        OrientationSolver().solve(bad)

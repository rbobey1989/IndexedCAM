import json
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.indexed_setup import IndexedSetup  # noqa: E402
from IndexedCAM.Core.orientation_solver import OrientationSolver  # noqa: E402
from IndexedCAM.Machine.bc_machine import AxisLimits, BCMachine  # noqa: E402


def make(normal=(1, 0, 1), **kwargs):
    angles = OrientationSolver().solve(normal).angles
    return IndexedSetup(
        name=kwargs.pop("name", "Cara 1"),
        normal=normal,
        b=angles.b,
        c=angles.c,
        **kwargs,
    )


def test_creation_normalizes_and_stores_fields():
    setup = make(origin=(1, 2, 3), wcs="G55", metadata={"face": "Face3"})
    assert math.isclose(math.sqrt(sum(v * v for v in setup.normal)), 1.0)
    assert setup.b == pytest.approx(45)
    assert setup.c == pytest.approx(0)
    assert setup.wcs == "G55"
    assert setup.origin == (1.0, 2.0, 3.0)
    assert setup.metadata == {"face": "Face3"}
    assert setup.operations == []


def test_default_wcs_and_name_trimmed():
    setup = make(name="  Top  ")
    assert setup.name == "Top"
    assert setup.wcs == "G54"


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_name_rejected(name):
    with pytest.raises(ValueError, match="name"):
        make(name=name)


def test_inconsistent_angles_rejected():
    with pytest.raises(ValueError, match="align"):
        IndexedSetup(name="x", normal=(0, 0, 1), b=30, c=0)


@pytest.mark.parametrize("normal", [(0, 0, 0), (math.nan, 0, 1), (1, 2)])
def test_invalid_normal_rejected(normal):
    with pytest.raises(ValueError):
        IndexedSetup(name="x", normal=normal, b=0, c=0)


def test_invalid_angles_rejected():
    with pytest.raises(ValueError):
        IndexedSetup(name="x", normal=(0, 0, 1), b=math.nan, c=0)


def test_local_frame_is_orthonormal_with_z_along_normal():
    setup = make(normal=(-1, 2, 3))
    f = setup.local_frame()
    axes = (f.x_axis, f.y_axis, f.z_axis)
    for i in range(3):
        for j in range(3):
            dot = sum(a * b for a, b in zip(axes[i], axes[j]))
            assert dot == pytest.approx(1.0 if i == j else 0.0, abs=1e-12)
    assert f.z_axis == pytest.approx(setup.normal)
    cross = (
        f.x_axis[1] * f.y_axis[2] - f.x_axis[2] * f.y_axis[1],
        f.x_axis[2] * f.y_axis[0] - f.x_axis[0] * f.y_axis[2],
        f.x_axis[0] * f.y_axis[1] - f.x_axis[1] * f.y_axis[0],
    )
    assert cross == pytest.approx(f.z_axis)


def test_operations_management():
    setup = make()
    setup.add_operation("Pocket")
    setup.add_operation(" Profile ")
    assert setup.operations == ["Pocket", "Profile"]
    with pytest.raises(ValueError, match="already"):
        setup.add_operation("Pocket")
    with pytest.raises(ValueError):
        setup.add_operation("  ")
    setup.remove_operation("Pocket")
    assert setup.operations == ["Profile"]
    with pytest.raises(ValueError, match="not in setup"):
        setup.remove_operation("Nope")


def test_constructor_copies_collections():
    ops = ["A"]
    setup = make(operations=ops)
    ops.append("B")
    assert setup.operations == ["A"]


def test_dict_roundtrip_is_json_safe():
    setup = make(origin=(1, 2, 3), metadata={"face": "Face3", "area": 12.5})
    setup.add_operation("Pocket")
    restored = IndexedSetup.from_dict(json.loads(json.dumps(setup.to_dict())))
    assert restored == setup


def test_from_dict_errors():
    with pytest.raises(ValueError, match="missing setup field: name"):
        IndexedSetup.from_dict({"normal": [0, 0, 1], "b": 0, "c": 0})
    data = make().to_dict()
    data["version"] = 99
    with pytest.raises(ValueError, match="version"):
        IndexedSetup.from_dict(data)


def test_validate_for_machine():
    setup = make(normal=(0, 0, -1))
    setup.validate_for(BCMachine())
    with pytest.raises(ValueError, match="B="):
        setup.validate_for(BCMachine(b_limits=AxisLimits(0, 90)))

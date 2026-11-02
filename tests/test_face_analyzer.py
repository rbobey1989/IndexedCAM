import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Core.face_analyzer import FaceAnalyzer  # noqa: E402


class Vector:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


class Plane:
    pass


class Face:
    ShapeType = "Face"
    Orientation = "Reversed"
    Area = 12.0
    CenterOfMass = Vector(2, 3, 4)
    ParameterRange = (0.0, 4.0, -2.0, 2.0)
    Surface = Plane()

    def normalAt(self, u, v):
        assert (u, v) == (2.0, 0.0)
        return Vector(0, 0, -2)

    def valueAt(self, u, v):
        return Vector(u, v, 4)


def test_extracts_face_geometry_and_normalizes_normal():
    result = FaceAnalyzer().analyze(Face())

    assert result.normal == (0.0, 0.0, -1.0)
    assert result.center == (2.0, 3.0, 4.0)
    assert result.area == 12.0
    assert result.orientation == "Reversed"
    assert result.surface_type == "Plane"
    assert result.normal_point == (2.0, 0.0, 4.0)


def test_rejects_non_face():
    with pytest.raises(TypeError, match="FreeCAD Face"):
        FaceAnalyzer().analyze(object())


@pytest.mark.parametrize("area", [0.0, -1.0, math.inf, math.nan])
def test_rejects_invalid_area(area):
    face = Face()
    face.Area = area
    with pytest.raises(ValueError, match="area"):
        FaceAnalyzer().analyze(face)


@pytest.mark.parametrize(
    "normal", [Vector(0, 0, 0), Vector(math.nan, 0, 1), Vector(math.inf, 0, 0)]
)
def test_rejects_invalid_normal(normal):
    face = Face()
    face.normalAt = lambda u, v: normal
    with pytest.raises(ValueError, match="normal"):
        FaceAnalyzer().analyze(face)


def test_rejects_invalid_center():
    face = Face()
    face.CenterOfMass = Vector(0, math.inf, 0)
    with pytest.raises(ValueError, match="center"):
        FaceAnalyzer().analyze(face)


def test_rejects_invalid_parameter_range():
    face = Face()
    face.ParameterRange = (0.0, 1.0, 0.0, math.nan)
    with pytest.raises(ValueError, match="parameter range"):
        FaceAnalyzer().analyze(face)

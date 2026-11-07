"""Extract representative geometry data from a FreeCAD face."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Tuple

Vector3 = Tuple[float, float, float]


class VectorLike(Protocol):
    """FreeCAD-style vector exposing Cartesian components."""

    x: float
    y: float
    z: float


class FaceLike(Protocol):
    """Subset of the FreeCAD face API consumed by :class:`FaceAnalyzer`."""

    ShapeType: str
    Orientation: str
    Area: float
    CenterOfMass: VectorLike
    ParameterRange: Tuple[float, float, float, float]
    Surface: object

    def normalAt(self, u: float, v: float) -> VectorLike:
        """Return the oriented face normal at surface parameters ``u, v``."""
        ...

    def valueAt(self, u: float, v: float) -> VectorLike:
        """Return the surface point at parameters ``u, v``."""
        ...


@dataclass(frozen=True)
class FaceAnalysis:
    """Geometric information extracted from one face.

    ``normal`` is sampled at the midpoint of the face's parameter range.
    ``center`` is the face center of mass and can differ from ``normal_point``
    for curved faces.
    """

    normal: Vector3
    center: Vector3
    area: float
    orientation: str
    surface_type: str
    normal_point: Vector3


class FaceAnalyzer:
    """Analyze FreeCAD faces without depending on FreeCADGui or the document."""

    def analyze(self, face: FaceLike, rotation: Optional[Any] = None) -> FaceAnalysis:
        """Return normal, center, area and orientation metadata for ``face``.

        The normal is evaluated at the midpoint of the face parameter bounds.
        For curved faces this is a representative sample, not a single normal
        valid across the whole face.

        Raises:
            TypeError: If the input is not a face.
            ValueError: If the face has invalid or degenerate geometric data.
        """
        if getattr(face, "ShapeType", None) != "Face":
            raise TypeError("face must be a FreeCAD Face")

        area = float(face.Area)
        if not math.isfinite(area) or area <= 0.0:
            raise ValueError("face area must be finite and greater than zero")

        center = self._vector(face.CenterOfMass, "face center")
        parameters = tuple(float(value) for value in face.ParameterRange)
        if len(parameters) != 4 or not all(math.isfinite(value) for value in parameters):
            raise ValueError("face parameter range must contain four finite values")
        u_min, u_max, v_min, v_max = parameters
        u = (u_min + u_max) / 2.0
        v = (v_min + v_max) / 2.0

        # FreeCAD reports ``normalAt`` in the shape's own frame, while the
        # center and every other point come already placed, so a part with a
        # Placement would otherwise yield an orientation that ignores it.
        sampled = face.normalAt(u, v)
        if rotation is not None:
            sampled = rotation.multVec(sampled)
        normal = self._vector(sampled, "face normal")
        magnitude = math.hypot(*normal)
        if magnitude == 0.0:
            raise ValueError("face normal must not be a zero-length vector")
        normalized_normal = (
            normal[0] / magnitude,
            normal[1] / magnitude,
            normal[2] / magnitude,
        )
        normal_point = self._vector(face.valueAt(u, v), "normal sample point")

        return FaceAnalysis(
            normal=normalized_normal,
            center=center,
            area=area,
            orientation=str(face.Orientation),
            surface_type=type(face.Surface).__name__,
            normal_point=normal_point,
        )

    @staticmethod
    def _vector(value: VectorLike, description: str) -> Vector3:
        try:
            components = (float(value.x), float(value.y), float(value.z))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError(
                "{} must have finite x, y and z components".format(description)
            ) from error
        if not all(math.isfinite(component) for component in components):
            raise ValueError("{} must have finite x, y and z components".format(description))
        return components

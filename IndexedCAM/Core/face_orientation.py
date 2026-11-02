"""Face selection and orientation workflow steps, independent from the GUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence, Tuple

from IndexedCAM.Core.face_analyzer import FaceAnalysis, FaceAnalyzer
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.orientation_solver import OrientationSolution, OrientationSolver
from IndexedCAM.Machine.bc_head import BCAngles
from IndexedCAM.Machine.bc_machine import BCMachine


class SelectionError(ValueError):
    """The current selection is not exactly one face."""


@dataclass(frozen=True)
class SelectedFace:
    """A face taken from the FreeCAD selection and its readable origin."""

    face: Any
    label: str


@dataclass(frozen=True)
class FaceOrientation:
    """Geometry of a selected face and the machine orientation chosen for it."""

    source: str
    analysis: FaceAnalysis
    solution: OrientationSolution


def extract_face(selection: Sequence[Any]) -> SelectedFace:
    """Return the single selected face from ``Gui.Selection.getSelectionEx()``."""
    faces = []
    for item in selection:
        names = list(getattr(item, "SubElementNames", ()))
        for index, sub in enumerate(getattr(item, "SubObjects", ())):
            kind = getattr(sub, "ShapeType", None)
            if kind != "Face":
                raise SelectionError(
                    "Solo se pueden seleccionar caras (seleccionado: {}).".format(kind)
                )
            name = names[index] if index < len(names) else "Face"
            faces.append(
                SelectedFace(sub, "{}.{}".format(getattr(item, "ObjectName", "?"), name))
            )
    if not faces:
        raise SelectionError("Selecciona una cara en la vista 3D.")
    if len(faces) > 1:
        raise SelectionError("Selecciona exactamente una cara.")
    return faces[0]


class FaceOrientationService:
    """Turn a selected face into a machine orientation and into a Setup."""

    def __init__(
        self,
        machine: Optional[BCMachine] = None,
        analyzer: Optional[FaceAnalyzer] = None,
        solver: Optional[OrientationSolver] = None,
    ) -> None:
        self._analyzer = analyzer or FaceAnalyzer()
        self._solver = solver or OrientationSolver(machine)

    def orient(self, selected: SelectedFace) -> FaceOrientation:
        """Analyze the face and solve B/C (may raise ``ValueError``)."""
        analysis = self._analyzer.analyze(selected.face)
        solution = self._solver.solve(analysis.normal)
        return FaceOrientation(selected.label, analysis, solution)

    @staticmethod
    def create_setup(orientation: FaceOrientation, name: str) -> IndexedSetup:
        """Build (without storing) the Setup for the chosen orientation."""
        analysis, angles = orientation.analysis, orientation.solution.angles
        return IndexedSetup(
            name=name,
            normal=analysis.normal,
            b=angles.b,
            c=angles.c,
            origin=analysis.center,
            metadata={
                "source": orientation.source,
                "area": analysis.area,
                "surface": analysis.surface_type,
            },
        )


def _pose(angles: BCAngles) -> Tuple[float, float]:
    return (round(angles.b, 6), round(angles.c % 360.0, 6) % 360.0)


def _distinct_alternatives(solution: OrientationSolution) -> int:
    """Alternatives that are a different pose, not just C plus whole turns."""
    others = {_pose(a) for a in solution.alternatives}
    others.discard(_pose(solution.angles))
    return len(others)


def describe(orientation: FaceOrientation) -> str:
    """Human-readable summary: normal, B/C and number of distinct alternatives."""
    n = orientation.analysis.normal
    angles = orientation.solution.angles
    return (
        "Cara: {}\n"
        "Normal: ({:.4f}, {:.4f}, {:.4f})\n"
        "B = {:.3f}°    C = {:.3f}°\n"
        "Poses alternativas alcanzables: {}"
    ).format(
        orientation.source,
        n[0],
        n[1],
        n[2],
        angles.b,
        angles.c,
        _distinct_alternatives(orientation.solution),
    )

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from IndexedCAM.Commands.face_orientation import FaceOrientationWorkflow  # noqa: E402
from IndexedCAM.Core.face_orientation import (  # noqa: E402
    FaceOrientationService,
    SelectionError,
    describe,
    extract_face,
)
from IndexedCAM.Core.orientation_solver import UnreachableOrientationError  # noqa: E402
from IndexedCAM.Core.setup_manager import MemoryStorage, SetupManager  # noqa: E402
from IndexedCAM.Machine.bc_machine import AxisLimits, BCMachine  # noqa: E402


class Vector:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class Face:
    ShapeType = "Face"
    Orientation = "Forward"
    Area = 400.0
    ParameterRange = (0.0, 1.0, 0.0, 1.0)

    class Surface:
        pass

    def __init__(self, normal=(1, 0, 1), center=(1, 2, 3)):
        self._normal = Vector(*normal)
        self.CenterOfMass = Vector(*center)
        self.Surface = Face.Surface()

    def normalAt(self, u, v):
        return self._normal

    def valueAt(self, u, v):
        return self.CenterOfMass


class Edge:
    ShapeType = "Edge"


class Selection:
    def __init__(self, subs, names=None, name="Box"):
        self.SubObjects = subs
        self.SubElementNames = names if names is not None else ["Face%d" % (i + 1) for i in range(len(subs))]
        self.ObjectName = name


class FakeTriad:
    def __init__(self):
        self.frames = []
        self.cleared = 0

    def show(self, frame, size):
        self.frames.append((frame, size))

    def clear(self):
        self.cleared += 1


class Shape:
    def __init__(self):
        self.Placement = type("Placement", (), {"Rotation": "rotacion"})()


class SelectedObject:
    def __init__(self, subs, name="Box", shape=None):
        self.SubObjects = subs
        self.SubElementNames = ["Face%d" % (i + 1) for i in range(len(subs))]
        self.ObjectName = name
        self.Object = type("Obj", (), {"Shape": shape})()


def test_extract_face_ok():
    selected = extract_face([Selection([Face()], ["Face3"])])
    assert selected.label == "Box.Face3"
    assert selected.rotation is None


def test_extract_face_keeps_the_object_rotation():
    selected = extract_face([SelectedObject([Face()], shape=Shape())])
    assert selected.rotation == "rotacion"


@pytest.mark.parametrize(
    "selection, message",
    [
        ([], "Selecciona una cara"),
        ([Selection([])], "Selecciona una cara"),
        ([Selection([Edge()], ["Edge1"])], "Solo se pueden seleccionar caras"),
        ([Selection([Face(), Face()])], "exactamente una"),
        ([Selection([Face()]), Selection([Face()], name="Other")], "exactamente una"),
    ],
)
def test_extract_face_errors(selection, message):
    with pytest.raises(SelectionError, match=message):
        extract_face(selection)


def test_service_orient_and_create_setup():
    service = FaceOrientationService()
    orientation = service.orient(extract_face([Selection([Face()])]))
    assert orientation.solution.angles.b == pytest.approx(45)
    setup = service.create_setup(orientation, "Lado")
    assert setup.name == "Lado"
    assert setup.origin == (1.0, 2.0, 3.0)
    assert setup.metadata["source"] == "Box.Face1"
    assert setup.metadata["area"] == 400.0
    assert setup.metadata["surface"] == "Surface"
    assert "B = 45.000" in describe(orientation)


def test_service_unreachable_face():
    service = FaceOrientationService(BCMachine(b_limits=AxisLimits(0, 90)))
    with pytest.raises(UnreachableOrientationError):
        service.orient(extract_face([Selection([Face(normal=(0, 0, -1))])]))


def make_workflow(ask, manager=None, transaction=None):
    manager = manager or SetupManager(MemoryStorage())
    triad = FakeTriad()
    workflow = FaceOrientationWorkflow(
        FaceOrientationService(), manager, triad, ask, transaction
    )
    return workflow, manager, triad


def test_workflow_creates_setup_with_default_name():
    seen = {}

    def ask(orientation, default):
        seen["default"] = default
        return default

    workflow, manager, triad = make_workflow(ask)
    setup = workflow.run([Selection([Face()])])
    assert seen["default"] == "Setup"
    assert manager.names() == ["Setup"]
    assert setup is manager.get("Setup")
    assert len(triad.frames) == 1 and triad.cleared == 0
    assert triad.frames[0][1] == pytest.approx(10.0)


def test_workflow_custom_name_and_unique_default():
    workflow, manager, _ = make_workflow(lambda o, d: "Cara X")
    manager.add(FaceOrientationService.create_setup(
        FaceOrientationService().orient(extract_face([Selection([Face()])])), "Setup"))
    workflow.run([Selection([Face()])])
    assert manager.names() == ["Setup", "Cara X"]


def test_workflow_default_name_avoids_collision():
    names = []
    workflow, manager, _ = make_workflow(lambda o, d: names.append(d) or d)
    workflow.run([Selection([Face()])])
    workflow.run([Selection([Face(normal=(1, 0, 0))])])
    assert names == ["Setup", "Setup 2"]
    assert manager.names() == ["Setup", "Setup 2"]


def test_workflow_cancel_clears_triad_and_stores_nothing():
    workflow, manager, triad = make_workflow(lambda o, d: None)
    assert workflow.run([Selection([Face()])]) is None
    assert len(manager) == 0
    assert triad.cleared == 1


def test_workflow_selection_error_has_no_side_effects():
    workflow, manager, triad = make_workflow(lambda o, d: d)
    with pytest.raises(SelectionError):
        workflow.run([])
    assert len(manager) == 0 and triad.frames == []


def test_workflow_duplicate_name_rejected_inside_transaction():
    events = []

    class Tx:
        def __enter__(self):
            events.append("open")

        def __exit__(self, exc_type, exc, tb):
            events.append("abort" if exc_type else "commit")

    workflow, manager, _ = make_workflow(lambda o, d: "A", transaction=Tx)
    workflow.run([Selection([Face()])])
    with pytest.raises(ValueError, match="already exists"):
        workflow.run([Selection([Face()])])
    assert events == ["open", "commit", "open", "abort"]
    assert manager.names() == ["A"]


def test_describe_ignores_full_turn_equivalents():
    service = FaceOrientationService()
    horizontal = service.orient(extract_face([Selection([Face(normal=(1, 0, 0))])]))
    assert "alcanzables: 0" in describe(horizontal)
    symmetric = FaceOrientationService(BCMachine(b_limits=AxisLimits(-90, 90)))
    assert "alcanzables: 1" in describe(
        symmetric.orient(extract_face([Selection([Face(normal=(1, 0, 1))])]))
    )

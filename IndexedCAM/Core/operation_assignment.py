"""Assign a CAM operation to a Setup: workflow independent from FreeCAD.

Flow: pick Setup and operation type -> make sure the single CAM Job and the
Setup's local model exist -> create the native CAM operation bound to the face
of the local model (the face the Setup was created from).
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable, ContextManager, List, Optional, Sequence, Tuple

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.setup_manager import SetupManager


class AssignmentError(ValueError):
    """The operation cannot be assigned (shown to the user as a warning)."""


@dataclass(frozen=True)
class OperationType:
    """A CAM operation offered by IndexedCAM (native CAM GUI module)."""

    key: str
    label: str
    gui_module: str


OPERATION_TYPES: Tuple[OperationType, ...] = (
    OperationType("MillFace", "Planeado (Face)", "Path.Op.Gui.MillFace"),
    OperationType("PocketShape", "Vaciado (Pocket Shape)", "Path.Op.Gui.PocketShape"),
    OperationType("Profile", "Contorneado (Profile)", "Path.Op.Gui.Profile"),
    OperationType("Adaptive", "Adaptativo (Adaptive)", "Path.Op.Gui.Adaptive"),
)


@dataclass(frozen=True)
class SourceFace:
    """Face a Setup was created from: document object name and ``FaceN``."""

    object_name: str
    face: str


def parse_source(source: str) -> SourceFace:
    """Parse the ``"Object.FaceN"`` label stored in the Setup metadata."""
    object_name, _, face = str(source).rpartition(".")
    if not object_name or not face.startswith("Face") or not face[4:].isdigit():
        raise AssignmentError(
            "El setup no guarda una cara de origen válida ('{}').".format(source)
        )
    return SourceFace(object_name, face)


@dataclass(frozen=True)
class Choice:
    setup_name: str
    operation: OperationType


@dataclass(frozen=True)
class Assignment:
    setup: IndexedSetup
    operation_type: OperationType
    operation: Any


Chooser = Callable[[Sequence[IndexedSetup], Sequence[OperationType]], Optional[Choice]]
Binder = Callable[[Any], None]


class OperationLauncher:
    """Creates the CAM operation (and its panel); implemented by the GUI adapter."""

    def launch(self, job: Any, operation: OperationType, bind: Binder) -> Any:
        raise NotImplementedError


class AssignOperationWorkflow:
    """Orchestrates Setup + operation choice and the creation of the operation."""

    def __init__(
        self,
        manager: SetupManager,
        bridge: Any,
        launcher: OperationLauncher,
        chooser: Chooser,
        find_source: Callable[[str], Any],
        transaction: Optional[Callable[[], ContextManager[Any]]] = None,
        operation_types: Sequence[OperationType] = OPERATION_TYPES,
    ) -> None:
        self._manager = manager
        self._bridge = bridge
        self._launcher = launcher
        self._chooser = chooser
        self._find_source = find_source
        self._transaction = transaction or nullcontext
        self._types: List[OperationType] = list(operation_types)

    def run(self) -> Optional[Assignment]:
        """Return the assignment, or None if the user cancelled."""
        setups = self._manager.list()
        if not setups:
            raise AssignmentError(
                "No hay setups. Crea uno con Face Orientation antes de asignar una operación."
            )
        existing_job = self._bridge.find_job()
        if existing_job is not None:
            self.sync_operations(existing_job)
        choice = self._chooser(setups, self._types)
        if choice is None:
            return None
        setup = self._manager.get(choice.setup_name)
        reference = parse_source(setup.metadata.get("source", ""))
        source = self._find_source(reference.object_name)
        if source is None:
            raise AssignmentError(
                "No existe el objeto '{}' del que se creó el setup '{}'.".format(
                    reference.object_name, setup.name
                )
            )
        with self._transaction():
            job = self._bridge.ensure_job(source)
            self._bridge.attach_setup(job, source, setup)

        def bind(operation: Any) -> None:
            self._bridge.bind_operation(operation, setup.name, reference.face)

        operation = self._launcher.launch(job, choice.operation, bind)
        if operation is None:
            return None
        self.sync_operations(job)
        return Assignment(setup, choice.operation, operation)

    def sync_operations(self, job: Any) -> None:
        """Make ``IndexedSetup.operations`` match the operations bound in the Job.

        The property ``IndexedSetup`` of each operation is the source of truth
        (an operation cancelled in its panel is deleted by CAM), so the stored
        list is refreshed from the Job instead of being edited on creation.
        """
        for setup in self._manager.list():
            names = [op.Name for op in self._bridge.operations_of(job, setup.name)]
            if names != setup.operations:
                setup.operations = names
                self._manager.update(setup)

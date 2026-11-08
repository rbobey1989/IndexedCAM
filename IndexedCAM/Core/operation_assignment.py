"""Associate existing CAM operations of a Job with indexed Setups.

The user creates the Job and its operations in the native CAM workbench;
IndexedCAM only orients them: the operation is moved to the Setup's local
model (same faces) and recorded in the Setup and in the program.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, Callable, ContextManager, List, Optional, Sequence, Tuple

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.program import Program
from IndexedCAM.Core.setup_manager import SetupManager


class AssignmentError(ValueError):
    """The operations cannot be associated (shown to the user as a warning)."""


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


class OperationAssigner:
    """Binds Job operations to Setups and keeps the stored lists in sync."""

    def __init__(
        self,
        manager: SetupManager,
        bridge: Any,
        find_source: Callable[[str], Any],
        program: Optional[Program] = None,
    ) -> None:
        self._manager = manager
        self._bridge = bridge
        self._find_source = find_source
        self._program = program

    def assign(self, setup_name: str, operations: Sequence[Any]) -> None:
        """Give the Setup its local model and orient ``operations`` to it."""
        setup = self._manager.get(setup_name)
        reference = parse_source(setup.metadata.get("source", ""))
        source = self._find_source(reference.object_name)
        if source is None:
            raise AssignmentError(
                "No existe el objeto '{}' del que se creó el setup '{}'.".format(
                    reference.object_name, setup.name
                )
            )
        self._bridge.attach_setup(source, setup)
        for operation in operations:
            self._bridge.bind_operation(operation, setup.name, reference.face)
        self.sync_operations()

    def sync_operations(self) -> None:
        """Make ``IndexedSetup.operations`` and the program match the Job.

        The ``IndexedSetup`` property of each operation is the source of truth
        (operations can be deleted or edited in CAM at any time).
        """
        for setup in self._manager.list():
            names = [op.Name for op in self._bridge.operations_of(setup.name)]
            if names != setup.operations:
                setup.operations = names
                self._manager.update(setup)
        if self._program is not None:
            self._program.sync(self._bridge.bound_steps())


Chooser = Callable[[Sequence[IndexedSetup], Sequence[Any]], Optional[Tuple[str, List[Any]]]]


@dataclass(frozen=True)
class Assignment:
    setup: IndexedSetup
    operations: Sequence[Any]


class AssignOperationWorkflow:
    """Choose a Setup and some Job operations -> orient them to the Setup."""

    def __init__(
        self,
        manager: SetupManager,
        bridge: Any,
        assigner: OperationAssigner,
        chooser: Chooser,
        transaction: Optional[Callable[[], ContextManager[Any]]] = None,
    ) -> None:
        self._manager = manager
        self._bridge = bridge
        self._assigner = assigner
        self._chooser = chooser
        self._transaction = transaction or nullcontext

    def run(self) -> Optional[Assignment]:
        """Return the assignment, or None if the user cancelled."""
        setups = self._manager.list()
        if not setups:
            raise AssignmentError(
                "No hay setups en este Job. Crea uno con Face Orientation primero."
            )
        operations = self._bridge.operations()
        if not operations:
            raise AssignmentError(
                "El Job no tiene operaciones. Créalas en el banco CAM y vuelve a intentarlo."
            )
        choice = self._chooser(setups, operations)
        if choice is None:
            return None
        setup_name, chosen = choice
        with self._transaction():
            self._assigner.assign(setup_name, chosen)
        return Assignment(self._manager.get(setup_name), chosen)

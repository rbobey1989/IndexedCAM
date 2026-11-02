"""Face Orientation command: select a face, compute B/C, show it, create a Setup.

``FaceOrientationWorkflow`` has no FreeCAD dependency (all collaborators are
injected) so it can be tested; ``FaceOrientationCommand`` is the thin FreeCAD
adapter and imports FreeCAD modules lazily.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, ContextManager, Optional, Sequence

from IndexedCAM.Core.face_orientation import (
    FaceOrientation,
    FaceOrientationService,
    describe,
    extract_face,
)
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.setup_manager import SetupManager

COMMAND_NAME = "IndexedCAM_FaceOrientation"
DIALOG_TITLE = "IndexedCAM - Face Orientation"

NameRequest = Callable[[FaceOrientation, str], Optional[str]]


class FaceOrientationWorkflow:
    """Select face -> orient -> preview triad -> confirm name -> store Setup."""

    def __init__(
        self,
        service: FaceOrientationService,
        manager: SetupManager,
        triad: Any,
        ask_name: NameRequest,
        transaction: Optional[Callable[[], ContextManager[Any]]] = None,
    ) -> None:
        self._service = service
        self._manager = manager
        self._triad = triad
        self._ask_name = ask_name
        self._transaction = transaction or nullcontext

    def run(self, selection: Sequence[Any]) -> Optional[IndexedSetup]:
        """Return the created Setup, or None if the user cancelled."""
        from IndexedCAM.Gui.triad import suggested_size

        orientation = self._service.orient(extract_face(selection))
        default_name = self._manager.unique_name("Setup")
        preview = self._service.create_setup(orientation, default_name)
        self._triad.show(preview.local_frame(), suggested_size(orientation.analysis.area))

        name = self._ask_name(orientation, default_name)
        if name is None:
            self._triad.clear()
            return None
        setup = (
            preview
            if name.strip() == default_name
            else self._service.create_setup(orientation, name)
        )
        with self._transaction():
            self._manager.add(setup)
        return setup


def _ask_name_dialog(orientation: FaceOrientation, default_name: str) -> Optional[str]:
    import FreeCADGui as Gui
    from PySide import QtWidgets

    label = describe(orientation) + "\n\nNombre del nuevo setup:"
    name, accepted = QtWidgets.QInputDialog.getText(
        Gui.getMainWindow(), DIALOG_TITLE, label, text=default_name
    )
    return name if accepted else None


class _DocumentTransaction:
    """Undoable document transaction (aborted if the block raises)."""

    def __init__(self, document: Any, label: str) -> None:
        self._document = document
        self._label = label

    def __enter__(self) -> "_DocumentTransaction":
        self._document.openTransaction(self._label)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self._document.commitTransaction()
        else:
            self._document.abortTransaction()


_triad: Any = None


def _shared_triad() -> Any:
    global _triad
    if _triad is None:
        from IndexedCAM.Gui.triad import TriadView

        _triad = TriadView()
    return _triad


class FaceOrientationCommand:
    """FreeCAD command ``IndexedCAM_FaceOrientation``."""

    def GetResources(self) -> dict:
        from IndexedCAM.Gui.resources import icon_path

        return {
            "Pixmap": icon_path("face_orientation.svg"),
            "MenuText": "Face Orientation",
            "ToolTip": (
                "Calcula B/C para la cara seleccionada, muestra su sistema "
                "local y crea un setup indexado 3+2"
            ),
        }

    def IsActive(self) -> bool:
        import FreeCAD

        return FreeCAD.ActiveDocument is not None

    def Activated(self) -> None:
        import FreeCAD
        import FreeCADGui as Gui
        from PySide import QtWidgets

        from IndexedCAM.Core.document_storage import DocumentStorage

        document = FreeCAD.ActiveDocument
        try:
            workflow = FaceOrientationWorkflow(
                FaceOrientationService(),
                SetupManager(DocumentStorage(document)),
                _shared_triad(),
                _ask_name_dialog,
                lambda: _DocumentTransaction(document, "Create indexed setup"),
            )
            setup = workflow.run(Gui.Selection.getSelectionEx())
        except ValueError as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, str(error))
            return
        if setup is not None:
            FreeCAD.Console.PrintMessage(
                "IndexedCAM: setup '{}' creado (B={:.3f}, C={:.3f})\n".format(
                    setup.name, setup.b, setup.c
                )
            )


def register() -> None:
    """Register the command with FreeCAD (idempotent)."""
    import FreeCADGui as Gui

    if COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(COMMAND_NAME, FaceOrientationCommand())

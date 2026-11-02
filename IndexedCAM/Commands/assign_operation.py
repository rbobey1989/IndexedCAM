"""Assign Operation command: create a native CAM operation for a Setup.

``CamOperationLauncher`` reuses the CAM workbench's own creation path
(``Path.Op.Gui.Base.Create``) so the user gets the standard operation panel;
only the object factory is wrapped to bind the operation to the Setup's local
model *before* the panel opens. CAM itself is not modified.
"""

from __future__ import annotations

import copy
import importlib
from typing import Any, Optional, Sequence

from IndexedCAM.Commands.transaction import DocumentTransaction
from IndexedCAM.Core.operation_assignment import (
    OPERATION_TYPES,
    AssignmentError,
    AssignOperationWorkflow,
    Binder,
    Choice,
    OperationLauncher,
    OperationType,
)
from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.setup_manager import SetupManager

COMMAND_NAME = "IndexedCAM_AssignOperation"
DIALOG_TITLE = "IndexedCAM - Asignar operación"


class CamOperationLauncher(OperationLauncher):
    """Creates an operation through CAM's own GUI command resources."""

    def __init__(self, document: Any) -> None:
        self._document = document

    def launch(self, job: Any, operation: OperationType, bind: Binder) -> Any:
        from Path.Op.Gui import Base as OpGui

        resources = copy.copy(importlib.import_module(operation.gui_module).Command.res)
        factory = resources.objFactory

        def bound_factory(name: str, obj: Any = None, parentJob: Any = None) -> Any:
            created = factory(name, obj=obj, parentJob=parentJob)
            bind(created)
            self._select_base(created)
            return created

        resources.objFactory = bound_factory
        resources.job = job
        try:
            return OpGui.Create(resources)
        except Exception:
            self._document.abortTransaction()
            raise


    @staticmethod
    def _select_base(operation: Any) -> None:
        """Select the bound face: CAM's panel fills a new operation's Base from the selection."""
        import FreeCADGui as Gui

        Gui.Selection.clearSelection()
        for model, subs in operation.Base:
            for sub in subs:
                Gui.Selection.addSelection(model.Document.Name, model.Name, sub)


def _choose_dialog(
    setups: Sequence[IndexedSetup], types: Sequence[OperationType]
) -> Optional[Choice]:
    from PySide import QtWidgets

    import FreeCADGui as Gui

    dialog = QtWidgets.QDialog(Gui.getMainWindow())
    dialog.setWindowTitle(DIALOG_TITLE)
    form = QtWidgets.QFormLayout(dialog)
    setup_box = QtWidgets.QComboBox()
    for setup in setups:
        setup_box.addItem(
            "{}  (B={:.2f}, C={:.2f})".format(setup.name, setup.b, setup.c), setup.name
        )
    setup_box.setCurrentIndex(setup_box.count() - 1)
    type_box = QtWidgets.QComboBox()
    for operation in types:
        type_box.addItem(operation.label, operation.key)
    form.addRow("Setup:", setup_box)
    form.addRow("Operación:", type_box)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if not dialog.exec_():
        return None
    return Choice(setup_box.currentData(), types[type_box.currentIndex()])


class AssignOperationCommand:
    """FreeCAD command ``IndexedCAM_AssignOperation``."""

    def GetResources(self) -> dict:
        from IndexedCAM.Gui.resources import icon_path

        return {
            "Pixmap": icon_path("assign_operation.svg"),
            "MenuText": "Assign Operation",
            "ToolTip": (
                "Crea una operación del banco CAM para un setup indexado, "
                "enlazada a la cara con la que se creó"
            ),
        }

    def IsActive(self) -> bool:
        import FreeCAD

        return FreeCAD.ActiveDocument is not None

    def Activated(self) -> None:
        import FreeCAD
        import FreeCADGui as Gui
        from PySide import QtWidgets

        from IndexedCAM.Core.cam_bridge import CamBridge
        from IndexedCAM.Core.document_storage import DocumentStorage, ProgramDocumentStorage
        from IndexedCAM.Core.program import Program

        document = FreeCAD.ActiveDocument
        try:
            workflow = AssignOperationWorkflow(
                SetupManager(DocumentStorage(document)),
                CamBridge(document),
                CamOperationLauncher(document),
                _choose_dialog,
                document.getObject,
                lambda: DocumentTransaction(document, "Prepare indexed setup for CAM"),
                program=Program(ProgramDocumentStorage(document)),
            )
            assignment = workflow.run()
        except (AssignmentError, ValueError) as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, str(error))
            return
        if assignment is not None:
            FreeCAD.Console.PrintMessage(
                "IndexedCAM: operación '{}' asignada al setup '{}'\n".format(
                    assignment.operation.Label, assignment.setup.name
                )
            )


def register() -> None:
    """Register the command with FreeCAD (idempotent)."""
    import FreeCADGui as Gui

    if COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(COMMAND_NAME, AssignOperationCommand())


__all__ = ["COMMAND_NAME", "OPERATION_TYPES", "register"]

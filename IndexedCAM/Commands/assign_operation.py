"""Assign Operation command: orient existing CAM operations to a Setup.

Operations are created by the user in the native CAM workbench; this command
only moves them to the Setup's local model so they are machined oriented to it.
"""

from __future__ import annotations

from IndexedCAM.Commands.transaction import DocumentTransaction
from IndexedCAM.Core.job_context import JobCancelled
from IndexedCAM.Core.operation_assignment import AssignmentError, AssignOperationWorkflow

COMMAND_NAME = "IndexedCAM_AssignOperation"
DIALOG_TITLE = "IndexedCAM - Asignar operación"


class AssignOperationCommand:
    """FreeCAD command ``IndexedCAM_AssignOperation``."""

    def GetResources(self) -> dict:
        from IndexedCAM.Gui.resources import icon_path

        return {
            "Pixmap": icon_path("assign_operation.svg"),
            "MenuText": "Assign Operation",
            "ToolTip": (
                "Asocia operaciones existentes del Job a un setup indexado: "
                "se mecanizarán orientadas a él"
            ),
        }

    def IsActive(self) -> bool:
        import FreeCAD

        return FreeCAD.ActiveDocument is not None

    def Activated(self) -> None:
        import FreeCAD
        import FreeCADGui as Gui
        from PySide import QtWidgets

        from IndexedCAM.Commands.context import open_context, selected_objects
        from IndexedCAM.Commands.dialogs import choose_setup_and_operations

        document = FreeCAD.ActiveDocument
        try:
            ctx = open_context(document, selected_objects())
            ctx.assigner.sync_operations()
            assignment = AssignOperationWorkflow(
                ctx.manager,
                ctx.bridge,
                ctx.assigner,
                lambda setups, operations: choose_setup_and_operations(
                    DIALOG_TITLE, setups, operations
                ),
                lambda: DocumentTransaction(document, "Assign operations to setup"),
            ).run()
        except JobCancelled:
            return
        except (AssignmentError, ValueError) as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, str(error))
            return
        if assignment is not None:
            FreeCAD.Console.PrintMessage(
                "IndexedCAM: {} operación(es) orientadas al setup '{}'\n".format(
                    len(assignment.operations), assignment.setup.name
                )
            )


def register() -> None:
    """Register the command with FreeCAD (idempotent)."""
    import FreeCADGui as Gui

    if COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(COMMAND_NAME, AssignOperationCommand())

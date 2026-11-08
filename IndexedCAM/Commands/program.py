"""Program command: show the chain of (Setup, operation) steps and reorder it."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from IndexedCAM.Core.path_endpoints import path_endpoints
from IndexedCAM.Core.program import ChainedStep, Program, chain
from IndexedCAM.Core.setup_manager import SetupManager

COMMAND_NAME = "IndexedCAM_Program"
DIALOG_TITLE = "IndexedCAM - Programa"


def resolve_program(
    program: Program, manager: SetupManager, bridge: Any, document: Any
) -> List[ChainedStep]:
    """Sync the program with the Job and chain it using each operation's real path."""
    program.sync(bridge.bound_steps())
    endpoints: Dict[str, Optional[Any]] = {}
    for step in program.steps():
        operation = document.getObject(step.operation)
        endpoints[step.operation] = (
            path_endpoints(operation.Path.Commands) if operation is not None else None
        )
    setups = {s.name: s for s in manager.list()}
    return chain(program, setups, endpoints)


class ProgramCommand:
    """FreeCAD command ``IndexedCAM_Program``."""

    def GetResources(self) -> dict:
        from IndexedCAM.Gui.resources import icon_path

        return {
            "Pixmap": icon_path("program.svg"),
            "MenuText": "Program",
            "ToolTip": "Muestra y reordena la secuencia de operaciones indexadas",
        }

    def IsActive(self) -> bool:
        import FreeCAD

        return FreeCAD.ActiveDocument is not None

    def Activated(self) -> None:
        import FreeCAD
        import FreeCADGui as Gui
        from PySide import QtWidgets

        from IndexedCAM.Commands.transaction import DocumentTransaction
        from IndexedCAM.Commands.context import open_context, selected_objects
        from IndexedCAM.Core.job_context import JobCancelled
        from IndexedCAM.Core.program import describe

        document = FreeCAD.ActiveDocument
        try:
            ctx = open_context(document, selected_objects())
        except JobCancelled:
            return
        except ValueError as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, str(error))
            return
        manager, program, bridge = ctx.manager, ctx.program, ctx.bridge

        dialog = QtWidgets.QDialog(Gui.getMainWindow())
        dialog.setWindowTitle(DIALOG_TITLE)
        layout = QtWidgets.QVBoxLayout(dialog)
        listing = QtWidgets.QListWidget()
        up = QtWidgets.QPushButton("Subir")
        down = QtWidgets.QPushButton("Bajar")
        close = QtWidgets.QPushButton("Cerrar")
        row = QtWidgets.QHBoxLayout()
        for button in (up, down, close):
            row.addWidget(button)
        layout.addWidget(listing)
        layout.addLayout(row)

        def refresh(select: int = 0) -> None:
            listing.clear()
            for number, item in enumerate(
                resolve_program(program, manager, bridge, document), 1
            ):
                entry = QtWidgets.QListWidgetItem(describe(item, number))
                entry.setData(0x0100, item.step.operation)
                listing.addItem(entry)
            if listing.count():
                listing.setCurrentRow(max(0, min(select, listing.count() - 1)))

        def shift(delta: int) -> None:
            current = listing.currentItem()
            if current is None:
                return
            row_index = listing.currentRow()
            with DocumentTransaction(document, "Reorder indexed program"):
                program.move(current.data(0x0100), row_index + delta)
            refresh(row_index + delta)

        up.clicked.connect(lambda: shift(-1))
        down.clicked.connect(lambda: shift(1))
        close.clicked.connect(dialog.accept)
        refresh()
        dialog.resize(560, 320)
        dialog.exec_()


def register() -> None:
    """Register the command with FreeCAD (idempotent)."""
    import FreeCADGui as Gui

    if COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(COMMAND_NAME, ProgramCommand())

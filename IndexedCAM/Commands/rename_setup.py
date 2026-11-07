"""Rename Setup command: change a Setup's name everywhere it is referenced.

``RenameSetupWorkflow`` has no FreeCAD dependency. Renaming updates, in one
undoable transaction, the stored Setup, its local model and the ``IndexedSetup``
property of every CAM operation bound to it.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, ContextManager, Optional, Protocol, Sequence, Tuple

from IndexedCAM.Core.indexed_setup import IndexedSetup
from IndexedCAM.Core.program import Program
from IndexedCAM.Core.setup_manager import SetupManager

COMMAND_NAME = "IndexedCAM_RenameSetup"
DIALOG_TITLE = "IndexedCAM - Renombrar setup"

RenameRequest = Callable[[Sequence[IndexedSetup], Callable[[str, str], str]], Optional[Tuple[str, str]]]


class SetupRenamer(Protocol):
    def rename_setup(self, old: str, new: str) -> None: ...


class RenameError(ValueError):
    """The rename cannot be performed."""


class RenameSetupWorkflow:
    """Choose a Setup and a new name -> rename it and everything linked to it."""

    def __init__(
        self,
        manager: SetupManager,
        renamer: SetupRenamer,
        ask: RenameRequest,
        transaction: Optional[Callable[[], ContextManager[Any]]] = None,
        program: Optional[Program] = None,
    ) -> None:
        self._program = program
        self._manager = manager
        self._renamer = renamer
        self._ask = ask
        self._transaction = transaction or nullcontext

    def run(self) -> Optional[IndexedSetup]:
        """Return the renamed Setup, or None if the user cancelled."""
        setups = self._manager.list()
        if not setups:
            raise RenameError("No hay setups que renombrar.")
        request = self._ask(
            setups, lambda old, new: self._manager.name_error(new, renaming=old)
        )
        if request is None:
            return None
        old, new = request
        error = self._manager.name_error(new, renaming=old)
        if error:
            raise RenameError(error)
        new = new.strip()
        with self._transaction():
            self._manager.rename(old, new)
            self._renamer.rename_setup(old, new)
            if self._program is not None:
                self._program.rename_setup(old, new)
        return self._manager.get(new)


def _ask_dialog(
    setups: Sequence[IndexedSetup], name_error: Callable[[str, str], str]
) -> Optional[Tuple[str, str]]:
    import FreeCADGui as Gui
    from PySide import QtWidgets

    dialog = QtWidgets.QDialog(Gui.getMainWindow())
    dialog.setWindowTitle(DIALOG_TITLE)
    form = QtWidgets.QFormLayout(dialog)
    setup_box = QtWidgets.QComboBox()
    for setup in setups:
        setup_box.addItem(setup.name, setup.name)
    name_edit = QtWidgets.QLineEdit(setups[0].name)
    message = QtWidgets.QLabel()
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )

    def refresh(*_: Any) -> None:
        error = name_error(setup_box.currentData(), name_edit.text())
        message.setText(error)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(not error)

    def pick(*_: Any) -> None:
        name_edit.setText(setup_box.currentData())

    setup_box.currentIndexChanged.connect(pick)
    name_edit.textChanged.connect(refresh)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow("Setup:", setup_box)
    form.addRow("Nuevo nombre:", name_edit)
    form.addRow(message)
    form.addRow(buttons)
    refresh()
    if not dialog.exec_():
        return None
    return setup_box.currentData(), name_edit.text()


class RenameSetupCommand:
    """FreeCAD command ``IndexedCAM_RenameSetup``."""

    def GetResources(self) -> dict:
        from IndexedCAM.Gui.resources import icon_path

        return {
            "Pixmap": icon_path("rename_setup.svg"),
            "MenuText": "Rename Setup",
            "ToolTip": (
                "Renombra un setup y actualiza su modelo local y sus operaciones CAM"
            ),
        }

    def IsActive(self) -> bool:
        import FreeCAD

        return FreeCAD.ActiveDocument is not None

    def Activated(self) -> None:
        import FreeCAD
        import FreeCADGui as Gui
        from PySide import QtWidgets

        from IndexedCAM.Commands.transaction import DocumentTransaction
        from IndexedCAM.Commands.context import build_context

        document = FreeCAD.ActiveDocument
        try:
            ctx = build_context(document)
            renamed = RenameSetupWorkflow(
                ctx.manager,
                ctx.bridge,
                _ask_dialog,
                lambda: DocumentTransaction(document, "Rename indexed setup"),
                ctx.program,
            ).run()
        except ValueError as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, str(error))
            return
        if renamed is not None:
            FreeCAD.Console.PrintMessage(
                "IndexedCAM: setup renombrado a '{}'\n".format(renamed.name)
            )


def register() -> None:
    """Register the command with FreeCAD (idempotent)."""
    import FreeCADGui as Gui

    if COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(COMMAND_NAME, RenameSetupCommand())

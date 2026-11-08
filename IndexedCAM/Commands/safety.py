"""Safety distance command: how high the head retracts to index (3+2).

The value is stored in the Job and used by both the Preview and the post
processor, so what you see is what the G-code does. Zero means the geometric
minimum (part half-diagonal + tool + holder), which keeps the retract as low as
possible inside the machine's travel.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, ContextManager, Optional

from IndexedCAM.Core.safety import MAXIMUM_MARGIN, MINIMUM_MARGIN, SafetyConfig

COMMAND_NAME = "IndexedCAM_Safety"
DIALOG_TITLE = "IndexedCAM - Distancia de seguridad"


class SafetyWorkflow:
    """Ask for the margin and store it; no FreeCAD dependency."""

    def __init__(
        self,
        storage: Any,
        ask: Callable[[SafetyConfig], Optional[SafetyConfig]],
        transaction: Optional[Callable[[], ContextManager[Any]]] = None,
    ) -> None:
        self._storage = storage
        self._ask = ask
        self._transaction = transaction or nullcontext

    def run(self) -> Optional[SafetyConfig]:
        """The stored config after the dialog, or None if the user cancelled."""
        current = self._storage.load()
        config = self._ask(current)
        if config is None:
            return None
        if config == current:
            return config
        with self._transaction():
            self._storage.save(config)
        return config


def _ask_dialog(current: SafetyConfig) -> Optional[SafetyConfig]:
    import FreeCADGui as Gui
    from PySide import QtWidgets

    dialog = QtWidgets.QDialog(Gui.getMainWindow())
    dialog.setWindowTitle(DIALOG_TITLE)
    form = QtWidgets.QFormLayout(dialog)
    spin = QtWidgets.QDoubleSpinBox()
    spin.setDecimals(1)
    spin.setSingleStep(5.0)
    spin.setRange(MINIMUM_MARGIN, MAXIMUM_MARGIN)
    spin.setSuffix(" mm")
    spin.setValue(current.margin)
    spin.setSpecialValueText("mínima (0 mm)")
    holder = QtWidgets.QCheckBox("Modelar el portaherramientas")
    holder.setChecked(current.holder)
    head = QtWidgets.QCheckBox("Modelar el cabezal")
    head.setChecked(current.head)
    accessories = QtWidgets.QLabel(
        "Por defecto solo se modela la herramienta. Actívalos para comprobar\n"
        "las colisiones contra el portaherramientas y el cabezal reales."
    )
    accessories.setWordWrap(True)
    explanation = QtWidgets.QLabel(
        "Altura adicional sobre el mínimo geométrico, que es la media\n"
        "diagonal de la pieza: en el giro la herramienta apunta hacia\n"
        "fuera, así que su largo y el del portaherramientas no cuentan.\n\n"
        "0 mm = mínimo. Súbelo si el Preview marca colisión en los giros\n"
        "o si el portaherramientas barre la pieza al indexar.\n"
        "Se usa en el Preview y en el G-code."
    )
    explanation.setWordWrap(True)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow("Distancia de seguridad:", spin)
    form.addRow(explanation)
    form.addRow(holder)
    form.addRow(head)
    form.addRow(accessories)
    form.addRow(buttons)
    if not dialog.exec_():
        return None
    return SafetyConfig(spin.value(), holder.isChecked(), head.isChecked())


class SafetyCommand:
    """FreeCAD command ``IndexedCAM_Safety``."""

    def GetResources(self) -> dict:
        from IndexedCAM.Gui.resources import icon_path

        return {
            "Pixmap": icon_path("safety.svg"),
            "MenuText": "Seguridad",
            "ToolTip": (
                "Altura de retirada para los giros B/C (la usan el Preview y el G-code)"
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
        from IndexedCAM.Commands.transaction import DocumentTransaction
        from IndexedCAM.Core.job_context import JobCancelled
        from IndexedCAM.Core.safety import JobSafetyStorage

        document = FreeCAD.ActiveDocument
        try:
            ctx = open_context(document, selected_objects())
            stored = SafetyWorkflow(
                JobSafetyStorage(ctx.job),
                _ask_dialog,
                lambda: DocumentTransaction(document, "Set indexed safety distance"),
            ).run()
        except JobCancelled:
            return
        except ValueError as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, str(error))
            return
        if stored is not None:
            FreeCAD.Console.PrintMessage("IndexedCAM: {}\n".format(stored.describe()))


def register() -> None:
    import FreeCADGui as Gui

    Gui.addCommand(COMMAND_NAME, SafetyCommand())

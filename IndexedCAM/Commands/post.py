"""Post command: write the Job's indexed program as LinuxCNC G-code.

``DocumentPostResources`` adapts the FreeCAD document to the pure
``PostBuilder``; the safety sphere is the same one the Preview uses, so the
retract and approach heights of the G-code match what was previewed.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Dict, List, Optional, Sequence

from IndexedCAM.Core.post_builder import PostBuilder
from IndexedCAM.Core.post_program import PostMove, PostProgram, PostTool, moves_from_commands
from IndexedCAM.Core.post_settings import PostSettings
from IndexedCAM.Core.preview import sphere_for
from IndexedCAM.Post.linuxcnc import LinuxCNCPost

COMMAND_NAME = "IndexedCAM_Post"
DIALOG_TITLE = "IndexedCAM - Postprocesar"
FILE_FILTER = "G-code LinuxCNC (*.ngc *.tap);;Todos los ficheros (*)"

COOLANTS = {"flood": "flood", "mist": "mist"}


class DocumentPostResources:
    """Moves, tool, spindle and coolant of each operation, read from the document."""

    def __init__(self, document: Any) -> None:
        self._document = document
        self._tools: Dict[str, PostTool] = {}

    def _operation(self, name: str) -> Any:
        operation = self._document.getObject(name)
        if operation is None:
            raise KeyError("la operación ya no existe: {}".format(name))
        return operation

    def moves(self, operation: str) -> Sequence[PostMove]:
        return moves_from_commands(self._operation(operation).Path.Commands)

    def tool(self, operation: str) -> PostTool:
        if operation not in self._tools:
            controller = getattr(self._operation(operation), "ToolController", None)
            tool = getattr(controller, "Tool", None)
            number = int(getattr(controller, "ToolNumber", 0) or 0)
            diameter = float(getattr(tool, "Diameter", 0.0) or 0.0)
            name = str(getattr(tool, "Label", "") or getattr(tool, "Name", ""))
            self._tools[operation] = PostTool(max(1, number), name, diameter)
        return self._tools[operation]

    def spindle(self, operation: str) -> Optional[int]:
        controller = getattr(self._operation(operation), "ToolController", None)
        speed = int(getattr(controller, "SpindleSpeed", 0) or 0)
        return speed if speed > 0 else None

    def coolant(self, operation: str) -> str:
        mode = str(getattr(self._operation(operation), "CoolantMode", "") or "").lower()
        return COOLANTS.get(mode, "")

    def feed(self, operation: str) -> Optional[float]:
        """Feed CAM would use: the horizontal one, else the vertical one.

        A freshly created ToolController has both at zero, which is what makes
        CAM emit ``G1`` blocks without a usable feed.
        """
        controller = getattr(self._operation(operation), "ToolController", None)
        for name in ("HorizFeed", "VertFeed"):
            value = getattr(getattr(controller, name, None), "Value", 0.0) or 0.0
            if value > 0.0:
                return float(value)
        return None


def build_post(document: Any, manager: Any, program: Any, bridge: Any, name: str = "", safety: Any = None) -> PostProgram:
    """Build the ``PostProgram`` of the document's indexed program."""
    from IndexedCAM.Commands.program import resolve_program
    from IndexedCAM.Core.safety import SafetyConfig
    items = resolve_program(program, manager, bridge, document)
    setups = {s.name: s for s in manager.list()}
    if not items:
        return PostProgram(name=name)
    resources = DocumentPostResources(document)
    margin = (safety or SafetyConfig()).margin
    sphere = _sphere(document, setups, items, margin)
    return PostBuilder(setups, resources, sphere, name).build(items)


def _sphere(document: Any, setups: Dict[str, Any], items: Sequence[Any], margin: float) -> Any:
    from IndexedCAM.Core.operation_assignment import parse_source

    source = document.getObject(parse_source(setups[items[0].step.setup].metadata["source"]).object_name)
    box = source.Shape.BoundBox
    return sphere_for(
        ((box.XMin, box.YMin, box.ZMin), (box.XMax, box.YMax, box.ZMax)), margin
    )


def write_program(text: str, path: str) -> None:
    """Write the G-code as LF line endings (LinuxCNC is happier with them)."""
    with open(path, "w", encoding="ascii", errors="replace", newline="\n") as handle:
        handle.write(text)


def default_path(document: Any, name: str) -> str:
    """Suggested file: next to the .FCStd, else in the home directory."""
    filename = getattr(document, "FileName", "") or ""
    folder = os.path.dirname(filename) if filename else os.path.expanduser("~")
    return os.path.join(folder, (name or "program") + ".ngc")


def options_dialog(current: PostSettings, program: PostProgram) -> Optional[PostSettings]:
    """Everything that depends on the controller, plus what the post will emit."""
    import FreeCADGui as Gui
    from PySide import QtWidgets

    dialog = QtWidgets.QDialog(Gui.getMainWindow())
    dialog.setWindowTitle(DIALOG_TITLE + " - opciones")
    signs = current.signs
    config = current.config

    b_sign = QtWidgets.QComboBox()
    b_sign.addItem("+  (B+ inclina la herramienta hacia +X con C=0)", 1.0)
    b_sign.addItem("-  (invertido)", -1.0)
    b_sign.setCurrentIndex(0 if signs.b_sign >= 0 else 1)
    c_sign = QtWidgets.QComboBox()
    c_sign.addItem("+  (C+ antihorario visto desde +Z)", 1.0)
    c_sign.addItem("-  (invertido)", -1.0)
    c_sign.setCurrentIndex(0 if signs.c_sign >= 0 else 1)

    def spin(value: float, low: float, high: float, step: float, suffix: str) -> Any:
        box = QtWidgets.QDoubleSpinBox()
        box.setDecimals(3)
        box.setRange(low, high)
        box.setSingleStep(step)
        box.setSuffix(suffix)
        box.setValue(value)
        return box

    b_zero = spin(signs.b_zero, -360.0, 360.0, 1.0, " °")
    c_zero = spin(signs.c_zero, -360.0, 360.0, 1.0, " °")
    units = QtWidgets.QComboBox()
    units.addItem("mm (G21)", "mm")
    units.addItem("pulgadas (G20)", "in")
    units.setCurrentIndex(0 if config.units == "mm" else 1)
    decimals = QtWidgets.QSpinBox()
    decimals.setRange(0, 6)
    decimals.setValue(config.decimals)
    default_feed = spin(config.default_feed, 1.0, 100000.0, 50.0, " mm/min")
    tool_length = QtWidgets.QComboBox()
    for label, value in (
        ("G43.4 (cinematica primaria)", "G43.4"),
        ("G43 (maquina sin conmutar)", "G43"),
        ("ninguna (lo pone el operador)", "none"),
    ):
        tool_length.addItem(label, value)
    tool_length.setCurrentIndex(
        {"G43.4": 0, "G43": 1, "none": 2}.get(config.tool_length, 0)
    )
    coolant = QtWidgets.QCheckBox("Refrigerante (M8/M7)")
    coolant.setChecked(config.coolant)
    stop_spindle = QtWidgets.QCheckBox("Parar el husillo entre orientaciones")
    stop_spindle.setChecked(config.stop_spindle_between)
    vertical = QtWidgets.QCheckBox("Cabezal vertical antes del cambio de herramienta")
    vertical.setChecked(config.vertical_before_tool_change)
    numbers = QtWidgets.QCheckBox("Numerar las líneas (N...)")
    numbers.setChecked(config.line_numbers)

    summary = QtWidgets.QPlainTextEdit()
    summary.setReadOnly(True)
    summary.setMaximumHeight(130)
    lines = []
    for orientation in program.orientations:
        lines.append(
            "{:<12} B{:8.3f} C{:9.3f}   normal ({:.3f}, {:.3f}, {:.3f})   {} op.".format(
                orientation.name,
                orientation.b,
                orientation.c,
                orientation.z_axis[0],
                orientation.z_axis[1],
                orientation.z_axis[2],
                len(orientation.operations),
            )
        )
    summary.setPlainText("\n".join(lines) or "(el programa está vacío)")

    head_group = QtWidgets.QGroupBox("Cabezal")
    head_form = QtWidgets.QFormLayout(head_group)
    head_form.addRow("Sentido de B:", b_sign)
    head_form.addRow("Cero de B:", b_zero)
    head_form.addRow("Sentido de C:", c_sign)
    head_form.addRow("Cero de C:", c_zero)

    control_group = QtWidgets.QGroupBox("Control")
    control_form = QtWidgets.QFormLayout(control_group)
    control_form.addRow("Longitud de herramienta:", tool_length)
    control_form.addRow(coolant)
    control_form.addRow(stop_spindle)
    control_form.addRow(vertical)

    format_group = QtWidgets.QGroupBox("Formato")
    format_form = QtWidgets.QFormLayout(format_group)
    format_form.addRow("Unidades:", units)
    format_form.addRow("Decimales:", decimals)
    format_form.addRow("Avance por defecto:", default_feed)
    format_form.addRow(numbers)

    note = QtWidgets.QLabel(
        "El avance por defecto solo se usa si CAM no trae ninguno.\n"
        "Si la herramienta entra por dentro de la pieza en una cara lateral,\n"
        "prueba a invertir el sentido de B (o el cero) y compara la normal."
    )
    note.setWordWrap(True)
    buttons = QtWidgets.QDialogButtonBox(
        QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
    )
    buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Postprocesar")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)

    box = QtWidgets.QVBoxLayout(dialog)
    box.addWidget(head_group)
    box.addWidget(control_group)
    box.addWidget(format_group)
    box.addWidget(QtWidgets.QLabel("Orientaciones del programa:"))
    box.addWidget(summary)
    box.addWidget(note)
    box.addWidget(buttons)
    if not dialog.exec_():
        return None
    from IndexedCAM.Post.linuxcnc import AxisSigns, LinuxCNCConfig

    return PostSettings(
        LinuxCNCConfig(
            units=units.currentData(),
            decimals=decimals.value(),
            feed_decimals=config.feed_decimals,
            line_numbers=numbers.isChecked(),
            line_start=config.line_start,
            line_step=config.line_step,
            tool_length=tool_length.currentData(),
            coolant=coolant.isChecked(),
            stop_spindle_between=stop_spindle.isChecked(),
            vertical_before_tool_change=vertical.isChecked(),
            default_feed=default_feed.value(),
            header=config.header,
            signs=AxisSigns(b_sign.currentData(), c_sign.currentData(), b_zero.value(), c_zero.value()),
        ),
        current.name,
    )


class PostCommand:
    """FreeCAD command ``IndexedCAM_Post``."""

    def GetResources(self) -> dict:
        from IndexedCAM.Gui.resources import icon_path

        return {
            "Pixmap": icon_path("post.svg"),
            "MenuText": "Postprocesar",
            "ToolTip": "Genera el G-code LinuxCNC del programa indexado (planos G68.2 + B/C)",
        }

    def IsActive(self) -> bool:
        import FreeCAD

        return FreeCAD.ActiveDocument is not None

    def Activated(self) -> None:
        import FreeCAD
        import FreeCADGui as Gui
        from PySide import QtWidgets

        from IndexedCAM.Commands.context import open_context, selected_objects
        from IndexedCAM.Core.job_context import JobCancelled
        from IndexedCAM.Core.post_settings import JobPostStorage
        from IndexedCAM.Core.safety import JobSafetyStorage

        document = FreeCAD.ActiveDocument
        try:
            ctx = open_context(document, selected_objects())
            name = str(getattr(ctx.job, "Label", "") or getattr(ctx.job, "Name", ""))
            safety = JobSafetyStorage(ctx.job).load()
            post = build_post(document, ctx.manager, ctx.program, ctx.bridge, name, safety)
        except JobCancelled:
            return
        except (ValueError, KeyError) as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, str(error))
            return
        if post.empty:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), DIALOG_TITLE, "El programa está vacío: asigna operaciones primero."
            )
            return
        storage = JobPostStorage(ctx.job)
        settings = options_dialog(storage.load(), post)
        if settings is None:
            return
        storage.save(PostSettings(settings.config, name))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            Gui.getMainWindow(), DIALOG_TITLE, default_path(document, name), FILE_FILTER
        )
        if not path:
            return
        config = settings.config
        if not config.header:
            config = dataclasses.replace(config, header=tuple(_header(post)))
        text = LinuxCNCPost().render(post, config)
        try:
            write_program(text, path)
        except OSError as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, "No se pudo escribir: {}".format(error))
            return
        summary = summary_text(post, len(text.splitlines()))
        FreeCAD.Console.PrintMessage(summary + " -> " + path + "\n")
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), DIALOG_TITLE, summary + "\n\n" + path)


def _header(post: PostProgram) -> List[str]:
    """Comment lines with the orientation of every block (B/C and face origin)."""
    lines = []
    for orientation in post.orientations:
        lines.append(
            "{}: B{:.3f} C{:.3f}, origen ({:.3f}, {:.3f}, {:.3f}), {} operación(es)".format(
                orientation.name,
                orientation.b,
                orientation.c,
                orientation.origin[0],
                orientation.origin[1],
                orientation.origin[2],
                len(orientation.operations),
            )
        )
    return lines


def summary_text(post: PostProgram, lines: int) -> str:
    """One line describing what was posted."""
    operations = len(post.operations())
    return "{} orientación(es), {} operación(es), {} herramienta(s), {} líneas".format(
        len(post), operations, len(post.tools()), lines
    )


def register() -> None:
    import FreeCADGui as Gui

    Gui.addCommand(COMMAND_NAME, PostCommand())

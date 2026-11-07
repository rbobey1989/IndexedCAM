"""Post command: write the Job's indexed program as LinuxCNC G-code.

``DocumentPostResources`` adapts the FreeCAD document to the pure
``PostBuilder``; the safety sphere is the same one the Preview uses, so the
retract and approach heights of the G-code match what was previewed.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from IndexedCAM.Core.post_builder import PostBuilder
from IndexedCAM.Core.post_program import PostMove, PostProgram, PostTool, moves_from_commands
from IndexedCAM.Core.preview import sphere_for
from IndexedCAM.Post.linuxcnc import LinuxCNCConfig, LinuxCNCPost

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
    from IndexedCAM.Machine.bc_machine import BCMachine

    items = resolve_program(program, manager, bridge, document)
    setups = {s.name: s for s in manager.list()}
    if not items:
        return PostProgram(name=name)
    machine = BCMachine()
    resources = DocumentPostResources(document)
    margin = (safety or SafetyConfig()).margin
    sphere = _sphere(document, setups, items, machine, margin)
    return PostBuilder(setups, resources, sphere, name).build(items)


def _sphere(
    document: Any, setups: Dict[str, Any], items: Sequence[Any], machine: Any, margin: float
) -> Any:
    from IndexedCAM.Core.operation_assignment import parse_source

    source = document.getObject(parse_source(setups[items[0].step.setup].metadata["source"]).object_name)
    box = source.Shape.BoundBox
    return sphere_for(
        ((box.XMin, box.YMin, box.ZMin), (box.XMax, box.YMax, box.ZMax)),
        machine.envelope,
        margin,
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
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            Gui.getMainWindow(), DIALOG_TITLE, default_path(document, name), FILE_FILTER
        )
        if not path:
            return
        config = LinuxCNCConfig(header=_header(post))
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

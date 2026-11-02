"""Preview command: see the tool move through the program, with collisions in red.

``DocumentResources`` adapts the FreeCAD document to the pure
``PreviewBuilder``; the dialog is a non-modal player (list, slider, play).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from IndexedCAM.Core.collision_checker import checker_for_operation
from IndexedCAM.Core.operation_assignment import parse_source
from IndexedCAM.Core.path_endpoints import path_points
from IndexedCAM.Core.preview import Clip, PreviewBuilder, sphere_for
from IndexedCAM.Core.transition_planner import TransitionPlanner
from IndexedCAM.Machine.bc_machine import BCMachine
from IndexedCAM.Machine.envelope import Envelope

COMMAND_NAME = "IndexedCAM_Preview"
DIALOG_TITLE = "IndexedCAM - Previsualización"
RED_TEXT = "color: #c00000; font-weight: bold"


class DocumentResources:
    """Envelope, checker and local path of each operation, read from the document."""

    def __init__(self, document: Any, bridge: Any, base: Envelope, step_setups: Dict[str, str], setups: Dict[str, Any]) -> None:
        self._document = document
        self._bridge = bridge
        self._base = base
        self._step_setups = step_setups
        self._setups = setups
        self._checkers: Dict[str, Any] = {}

    def _operation(self, name: str) -> Any:
        return self._document.getObject(name)

    def envelope(self, operation: str) -> Envelope:
        return self._bridge.envelope_for(self._operation(operation), self._base)

    def checker(self, operation: str) -> Any:
        if operation not in self._checkers:
            setup = self._setups[self._step_setups[operation]]
            source = self._document.getObject(parse_source(setup.metadata["source"]).object_name)
            self._checkers[operation] = checker_for_operation(
                self._bridge, source, self._operation(operation), self._base
            )
        return self._checkers[operation]

    def local_path(self, operation: str) -> Sequence[Any]:
        return path_points(self._operation(operation).Path.Commands, step=2.0)


def build_clips(document: Any, manager: Any, program: Any, bridge: Any, machine: Optional[BCMachine] = None) -> List[Clip]:
    from IndexedCAM.Commands.program import resolve_program

    machine = machine or BCMachine()
    items = resolve_program(program, manager, bridge, document)
    if not items:
        return []
    setups = {s.name: s for s in manager.list()}
    resources = DocumentResources(
        document, bridge, machine.envelope, {i.step.operation: i.step.setup for i in items}, setups
    )
    first = setups[items[0].step.setup]
    source = document.getObject(parse_source(first.metadata["source"]).object_name)
    box = source.Shape.BoundBox
    sphere = sphere_for(
        ((box.XMin, box.YMin, box.ZMin), (box.XMax, box.YMax, box.ZMax)), machine.envelope
    )
    # a transition is validated with the tool of the step it leads to
    return PreviewBuilder(
        setups,
        resources,
        lambda operation: TransitionPlanner(machine, resources.checker(operation), sphere),
    ).build(items)


class PreviewCommand:
    """FreeCAD command ``IndexedCAM_Preview``."""

    _window: Any = None

    def GetResources(self) -> dict:
        from IndexedCAM.Gui.resources import icon_path

        return {
            "Pixmap": icon_path("preview.svg"),
            "MenuText": "Preview",
            "ToolTip": "Reproduce el programa mostrando herramienta, cabezal y colisiones",
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
        from IndexedCAM.Core.setup_manager import SetupManager

        document = FreeCAD.ActiveDocument
        try:
            clips = build_clips(
                document,
                SetupManager(DocumentStorage(document)),
                Program(ProgramDocumentStorage(document)),
                CamBridge(document),
            )
        except (ValueError, KeyError) as error:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), DIALOG_TITLE, str(error))
            return
        if not clips:
            QtWidgets.QMessageBox.information(
                Gui.getMainWindow(), DIALOG_TITLE, "El programa está vacío: asigna operaciones primero."
            )
            return
        if PreviewCommand._window is not None:
            PreviewCommand._window.close()
        PreviewCommand._window = PreviewWindow(clips)
        PreviewCommand._window.show()


class PreviewWindow:
    """Non-modal player: pick a clip, drag the slider or press play."""

    def __init__(self, clips: Sequence[Clip]) -> None:
        import FreeCADGui as Gui
        from PySide import QtCore, QtWidgets

        from IndexedCAM.Gui.tool_view import ToolView

        self._clips = list(clips)
        self._view = ToolView()
        self._dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self._dialog.setWindowTitle(DIALOG_TITLE)
        self._dialog.finished.connect(lambda *_: self._view.clear())
        layout = QtWidgets.QVBoxLayout(self._dialog)
        self._list = QtWidgets.QListWidget()
        for clip in self._clips:
            self._list.addItem(clip.title + ("  ⚠" if clip.error else ""))
        self._status = QtWidgets.QLabel()
        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._play = QtWidgets.QPushButton("▶ Reproducir")
        self._check = QtWidgets.QPushButton("Buscar colisiones")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self._play)
        row.addWidget(self._check)
        for widget in (self._list, self._slider, self._status):
            layout.addWidget(widget)
        layout.addLayout(row)
        self._timer = QtCore.QTimer(self._dialog)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._list.currentRowChanged.connect(self._select)
        self._slider.valueChanged.connect(self._show)
        self._play.clicked.connect(self._toggle)
        self._check.clicked.connect(self._find_collision)
        self._dialog.resize(520, 380)
        self._list.setCurrentRow(0)

    def show(self) -> None:
        self._dialog.show()

    def close(self) -> None:
        self._dialog.close()

    @property
    def _clip(self) -> Clip:
        return self._clips[max(0, self._list.currentRow())]

    def _select(self, row: int) -> None:
        if row < 0:
            return
        self._timer.stop()
        self._play.setText("▶ Reproducir")
        clip = self._clip
        self._view.show_path(clip.tips())
        self._slider.blockSignals(True)
        self._slider.setRange(0, max(0, len(clip) - 1))
        self._slider.setValue(0)
        self._slider.blockSignals(False)
        self._show(0)

    def _show(self, index: int) -> None:
        clip = self._clip
        if not len(clip):
            self._status.setText(clip.error or "Sin movimientos")
            return
        frame = clip.frames[index]
        hit = clip.collision(index)
        self._view.show_tool(clip.poses(index), collides=bool(hit))
        text = "{}  B={:.1f} C={:.1f}  {}".format(clip.title, frame.b, frame.c, frame.label)
        if hit:
            text += "\nCOLISIÓN: " + hit
        elif clip.error:
            text += "\n" + clip.error
        self._status.setStyleSheet(RED_TEXT if hit or clip.error else "")
        self._status.setText(text)

    def _toggle(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._play.setText("▶ Reproducir")
        else:
            if self._slider.value() >= self._slider.maximum():
                self._slider.setValue(0)
            self._timer.start()
            self._play.setText("⏸ Pausa")

    def _tick(self) -> None:
        if self._slider.value() >= self._slider.maximum():
            self._toggle()
            return
        self._slider.setValue(self._slider.value() + 1)

    def _find_collision(self) -> None:
        index = self._clip.first_collision()
        if index is None:
            self._status.setStyleSheet("")
            self._status.setText(self._clip.title + ": sin colisiones")
        else:
            self._slider.setValue(index)


def register() -> None:
    """Register the command with FreeCAD (idempotent)."""
    import FreeCADGui as Gui

    if COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(COMMAND_NAME, PreviewCommand())

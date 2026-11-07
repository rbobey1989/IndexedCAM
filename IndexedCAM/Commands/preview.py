"""Preview command: see the tool move through the program, with collisions in red.

``DocumentResources`` adapts the FreeCAD document to the pure
``PreviewBuilder``; the dialog is a non-modal player (list, slider, play).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from IndexedCAM.Core.collision_checker import checker_for_operation
from IndexedCAM.Core.operation_assignment import parse_source, source_box
from IndexedCAM.Core.path_endpoints import path_points
from IndexedCAM.Core.preview import Clip, Playlist, PreviewBuilder, describe_tool, sphere_for
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
        self._meshes: Dict[Any, Any] = {}

    def _operation(self, name: str) -> Any:
        return self._document.getObject(name)

    def envelope(self, operation: str) -> Envelope:
        return self._bridge.envelope_for(self._operation(operation), self._base)

    def tool_mesh(self, operation: str) -> Any:
        """Triangles of the real tool shape (tip at the origin, axis +Z), cached per tool."""
        tool = getattr(getattr(self._operation(operation), "ToolController", None), "Tool", None)
        key = getattr(tool, "Name", None) or id(tool)
        if key not in self._meshes:
            self._meshes[key] = tessellate_tool(tool)
        return self._meshes[key]

    def tool_label(self, operation: str) -> str:
        controller = getattr(self._operation(operation), "ToolController", None)
        name = getattr(controller, "Label", "")
        detail = describe_tool(self.envelope(operation))
        return "{} ({})".format(name, detail) if name else detail

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


def tessellate_tool(tool: Any, tolerance: float = 0.05) -> Any:
    """(vertices, triangles) of the CAM tool shape, or None if it has none."""
    try:
        shape = tool.Shape
        if shape is None or shape.isNull():
            return None
        vertices, faces = shape.tessellate(tolerance)
    except Exception:
        return None
    return [(v.x, v.y, v.z) for v in vertices], [tuple(f) for f in faces]


def build_clips(
    document: Any,
    manager: Any,
    program: Any,
    bridge: Any,
    machine: Optional[BCMachine] = None,
    owner: Any = None,
) -> List[Clip]:
    from IndexedCAM.Commands.program import resolve_program
    from IndexedCAM.Core.safety import DocumentSafetyStorage, SafetyConfig

    safety = DocumentSafetyStorage(owner).load() if owner is not None else SafetyConfig()
    if machine is None:
        machine = BCMachine()
        machine = BCMachine(envelope=machine.envelope.with_accessories(safety.holder, safety.head))
    items = resolve_program(program, manager, bridge, document)
    if not items:
        return []
    setups = {s.name: s for s in manager.list()}
    resources = DocumentResources(
        document, bridge, machine.envelope, {i.step.operation: i.step.setup for i in items}, setups
    )
    sphere = sphere_for(source_box(document, setups[items[0].step.setup]), safety.margin)
    # a transition is validated with the tool of the step it leads to
    return PreviewBuilder(
        setups,
        resources,
        lambda operation: TransitionPlanner(machine, resources.checker(operation), sphere),
        sphere,
    ).build(items)


STOCK_MAX_CELLS = 800_000
STOCK_ALLOWANCE = 1.0
REFRESH_SECONDS = 0.15


def stock_for_program(document: Any, bridge: Any, allowance: float = STOCK_ALLOWANCE) -> Any:
    """Voxel stock of the whole program: the box around the machined part.

    The stock is in part coordinates because that is what the preview carves
    (each clip converts its local path through its Setup's frame). It is grown
    by ``allowance`` so the material the tool takes off the faces is visible.
    """
    from IndexedCAM.Core.voxel_stock import VoxelStock

    setups = bridge.jobs.setups()
    corners = source_box(document, setups[0]) if setups else None
    if corners is None:
        return None
    low = tuple(value - allowance for value in corners[0])
    high = tuple(value + allowance for value in corners[1])
    resolution = (
        (high[0] - low[0]) * (high[1] - low[1]) * (high[2] - low[2]) / STOCK_MAX_CELLS
    ) ** (1 / 3)
    return VoxelStock(low, high, resolution, STOCK_MAX_CELLS, None)


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

        from IndexedCAM.Commands.context import build_context

        document = FreeCAD.ActiveDocument
        try:
            ctx = build_context(document)
            clips = build_clips(document, ctx.manager, ctx.program, ctx.bridge, owner=document)
            stock = stock_for_program(document, ctx.bridge) if clips else None
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
        PreviewCommand._window = PreviewWindow(clips, stock, ctx.bridge.stocks())
        PreviewCommand._window.show()


class PreviewWindow:
    """Non-modal player over the ticked clips, in order.

    Every entry of the list has a checkbox: the slider and the play button run
    the ticked ones one after another, so the whole program (operations,
    transitions and the final return to vertical) is one continuous movement.
    """

    def __init__(self, clips: Sequence[Clip], stock: Any = None, stocks: Sequence[Any] = ()) -> None:
        import FreeCADGui as Gui
        from PySide import QtCore, QtWidgets

        from IndexedCAM.Gui.tool_view import ToolView

        self._clips = list(clips)
        self._view = ToolView()
        self._timeline = None
        self._stocks = list(stocks)
        self._stocks_visible: Dict[Any, bool] = {}
        self._last_refresh = 0.0
        self._playlist = Playlist.of(self._clips)
        self._clip_index: Optional[int] = None
        if stock is not None:
            from IndexedCAM.Core.stock_timeline import StockTimeline

            self._timeline = StockTimeline(stock, self._clips)
        self._dialog = QtWidgets.QDialog(Gui.getMainWindow())
        self._dialog.setWindowTitle(DIALOG_TITLE)
        self._dialog.finished.connect(lambda *_: self._closed())
        layout = QtWidgets.QVBoxLayout(self._dialog)
        self._list = QtWidgets.QListWidget()
        for clip in self._clips:
            item = QtWidgets.QListWidgetItem(
                clip.title + ("  ⚠" if clip.error else "") + ("\n    " + clip.tool if clip.tool else "")
            )
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            self._list.addItem(item)
        self._status = QtWidgets.QLabel()
        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._play = QtWidgets.QPushButton("▶ Reproducir seleccionadas")
        self._check = QtWidgets.QPushButton("Buscar colisiones")
        self._all = QtWidgets.QPushButton("Todas")
        self._none = QtWidgets.QPushButton("Ninguna")
        self._stock_box = QtWidgets.QCheckBox("Mostrar stock y material retirado")
        self._stock_box.setChecked(self._timeline is not None)
        self._stock_box.setEnabled(self._timeline is not None)
        self._stock_box.toggled.connect(lambda _: self._show(self._slider.value(), force=True))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self._play)
        row.addWidget(self._check)
        selection = QtWidgets.QHBoxLayout()
        selection.addWidget(QtWidgets.QLabel("Reproducir:"))
        selection.addWidget(self._all)
        selection.addWidget(self._none)
        selection.addStretch()
        for widget in (self._list, self._slider, self._status):
            layout.addWidget(widget)
        layout.addWidget(self._stock_box)
        layout.addLayout(selection)
        layout.addLayout(row)
        self._timer = QtCore.QTimer(self._dialog)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._list.currentRowChanged.connect(self._select)
        self._list.itemChanged.connect(self._checked)
        self._slider.valueChanged.connect(self._show)
        self._play.clicked.connect(self._toggle)
        self._check.clicked.connect(self._find_collision)
        self._all.clicked.connect(lambda: self._tick_all(True))
        self._none.clicked.connect(lambda: self._tick_all(False))
        self._dialog.resize(560, 420)
        self._rebuild(0)
        self._list.setCurrentRow(0)

    def show(self) -> None:
        self._hide_stocks()
        self._dialog.show()
        self._show(self._slider.value(), force=True)

    # --- playlist -------------------------------------------------------

    def _selected(self) -> List[int]:
        from PySide import QtCore

        return [
            row
            for row in range(self._list.count())
            if self._list.item(row).checkState() == QtCore.Qt.Checked
        ]

    def _rebuild(self, position: Optional[int] = None) -> None:
        self._playlist = Playlist.of(self._clips, self._selected())
        self._slider.blockSignals(True)
        self._slider.setRange(0, max(0, len(self._playlist) - 1))
        self._slider.setValue(min(position or 0, self._slider.maximum()))
        self._slider.blockSignals(False)
        self._clip_index = None

    def _tick_all(self, checked: bool) -> None:
        from PySide import QtCore

        self._list.blockSignals(True)
        for row in range(self._list.count()):
            self._list.item(row).setCheckState(QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked)
        self._list.blockSignals(False)
        self._checked(None)

    def _checked(self, item: Any) -> None:
        current = self._playlist.at(self._slider.value()) if len(self._playlist) else None
        self._rebuild(0 if current is None else self._playlist.entries.index(current))
        self._show(self._slider.value(), force=True)

    def _select(self, row: int) -> None:
        """Clicking a row shows its first frame and includes it in the playlist."""
        from PySide import QtCore

        if row < 0:
            return
        self._timer.stop()
        self._play.setText("▶ Reproducir seleccionadas")
        if self._list.item(row).checkState() != QtCore.Qt.Checked:
            self._list.blockSignals(True)
            self._list.item(row).setCheckState(QtCore.Qt.Checked)
            self._list.blockSignals(False)
            self._rebuild(0)
        position = self._playlist.first_in(row)
        if position is not None:
            self._slider.setValue(position)
        self._show(self._slider.value(), force=True)

    # --- drawing --------------------------------------------------------

    def _hide_stocks(self) -> None:
        for stock in self._stocks:
            self._hide_stock(stock)

    def _hide_stock(self, stock: Any) -> None:
        view = getattr(stock, "ViewObject", None)
        if view is not None and self._timeline is not None:
            self._stocks_visible[stock.Name] = view.Visibility
            view.Visibility = False

    def _closed(self) -> None:
        self._timer.stop()
        self._view.clear()
        for stock in self._stocks:
            view = getattr(stock, "ViewObject", None)
            if view is not None and stock.Name in self._stocks_visible:
                view.Visibility = self._stocks_visible[stock.Name]

    def _update_stock(self, clip_index: int, index: int, force: bool) -> None:
        import time

        if self._timeline is None:
            return
        if not self._stock_box.isChecked():
            self._view.hide_stock()
            return
        stock = self._timeline.show(clip_index, index)
        now = time.monotonic()
        # while playing, the mesh is rebuilt only a few times per second
        if force or not self._timer.isActive() or now - self._last_refresh >= REFRESH_SECONDS:
            self._view.show_stock(stock.triangles())
            self._last_refresh = now

    def close(self) -> None:
        self._dialog.close()

    def _show(self, position: int, force: bool = False) -> None:
        entry = self._playlist.at(position)
        if entry is None:
            self._status.setStyleSheet("")
            self._status.setText("No hay nada seleccionado: marca alguna entrada.")
            self._view.clear()
            return
        clip_index, index = entry
        clip = self._clips[clip_index]
        if clip_index != self._clip_index:
            self._clip_index = clip_index
            self._list.blockSignals(True)
            self._list.setCurrentRow(clip_index)
            self._list.blockSignals(False)
            self._view.show_path(clip.tips())
        if not len(clip):
            self._status.setText(clip.error or "Sin movimientos")
            return
        frame = clip.frames[index]
        hit = clip.collision(index)
        self._view.show_tool(clip.poses(index), collides=bool(hit), mesh=clip.tool_mesh)
        self._update_stock(clip_index, index, force)
        text = "{} / {}  ·  {}  B={:.1f} C={:.1f}  {}".format(
            position + 1, len(self._playlist), clip.title, frame.b, frame.c, frame.label
        )
        if clip.tool:
            text += "\nHerramienta: " + clip.tool
        if hit:
            text += "\nCOLISIÓN: " + hit
        elif clip.error:
            text += "\n" + clip.error
        self._status.setStyleSheet(RED_TEXT if hit or clip.error else "")
        self._status.setText(text)

    def _toggle(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._play.setText("▶ Reproducir seleccionadas")
            return
        if not len(self._playlist):
            self._status.setText("No hay nada seleccionado: marca alguna entrada.")
            return
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
        for position in range(len(self._playlist)):
            clip_index, index = self._playlist.at(position)  # type: ignore[misc]
            if self._clips[clip_index].collision(index):
                self._slider.setValue(position)
                return
        self._status.setStyleSheet("")
        self._status.setText("sin colisiones en lo seleccionado")


def register() -> None:
    """Register the command with FreeCAD (idempotent)."""
    import FreeCADGui as Gui

    if COMMAND_NAME not in Gui.listCommands():
        Gui.addCommand(COMMAND_NAME, PreviewCommand())

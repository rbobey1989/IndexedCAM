"""Preview command: see the tool move through the program, with collisions in red.

``DocumentResources`` adapts the FreeCAD document to the pure
``PreviewBuilder``; the dialog is a non-modal player (list, slider, play).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from IndexedCAM.Core.collision_checker import checker_for_operation
from IndexedCAM.Core.operation_assignment import parse_source
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
    job: Any = None,
) -> List[Clip]:
    from IndexedCAM.Commands.program import resolve_program
    from IndexedCAM.Core.safety import JobSafetyStorage, SafetyConfig

    safety = JobSafetyStorage(job).load() if job is not None else SafetyConfig()
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
    first = setups[items[0].step.setup]
    source = document.getObject(parse_source(first.metadata["source"]).object_name)
    box = source.Shape.BoundBox
    margin = safety.margin
    sphere = sphere_for(
        ((box.XMin, box.YMin, box.ZMin), (box.XMax, box.YMax, box.ZMax)), margin
    )
    # a transition is validated with the tool of the step it leads to
    return PreviewBuilder(
        setups,
        resources,
        lambda operation: TransitionPlanner(machine, resources.checker(operation), sphere),
        sphere,
    ).build(items)


#: voxel size of the previewed material, from coarsest to finest (mm)
STOCK_DETAILS = (("Grueso", 0.5), ("Normal", 0.25), ("Fino", 0.15))
DEFAULT_DETAIL = "Normal"
#: cell budgets: a box is cheap, masking a shaped stock tests every centre
STOCK_MAX_CELLS = 12_000_000
NON_BOX_MAX_CELLS = 1_500_000
REFRESH_SECONDS = 0.15


def stock_resolution(detail: str = DEFAULT_DETAIL) -> float:
    """Voxel size for a detail name (the default when it is unknown)."""
    for name, resolution in STOCK_DETAILS:
        if name.casefold() == str(detail).casefold():
            return resolution
    return dict(STOCK_DETAILS)[DEFAULT_DETAIL]


def stock_for_job(job: Any, detail: str = DEFAULT_DETAIL) -> Any:
    """Voxel model of the Job's stock (None if the Job has no usable stock).

    ``detail`` picks the voxel size; it is coarsened automatically when the
    stock is so large that the cell budget would be exceeded.
    """
    from IndexedCAM.Core.voxel_stock import VoxelStock

    shape = getattr(getattr(job, "Stock", None), "Shape", None)
    if shape is None or shape.isNull():
        return None
    box = shape.BoundBox
    low, high = (box.XMin, box.YMin, box.ZMin), (box.XMax, box.YMax, box.ZMax)
    is_box = abs(shape.Volume - box.XLength * box.YLength * box.ZLength) < 1e-3 * shape.Volume
    inside = None
    cells = STOCK_MAX_CELLS
    if not is_box:
        import FreeCAD

        cells = NON_BOX_MAX_CELLS
        inside = lambda centres: [shape.isInside(FreeCAD.Vector(*c), 1e-6, True) for c in centres]
    return VoxelStock(low, high, stock_resolution(detail), cells, inside)


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

        from IndexedCAM.Commands.context import open_context, selected_objects
        from IndexedCAM.Core.job_context import JobCancelled

        document = FreeCAD.ActiveDocument
        try:
            ctx = open_context(document, selected_objects())
            clips = build_clips(document, ctx.manager, ctx.program, ctx.bridge, job=ctx.job)
            stock = stock_for_job(ctx.job) if clips else None
        except JobCancelled:
            return
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
        PreviewCommand._window = PreviewWindow(clips, stock, ctx.job)
        PreviewCommand._window.show()


class PreviewWindow:
    """Non-modal player over the ticked clips, in order.

    Every entry of the list has a checkbox: the slider and the play button run
    the ticked ones one after another, so the whole program (operations,
    transitions and the final return to vertical) is one continuous movement.
    """

    def __init__(
        self,
        clips: Sequence[Clip],
        stock: Any = None,
        job: Any = None,
        detail: str = DEFAULT_DETAIL,
    ) -> None:
        import FreeCADGui as Gui
        from PySide import QtCore, QtWidgets

        from IndexedCAM.Gui.tool_view import ToolView

        self._clips = list(clips)
        self._view = ToolView()
        self._timeline = None
        self._job = job
        self._detail = detail
        self._job_stock_visible = None
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
        self._detail_box = QtWidgets.QComboBox()
        for name, resolution in STOCK_DETAILS:
            self._detail_box.addItem("{} ({:g} mm)".format(name, resolution), name)
        self._detail_box.setCurrentIndex(
            self._detail_box.findData(detail) if self._detail_box.findData(detail) >= 0 else 0
        )
        self._detail_box.setEnabled(self._timeline is not None)
        self._detail_box.currentIndexChanged.connect(lambda _: self._rebuild_stock())
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
        stock_row = QtWidgets.QHBoxLayout()
        stock_row.addWidget(self._stock_box)
        stock_row.addWidget(QtWidgets.QLabel("Detalle del material:"))
        stock_row.addWidget(self._detail_box)
        stock_row.addStretch()
        layout.addLayout(stock_row)
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
        self._hide_job_stock()
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

    def _rebuild_stock(self) -> None:
        """Rebuild the voxel stock at the chosen detail, keeping the frame."""
        if self._job is None:
            return
        from IndexedCAM.Core.stock_timeline import StockTimeline

        position, clip_index, index = self._slider.value(), self._clip_index, None
        entry = self._playlist.at(position)
        if entry is not None:
            index = entry[1]
        stock = stock_for_job(self._job, self._detail_box.currentData() or DEFAULT_DETAIL)
        if stock is None:
            return
        self._detail = self._detail_box.currentData() or DEFAULT_DETAIL
        self._timeline = StockTimeline(stock, self._clips)
        self._stock_box.setChecked(True)
        if clip_index is not None and index is not None:
            self._view.show_stock(self._timeline.show(clip_index, index).triangles())
        else:
            self._show(position, force=True)

    def _hide_job_stock(self) -> None:
        view = getattr(getattr(self._job, "Stock", None), "ViewObject", None)
        if view is not None and self._timeline is not None:
            self._job_stock_visible = view.Visibility
            view.Visibility = False

    def _closed(self) -> None:
        self._timer.stop()
        self._view.clear()
        view = getattr(getattr(self._job, "Stock", None), "ViewObject", None)
        if view is not None and self._job_stock_visible is not None:
            view.Visibility = self._job_stock_visible

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

"""Show the tool inclination in the 3D view while a bound CAM operation is selected.

CAM draws a path with a vertical tool; this observer adds, for the selected
operation, its path on the part and the tool/holder/head posed with the
Setup's B/C. Nothing is stored in the document.
"""

from __future__ import annotations

from typing import Any, List, Optional

from IndexedCAM.Gui.tool_view import ToolView

_observer: Optional["OperationToolObserver"] = None


def selected_operation(objects: List[Any]) -> Optional[Any]:
    """The single selected object that is bound to a Setup, if any."""
    if len(objects) == 1 and getattr(objects[0], "IndexedSetup", ""):
        return objects[0]
    return None


class OperationToolObserver:
    """Selection observer driving a ``ToolView`` (registered with Gui.Selection)."""

    def __init__(self) -> None:
        self._view = ToolView()
        self._shown: Optional[str] = None

    def addSelection(self, *_: Any) -> None:
        self.refresh()

    def removeSelection(self, *_: Any) -> None:
        self.refresh()

    def setSelection(self, *_: Any) -> None:
        self.refresh()

    def clearSelection(self, *_: Any) -> None:
        self.refresh()

    def refresh(self) -> None:
        import FreeCADGui as Gui

        try:
            operation = selected_operation(list(Gui.Selection.getSelection()))
            if operation is None:
                self._hide()
            elif operation.Name != self._shown or not self._view.visible:
                self._show(operation)
        except Exception as error:  # never break selection because of a preview
            import FreeCAD

            FreeCAD.Console.PrintWarning("IndexedCAM: herramienta no mostrada: {}\n".format(error))
            self._hide()

    def _hide(self) -> None:
        if self._shown is not None or self._view.visible:
            self._view.clear()
        self._shown = None

    def _show(self, operation: Any) -> None:
        from IndexedCAM.Commands.context import build_context
        from IndexedCAM.Core.job_context import jobs_of
        from IndexedCAM.Core.operation_pose import operation_pose
        from IndexedCAM.Machine.bc_machine import BCMachine

        jobs = jobs_of(operation)
        if not jobs:
            return self._hide()
        ctx = build_context(operation.Document, jobs[0])
        setup = ctx.manager.get(operation.IndexedSetup)
        pose = operation_pose(setup, operation.Path.Commands)
        if not pose.points:
            return self._hide()
        envelope = ctx.bridge.envelope_for(operation, BCMachine().envelope)
        self._view.clear()
        self._view.show_path(pose.points)
        self._view.show_tool(envelope.place(pose.tip, pose.b, pose.c))
        self._shown = operation.Name


def install() -> None:
    """Start observing the selection (idempotent)."""
    global _observer
    if _observer is None:
        import FreeCADGui as Gui

        _observer = OperationToolObserver()
        Gui.Selection.addObserver(_observer)

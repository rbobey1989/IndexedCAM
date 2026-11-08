"""Keep the IndexedCAM helpers tidy when a document is opened.

* FreeCAD turns Visibility back on while a document is being restored, so the
  local models of the orientations would reappear in the 3D view.
* A document written by an older version still keeps the orientation Jobs
  inside a container group and without a view provider, so their groups would
  show up loose in the tree.

FreeCAD's Python observer has no "restore finished" slot, so the pass that fixes
the tree is deferred to the event loop: ``openDocument`` is synchronous and the
timer runs right after it, with the document already complete.
"""

from __future__ import annotations

from typing import Any

_observer: Any = None


def is_helper(obj: Any) -> bool:
    return hasattr(obj, "LocalPlacement") and hasattr(obj, "SetupName")


def tidy(document: Any) -> None:
    """Adopt the old container layout and nest every orientation Job."""
    from IndexedCAM.Core.orientation_jobs import OrientationJobs
    from IndexedCAM.Gui import job_view

    try:
        OrientationJobs(document).adopt_legacy()
        job_view.attach_all(document)
    except Exception:  # a closed document or a broken addon must never raise here
        pass


class RestoreObserver:
    """Acts only while a document is being restored or right after opening."""

    def slotChangedObject(self, obj: Any, prop: str) -> None:
        restoring = getattr(obj.Document, "Restoring", False)
        if prop == "Visibility" and obj.Visibility and restoring and is_helper(obj):
            obj.Visibility = False
        elif prop == "IndexedCAMSetup" and not restoring:
            tidy(obj.Document)

    def slotCreatedDocument(self, document: Any) -> None:
        from PySide import QtCore

        QtCore.QTimer.singleShot(0, lambda: tidy(document))


def install() -> None:
    global _observer
    if _observer is None:
        import FreeCAD

        _observer = RestoreObserver()
        FreeCAD.addDocumentObserver(_observer)

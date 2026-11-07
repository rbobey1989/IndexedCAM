"""Keeps the IndexedCAM helper objects (container, local models) hidden after a
document is reopened."""

from __future__ import annotations

from typing import Any

from IndexedCAM.Core.orientation_jobs import CONTAINER_MARKER, SETUP_PROPERTY

_observer: Any = None


def is_helper(obj: Any) -> bool:
    return bool(
        hasattr(obj, CONTAINER_MARKER)
        or hasattr(obj, SETUP_PROPERTY)
        or (hasattr(obj, "LocalPlacement") and hasattr(obj, "SetupName"))
    )


class RestoreObserver:
    """FreeCAD turns Visibility back on while a document is being restored;
    undo that for the helpers (it only acts during the restore)."""

    def slotChangedObject(self, obj: Any, prop: str) -> None:
        if prop == "Visibility" and obj.Visibility and obj.Document.Restoring and is_helper(obj):
            obj.Visibility = False


def install() -> None:
    global _observer
    if _observer is None:
        import FreeCAD

        _observer = RestoreObserver()
        FreeCAD.addDocumentObserver(_observer)

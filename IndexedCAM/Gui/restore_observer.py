"""Keeps the IndexedCAM helper objects (local models, orientation groups) hidden
after a document is reopened."""

from __future__ import annotations

from typing import Any

from IndexedCAM.Core.document_storage import GROUP_MARKER, ORIENTATION_DATA

_observer: Any = None


def is_helper(obj: Any) -> bool:
    return bool(
        hasattr(obj, GROUP_MARKER)
        or hasattr(obj, ORIENTATION_DATA)
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

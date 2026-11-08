"""Keeps the local models of the orientations hidden after a document is reopened."""

from __future__ import annotations

from typing import Any

_observer: Any = None


def is_helper(obj: Any) -> bool:
    return hasattr(obj, "LocalPlacement") and hasattr(obj, "SetupName")


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

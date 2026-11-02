"""Undoable FreeCAD document transaction shared by the IndexedCAM commands."""

from __future__ import annotations

from typing import Any


class DocumentTransaction:
    """Context manager: commits on success, aborts if the block raises."""

    def __init__(self, document: Any, label: str) -> None:
        self._document = document
        self._label = label

    def __enter__(self) -> "DocumentTransaction":
        self._document.openTransaction(self._label)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self._document.commitTransaction()
        else:
            self._document.abortTransaction()

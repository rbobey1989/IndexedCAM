"""Documents whose operations may hold a ``Path`` that no longer matches the part.

CAM rebuilds an operation's Path only when one of its inputs is flagged as
changed. Some of the inputs IndexedCAM adds never flag anything:

* a ``LocalModel`` keeps its Shape *transient*, so it is rebuilt silently on
  load, outside the recompute pass;
* the Job's stock is recomputed by IndexedCAM itself when it repairs a stock
  that grew with the rotated copies.

An operation restored from such a document keeps the Path computed against the
old geometry, with the object reported as ``Up-to-date``: no recompute fixes it,
only touching the operation does. ``mark`` remembers the document and ``take``
reports it once, so the first command that uses the paths rebuilds them.
"""

from __future__ import annotations

from typing import Any, Set

_STALE: Set[str] = set()


def mark(document: Any) -> None:
    """Record that the operations of ``document`` may have a stale Path."""
    name = getattr(document, "Name", None)
    if name:
        _STALE.add(name)


def take(document: Any) -> bool:
    """True the first time it is called for a marked document."""
    name = getattr(document, "Name", None)
    if name in _STALE:
        _STALE.discard(name)
        return True
    return False


def marked(document: Any) -> bool:
    """True if ``document`` is marked (``take`` does not consume the mark)."""
    return getattr(document, "Name", None) in _STALE


def forget(document: Any = None) -> None:
    """Drop the mark of ``document`` (all of them when it is None)."""
    if document is None:
        _STALE.clear()
    else:
        _STALE.discard(getattr(document, "Name", None))

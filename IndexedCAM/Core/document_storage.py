"""Store IndexedCAM data as JSON inside the document (persisted in the .FCStd).

Everything IndexedCAM owns lives in one hidden container object (see
``orientation_jobs.container``): the setups, the program order, the post
options and the safety distance, plus the orientation CAM Jobs and the local
models they follow. A property is only created on the first save, so merely
opening or analyzing a document never modifies it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional, Sequence

CONTAINER_NAME = "IndexedCAM"
PROPERTY_NAME = "SetupsJson"
PROGRAM_PROPERTY_NAME = "StepsJson"
GROUP_TITLE = "IndexedCAM"


def orientations_group(owner: Any) -> Optional[Any]:
    """The IndexedCAM container of ``owner``'s document, or None."""
    from IndexedCAM.Core.orientation_jobs import find_container

    return find_container(getattr(owner, "Document", owner))


def ensure_orientations_group(owner: Any) -> Any:
    """The IndexedCAM container of ``owner``'s document, created if missing."""
    from IndexedCAM.Core.orientation_jobs import container

    return container(getattr(owner, "Document", owner))


def hide_group(group: Any) -> None:
    """The container (and its groups) must never show up in the 3D view."""
    group.Visibility = False
    view = getattr(group, "ViewObject", None)
    if view is not None:
        view.Visibility = False


def _string_property(owner: Any, name: str, tooltip: str) -> None:
    if not hasattr(owner, name):
        owner.addProperty("App::PropertyString", name, GROUP_TITLE, tooltip)
        owner.setEditorMode(name, 2)


class DocumentStorage:
    """Setup storage backed by the document's IndexedCAM container."""

    def __init__(self, document: Any) -> None:
        self._document = document

    def _container(self) -> Optional[Any]:
        from IndexedCAM.Core.orientation_jobs import find_container

        return find_container(self._document)

    def load(self) -> List[Dict[str, Any]]:
        container = self._container()
        if container is None or not hasattr(container, PROPERTY_NAME):
            return []
        raw = getattr(container, PROPERTY_NAME)
        if not raw:
            return []
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("stored setups must be a JSON list")
        return data

    def save(self, setups: Sequence[Mapping[str, Any]]) -> None:
        from IndexedCAM.Core.orientation_jobs import container

        owner = container(self._document)
        _string_property(owner, PROPERTY_NAME, "Serialized setups")
        setattr(owner, PROPERTY_NAME, json.dumps(list(setups)))


class ProgramStepsStorage:
    """Program order stored on the IndexedCAM container."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def load(self) -> List[Dict[str, Any]]:
        container = orientations_group(self._owner)
        raw = getattr(container, PROGRAM_PROPERTY_NAME, "") if container is not None else ""
        return json.loads(raw) if raw else []

    def save(self, steps: Sequence[Mapping[str, Any]]) -> None:
        if not steps and orientations_group(self._owner) is None:
            return
        owner = ensure_orientations_group(self._owner)
        _string_property(owner, PROGRAM_PROPERTY_NAME, "Program steps")
        setattr(owner, PROGRAM_PROPERTY_NAME, json.dumps(list(steps)))

"""Store setups as JSON inside a FreeCAD document (persisted in the FCStd)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Sequence

CONTAINER_NAME = "IndexedCAM_Setups"
PROPERTY_NAME = "SetupsJson"


class DocumentStorage:
    """SetupStorage backed by one App::FeaturePython object of the document.

    The container object is created lazily on the first save, so merely
    opening or analyzing a document never modifies it.
    """

    def __init__(self, document: Any) -> None:
        self._document = document

    def _container(self) -> Any:
        return self._document.getObject(CONTAINER_NAME)

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
        container = self._container()
        if container is None:
            container = self._document.addObject("App::FeaturePython", CONTAINER_NAME)
            container.addProperty(
                "App::PropertyString", PROPERTY_NAME, "IndexedCAM", "Serialized setups"
            )
            container.setEditorMode(PROPERTY_NAME, 2)
        setattr(container, PROPERTY_NAME, json.dumps(list(setups)))

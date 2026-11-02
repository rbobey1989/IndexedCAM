"""Store setups as JSON inside a FreeCAD document (persisted in the FCStd)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Sequence

CONTAINER_NAME = "IndexedCAM_Setups"
PROPERTY_NAME = "SetupsJson"
PROGRAM_CONTAINER_NAME = "IndexedCAM_Program"
PROGRAM_PROPERTY_NAME = "StepsJson"


class DocumentStorage:
    """SetupStorage backed by one App::FeaturePython object of the document.

    The container object is created lazily on the first save, so merely
    opening or analyzing a document never modifies it.
    """

    container_name = CONTAINER_NAME
    property_name = PROPERTY_NAME

    def __init__(self, document: Any) -> None:
        self._document = document

    def _container(self) -> Any:
        return self._document.getObject(self.container_name)

    def load(self) -> List[Dict[str, Any]]:
        container = self._container()
        if container is None or not hasattr(container, self.property_name):
            return []
        raw = getattr(container, self.property_name)
        if not raw:
            return []
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("stored setups must be a JSON list")
        return data

    def save(self, setups: Sequence[Mapping[str, Any]]) -> None:
        container = self._container()
        if container is None:
            container = self._document.addObject("App::FeaturePython", self.container_name)
            container.addProperty(
                "App::PropertyString", self.property_name, "IndexedCAM", "Serialized data"
            )
            container.setEditorMode(self.property_name, 2)
        setattr(container, self.property_name, json.dumps(list(setups)))


class ProgramDocumentStorage(DocumentStorage):
    """Program steps stored in their own container object."""

    container_name = PROGRAM_CONTAINER_NAME
    property_name = PROGRAM_PROPERTY_NAME

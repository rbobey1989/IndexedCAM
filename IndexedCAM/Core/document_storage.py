"""Store the IndexedCAM data in hidden properties of the CAM Job.

Everything IndexedCAM knows travels inside the Job the user created in CAM:
the Setups, the program order and the controller settings. No extra object is
added to the document, so the tree shows only the Job with its own groups
(Operations, Model, Stock, SetupSheet and Tools). A property is created on the
first save, so merely opening a document never modifies it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Sequence

GROUP_TITLE = "IndexedCAM"
SETUPS_PROPERTY_NAME = "IndexedCAMSetups"
PROGRAM_PROPERTY_NAME = "IndexedCAMProgram"


def string_property(owner: Any, name: str, tooltip: str) -> None:
    """Add a hidden string property to ``owner`` if it does not have it yet."""
    if not hasattr(owner, name):
        owner.addProperty("App::PropertyString", name, GROUP_TITLE, tooltip)
        owner.setEditorMode(name, 2)


class JobSetupsStorage:
    """Setup storage backed by the Job's own hidden property."""

    def __init__(self, job: Any) -> None:
        self._job = job

    def load(self) -> List[Dict[str, Any]]:
        raw = getattr(self._job, SETUPS_PROPERTY_NAME, "")
        if not raw:
            return []
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("stored setups must be a JSON list")
        return data

    def save(self, setups: Sequence[Mapping[str, Any]]) -> None:
        string_property(self._job, SETUPS_PROPERTY_NAME, "Serialized setups")
        setattr(self._job, SETUPS_PROPERTY_NAME, json.dumps(list(setups)))


class JobProgramStorage:
    """Program order stored on the Job."""

    def __init__(self, job: Any) -> None:
        self._job = job

    def load(self) -> List[Dict[str, Any]]:
        raw = getattr(self._job, PROGRAM_PROPERTY_NAME, "")
        return json.loads(raw) if raw else []

    def save(self, steps: Sequence[Mapping[str, Any]]) -> None:
        string_property(self._job, PROGRAM_PROPERTY_NAME, "Program steps")
        setattr(self._job, PROGRAM_PROPERTY_NAME, json.dumps(list(steps)))


class JobSettingStorage:
    """Base for a document setting stored on the Job (safety, post options).

    Subclasses set ``property_name`` and ``tooltip`` and convert to and from
    their own value type with ``_raw()``/``_store()``.
    """

    property_name = ""
    tooltip = ""

    def __init__(self, job: Any) -> None:
        self._job = job

    def _raw(self) -> str:
        return getattr(self._job, self.property_name, "")

    def _store(self, value: Mapping[str, Any]) -> None:
        string_property(self._job, self.property_name, self.tooltip)
        setattr(self._job, self.property_name, json.dumps(dict(value)))

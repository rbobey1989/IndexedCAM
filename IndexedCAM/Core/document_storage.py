"""Store setups as JSON inside a FreeCAD document (persisted in the FCStd)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Sequence

CONTAINER_NAME = "IndexedCAM_Setups"
PROPERTY_NAME = "SetupsJson"
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


GROUP_NAME = "Orientations"
GROUP_MARKER = "IndexedCAMOrientations"
ORIENTATION_PREFIX = "IndexedCAM_Orientation"
ORIENTATION_DATA = "IndexedCAMData"


def orientations_group(job: Any) -> Any:
    """The group of ``job`` that holds its orientations, or None."""
    for child in getattr(job, "Group", ()):
        if hasattr(child, GROUP_MARKER):
            return child
    return None


def _ensure_group(job: Any) -> Any:
    group = orientations_group(job)
    if group is None:
        group = job.Document.addObject("App::DocumentObjectGroup", GROUP_NAME)
        group.addProperty("App::PropertyBool", GROUP_MARKER, "IndexedCAM", "Orientations of a Job")
        setattr(group, GROUP_MARKER, True)
        group.Label = GROUP_NAME
        job.addObject(group)
    return group


class JobStorage:
    """SetupStorage keeping each orientation as an object inside its CAM Job.

    The Job gets an ``Orientations`` group (created on the first save) with one
    child per orientation; the full data stays in a hidden JSON property and
    B/C/Source are shown read-only. Children are reused by position, so a
    rename or reorder never leaves stale objects.
    """

    def __init__(self, job: Any) -> None:
        self._job = job

    def _children(self) -> List[Any]:
        group = orientations_group(self._job)
        if group is None:
            return []
        return [o for o in group.Group if hasattr(o, ORIENTATION_DATA)]

    def load(self) -> List[Dict[str, Any]]:
        return [json.loads(child.IndexedCAMData) for child in self._children()]

    def save(self, setups: Sequence[Mapping[str, Any]]) -> None:
        children = self._children()
        if not setups and not children:
            return
        group = _ensure_group(self._job)
        document = self._job.Document
        for index, data in enumerate(setups):
            if index < len(children):
                child = children[index]
            else:
                child = document.addObject("App::FeaturePython", ORIENTATION_PREFIX)
                self._add_properties(child)
                group.addObject(child)
            self._fill(child, data)
        for child in children[len(setups):]:
            document.removeObject(child.Name)

    @staticmethod
    def _add_properties(child: Any) -> None:
        child.addProperty("App::PropertyString", ORIENTATION_DATA, "IndexedCAM", "Serialized data")
        child.setEditorMode(ORIENTATION_DATA, 2)
        child.addProperty("App::PropertyFloat", "B", "IndexedCAM", "B angle (deg)")
        child.addProperty("App::PropertyFloat", "C", "IndexedCAM", "C angle (deg)")
        child.addProperty("App::PropertyString", "Source", "IndexedCAM", "Face it came from")
        for name in ("B", "C", "Source"):
            child.setEditorMode(name, 1)

    @staticmethod
    def _fill(child: Any, data: Mapping[str, Any]) -> None:
        child.IndexedCAMData = json.dumps(dict(data))
        child.Label = str(data.get("name", "Orientation"))
        child.B = float(data.get("b", 0.0))
        child.C = float(data.get("c", 0.0))
        child.Source = str(data.get("metadata", {}).get("source", ""))


class JobProgramStorage:
    """Program steps stored on the ``Orientations`` group of the Job."""

    def __init__(self, job: Any) -> None:
        self._job = job

    def load(self) -> List[Dict[str, Any]]:
        group = orientations_group(self._job)
        raw = getattr(group, PROGRAM_PROPERTY_NAME, "") if group is not None else ""
        return json.loads(raw) if raw else []

    def save(self, steps: Sequence[Mapping[str, Any]]) -> None:
        group = orientations_group(self._job)
        if group is None:
            if not steps:
                return
            group = _ensure_group(self._job)
        if not hasattr(group, PROGRAM_PROPERTY_NAME):
            group.addProperty(
                "App::PropertyString", PROGRAM_PROPERTY_NAME, "IndexedCAM", "Program steps"
            )
            group.setEditorMode(PROGRAM_PROPERTY_NAME, 2)
        setattr(group, PROGRAM_PROPERTY_NAME, json.dumps(list(steps)))
